# Prioritized Refactoring Plan

**Based on:** Architecture audit of `gui.py`, `ui.py`, `emulation.py`, `umsa_core` package, emulator launch path  
**Principle:** Small, independently testable changes; preserve all public contracts; prioritize structural clarity over line-count reduction

---

## Step 1: Remove Dead Code in `UMSA.run_emulator()` (Trivial, Zero Risk) ✅ **COMPLETED**

| Aspect | Detail |
|--------|--------|
| **Goal** | Delete unreachable legacy body (lines 2545–2636) after `launch_emulator(ctx)` / `run_retroplayer(ctx)` return |
| **Files** | `plugin.program.umsa.mame.surfer/resources/lib/gui.py` |
| **Responsibility moved** | None — code is dead duplicate of `emulator_launcher.py` |
| **Contracts unchanged** | `UMSA.run_emulator(emu_infos)` signature, `LaunchCtx`/`RetroplayerCtx`, `launch_emulator`, `run_retroplayer` |
| **Tests** | `tests/test_frontend_entrypoint.py` (7 passed), `tests/test_emulator_launcher.py` (5 passed), `tests/test_architecture_boundaries.py` (7 passed) |
| **Risk** | None — code is provably unreachable (two `return` statements before it) |
| **Dependencies** | None — can be done immediately |
| **Acceptance** | ✅ `gui.py` lines 2545–2636 removed; `run_emulator` now ends at line 2542; 19 relevant tests pass |
| **Completed** | 2026-10-20 — dead block (92 lines) removed; no imports removed (all used elsewhere in `gui.py`); no behavior change |

---

## Step 2: Extract `Emulation` Emulator-Specific Preparation (High Value, Medium Risk) ✅ **COMPLETED**

| Aspect | Detail |
|--------|--------|
| **Goal** | Split `Emulation` (1200 lines) into focused modules: per-emulator preparers, ROM/CHD finders/extractors, VGM player |
| **Files** | `script.module.umsa.core/lib/umsa_core/emulation.py` → new modules under `umsa_core/` |
| **Modules created** | <ul><li>`launch_preparer.py` — `LaunchPreparer` with `prepare_mame_run`, `prepare_exodos_run`, `prepare_marp_run`, `other_emulator`, `demul`, `fsuae`, `flycast`</li><li>`rom_finder.py` — `find_roms`, `find_nonmame_roms`</li><li>`rom_extractor.py` — `extract_rom`</li><li>`chd_extractor.py` — `extract_chd` (keeps `CHDExtractionCancelled`/`CHDExtractionError`)</li><li>`vgm_player.py` — `prepare_vgm_run`, `play_random_vgm_thread`, `play_vgm`, VGM callbacks</li></ul> |
| **Responsibility moved** | Emulator-specific prep, ROM/CHD discovery/extraction, VGM playback — **out of `Emulation`** |
| **Contracts unchanged** | <ul><li>`Emulation.__init__` (keeps `ProcessRunner`, config, callbacks)</li><li>`Emulation.prepare_mame_run(ggdb, actset, dialog)` → delegates to `LaunchPreparer`</li><li>`Emulation.prepare_exodos_run(emu_infos)` → delegates to `LaunchPreparer`</li><li>`Emulation.prepare_marp_run(emu_infos)` → delegates to `LaunchPreparer`</li><li>`Emulation.other_emulator(emu_infos, dialog, sleep)` → delegates to `LaunchPreparer`</li><li>`Emulation.find_roms`/`find_nonmame_roms` → delegates to `RomFinder`</li><li>`Emulation.extract_rom` → delegates to `RomExtractor`</li><li>`Emulation.extract_chd` → delegates to `ChdExtractor`</li><li>`Emulation.play_vgm`/`play_vgm_thread`/`play_random_vgm`/`play_random_vgm_thread` keep their signatures and own the worker thread and the socket lifecycle; the run preparation and the random candidate loop are delegated to `VgmPlayer`</li></ul> |
| **Tests** | <ul><li>`tests/test_emulation_process.py` (process mgmt)</li><li>`tests/test_emulation_chd.py` (CHD extraction + NULL-disk fix)</li><li>`tests/test_emulation_vgm_callback.py` (VGM callback)</li><li>`tests/test_vgmplay_preexit.py` + `test_vgmplay_preexit.lua` (Lua pre-exit)</li><li>`tests/test_vgm_preexit_mame.py` (real MAME, gated)</li><li>`tests/test_emulator_launcher.py` (integration via `launch_emulator`)</li></ul> |
| **Risk** | Medium — `Emulation` is central; `emurun` dict structure must stay identical; `ProcessRunner` integration unchanged |
| **Dependencies** | Step 1 (clean `run_emulator` first); `GameRepository` reads stable (Phase 4.4 done) |
| **Acceptance** | ✅ `emulation.py` is a 592-line facade (keeps `ProcessRunner` integration, `emurun` management, `wait_for_completion`, `after_run`, VGM socket mgmt)<br>✅ All existing tests pass unchanged (1081 passed, 5 skipped)<br>✅ `emulator_launcher.launch_emulator` works without modification<br>✅ Core modules remain Kodi-free; no circular imports; `ProcessRunner` ownership unchanged |

