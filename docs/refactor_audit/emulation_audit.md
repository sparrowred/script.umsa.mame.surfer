# Emulation Audit — Full Launch Path

**Audited at:** git HEAD `9a98cfe`  
**Scope:** `UMSA.run_emulator()` → `emulator_launcher.py` → `retroplayer_cache.py` → `Emulation` (prepare/run/wait) → `DBMod.get_cmd_line_options()`/`create_cmdline()` → `GameRepository` reads → `ProcessRunner`

---

## Full Launch Path Trace

```
UMSA.run_emulator(emu_infos)
│
├─ exe == 'kodi' → RetroplayerCtx → retroplayer_cache.run_retroplayer(ctx)
│   └─ Cache folder setup (batomame mapping) → ROM search/copy/extract → xbmc.Player.play()
│
└─ exe != 'kodi' → LaunchCtx → emulator_launcher.launch_emulator(ctx)
    │
    ├─ Stop any running VGM
    ├─ UI prep: emu_dialog.create(), stop_screensaver()
    ├─ Build emurun dict:
    │   ├─ emulation_start, working_dir, swl_name, set_name, description, publisher
    │   ├─ set_clone ← ggdb.get_set_name(actset['clone'])
    │   └─ disks ← ggdb.get_disks(swl_name, set_name)
    │
    ├─ Disk selection (if multiple CHDs): dialog.select('Select CHD:') → promote picked to [0]
    │
    ├─ Emulator-specific preparation:
    │   ├─ exodos     → Emulation.prepare_exodos_run() → find_nonmame_roms('shell'|'alt')
    │   ├─ marp       → Emulation.prepare_marp_run() → marp_download → -playback args
    │   ├─ mame       → Emulation.prepare_mame_run(ggdb, actset, dialog)
    │   │               └─ ggdb.get_cmd_line_options(set_id, name, machine_name, swl_name)
    │   │                   ├─ GameRepository.get_swl_options(swl_name)
    │   │                   ├─ GameRepository.get_machine_id(machine_name)
    │   │                   ├─ GameRepository.get_devices_for_machine(machine_id)
    │   │                   ├─ GameRepository.get_sharedfeat_requirement(set_id)
    │   │                   ├─ GameRepository.get_parts_for_set_id(set_id)
    │   │                   └─ GameRepository.get_disks(swl_name, set_name) (facade)
    │   │               └─ DBMod.create_cmdline(parts, devices, setname) → (cmd_options, first_device)
    │   └─ other      → Emulation.other_emulator(emu_infos, dialog, sleep)
    │                   ├─ folder = temp_dir/swl_set
    │                   ├─ find_nonmame_roms() OR find_roms()
    │                   ├─ extract_rom() / extract_chd() if not zip mode
    │                   ├─ Special handling: demul, fs-uae, flycast
    │                   └─ Sets emurun['args'] / emurun['emu_exe']
    │
    ├─ Pause media (video stop / audio pause)
    ├─ Execute:
    │   ├─ emulation_start in (0,1) → Emulation.start_managed_process(capture_output=(1))
    │   │   └─ ProcessRunner.start(args, cwd, capture_output, env)
    │   └─ emulation_start == 2 (fallback) → Emulation.run() → raw subprocess.Popen
    │
    ├─ Wait for completion: Emulation.wait_for_completion(dialog, sleep)
    │   ├─ Poll ProcessRunner.status() or process.poll()
    │   ├─ Dialog cancel → terminate → sleep(3000) → kill if still running
    │   └─ Returns (stdout, stderr) if capture_output
    │
    ├─ Post-run:
    │   ├─ Average speed parse from stdout
    │   ├─ Exit code → add_or_update_emu_output (TEXTLIST tab)
    │   ├─ If not marp & played > 60s → ggdb.write_status_after_play(set_id, seconds)
    │   ├─ If mame → refresh local snaps + show_artwork('set')
    │   └─ notify_final(notif, emu_name, screensaver_mode)
    │
    └─ Cleanup: Emulation.after_run() (symlink removal)
```

