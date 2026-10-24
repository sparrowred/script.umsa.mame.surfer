# GUI Audit — `plugin.program.umsa.mame.surfer/resources/lib/gui.py`

**Audited at:** git HEAD `4186b5f5dd3479b19df84215d1fa21a4cbb38f29` (2026-10-23), split completed against HEAD `ace91cb`  
**File size:** ~1231 lines (adapter), single `UMSA` class (inherits `xbmcgui.WindowXMLDialog`) + module-level constants, helpers, `VgmCommandMonitor`, `GamelistCtx`, `RetroplayerCtx`, `main()`; workflows in `resources/lib/umsa_gui/` (15 modules, ~2000 lines)

> **Status: split done (2026-10-21).** `gui.py` is now the Kodi adapter
> (1231 lines) and the workflows live in `resources/lib/umsa_gui/`
> (15 modules, 2,000 lines). See
> [Current Module Layout](#current-module-layout) at the end of this file.

---

## Responsibility Map — `UMSA` Class

| Responsibility | Methods / Attributes | Kodi-Dependent? | Extraction Candidate |
|----------------|----------------------|-----------------|---------------------|
| **Window lifecycle** | `__init__`, `onInit`, `exit`, `main()` (module) | Yes — `xbmcgui.WindowXMLDialog`, `xbmcaddon`, `xbmcvfs` | No — core GUI adapter |
| **Input / focus / navigation** | `onFocus`, `onAction`, `onClick`, `ACTION_*` constants, `dummy`, `enter`, `selected_control_id`, `main_focus` | Yes — action codes, control IDs | No — Kodi event handling |
| **Main menu / context handling** | `build_main_menu`, `build_sublist_menu`, `onAction` (MAIN_MENU, LISTMODE_MENU branches), `M_*` constants | Yes — `xbmcgui.Dialog`, `ListItem`, control IDs | Partial — menu *structure* could be data-driven |
| **Gamelist / filtering** | `update_gamelist`, `popup_gamelist`, `gamelist_click`, `gamelist_context`, `gamelist_move`, `gamelist_switch_filter`, `filter_category`, `filter_content`, `set_filter_content`, `build_filter_lists` (imported), `GAMELIST_STRATEGIES` (imported) | Yes — `ListItem`, control IDs, `Dialog` | **Yes** — `gamelist_strategies.py` already extracted; filter UI could be separate |
| **Software/set/machine selection** | `select_software`, `software_move`, `machine_move`, `fill_set_list`, `choose_media`, `show_rec`, `open_software` (screensaver handoff) | Yes — `ListItem`, `Player`, control IDs | Partial — selection *logic* (`select_software` calls `ggdb.get_all_for_software`) could be a service |
| **Artwork / media / info display** | `create_artworklist`, `show_artwork`, `search_snaps`, `create_gui_element_from_snap`, `get_machine_pic`, `create_artworklist`, `TEXTLIST` population, `IMAGE_BIG_LIST`/`IMAGE_LIST` population | Yes — `ListItem`, `ControlImage`, control IDs, `xbmcvfs` | **Yes** — artwork resolution uses Core (`resolve_artwork_path`, `categorize_art_type`); display is GUI |
| **Scan orchestration** | `update`, `run_scan_with_progress` (imported), `scan_thread`, `progress_dialog` | Yes — `DialogProgress`, `Thread`, `xbmc.sleep` | **Yes** — progress callbacks injected; scan logic in Core scanners |
| **Screensaver / VGM communication** | `VgmCommandMonitor` (class), `start_screensaver`, `stop_screensaver`, `get_screensaver_mode`, `_show_vgm_info`, `_hide_vgm_info`, `_handle_vgm_action`, `open_software`, `EMULATOR_RUNNING_PROPERTY` | Yes — `xbmc.Monitor`, `xbmc.executebuiltin`, window properties | Partial — protocol (`VGM_SENDER`, notifications) could be in Core adapter |
| **Emulator startup / completion** | `run_emulator`, `_add_or_update_emu_output`, `_notify_final_launch`, `LaunchCtx` (dataclass), `RetroplayerCtx` (dataclass) | Yes — `DialogProgress`, `Player`, `xbmc.sleep`, `Dialog` | **Yes** — `emulator_launcher.py` + `retroplayer_cache.py` already extracted; `run_emulator` has **dead code** after `launch_emulator` return |
| **Database access / state persistence** | `ggdb` (`DBMod`), `filter_lists`, `act_filter`, `last`/`lastptr`, `_remember_and_select`, `_save_lastgames`, `run_startup_import`, `read_settings` | Yes — `DBMod` (Core), `xbmcaddon` settings | Partial — `lastgames`/`filter` persistence moving to `status.db` (Phase 4.6.1) |
| **Settings management** | `read_settings`, `load_all_settings` (imported), `artwork_source_roots` | Yes — `xbmcaddon.Addon` settings | **Yes** — `settings_adapter.py` already extracted |

---

## Workflow Grouping

### 1. GUI Lifecycle & Initialization
- `__init__` (lines 239–293): attribute init, settings check, `read_settings()`, `set_emulator_running(False)`
- `onInit` (lines 295–397): control visibility, `Player`, `Dialog*` init, aspect-ratio adjustment, `Emulation` init, `VgmCommandMonitor`, `DBMod` creation (or DB download + background scan), `run_startup_import()`, filter load, `lastgames` load, initial `select_software`
- `exit` (lines 2638–2671): `_save_lastgames()`, VGM cleanup, scan thread join, `ggdb.close()`, `close()`
- `main()` (module, lines 2673–2689): logging setup, `UMSA` instantiation, `doModal()`

### 2. Input, Focus, Navigation
- `onFocus` (lines 497–535): popup closing logic, `dummy`/`enter` management
- `onAction` (lines 679–920): **massive** method (240+ lines) — routes by `selected_control_id` (SOFTWARE_BUTTON, MAIN_MENU, LISTMODE_MENU, SYSTEM_WRAPLIST, TEXTLIST, GAME_LIST, FILTER_*, SET_LIST)
- `onClick` (lines 580–671): clicks on SOFTWARE_BUTTON/SET_LIST/SYSTEM_WRAPLIST → `run_emulator`; TEXTLIST → series/text viewer; GAME_LIST_OPTIONS → search/play-status/sort; FILTER_OPTIONS → filter select all/none/invert

### 3. Menu System
- `build_main_menu` (lines 1086–1140): constructs context menu items (series, media, emulators, search, filter, screensaver, update, settings, exit) with dynamic labels
- `build_sublist_menu` (lines 1025–1084): listmode submenu (all, series, maker, category, recommended, year, players, source/swl, screensaver, play status)
- `SUBMENU_ORDER` constant defines display order

### 4. Gamelist & Filtering
- `update_gamelist` (lines 1819–1894): dispatches to `GAMELIST_STRATEGIES` (in `gamelist_strategies.py`), handles empty/single-result cases, builds filter toggle options, calls `popup_gamelist`
- `popup_gamelist` (lines 1896–1922): populates `GAME_LIST` control with `ListItem`s, sets label/options/sort, calls `gamelist_move` for initial artwork
- `gamelist_click` (lines 1195–1354): **large** (160 lines) — handles prev/next, select-label dispatch (source, swl, category, maker, year, players, emulator choices, media, software selection via `_remember_and_select`)
- `gamelist_context` (lines 1356–1387): emulator reconfigure/remove, filter toggle
- Filter UI: `filter_category` (load/save filter dialogs), `filter_content` (active/inactive toggle), `set_filter_content` (partition via `build_filter_lists`)

### 5. Software/Set/Machine Selection
- `select_software` (lines 2087–2264): **core display method** (177 lines) — calls `ggdb.get_all_for_software`, fills `SYSTEM_WRAPLIST`/`SET_LIST`, sets borders, creates artwork list, plays video/intro VGM, shows artwork/info, updates indicators
- `software_move` (lines 1935–1951): left/right navigation in `last` history (10-entry window), `_remember_and_select` on right-past-end
- `machine_move` (lines 1924–1933): updates set list + artwork on machine wrap selection
- `fill_set_list` (lines 2029–2085): builds `SET_LIST` items with labels, properties (title, year, maker, machine)
- `choose_media` (lines 1735–1802): builds media list (video, manual, VGM, youtube, MARP) → `popup_gamelist`
- `show_rec` (lines 1804–1817): parses recommended games from DAT → `popup_gamelist`
- `open_software` (lines 1527–1531): screensaver handoff → `_remember_and_select`

### 6. Artwork / Media / Info Display
- `create_artworklist` (lines 2278–2335): iterates `self.info`, builds `right_pics`/`left_pics`/`localsnaps`/`video`/`manual` per set using Core `resolve_artwork_path`, `categorize_art_type`, `find_local_snapshots`; sums play stats
- `show_artwork` (lines 2337–2465): populates `IMAGE_BIG_LIST` (right) and `IMAGE_LIST` (left) controls; populates `TEXTLIST` with DAT info + play status; updates `SHADOW_DAT` visibility
- `search_snaps` (lines 2266–2276): local snapshot search via Core `find_local_snapshots`
- `get_machine_pic` (lines 573–578): machine artwork path via Core `get_machine_artwork_path`

### 7. Scan Orchestration
- `update` (lines 1656–1733): 'db' → `download_and_update_umsa_db` + `open_db`; 'dat'/'exo'/'gb64'/'art' → `run_scan_with_progress` with progress dialog + `xbmc.sleep`
- Progress callbacks injected (`xbmc.sleep`, `DialogProgress.update`)

### 8. Screensaver / VGM Communication
- `VgmCommandMonitor` (lines 213–235): `xbmc.Monitor` subclass, `onNotification` parses `VGM_SENDER` methods → `open_software` or `_handle_vgm_action`
- `start_screensaver` / `stop_screensaver` / `get_screensaver_mode`: window property `UMSA.Screensaver.Mode` + `RunScript(screensaver.umsa.mame.surfer, token)`
- `_show_vgm_info` / `_hide_vgm_info`: `publish_vgm_info`/`clear_vgm_info` (adapter) + local label
- `_handle_vgm_action`: volume/next/stop via `emulation.send_vgmaction`

### 9. Emulator Launch (Split Across Files)
- `run_emulator` (lines 2504–2636): **entry point** — creates `LaunchCtx`/`RetroplayerCtx`, calls `launch_emulator(ctx)` (extracted) or `run_retroplayer(ctx)`
  - **Dead code** (lines 2545–2636): legacy body duplicating `emulator_launcher.py` logic — **should be removed**
- `emulator_launcher.py`: `LaunchCtx` dataclass, `launch_emulator(ctx)` — orchestrates prep, disk selection, emulator-specific prep, process execution, status write, notification
- `retroplayer_cache.py`: `run_retroplayer(ctx)` — cache folder setup, ROM copy/extract, `xbmc.Player` game launch

### 10. Database / Persistence
- `ggdb` = `DBMod` instance (created in `onInit` or `update('db')`)
- `filter_lists` / `act_filter`: loaded from `status.db` via `load_filter_selections` / `define_filter` (Phase 4.6.1)
- `last` / `lastptr`: loaded from `status.db` via `load_lastgames` (Phase 4.6.1), padded with `get_random_id`
- `_remember_and_select` (lines 473–493): inserts into `last`, calls `select_software`, **rolls back on failure**, persists on success (new 100-entry cap)
- `_save_lastgames` (lines 467–471): `ggdb.save_lastgames(self.last)`
- `run_startup_import` (lines 400–465): drives `ggdb.run_legacy_import()`, shows notifications
- `read_settings` (lines 1533–1563): Core settings via `get_core_settings()` + GUI/emulator settings via `settings_adapter.load_all_settings`

---

## Large Methods (>100 lines)

| Method | Lines | Responsibilities | Recommendation |
|--------|-------|------------------|----------------|
| `onAction` | 679–920 (~240) | Routes all input by control ID; 10+ control-ID branches | Split into per-control handlers or dispatch table |
| `gamelist_click` | 1195–1354 (~160) | Handles 15+ select-label cases, prev/next, media, emulator launch | Delegate to `gamelist_strategies`-style handlers |
| `select_software` | 2087–2264 (~177) | DB fetch, UI population, artwork, video/VGM, indicators | Split: data fetch → UI population → media start |
| `create_artworklist` | 2278–2335 (~57) | Iterates all sets, resolves artwork, categorizes, sums stats | Could be a `ArtworkPresenter` service |
| `show_artwork` | 2337–2465 (~128) | Populates 3 controls (IMAGE_BIG_LIST, IMAGE_LIST, TEXTLIST) | Split per control; DAT info → separate presenter |
| `update` | 1656–1733 (~77) | DB download + 4 scan types with progress | Already delegates to Core; progress callback injection is fine |
| `run_emulator` | 2504–2636 (~132) | **Dead code after line 2543** — legacy body duplicates `emulator_launcher` | **Remove lines 2545–2636** |

---

## Dead Code / Stale Compatibility

1. **`run_emulator` legacy body (lines 2545–2636)**: After `launch_emulator(ctx)` returns at line 2543, a 92-line block duplicates `emulator_launcher.py` logic (process start, wait, output capture, status write, notification). **Unreachable** — `launch_emulator` handles all non-retroplayer paths. **Remove.**

2. **`lastsaver.txt` handling**: `load_lastsaver` imported but never used (no writer exists). `CORE_DATA_PATHS.lastsaver_file` passed to `GamelistCtx` but `last_saver` strategy now uses `ggdb.get_screensaver_history()`. **Remove import and context field.**

3. **`batomame` dict**: Loaded in `read_settings` → `self.batomame`, passed to `LaunchCtx`/`RetroplayerCtx`. Used only in `retroplayer_cache.py` for cache folder mapping. **Keep** — active.

4. **`vgms` set**: Built in `select_software` (lines 2190–2200) from DAT `others` field; used in `choose_media` for VGM list. **Keep** — active.

5. **`playvideo` / `already_playing`**: Video playback control flags. **Keep** — active.

6. **`M_LSSAVER` (84) / `last_saver` strategy**: Now uses database-backed screensaver history (Phase 4.6.2). Legacy `lastsaver.txt` code path dead. **Keep strategy** (uses `ggdb.get_screensaver_history()`).

---

## Shared Mutable State & Implicit Order Dependencies

| State | Writers | Readers | Order Dependency |
|-------|---------|---------|------------------|
| `self.ggdb` | `onInit`, `update('db')` | All DB methods | Must be initialized before `select_software`, `update_gamelist`, `run_emulator` |
| `self.filter_lists` / `self.act_filter` | `onInit` (load), `filter_category` (load/save), `gamelist_switch_filter` (toggle) | `update_gamelist` → strategies → `ggdb.get_by_*` | Filter must be defined via `ggdb.define_filter` before gamelist queries |
| `self.last` / `self.lastptr` | `onInit` (load + pad), `_remember_and_select`, `software_move` | `onInit` (initial select), `software_move`, `gamelist_click` (software select) | `lastptr` must be valid index; `_remember_and_select` rolls back on failure |
| `self.info` / `self.actset` | `select_software`, `machine_move`, `SET_LIST` click | `show_artwork`, `create_artworklist`, `run_emulator`, `choose_media`, `gamelist_click` | `select_software` must run first; `actset` updated before dependent calls |
| `self.all_art` / `self.all_dat` | `select_software` | `create_artworklist`, `choose_media`, `show_artwork`, `gamelist_click` | Set by `get_all_for_software` |
| `self.vgms` | `select_software` | `choose_media` | Built during `select_software` |
| `self.emulation` | `onInit` | `run_emulator`, `choose_media` (VGM), `_handle_vgm_action` | Initialized in `onInit` before any emulator action |
| `self.scan_thread` | `onInit` (dat scan), `update` (scans) | `exit` (join), `update` (sanity check) | Must check `.is_alive()` before new scan |

---

## Extraction Candidates (UI-Independent Logic)

| Logic | Current Location | Could Move To | Reason |
|-------|------------------|---------------|--------|
| Artwork resolution per set | `create_artworklist` (lines 2288–2331) | Core `artwork.py` or new `gui/artwork_presenter.py` | Uses only Core helpers (`resolve_artwork_path`, `categorize_art_type`, `find_local_snapshots`) + `artwork_source_roots` |
| DAT info formatting for TEXTLIST | `show_artwork` (lines 2426–2453) | New `gui/dat_presenter.py` | Pure formatting, no Kodi controls |
| Play status formatting | `show_artwork` (lines 2410–2424), `choose_media` | Core `make_time_nice` (already) + new presenter | `make_time_nice` in Core; formatting is presentation |
| Filter list partitioning | `set_filter_content` → `build_filter_lists` (imported from Core) | Already in Core (`database.build_filter_lists`) | ✅ Already extracted |
| Gamelist strategy dispatch | `update_gamelist` → `GAMELIST_STRATEGIES` | Already in `gamelist_strategies.py` | ✅ Already extracted |
| Emulator launch prep | `run_emulator` → `LaunchCtx` + `emulator_launcher.launch_emulator` | Already in `emulator_launcher.py` | ✅ Already extracted (but dead code remains) |
| Retroplayer cache/launch | `run_emulator` → `RetroplayerCtx` + `retroplayer_cache.run_retroplayer` | Already in `retroplayer_cache.py` | ✅ Already extracted |
| Settings loading | `read_settings` → `settings_adapter.load_all_settings` | Already in `settings_adapter.py` | ✅ Already extracted |
| Legacy import + notification | `run_startup_import` | Could be `gui/startup_import.py` | Separates startup concerns |

---

## Existing Extracted Modules (Reuse, Don't Replace)

| Module | Responsibility | Used By |
|--------|----------------|---------|
| `gamelist_strategies.py` | 13 strategy functions (`all_games`, `software_list`, `category`, `year`, `players`, `maker`, `play_status`, `machine`, `all_emulators`, `source`, `last_saver`, `series`, `recommended`, `search_new`, `search`) | `UMSA.update_gamelist` |
| `emulator_launcher.py` | `LaunchCtx`, `launch_emulator` — non-retroplayer launch orchestration | `UMSA.run_emulator` |
| `retroplayer_cache.py` | `run_retroplayer` — Retroplayer cache prep + launch | `UMSA.run_emulator` (exe='kodi') |
| `settings_adapter.py` | `load_all_settings` — merges Core + GUI + emulator settings | `UMSA.read_settings` |

---

## Behavior That Must Remain Compatible

- Control IDs (`SOFTWARE_BUTTON=4000`, `GAME_LIST=4007`, `MAIN_MENU=4901`, etc.) — skin contract
- Action codes (`ACTION_ENTER=7`, `ACTION_CONTEXT=117`, `ACTION_CANCEL_DIALOG=(9,10,51,92,110)`, etc.) — remote/keyboard mapping
- `EMULATOR_RUNNING_PROPERTY` — shared with screensaver add-on (identical name required)
- `UMSA.Screensaver.Mode` window property — screensaver communication
- `VGM_SENDER` notification protocol — screensaver → frontend
- `select_software` return `True`/`False` — `_remember_and_select` depends on it for rollback
- `ggdb` facade methods — `define_filter`, `get_by_*`, `execute_statement`, `get_all_for_software`, `get_cmd_line_options`, `get_disks`, `get_emulators`, `save_emulator`, `write_status_after_play`, `save_lastgames`, `load_lastgames`, `load_filter_selections`, `save_filter_selections`, `list_filter_names`, `run_legacy_import`, `record_screensaver_display`, `get_screensaver_history`
- `Emulation` methods — `prepare_mame_run`, `play_vgm`, `play_random_vgm`, `send_vgmaction`, `start_managed_process`, `wait_for_completion`, `find_roms`, `extract_rom`, `extract_chd`

---

## Proposed Future Changes (Not Yet Implemented)

1. **Remove dead code in `run_emulator` (lines 2545–2636) — trivial, no behavior change** ✅ **COMPLETED** (2026-10-20)
2. **Split `UMSA` into coordinator + workflow modules** — ✅ **COMPLETED** (2026-10-21), see [Current Module Layout](#current-module-layout):
   - `umsa_gui/menu.py` — `build_main_menu`, `build_sublist_menu`, menu constants
   - `umsa_gui/gamelist.py` — `popup_gamelist`, `gamelist_move`, `gamelist_switch_filter`, `show_fulllist`, `update_gamelist`
   - `umsa_gui/gamelist_actions.py` — `gamelist_click`, `gamelist_context`
   - `umsa_gui/filter_ui.py` — `filter_category`, `filter_content`, `set_filter_content`, `close_filterlist`
   - `umsa_gui/artwork_presenter.py` — `create_artworklist`, `show_artwork`, `search_snaps`, `get_machine_pic`
   - `umsa_gui/software_selector.py` — `select_software`, `software_move`, `machine_move`, `fill_set_list`, `open_software`
   - `umsa_gui/media_list.py` — `choose_media`, `show_rec`
   - `umsa_gui/scan_orchestrator.py` — `update`, progress callbacks
   - `umsa_gui/screensaver_vgm.py` — `start/stop/get_screensaver_mode`, `_show/hide_vgm_info`, `_handle_vgm_action`
   - `umsa_gui/startup_import.py` — `run_startup_import`, `remember_and_select`, `save_lastgames`
   - `umsa_gui/emulator_setup.py` — `configure_emulator`, `get_diff_emulator`, `marp_replayer`, emulator output/notification
   - `umsa_gui/constants.py`, `umsa_gui/paths.py`, `umsa_gui/optional_plugins.py` — shared constants, add-on paths, optional plugin probes
   - `UMSA` retains: `__init__`, `onInit`, `onFocus`, `onAction` (dispatch), `onClick` (dispatch), `exit`, `run_emulator`, `main()`
3. **Extract `Emulation` emulator-specific prep** (see `emulation_audit.md`)
4. **Reassess `DBMod` after Phase 4.9** — move non-DB helpers (`download_and_update_umsa_db` → done, `run_scan_with_progress`, `split_gamename`, `COUNTRIES`, `make_time_nice`, `get_best_machine_for_set`, `parse_recommended_games`, `build_filter_lists`, `create_cmdline`, `get_cmd_line_options` assembly) to focused modules

---

## Current Module Layout

Split completed 2026-10-21 against HEAD `00bf063`. `gui.py` is the Kodi
adapter; the workflows live in the new package `resources/lib/umsa_gui/`.
The package is **not** named `gui/` on purpose: `addon.py` puts
`resources/lib` on `sys.path` and imports `gui`, so a `gui/` package would
shadow `gui.py`.

### Adapter — `resources/lib/gui.py` (1231 lines)

| Part | Lines | Content |
|------|-------|---------|
| Imports / re-exports | ~140 | `umsa_gui.constants` (control IDs, action codes, `M_*`), `umsa_gui.paths`, `umsa_gui.optional_plugins` |
| `__all__` | ~90 | Explicit public API (all names that existed before the split) |
| `VgmCommandMonitor` | 22 | `xbmc.Monitor` subclass, unchanged |
| `UMSA` | 925 | `__init__`, `onInit`, `onFocus`, `onClick`, `onAction`, `exit`, `run_emulator` (dispatch), `read_settings`, `artwork_source_roots` + thin wrappers for every extracted workflow |
| `RetroplayerCtx` / `main()` | ~40 | Unchanged |

### Workflow package — `resources/lib/umsa_gui/`

| Module | Lines | Public functions |
|--------|-------|------------------|
| `constants.py` | 110 | control IDs, action codes, `M_*`, `SUBMENU_ORDER`, `FILTER_CATEGORY_KEYS`, `EMULATOR_RUNNING_PROPERTY`, `WAIT_GUI`/`WAIT_PLAYER` |
| `paths.py` | 17 | `ADDON`, `ADDON_PATH`, `RESOURCE_LIB`, `SKIN_MEDIA_FOLDER` |
| `optional_plugins.py` | 18 | `KODIPDF`, `KODIYT`, `play_pdf` (optional add-on probes) |
| `menu.py` | 156 | `build_main_menu`, `build_sublist_menu` |
| `gamelist.py` | 227 | `GamelistCtx`, `update_gamelist`, `popup_gamelist`, `gamelist_move`, `gamelist_switch_filter`, `show_fulllist` |
| `gamelist_actions.py` | 223 | `gamelist_click`, `gamelist_context` |
| `filter_ui.py` | 195 | `empty_filter_lists`, `close_filterlist`, `filter_category`, `filter_content`, `set_filter_content` |
| `artwork_presenter.py` | 262 | `create_gui_element_from_snap`, `create_artworklist`, `show_artwork`, `search_snaps`, `get_machine_pic` |
| `software_selector.py` | 303 | `select_software`, `software_move`, `machine_move`, `fill_set_list`, `open_software` |
| `media_list.py` | 96 | `choose_media`, `show_rec` |
| `emulator_setup.py` | 160 | `get_diff_emulator`, `configure_emulator`, `marp_replayer`, `add_or_update_emu_output`, `notify_final_launch` |
| `scan_orchestrator.py` | 97 | `update` |
| `screensaver_vgm.py` | 86 | `get_screensaver_mode`, `start_screensaver`, `stop_screensaver`, `show_vgm_info`, `hide_vgm_info`, `handle_vgm_action` |
| `startup_import.py` | 109 | `run_startup_import`, `save_lastgames`, `remember_and_select` |

### Conventions used by the split

- Workflow functions take the `UMSA` instance as first argument (`gui`) and
  return nothing (or a value the wrapper forwards).
- Cross-workflow calls go through the instance (`gui.select_software(...)`,
  `gui._save_lastgames()`) so that overrides and the original `self.`
  dispatch semantics are preserved.
- `update_gamelist` and `update` take the values they used to read from
  module globals as parameters (`lastsaver_path`, `core_data_paths`) so that
  no stub-missing attribute is touched at import time.
- The `gamelist` module is imported as `gamelist_workflows` in `gui.py`:
  the public method `popup_gamelist(self, gamelist, ...)` would otherwise
  shadow the module name.
- `gui.py` re-exports every name that existed before the split and lists them
  in `__all__`; `tests/test_umsa_gui_workflows.py` asserts the parity.

### Verification

- `tests/test_umsa_gui_workflows.py` (47 tests) — new, local-only (`tests/` is
  gitignored): covers every workflow module with a fake `UMSA` instance.
- `tests/test_gui_oninit_first_start.py` (5 tests) — new, local-only: pins the
  first-start branch of `UMSA.onInit` (database download in the foreground,
  DAT scan in a worker thread).
- `tests/test_gui_history_navigation.py` — unchanged, still binds the same
  `UMSA` methods.
- `tests/test_scan_artwork.py` — the AST check for the artwork scan roots now
  points at `umsa_gui/scan_orchestrator.py` (the dict moved with the code).
- Full suite: **1081 passed, 5 skipped, 18 subtests**.

### Fixes found during the final verification (2026-10-21)

- **First-start DAT scan ran in the foreground.** `UMSA.onInit` started the
  background scan with `Thread(target=self.update('dat'))`: the call was
  evaluated while the thread was being built, so the DAT scan ran
  synchronously on the calling thread and the thread itself had no target.
  The bug existed since commit `9750a44` and survived the extraction.
  Fixed to `Thread(target=self.update, args=('dat',))` — the same pattern the
  `M_UPD` branches of `onAction` already used — and pinned by
  `tests/test_gui_oninit_first_start.py`.

### Still open (maintainer, requires a real Kodi runtime)

- First-run database download and the background DAT scan.
- Menu navigation, gamelist/filter handling, software selection, artwork.
- Emulator launch, Retroplayer handoff, screensaver handoff, VGM controls.
- See `release-plan.md` open manual areas for the three explicit remaining areas.