---

## Step 2b: Callback Signature Fix (2026-10-21) ✅ **COMPLETED**

Following the extraction in Step 2, a correctness issue was identified and fixed:

### Problem
The `Emulation` class injected lambdas that forwarded calls to facade methods (`Emulation.find_roms`, `Emulation.extract_chd`, etc.) which had incompatible signatures with what `LaunchPreparer` expected:

| Callback | `LaunchPreparer` Expected | Emulation Facade Provided |
|----------|--------------------------|---------------------------|
| `find_roms` | `(emurun, rom_paths)` | `(swl_name=None, set_name=None)` |
| `find_nonmame_roms` | `(emurun, nonmame, exodos_shell)` | `(exodos_shell='')` |
| `extract_rom` | `(emurun)` | `()` |
| `extract_chd` | `(emurun, chdman_exe, sleep, dialog)` | `(sleep=None, dialog=None)` |

The lambdas passed arbitrary arguments to facade methods that ignored them and operated on `self.emurun` internally. A `try/except TypeError` block in `LaunchPreparer.other_emulator()` silently swallowed signature mismatches, masking the bug.

### Fix Applied
1. **`Emulation.__init__`**: Replaced lambdas with direct references to core-level functions (`find_roms`, `find_nonmame_roms`, `extract_rom`, `extract_chd`) that have the correct signatures expected by `LaunchPreparer`.

2. **`LaunchPreparer.other_emulator()`**: Removed the `try/except TypeError` block that was hiding callback signature mismatches.

3. **`vgm_player.py`**: Fixed import of `parse_vgm_header` and `calculate_playback_plan` to come from `umsa_core.vgm_header` directly instead of through `umsa_core.emulation`, eliminating an unnecessary runtime dependency on the `Emulation` module.

### Tests Updated
- `tests/test_emulation_chd.py::test_other_emulator_propagates_chd_cancellation_before_preparing_launch` — Now injects mock into `LaunchPreparer._extract_chd` and `LaunchPreparer._find_roms` directly
- `tests/test_emulation_vgm_callback.py::test_random_vgm_info_is_forwarded_through_injected_callback` — Now patches `umsa_core.vgm_header.parse_vgm_header` instead of `umsa_core.emulation.parse_vgm_header`

### Verification Results (at the time of this step)
- **All 887 tests passed** (5 skipped for real-MAME integration) — historical count at Step 2b commit
- Current full suite at audited HEAD: **1081 passed, 5 skipped, 18 subtests**
- Architecture boundary tests pass (7/7)
- Command-line options tests pass (23/23)
- Emulator launcher tests pass (5/5)
- Random VGM player tests pass (8/8)
- Lua socket log tests pass (30/30)
- CHD extraction tests pass (10/10)
- VGM callback tests pass (4/4)

---

## Step 2c: VGM Socket Transport Extraction (2026-10-21) ✅ **COMPLETED**

Following the callback signature fix (Step 2b), the VGM socket transport and Lua log protocol were extracted from `Emulation` into a dedicated `vgm_socket.py` module to complete the separation of VGM concerns.