---

## Layer Ownership Map

| Layer | Responsibility | Owner | Key Code |
|-------|----------------|-------|----------|
| **1. Database-backed metadata lookup** | Game/software/set/machine/device/part/sharedfeat queries | `GameRepository` (Core) | `get_swl_options`, `get_machine_id`, `get_devices_for_machine`, `get_sharedfeat_requirement`, `get_parts_for_set_id`, `get_disks` |
| **2. Deterministic command-line assembly** | Argument list construction from metadata | `DBMod` (Core) | `get_cmd_line_options` (orchestrates repo reads), `create_cmdline` (pure assembly) |
| **3. ROM/CHD discovery & extraction** | Filesystem search, ZIP/CHD extraction, temp folder management | `Emulation` (Core) | `find_roms`, `find_nonmame_roms`, `extract_rom`, `extract_chd`, `prepare_exodos_run`, `prepare_marp_run` |
| **4. Emulator-specific launch preparation** | Per-emulator argument building, working dir, env, special handling | `Emulation` (Core) | `prepare_mame_run`, `prepare_exodos_run`, `prepare_marp_run`, `other_emulator`, `demul`, `fsuae`, `flycast`, `mame` (stub) |
| **5. Process startup, monitoring, cancellation, cleanup** | Process ownership, output capture, terminate/kill, wait | `ProcessRunner` + `Emulation` (Core) | `ProcessRunner.start/status/terminate/kill/read_output`, `Emulation.start_managed_process/wait_for_completion/run/terminate/kill/after_run` |
| **6. GUI progress, notifications, window lifecycle** | Dialogs, progress updates, screensaver control, TEXTLIST output, final notification | `emulator_launcher.py` + `gui.py` (GUI) | `LaunchCtx` callbacks (`emu_dialog`, `dialog`, `sleep`, `stop_screensaver`, `set_emulator_running`, `notify_final`, `add_or_update_emu_output`, `search_snaps`, `show_artwork`) |
| **7. Retroplayer cache & launch** | Kodi Retroplayer-specific cache folder, ROM copy, game Item creation | `retroplayer_cache.py` (GUI) | `run_retroplayer(ctx)` |

---

## Detailed Component Analysis

### `DBMod.get_cmd_line_options()` / `create_cmdline()` (Core)

**Location:** `script.module.umsa.core/lib/umsa_core/database.py`

**Responsibility:** Deterministic MAME command-line assembly from database metadata.

**Flow:**
1. `get_swl_options(swl_name)` → SWL row (driver options)
2. `get_machine_id(machine_name)` → machine `id` (for `-machine`)
3. `get_devices_for_machine(machine_id)` → device list (for `-device`)
4. `get_sharedfeat_requirement(set_id)` → shared feature chain (recursive, expands `-device`/`-slot`)
5. `get_parts_for_set_id(set_id)` → parts (for `-cart`/`-flop`/etc.)
6. `get_disks(swl_name, set_name)` → CHD disk info (for `-hard1`/etc.)
7. `create_cmdline(parts, devices, setname)` → pure assembly:
   - Parts → `-cartN`/`-flopN`/etc. (mutates `parts` list in place)
   - Devices → `-device` args
   - Returns `(cmd_options_list, first_device)`

**Dependencies:** `GameRepository` (5 read methods), `DBMod` instance for shared-feature recursion.

**Callers:** `Emulation.prepare_mame_run()` (via `ggdb`)

**Tests:** `tests/test_cmd_line_options.py` (23 golden tests pinning exact `prepare_mame_run` argument list)

---

### `Emulation.prepare_mame_run()` (Core)

**Location:** `script.module.umsa.core/lib/umsa_core/emulation.py:373`

**Responsibility:** Populate `self.emurun['args']` for MAME launch.