| Aspect | Detail |
|--------|--------|
| **Goal** | Extract VGM TCP transport lifecycle, Lua log protocol, connection acceptance, command sending, and log frame parsing from `Emulation` into a dedicated `VgmSocketServer` class |
| **Files** | `script.module.umsa.core/lib/umsa_core/emulation.py` → new `umsa_core/vgm_socket.py` |
| **Module created** | `vgm_socket.py` — `VgmSocketServer` with `start_server`, `wait_for_connection`, `send_command`, `close_client`, `close_server`, `_start_reader`, `_stop_reader`, `_drain_buffer`, `_forward_log_frame` |
| **Responsibility moved** | VGM TCP transport lifecycle, Lua log protocol, connection acceptance, command sending, log frame parsing — **out of `Emulation`** |
| **Contracts unchanged** | <ul><li>`Emulation` public methods preserved via delegation: `_start_vgm_server`, `_accept_vgm_conn`, `_close_vgm_sockets`, `send_vgmaction`, `_vgm_process_env`, `_start_lua_log_reader`, `_stop_lua_log_reader`, `_close_accepted_conn`, `_drain_lua_log`</li><li>Protocol constants re-exported: `LUA_LOG_TAG`, `LUA_LOG_LEVELS`, `LUA_LOG_FALLBACK_LEVEL`, `LUA_LOG_MSG_PREFIX`, `LUA_READ_POLL_TIMEOUT`, `LUA_READER_JOIN_TIMEOUT`, `LUA_LOG_MAX_LINE_BYTES`, `VGMPLAY_DEFAULT_PORT`, `_parse_vgmplay_port`, `parse_lua_log_line`</li><li>`Emulation` socket state properties: `lua_server`, `lua_socket`, `lua_log_thread`, `lua_log_stop`</li></ul> |
| **Tests** | <ul><li>`tests/test_lua_socket_log.py` (30 tests — Lua socket protocol)</li><li>`tests/test_vgmplay_port.py` (10 tests — port handling)</li><li>`tests/test_vgmplay_preexit.py` (17 tests — Lua pre-exit logic)</li><li>`tests/test_emulation_vgm_callback.py` (4 tests — VGM callbacks)</li><li>`tests/test_random_vgm_player.py` (8 tests — random VGM playback)</li></ul> |
| **Risk** | Medium — `Emulation` is central; socket lifecycle must remain identical; protocol must not change |
| **Dependencies** | Step 2b (callback signature fix) |
| **Acceptance** | ✅ `vgm_socket.py` 354 lines; `emulation.py` 592 lines (down from ~1,200)<br>✅ All existing tests pass unchanged (1081 passed, 5 skipped)<br>✅ Architecture boundary tests pass (7/7)<br>✅ Core modules remain Kodi-free; no circular imports; `ProcessRunner` ownership unchanged |

### Verification Results (at the time of this step)
- **All 887 tests passed** (5 skipped for real-MAME integration) — historical count at Step 2c commit
- Current full suite at audited HEAD: **1081 passed, 5 skipped, 18 subtests**
- Architecture boundary tests pass (7/7)
- Command-line options tests pass (23/23)
- Emulator launcher tests pass (5/5)
- Random VGM player tests pass (8/8)
- Lua socket log tests pass (30/30)
- CHD extraction tests pass (10/10)
- VGM callback tests pass (4/4)

---

## Step 2e: VGM Follow-up Fixes (2026-10-21) ✅ **COMPLETED**

Following the VGM socket extraction (Step 2c), several correctness issues were identified and fixed:

| Aspect | Detail |
|--------|--------|
| **Goal** | Fix remaining VGM integration issues: port type handling, socket startup failure handling, exception-safe playback cleanup, shutdown-safe connection acceptance, and argument order bug in `_play_vgm_thread_impl` |
| **Files** | `script.module.umsa.core/lib/umsa_core/emulation.py`, `script.module.umsa.core/lib/umsa_core/vgm_player.py`, `script.module.umsa.core/lib/umsa_core/vgm_socket.py`, `tests/vgmplayer/vgmplayer/mame.py` |
| **Issues Fixed** | <ul><li><strong>Port type handling</strong>: `bound_port` (int) was passed to subprocess environment without string conversion. Fixed by converting to string at the boundary in `Emulation.play_vgm_thread()` and `VgmPlayer._play_vgm_thread_impl()`. Added validation in `VgmPlayer._vgm_process_env()` to reject invalid ports.</li><li><strong>Socket startup failure</strong>: `_start_vgm_server()` now checks `start_server()` return value and returns `False` on failure, preventing connection wait on non-existent listener. `play_vgm()` and `play_random_vgm_thread()` handle startup failure gracefully.</li><li><strong>Exception-safe playback cleanup</strong>: `play_vgm_thread()` wrapped in try/finally to ensure `playvgm` flag reset and socket cleanup. `play_random_vgm_thread()` already had finally block; verified correct.</li><li><strong>Shutdown-safe connection acceptance</strong>: `wait_for_connection()` now uses stable local reference to listener, avoiding `AttributeError` if listener is closed concurrently.</li><li><strong>Argument order fix</strong>: Fixed `_play_vgm_thread_impl()` call to `prepare_vgm_run()` - removed erroneous `sleep` argument and corrected parameter order. The separate thread argument tuple stayed broken and was fixed in Step 2f.</li></ul> |
| **Tests Updated** | <ul><li>`tests/test_vgmplay_port.py` - Added 4 new tests for port type handling, invalid port propagation, missing port propagation, and environment value types</li><li>`tests/test_random_vgm_player.py` - Updated mock to return `True` for `_start_vgm_server`</li><li>`tests/test_emulation_vgm_callback.py` - Updated mock to return `True` for `_start_vgm_server`</li></ul> |
| **Tests Added** | <ul><li>4 new tests in `test_vgmplay_port.py`: `test_environment_values_are_strings`, `test_invalid_port_does_not_propagate_none`, `test_missing_port_does_not_propagate`</li></ul> |
| **Verification** | ✅ All 890 tests pass (5 skipped) — historical count at Step 2e commit<br>✅ Current full suite at audited HEAD: **1081 passed, 5 skipped, 18 subtests**<br>✅ Architecture boundary tests pass (7/7)<br>✅ Core modules remain Kodi-free |