```python
def prepare_mame_run(self, ggdb, actset, dialog=None):
    self.emurun['emu_exe'] = self.mame_exe
    if actset['swl_name'] == 'mame':
        self.emurun['args'] = actset['name']  # bare driver name
    elif actset['swl_name'].startswith('gb64_'):
        # C64 variants
    else:
        if dialog: dialog.update(20, 'create swl options...')
        self.emurun['args'] = ggdb.get_cmd_line_options(
            actset['id'], actset['name'],
            actset['machine_name'], actset['swl_name'])
```

**Note:** For `swl_name == 'mame'`, args is just the driver name (string). For SWL, delegates to `DBMod.get_cmd_line_options()`.

---

### `Emulation` — Emulator-Specific Preparation Methods

| Method | Emulator | Key Logic |
|--------|----------|-----------|
| `prepare_exodos_run` | eXoDOS | `find_nonmame_roms('shell'|'alt')` → sets `emurun['args']=[]`, `emulation_start=2` (fallback/terminal) |
| `prepare_marp_run` | MARP replay | `marp_download(inp_url, input_dir)` → args = `[set_name, "-playback", inp_file, "-exit_after_playback"]` |
| `other_emulator` | All others | Sets `folder`, `emu_exe`, `working_dir`, `emulation_start`; calls `find_nonmame_roms()` or `find_roms()`; if not zip mode: `extract_rom()` + `extract_chd()`; special cases: `demul()`, `fsuae()`, `flycast()` |
| `demul` | Demul | Runs `emu_exe -listroms`, parses output to find section + rom → `-run=section -rom=name` |
| `fsuae` | FS-UAE | Model from SWL; CDROM or floppy args; `--floppies_dir` + `--floppy_image_N` |
| `flycast` | Flycast | Stub — sets `symlink = ""` |

---

### `Emulation.find_roms()` / `find_nonmame_roms()` (Core)

**`find_roms(swl_name=None, set_name=None)`** (lines 874–919):
- Builds `zip_name` from `swl_name`/`set_name` or `emurun`
- Builds `all_chds` from `emurun['disks']` (with clone fallback)
- Searches `self.rom_paths` (from `mame.ini`) for zip + CHDs
- Sets `emurun['zips']`, `emurun['chds']`
- Returns first zip if `swl_name`/`set_name` provided (for VGM)

**`find_nonmame_roms(exodos_shell='')`** (lines 812–872):
- eXoDOS: searches `!dos/<set_name>/` for `.bat` (excl. install/exception), sets shell script or alternate launcher, constructs zip path
- GB64: `gb64/Games/<set_name>.zip`
- WHDLoad: complex path construction from description + publisher

---

### `Emulation.extract_rom()` / `extract_chd()` (Core)

**`extract_rom()`** (lines 989–1047):
- Extracts ZIP to `emurun['folder']` (temp dir)
- NES 2-file hack: concatenates PRG+CHR in correct order
- Renames to platform extension (`.sfc`, `.gb`, `.gbc`, etc. from `EXTENSIONS` map)
- Sets `emurun['extract_files']`

**`extract_chd(sleep, dialog)`** (lines 920–987):
- Runs `chdman extractcd -i <chd> -o <folder>/<name>.cue` (or `.gdi` for DC)
- Progress via `dialog.update` parsing `chdman` stderr `%`
- Cancel support → `CHDExtractionCancelled`
- Failure → `CHDExtractionError`

---

### `ProcessRunner` + `Emulation` Process Management (Core)

| Class/Method | Responsibility |
|--------------|----------------|
| `ProcessRunner` | Owns one `Popen`; `start(command, cwd, capture_output, env)`, `status() → ProcessState`, `terminate()`, `kill()`, `read_output() → (stdout, stderr)` |
| `Emulation.start_managed_process(capture_output)` | Delegates to `ProcessRunner.start()` with `emurun['args']`, `working_dir`, `env` |
| `Emulation.wait_for_completion(dialog, sleep)` | Polls `ProcessRunner.status()` or `process.poll()`; handles dialog cancel → terminate → kill; returns captured output if `emulation_start==1` |
| `Emulation.run()` | Fallback/terminal: raw `subprocess.Popen` (no capture) or terminal wrapper (`terminal -e "cmd"`) |
| `Emulation.terminate()` / `kill()` | Raw process terminate/kill (for fallback mode) |
| `Emulation.after_run()` | Cleans up `emurun['symlink']` |