---

## Step 2f: VGM Playback Entry Point Verification (2026-10-21) ✅ **COMPLETED**

Follow-up to Step 2e: every VGM playback entry point was traced and the
argument forwarding was verified against the implementation signatures.

| Aspect | Detail |
|--------|--------|
| **Goal** | Verify the VGM playback entry points, fix the broken thread argument forwarding, and keep the Kodi-facing surface intact |
| **Files** | `script.module.umsa.core/lib/umsa_core/vgm_player.py`, `script.module.umsa.core/lib/umsa_core/emulation.py`, `tests/test_vgm_player_entrypoints.py` |
| **Findings** | <ul><li><strong>Broken thread forwarding</strong>: `VgmPlayer.play_vgm()` passed 8 values to `_play_vgm_thread_impl()`, which takes 9 — every call raised `TypeError` inside the worker thread. Introduced by commit `eaaffe1`.</li><li><strong>Missing facade method</strong>: `Emulation.play_random_vgm()` was dropped by commit `c8f43c0`, but `gui.py:852` calls it — the GUI raised `AttributeError` when "Play random Video Game Music" was selected.</li><li><strong>Stuck playback state</strong>: a failing playback left `playvgm` at `True` and never raised the stopped callback.</li><li><strong>Duplicate import</strong>: `parse_lua_log_line` was imported twice from `umsa_core.vgm_socket` (ruff `F811`).</li><li><strong>Mutable default</strong>: `Emulation.__init__(nonmame={})` shared one dict between all instances.</li><li><strong>Duplicate stopped notification</strong>: the playback owner (`Emulation.play_vgm_thread()`) and the playback worker (`VgmPlayer._play_vgm_thread_impl()`) both notified the Kodi layer at the end of a track, so a wiring that routes the owner as `run_func` reported "VGM stopped" twice.</li></ul> |
| **Fixes applied** | <ul><li>Thread arguments are forwarded as explicit keywords, so they can no longer drift from `_play_vgm_thread_impl()`.</li><li>`Emulation.play_random_vgm()` restored (thread owner; socket lifecycle stays in `play_random_vgm_thread()`).</li><li>`playvgm` reset and stopped callback moved into a `finally` block, matching `Emulation.play_vgm_thread()`.</li><li>Duplicate import removed; `nonmame` default is `None` with a fresh dict per instance.</li><li>The stopped callback is delivered at most once per playback: `VgmPlayer.begin_vgm_playback()` clears the one-shot guard at the start of every playback, so each playback still reports its end exactly once.</li></ul> |
| **Contracts unchanged** | `VgmPlayer.play_vgm()` and `VgmPlayer.play_random_vgm()` keep their signatures — both have no in-repo caller, are the extracted counterparts of the pre-refactor `Emulation` methods, and are documented as compatibility surfaces. They are kept, fixed and covered by tests instead of being removed on assumption. |
| **Tests** | `tests/test_vgm_player_entrypoints.py` (24 tests — thread target arguments, argument forwarding, playback state reset, stopped callback on success and failure, no duplicate stopped notification, one notification per playback, `Emulation` compatibility wrappers) |
| **Verification** | ✅ VGM test group (10 files): 137 passed, 18 subtests — historical at Step 2f<br>✅ Full suite: 914 passed, 5 skipped, 18 subtests — historical at Step 2f<br>✅ Current full suite at audited HEAD: **1081 passed, 5 skipped, 18 subtests**<br>✅ Real MAME (`VGM_MAME_TESTS=1`): 4 passed, 1 skipped (90 s long track needs `VGM_MAME_TESTS_FULL=1`)<br>✅ Lua pre-exit harness: `PASS trigger_exact`<br>✅ Regression proof: 13 of 24 tests fail on `eaaffe1` (pre-fix) and 1 fails on `dc122c9` (before the one-shot guard) |
| **Acceptance** | ✅ Supported entry points have consistent signatures and correct argument forwarding<br>✅ GUI call sites of `Emulation` verified against the class (no missing attribute left)<br>✅ Stopped callback fires exactly once per playback, on success and on failure<br>✅ No change to database behavior, port allocation or Kodi-facing behavior |
| **State** | Argument forwarding, restored `Emulation.play_random_vgm()`, import cleanup and `nonmame` default are committed in `dc122c9`. The one-shot guard for the stopped callback and the four extra tests are in the working tree and **not** committed (this task forbids committing). `tests/` is gitignored (`.gitignore:15`), so `tests/test_vgm_player_entrypoints.py` is a local-only file by repository convention. |

---

## Step 3: Split `gui.py` `UMSA` into Focused Workflow Modules (High Value, High Risk)

| Aspect | Detail |
|--------|--------|
| **Goal** | Reduce `UMSA` from ~2700 lines to ~800 lines as Kodi dialog coordinator; extract workflow modules |
| **Files** | `plugin.program.umsa.mame.surfer/resources/lib/gui.py` → new modules under `resources/lib/umsa_gui/` |
| **Proposed modules** | <ul><li>`umsa_gui/menu.py` — `build_main_menu`, `build_sublist_menu`, `M_*` constants, `SUBMENU_ORDER`</li><li>`umsa_gui/gamelist.py` — `popup_gamelist`, `gamelist_click`, `gamelist_context`, `gamelist_move`, `gamelist_switch_filter`</li><li>`umsa_gui/filter_ui.py` — `filter_category`, `filter_content`, `set_filter_content`</li><li>`umsa_gui/artwork_presenter.py` — `create_artworklist`, `show_artwork`, `search_snaps`, `get_machine_pic`</li><li>`umsa_gui/software_selector.py` — `select_software`, `software_move`, `machine_move`, `fill_set_list`, `choose_media`, `show_rec`, `open_software`</li><li>`umsa_gui/scan_orchestrator.py` — `update` (progress callbacks injected)</li><li>`umsa_gui/screensaver_vgm.py` — `VgmCommandMonitor`, `start/stop/get_screensaver_mode`, `_show/hide_vgm_info`, `_handle_vgm_action`</li><li>`umsa_gui/startup_import.py` — `run_startup_import`, `_remember_and_select`, `_save_lastgames`</li><li>`umsa_gui/emulator_setup.py` — `configure_emulator`, `get_diff_emulator`, `marp_replayer`, emulator output/notification</li><li>`umsa_gui/gamelist_actions.py` — `gamelist_click`, `gamelist_context`</li><li>`umsa_gui/media_list.py` — `choose_media`, `show_rec`</li><li>`umsa_gui/constants.py`, `umsa_gui/paths.py`, `umsa_gui/optional_plugins.py` — shared constants, add-on paths, optional plugin probes</li></ul> |
| **Responsibility moved** | All UI workflow logic — **out of `UMSA`** |
| **Contracts unchanged** | <ul><li>`UMSA.__init__`, `onInit`, `onFocus`, `onAction`, `onClick`, `exit`, `run_emulator` (dispatch only)</li><li>Control IDs, action codes, `EMULATOR_RUNNING_PROPERTY`, `UMSA.Screensaver.Mode`</li><li>`select_software` return `True`/`False` (for `_remember_and_select` rollback)</li><li>`ggdb` facade methods, `Emulation` methods</li></ul> |
| **Tests** | <ul><li>`tests/test_gamelist_filter.py` (35 tests — filter logic)</li><li>`tests/test_filter_state_accessors.py` (2 tests)</li><li>`tests/test_frontend_entrypoint.py`</li><li>`tests/test_emulator_launcher.py`</li><li>**New**: `tests/test_umsa_gui_workflows.py` (47 tests — all 15 workflow modules), `tests/test_gui_oninit_first_start.py` (5 tests — first-start scan thread)</li></ul> |
| **Risk** | High — touches Kodi window lifecycle, focus management, control IDs. Must not change observable behavior. |
| **Dependencies** | Step 1 (dead code gone); Step 2 (Emulation prep extracted) reduces `UMSA` coupling to `Emulation` internals |
| **Acceptance** | <ul><li>Workflow logic moved out of `UMSA`; `UMSA` retains only the Kodi dialog coordination</li><li>All existing tests pass</li><li>Maintainer-confirmed Kodi smoke test: menu navigation, gamelist filtering, software selection, artwork display</li></ul> |
| **State** | ✅ **CODE-VERIFIED** (2026-10-21), extraction committed in `ace91cb`. 15 workflow modules live in `resources/lib/umsa_gui/`; `gui.py` remains the adapter. Public names of `gui.py` are unchanged and listed in its `__all__`. Full suite: **1081 passed, 5 skipped, 18 subtests** (`tests/test_umsa_gui_workflows.py` 47 tests, `tests/test_gui_oninit_first_start.py` 5 tests — both **local-only**, `tests/` is gitignored). One regression was found and fixed during the final verification: the first-start branch started the DAT scan with `Thread(target=self.update('dat'))`, which ran the scan synchronously inside the thread constructor and left the thread without a target; it is now `Thread(target=self.update, args=('dat',))`, matching the `M_UPD` branches. GUI navigation is maintainer-verified; the wider emulator-startup matrix remains open (see `release-plan.md`). |