**Thread safety:** `ProcessRunner` documented as "not thread-safe; intended for serialized calls from one owner."

---

### `emulator_launcher.py` (GUI)

**Location:** `plugin.program.umsa.mame.surfer/resources/lib/emulator_launcher.py`

**Responsibility:** GUI-side launch orchestration — bridges `UMSA` state to `Emulation` via callbacks.

**`LaunchCtx` dataclass** — carries:
- Data: `actset`, `emu_infos`, `emulation`, `ggdb`, `emu_dialog`, `dialog`, `player`, `mame_dir`, `emulation_start`, `playvideo`
- Callbacks: `stop_screensaver`, `get_screensaver_mode`, `set_emulator_running`, `search_snaps`, `show_artwork`, `add_or_update_emu_output`, `notify_final`, `sleep`

**`launch_emulator(ctx)`** — 250 lines, preserves all original behavior:
1. Stop VGM, UI prep, build `emurun` dict (includes `set_clone`, `disks` from `ggdb`)
2. Disk selection dialog (multiple CHDs)
3. Emulator-specific prep (exodos/marp/mame/other) — calls `Emulation` methods
4. Error handling for `CHDExtractionCancelled`/`CHDExtractionError`
5. Multiple extracted files → selection dialog
6. Pause media, execute via `Emulation`, wait
7. Post-run: speed parse, exit code + output → `add_or_update_emu_output`, status write, local snaps refresh, `notify_final`

---

### `retroplayer_cache.py` (GUI)

**Location:** `plugin.program.umsa.mame.surfer/resources/lib/retroplayer_cache.py`

**Responsibility:** Retroplayer-specific cache folder setup + ROM copy/extract + `xbmc.Player` launch.

**Flow:**
1. Cache folder from `batomame` mapping (per source/SWL)
2. Check cache for existing ROM → `playfile`
3. If missing: `Emulation.find_nonmame_roms()` or `find_roms()` → copy/extract to cache
4. Create `xbmcgui.ListItem` with game info tags (title, platform, genre, publisher, developer, year)
5. `player.play(playfile, game_item)` → `stop_screensaver()`, `emu_dialog.close()`, `ctx.exit()`

**Note:** `ctx.exit()` closes the GUI window — TODO notes uncertainty about play-session end detection.

---

### `UMSA.run_emulator()` (GUI) — **Dead Code Removed (Step 1 Complete)**

**Location:** `gui.py:2504–2542` (formerly `gui.py:2504–2636`)

```python
def run_emulator(self, emu_infos):
    if emu_infos.get('exe') == 'kodi':
        # Retroplayer path
        rp_ctx = RetroplayerCtx(...)
        run_retroplayer(rp_ctx)
        return  # ← RETURNS HERE

    ctx = LaunchCtx(...)
    launch_emulator(ctx)
    return  # ← RETURNS HERE
```

**Verdict:** The 92-line legacy body (formerly lines 2545–2636) that duplicated `emulator_launcher.py` logic was **removed on 2026-10-20**. `launch_emulator` and `run_retroplayer` handle all paths.

---

## GameRepository Methods Used for Launch