---

## Step 4: Separate Screensaver Rendering, Playback, Lifecycle (Medium Value, Medium Risk) ✅ **COMPLETED**

| Aspect | Detail |
|--------|--------|
| **Goal** | Split the monolithic screensaver `ui.py` into `Saver` (dispatch), `Player`, `Monitor` + focused modules |
| **Files** | `screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py` → new modules under `lib/umsa_screensaver/` |
| **Proposed modules** | <ul><li>`artwork_selector.py` — `get_random_art` → `resolve_art_path` → `check_snapshot` → aspect</li><li>`rendering.py` — cross/slide/wall render strategies (strategy pattern)</li><li>`wall_layout.py` — `create_wall` geometry</li><li>`video_playlist.py` — `add_video_to_playlist`, `Player.onPlayBackEnded`</li><li>`history.py` — `record_display` + `onAVStarted` deduplication</li><li>`temp_video.py` — `_extract_exodos_video`, `_cleanup_temp_videos`</li><li>`image_validator.py` — `check_snapshot` (configurable bad-image list)</li><li>`settings.py` — screensaver settings dataclass</li></ul> |
| **Responsibility moved** | Artwork selection/validation, mode-specific rendering, video playlist, history recording, temp video, image validation — **out of `Saver`/`Player`** |
| **Contracts unchanged** | <ul><li>`Saver.__init__`, `onInit`, `onAction`, `remember_art`, `record_display`, `open_software`, `get_art_and_call_saver` (orchestrates extracted modules)</li><li>`Player.__init__`, `onPlayBackStarted`, `onAVStarted`, `onPlayBackEnded` (call `history.py`)</li><li>`Monitor.__init__`, `startme`, `onScreensaverActivated`, `onScreensaverDeactivated`, `reallyDeactivateScreensaver`, `onDPMSActivated`</li><li>Window properties: `UMSA.Screensaver.Mode`, `UMSA.Emulator.Running`</li><li>`attach_set_id`/`read_set_id`/`read_software_id` signatures</li><li>`vgm_active()`/`send_vgm_action()` protocol</li></ul> |
| **Tests** | <ul><li>`tests/test_screensaver_history_hooks.py` (52 Kodi-stub tests)</li><li>`tests/test_screensaver_history_repository.py` (51 tests)</li><li>`tests/test_screensaver_addon.py`</li><li>`tests/test_screensaver_exodos_extraction.py`</li><li>**New**: unit tests for `artwork_selector`, `rendering` strategies, `wall_layout`, `temp_video`, `image_validator`</li></ul> |
| **Risk** | Medium — `Saver.get_art_and_call_saver()` is a 400-line loop with tight Kodi control manipulation. Extraction must preserve render timing and control IDs. |
| **Dependencies** | Step 2 (Core `Emulation` extraction clarifies VGM interface); Step 3 (GUI `screensaver_vgm.py` extraction aligns protocol) |
| **Acceptance** | <ul><li>Rendering, playback and lifecycle concerns separated into focused modules</li><li>All existing tests pass</li><li>Kodi-stub tests for `onAVStarted` deduplication pass</li></ul> |
| **State** | ✅ **CODE-VERIFIED** (2026-10-21). `ui.py` retains the Kodi window/playlist/callbacks. 11 focused modules live under `lib/umsa_screensaver/`: `actions.py`, `artwork_selector.py`, `availability.py`, `constants.py`, `history.py`, `image_validator.py`, `rendering.py`, `settings.py`, `temp_video.py`, `video_playlist.py`, `wall_layout.py` (current sizes are in `screensaver_audit.md`). The Kodi modules are resolved at call time in `ui.py` and injected, so the tests keep patching `ui.xbmc` / `ui.xbmcgui` / `ui.xbmcvfs` / `ui.PIL`; `ui.py` re-exports the old module-level names (`attach_set_id`, `read_set_id`, `read_software_id`, `SET_ID_UNIQUE_TYPE`, `PIL`, control/action constants) through `__all__`. New tests: `tests/test_screensaver_ui_modules.py` (62 tests — **local-only**, `tests/` is gitignored). Focused screensaver tests: **139 passed**. Full suite: **1081 passed, 5 skipped, 18 subtests**. `ruff check screensaver.umsa.mame.surfer/` is clean (the old `ui.py` had 2 findings). The only deliberate behavioural deviation is the snapshot file read, which no longer raises out of the render loop. Screensaver modes and video playback are maintainer-verified (see `release-plan.md`). |

---

### Post-A4 Screensaver Fixes (2026-10-22) ✅ **COMPLETED**

Following the A4 screensaver module split, five remaining correctness issues were identified and fixed:

| Fix | Issue | Resolution | Files Changed |
|-----|-------|------------|---------------|
| **1. Playback Ownership** | `shutdown_video_mode()` called `player.stop()` unconditionally, stopping pre-existing Kodi audio when screensaver ran in image modes. | Added `_playback_owned` flag to `Saver`. `stop_video_playback()` and `shutdown_video_mode()` only stop playback when flag is set. `_start_video_mode()` sets flag; `prepare_artwork_mode()` and `shutdown_video_mode()` clear it. | `ui.py`, `rendering.py` |
| **2. Playback Callbacks** | Missing `onPlayBackStopped()` and `onPlayBackError()` handlers; only `onPlayBackEnded()` handled normal completion. | Added both callbacks to `Player`, delegating to shared `_handle_playback_stopped()`. Idempotent handling of duplicate sequences (error→stopped). `video_teardown` guard prevents playlist replenishment during shutdown. | `ui.py` |
| **3. eXoDOS Extraction Failure** | Failed extraction fell back to zip:// URL, which is invalid for Kodi playback of archive members. | `add_video_to_playlist()` now rejects candidate when required extraction fails. No fallback to archive-backed path. `.part` files cleaned up. Bounded retry policy handles failed candidate. | `ui.py` |
| **4. Playlist Lifecycle** | The previous `shutdown_video_mode()` cleared the shared Kodi video playlist on every shutdown. | `shutdown_video_mode()` no longer clears the playlist; temp-file cleanup still runs. `Saver.onInit()` still calls `playlist.clear()` once at initialization (`ui.py:146`), so the shared Kodi video playlist is cleared at screensaver start and existing user video-playlist entries are not preserved. | `ui.py` |
| **5. Rendering Cleanup** | Unexpected exceptions in render loop skipped `_cleanup()`, leaving dynamic controls and stale state. | `RenderSession.run()` wrapped in `try/finally`. `_cleanup(ctx)` always executes. Exception logged with traceback. | `rendering.py` |

**Verification** (historical at Step 4 commit): 247 screensaver tests pass; 254 relevant tests pass (screensaver + architecture boundaries). Current focused screensaver tests: **139 passed**; full suite **1081 passed, 5 skipped, 18 subtests**. Ruff clean on screensaver add-on. Mypy clean on `vgm_header.py`.

---

## Step 5: Reassess `umsa_core` Layout — Phase 4.9 `database.py` Reorganisation (Optional / Deferred)

| Aspect | Detail |
|--------|--------|
| **Goal** | Move non-DB helpers out of `database.py` (~1857 lines, down from 69k) per Phase 4.9 proposal |
| **Files** | `script.module.umsa.core/lib/umsa_core/database.py` → new modules |
| **Proposed moves** (from `roadmap.md`) | <ul><li>`download_and_update_umsa_db` → `umsa_db_download.py` ✅ **Done (4.9a)**</li><li>`_scan_state_ownership`, `run_scan_with_progress` → `scan_progress.py`</li><li>`split_gamename`, `COUNTRIES`, `make_time_nice`, `get_best_machine_for_set`, `parse_recommended_games`, `build_filter_lists` → `game_labels.py` (or split)</li><li>`create_cmdline`, `get_cmd_line_options` assembly helpers → `cmdline.py` (after Step 2 clarifies ownership)</li></ul> |
| **Responsibility moved** | Pure application helpers, scan progress, cmdline assembly — **out of `DBMod`** |
| **Contracts unchanged** | `DBMod` re-exports names; `run_scan_with_progress` callback signature; `get_cmd_line_options`/`create_cmdline` signatures |
| **Tests** | `tests/test_database.py`, `tests/test_scan_coordinator.py`, `tests/test_run_scan_with_progress.py`, `tests/test_cmd_line_options.py` |
| **Risk** | Low — pure moves, no behavior change; boundary tests enforce no Kodi imports |
| **Dependencies** | Steps 2–4 (launch prep + GUI extraction clarify what `DBMod` actually needs to keep) |
| **Acceptance** | <ul><li>`database.py` < 30k lines (facades + lifecycle + mixed queries only)</li><li>All re-exports work; no import breaks in GUI/Screensaver</li><li>Boundary tests pass</li></ul> |