| Method | Used By | Purpose |
|--------|---------|---------|
| `get_swl_options(name)` | `get_cmd_line_options` | SWL driver options row |
| `get_machine_id(name)` | `get_cmd_line_options` | Machine `id` for `-machine` |
| `get_devices_for_machine(id)` | `get_cmd_line_options` | Device list for `-device` |
| `get_sharedfeat_requirement(set_id)` | `get_cmd_line_options` | Shared feature → recursive device expansion |
| `get_parts_for_set_id(set_id)` | `get_cmd_line_options` + `create_cmdline` | Parts for `-cart`/`-flop`/etc. |
| `get_disks(swl_name, set_name)` | `get_cmd_line_options` + `emulator_launcher` (disks) | CHD disk info for `-hardN` |
| `get_set_name(clone_id)` | `emulator_launcher` (set_clone) | Clone set name for merged CHD search |
| `get_machine_name(machine_id)` | `gui.py` (machine selection) | Machine name/label for display |

---

## Unreachable / Obsolete Code

| Code | Location | Status |
|------|----------|--------|
| `run_emulator` legacy body (lines 2545–2636) | `gui.py` | **Dead** — after `launch_emulator`/`run_retroplayer` return |
| `Emulation.mame()` | `emulation.py:1139` | **Stub** — only docstring/TODOs, never called |
| `Emulation.other_emulator` → `demul`/`fsuae`/`flycast` | `emulation.py` | **Active** — called from `other_emulator` for those emulators |
| `batomame` mapping | `gui.py` + `retroplayer_cache.py` | **Active** — Retroplayer cache folders |
| `vgmplay_exe` setting | Core settings → `Emulation.vgmplay_exe` | **Active** — VGM playback uses dedicated exe |

---

## Cross-Layer Dependencies

```
GUI (gui.py)
  └─ run_emulator(emu_infos)
       ├─ exe='kodi' → retroplayer_cache.run_retroplayer(RetroplayerCtx)
       │     └─ ctx.emulation.find_roms/extract_rom → Emulation (Core)
       └─ exe!='kodi' → emulator_launcher.launch_emulator(LaunchCtx)
             ├─ ctx.ggdb.get_disks / get_set_name → DBMod → GameRepository (Core)
             ├─ ctx.emulation.prepare_*_run → Emulation (Core)
             │     ├─ prepare_mame_run → ggdb.get_cmd_line_options → DBMod (Core)
             │     │     └─ GameRepository reads (Core)
             │     ├─ prepare_exodos_run → find_nonmame_roms (Core)
             │     ├─ prepare_marp_run → marp_download (Core support)
             │     └─ other_emulator → find_roms/extract_rom/extract_chd/demul/fsuae/flycast (Core)
             └─ ctx.emulation.start_managed_process/wait_for_completion → ProcessRunner (Core)
```

---

## Existing Helper Modules & Tests Supporting Separation

| Module | Purpose | Tests |
|--------|---------|-------|
| `emulator_launcher.py` | GUI launch orchestration (extracted) | `tests/test_emulator_launcher.py` (5 tests + CHD dialog fix) |
| `retroplayer_cache.py` | Retroplayer cache/launch (extracted) | `tests/test_emulator_launcher.py` (indirect) |
| `GameRepository` | DB reads for cmdline (extracted Phase 4.4) | `tests/test_game_repository.py`, `tests/test_cmd_line_options.py` (23 golden) |
| `ProcessRunner` | Process ownership (Core) | `tests/test_process.py`, `tests/test_emulation_process.py` |
| `Emulation` VGM | VGM playback + Lua socket | `tests/test_emulation_vgm_callback.py`, `tests/test_vgmplay_preexit.py`, `tests/test_vgm_preexit_mame.py` (real MAME) |
| `Emulation` CHD | CHD extraction | `tests/test_emulation_chd.py` (4 new tests for NULL-disk fix) |

---

## Identified Separation Opportunities

| Current Coupling | Proposed Boundary | Rationale |
|------------------|-------------------|-----------|
| `Emulation` mixes **process mgmt** + **emulator prep** + **ROM discovery** + **CHD extraction** + **VGM** | Split: `ProcessRunner` (done) + `LaunchPreparer` (per-emulator) + `RomFinder` + `ChdExtractor` + `VgmPlayer` | Each is independently testable; `ProcessRunner` already clean |
| `DBMod.get_cmd_line_options()` does **reads + assembly** | Keep assembly in `DBMod` (or `cmdline.py` Phase 4.9); reads already in `GameRepository` | Phase 4.4 achieved read/assembly split; assembly stays in `DBMod` as orchestration |
| `emulator_launcher.py` builds `emurun` dict + calls `Emulation` prep | `LaunchPreparer` in Core could own `emurun` construction | Would make `emulator_launcher` thinner (just callbacks + execution) |
| `retroplayer_cache.py` calls `Emulation.find_roms/extract_rom` | OK — Retroplayer is GUI-specific; uses Core ROM discovery | No change needed |

---

## Behavior That Must Remain Compatible

- `LaunchCtx` / `RetroplayerCtx` dataclass fields — `emulator_launcher`/`retroplayer_cache` depend on them
- `Emulation.emurun` dict structure — keys: `emu_exe`, `args`, `working_dir`, `emulation_start`, `swl_name`, `set_name`, `description`, `publisher`, `set_clone`, `disks`, `folder`, `zips`, `chds`, `extract_files`, `extractcd`, `symlink`, `env`
- `Emulation.prepare_mame_run(ggdb, actset, dialog)` signature — called by `emulator_launcher`
- `Emulation.other_emulator(emu_infos, dialog, sleep)` signature — called by `emulator_launcher`
- `ProcessRunner.start(command, cwd, capture_output, env)` — used by `Emulation.start_managed_process`
- `Emulation.wait_for_completion(dialog, sleep)` → `(stdout, stderr)` — used by `emulator_launcher`
- `ggdb.get_cmd_line_options(set_id, name, machine_name, swl_name)` → `list[str]` — used by `Emulation.prepare_mame_run`
- `ggdb.get_disks(swl_name, set_name)` → `list[Row]` — used by `emulator_launcher` (disk selection) and `get_cmd_line_options`
- `ggdb.get_set_name(clone_id)` → `str` — used by `emulator_launcher` for `set_clone`
- `ggdb.write_status_after_play(set_id, seconds)` — called by `emulator_launcher` post-run
- `retroplayer_cache.run_retroplayer(ctx)` signature — called by `UMSA.run_emulator`
- `UMSA.run_emulator(emu_infos)` — entry point from GUI clicks/context menus

---

## Proposed Changes (Not Implemented)

1. **Remove dead code in `UMSA.run_emulator`** (lines 2545–2636) — trivial, no behavior change
2. **Extract `Emulation` emulator-specific prep** into `LaunchPreparer` or per-emulator modules:
   - `MameLaunchPreparer` (wraps `prepare_mame_run` + `get_cmd_line_options` delegation)
   - `ExodosLaunchPreparer` (`prepare_exodos_run`)
   - `MarpLaunchPreparer` (`prepare_marp_run`)
   - `GenericLaunchPreparer` (`other_emulator` + `demul`/`fsuae`/`flycast`)
   - `RomFinder` (`find_roms`, `find_nonmame_roms`)
   - `ChdExtractor` (`extract_chd`)
   - `RomExtractor` (`extract_rom`)
   - `VgmPlayer` (`play_vgm`, `play_random_vgm`, Lua socket)
3. **Move `emurun` dict construction** from `emulator_launcher` into `LaunchPreparer` — `emulator_launcher` becomes pure callback/execution orchestration
4. **Phase 4.9**: Move `get_cmd_line_options`/`create_cmdline` assembly to `umsa_core/cmdline.py` (after launch prep extraction clarifies ownership)
5. **Keep `retroplayer_cache.py` in GUI** — correctly separated, uses Core only for ROM discovery
---

## Extraction Completed (2026-10-21)

The following modules have been extracted from `Emulation` (originally 1221 lines, now 766 lines):