---

## Step 6: Resume Optional Database Refactor (Deferred)

| Aspect | Detail |
|--------|--------|
| **Goal** | Further `DBMod` decomposition if needed (mixed queries: `get_random_id`, `get_random_art`, `get_artwork_by_software_id`; cross-db `open_db`) |
| **Status** | **Deferred** — Phase 4.9 is optional; current `DBMod` is stable with repositories + `gamelist_filter` |
| **Trigger** | Only if `DBMod` size/complexity becomes a maintenance burden after Steps 1–5 |

---

## Dependency Graph

```
Step 1 (dead code removal)
    │
    ├─→ Step 2 (Emulation prep extraction) ──→ Step 5 (Core reorg: cmdline.py)
    │
    └─→ Step 3 (GUI workflow extraction) ──→ Step 4 (Screensaver split)
          │                                        │
          └──────────────────┬───────────────────┘
                             │
                    (shared VGM/screensaver protocol)
```

---

## Test Strategy Summary

| Step | Existing Tests to Preserve | New Tests Needed |
|------|----------------------------|------------------|
| 1 | `test_frontend_entrypoint.py`, `test_emulator_launcher.py` | None (deletion only) |
| 2 | `test_emulation_process.py`, `test_emulation_chd.py`, `test_emulation_vgm_callback.py`, `test_vgmplay_preexit.py`, `test_vgm_preexit_mame.py`, `test_emulator_launcher.py` | Unit tests for each preparer/finder/extractor/VGM player |
| 3 | `test_gamelist_filter.py`, `test_filter_state_accessors.py`, `test_frontend_entrypoint.py`, `test_emulator_launcher.py` | Unit tests for `menu`, `gamelist`, `filter_ui`, `artwork_presenter`, `software_selector`, `scan_orchestrator`, `screensaver_vgm`, `startup_import` |
| 4 | `test_screensaver_history_hooks.py`, `test_screensaver_history_repository.py`, `test_screensaver_addon.py`, `test_screensaver_exodos_extraction.py` | Unit tests for `artwork_selector`, `rendering`, `wall_layout`, `video_playlist`, `history`, `temp_video`, `image_validator` |
| 5 | `test_database.py`, `test_scan_coordinator.py`, `test_run_scan_with_progress.py`, `test_cmd_line_options.py` | Tests for `scan_progress.py`, `game_labels.py`, `cmdline.py` |

---

## Behavioral Risks Requiring Manual Kodi Verification

| Risk | Step | Verification |
|------|------|--------------|
| Focus/navigation regression | 3 | Full menu → gamelist → filter → software select → artwork → emulator launch |
| Screensaver render timing | 4 | Cross/slide/wall modes run without flicker; wait-loop timing preserved |
| Video playback history | 4 | `onAVStarted` fires once per video; `umsa_set_id` recorded on Kodi 20+ |
| VGM control from screensaver | 3,4 | Volume/next/stop commands work; screensaver doesn't deactivate during VGM |
| Retroplayer session | 3 | Game launches, plays, exits cleanly; `ctx.exit()` behavior |
| Emulator launch (all types) | 2 | MAME, SWL, eXoDOS, GB64, MARP, Demul, FS-UAE, Flycast, Retroplayer all launch |

---

## Acceptance Criteria Checklist

- [x] Step 1: Dead code removed, suite green
- [x] Step 2: `emulation.py` split, all preparer/finder/extractor/VGM tests added, suite green
- [x] Step 3: `UMSA` < 1000 lines, workflow modules extracted, suite green, manual smoke pass
- [x] Step 4: `Saver`/`Player`/`Monitor` split, rendering/history modules extracted, suite green
- [ ] Step 5: `database.py` non-DB helpers moved, re-exports work, boundary tests pass
- [x] All architecture boundary tests pass throughout (`test_architecture_boundaries.py` — 7 tests)
- [x] Full suite green at the audited HEAD (1081 passed, 5 skipped)
- [x] No Kodi imports in `umsa_core/` (except `umsa_core_kodi.py`)
- [x] No `gdb`/`gdbc`/`sdb`/`sdbc`/`ggdb` attribute access outside `database.py`