### New Modules Created

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `rom_finder.py` | 143 | ROM and non-MAME file discovery (`find_roms`, `find_nonmame_roms`) |
| `rom_extractor.py` | 67 | ZIP extraction and ROM-specific post-processing (`extract_rom`) |
| `chd_extractor.py` | 123 | CHD extraction, cancellation and cleanup (`extract_chd`, `CHDExtractionCancelled`, `CHDExtractionError`) |
| `launch_preparer.py` | 263 | Emulator-specific launch preparation (`prepare_mame_run`, `prepare_exodos_run`, `prepare_marp_run`, `other_emulator`, `demul`, `fsuae`, `flycast`) |
| `vgm_player.py` | 266 | VGM playback logic, header parsing, callbacks (`prepare_vgm_run`, `play_random_vgm_thread`, `play_vgm`) |

### Emulation Facade (766 lines)

The `Emulation` class now serves as a focused facade and lifecycle coordinator:

- **Constructor & configuration**: `__init__`, `launch_preparer`, `vgm_player` initialization
- **VGM state properties**: `playvgm`, `playintrovgm`, `playrandomvgm`, `vgm_info_callback`, `vgm_stopped_callback` (delegated to `VgmPlayer`)
- **Socket state & management**: `lua_socket`, `lua_server`, `lua_log_thread`, `lua_log_stop`, `vgm_port_env`, `_start_vgm_server`, `_accept_vgm_conn`, `_close_vgm_sockets`, `_close_accepted_conn`, `_stop_lua_log_reader`, `_start_lua_log_reader`, `_lua_log_reader`, `_drain_lua_log`, `_log_lua_line`, `send_vgmaction`, `_vgm_process_env`
- **Process lifecycle**: `run`, `_process_args`, `start_managed_process`, `managed_process_status`, `terminate_managed_process`, `kill_managed_process`, `read_managed_process_output`, `wait_for_completion`, `terminate`, `kill`, `after_run`
- **Delegated methods**: `prepare_exodos_run`, `prepare_marp_run`, `prepare_mame_run`, `find_nonmame_roms`, `find_roms`, `extract_chd`, `extract_rom`, `demul`, `fsuae`, `flycast`, `other_emulator`, `play_vgm_thread`, `play_random_vgm_thread`, `play_random_vgm`, `play_vgm` (all delegate to `LaunchPreparer` or `VgmPlayer`)
- **VGM playback**: `play_vgm`, `play_random_vgm` (thread management)

### Verification Results

All 887 tests pass (5 skipped for real-MAME integration):

```
887 passed, 5 skipped, 18 subtests passed in 14.19s
```

Key test categories verified:
- CHD extraction: `test_emulation_chd.py` (10 tests)
- Process management: `test_emulation_process.py` (2 tests)
- VGM callbacks: `test_emulation_vgm_callback.py` (4 tests)
- VGM Lua socket protocol: `test_lua_socket_log.py` (18 tests)
- VGM pre-exit logic: `test_vgmplay_preexit.py` (17 tests)
- VGM port handling: `test_vgmplay_port.py` (10 tests)
- Random VGM player: `test_random_vgm_player.py` (8 tests)
- Command line options: `test_cmd_line_options.py` (23 tests)
- Emulator launcher: `test_emulator_launcher.py` (5 tests)
- Architecture boundaries: `test_architecture_boundaries.py` (7 tests)

### Architecture Compliance

- Core modules remain Kodi-free (no `xbmc*` imports)
- No circular imports introduced
- `ProcessRunner` ownership unchanged
- No duplicate process lifecycle
- Public contracts preserved (all existing method signatures maintained)
- `emulator_launcher.py` and `retroplayer_cache.py` work without modification

### Deferred Work

The following items from the refactoring plan remain for future work:
- VGM pre-exit logic integration with real MAME (tests skipped, gated by `VGM_MAME_TESTS=1`)
- Phase 4.9 `database.py` reorganization (`cmdline.py`, `scan_progress.py`, `game_labels.py`)
- `gui.py` `UMSA` class extraction (Step 3)
- Screensaver `ui.py` extraction (Step 4)
- `database.py` further decomposition (Step 5)
