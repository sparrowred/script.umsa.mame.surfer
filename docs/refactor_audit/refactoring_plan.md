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
| **Contracts unchanged** | <ul><li>`Emulation.__init__` (keeps `ProcessRunner`, config, callbacks)</li><li>`Emulation.prepare_mame_run(ggdb, actset, dialog)` → delegates to `LaunchPreparer`</li><li>`Emulation.prepare_exodos_run(emu_infos)` → delegates to `LaunchPreparer`</li><li>`Emulation.prepare_marp_run(emu_infos)` → delegates to `LaunchPreparer`</li><li>`Emulation.other_emulator(emu_infos, dialog, sleep)` → delegates to `LaunchPreparer`</li><li>`Emulation.find_roms`/`find_nonmame_roms` → delegates to `RomFinder`</li><li>`Emulation.extract_rom` → delegates to `RomExtractor`</li><li>`Emulation.extract_chd` → delegates to `ChdExtractor`</li><li>`Emulation.play_vgm`/`play_random_vgm` → delegates to `VgmPlayer`</li></ul> |
| **Tests** | <ul><li>`tests/test_emulation_process.py` (process mgmt)</li><li>`tests/test_emulation_chd.py` (CHD extraction + NULL-disk fix)</li><li>`tests/test_emulation_vgm_callback.py` (VGM callback)</li><li>`tests/test_vgmplay_preexit.py` + `test_vgmplay_preexit.lua` (Lua pre-exit)</li><li>`tests/test_vgm_preexit_mame.py` (real MAME, gated)</li><li>`tests/test_emulator_launcher.py` (integration via `launch_emulator`)</li></ul> |
| **Risk** | Medium — `Emulation` is central; `emurun` dict structure must stay identical; `ProcessRunner` integration unchanged |
| **Dependencies** | Step 1 (clean `run_emulator` first); `GameRepository` reads stable (Phase 4.4 done) |
| **Acceptance** | ✅ `emulation.py` 766 lines (keeps `ProcessRunner` integration, `emurun` management, `wait_for_completion`, `after_run`, VGM socket mgmt)<br>✅ All existing tests pass unchanged (887 passed, 5 skipped)<br>✅ `emulator_launcher.launch_emulator` works without modification<br>✅ Core modules remain Kodi-free; no circular imports; `ProcessRunner` ownership unchanged |

---

## Step 3: Split `gui.py` `UMSA` into Focused Workflow Modules (High Value, High Risk)

| Aspect | Detail |
|--------|--------|
| **Goal** | Reduce `UMSA` from ~2700 lines to ~800 lines as Kodi dialog coordinator; extract workflow modules |
| **Files** | `plugin.program.umsa.mame.surfer/resources/lib/gui.py` → new modules under `resources/lib/` |
| **Proposed modules** | <ul><li>`gui/menu.py` — `build_main_menu`, `build_sublist_menu`, `M_*` constants, `SUBMENU_ORDER`</li><li>`gui/gamelist.py` — `popup_gamelist`, `gamelist_click`, `gamelist_context`, `gamelist_move`, `gamelist_switch_filter`</li><li>`gui/filter_ui.py` — `filter_category`, `filter_content`, `set_filter_content`</li><li>`gui/artwork_presenter.py` — `create_artworklist`, `show_artwork`, `search_snaps`, `get_machine_pic`</li><li>`gui/software_selector.py` — `select_software`, `software_move`, `machine_move`, `fill_set_list`, `choose_media`, `show_rec`, `open_software`</li><li>`gui/scan_orchestrator.py` — `update` (progress callbacks injected)</li><li>`gui/screensaver_vgm.py` — `VgmCommandMonitor`, `start/stop/get_screensaver_mode`, `_show/hide_vgm_info`, `_handle_vgm_action`</li><li>`gui/startup_import.py` — `run_startup_import`, `_remember_and_select`, `_save_lastgames`</li></ul> |
| **Responsibility moved** | All UI workflow logic — **out of `UMSA`** |
| **Contracts unchanged** | <ul><li>`UMSA.__init__`, `onInit`, `onFocus`, `onAction`, `onClick`, `exit`, `run_emulator` (dispatch only)</li><li>Control IDs, action codes, `EMULATOR_RUNNING_PROPERTY`, `UMSA.Screensaver.Mode`</li><li>`select_software` return `True`/`False` (for `_remember_and_select` rollback)</li><li>`ggdb` facade methods, `Emulation` methods</li></ul> |
| **Tests** | <ul><li>`tests/test_gamelist_filter.py` (35 tests — filter logic)</li><li>`tests/test_filter_state_accessors.py` (2 tests)</li><li>`tests/test_frontend_entrypoint.py`</li><li>`tests/test_emulator_launcher.py`</li><li>**New**: unit tests for each extracted module (mock Kodi controls where needed)</li></ul> |
| **Risk** | High — touches Kodi window lifecycle, focus management, control IDs. Must not change observable behavior. |
| **Dependencies** | Step 1 (dead code gone); Step 2 (Emulation prep extracted) reduces `UMSA` coupling to `Emulation` internals |
| **Acceptance** | <ul><li>`UMSA` class < 1000 lines; each workflow module < 300 lines</li><li>All existing tests pass</li><li>Manual Kodi smoke test: menu navigation, gamelist filtering, software selection, artwork display, scan, emulator launch, screensaver handoff</li></ul> |

---

## Step 4: Separate Screensaver Rendering, Playback, Lifecycle (Medium Value, Medium Risk)

| Aspect | Detail |
|--------|--------|
| **Goal** | Split `ui.py` (1231 lines) into `Saver` (dispatch), `Player`, `Monitor` + focused modules |
| **Files** | `screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py` → new modules under `lib/umsa_screensaver/` |
| **Proposed modules** | <ul><li>`artwork_selector.py` — `get_random_art` → `resolve_art_path` → `check_snapshot` → aspect</li><li>`rendering.py` — cross/slide/wall render strategies (strategy pattern)</li><li>`wall_layout.py` — `create_wall` geometry</li><li>`video_playlist.py` — `add_video_to_playlist`, `Player.onPlayBackEnded`</li><li>`history.py` — `record_display` + `onAVStarted` deduplication</li><li>`temp_video.py` — `_extract_exodos_video`, `_cleanup_temp_videos`</li><li>`image_validator.py` — `check_snapshot` (configurable bad-image list)</li><li>`settings.py` — screensaver settings dataclass</li></ul> |
| **Responsibility moved** | Artwork selection/validation, mode-specific rendering, video playlist, history recording, temp video, image validation — **out of `Saver`/`Player`** |
| **Contracts unchanged** | <ul><li>`Saver.__init__`, `onInit`, `onAction`, `remember_art`, `record_display`, `open_software`, `get_art_and_call_saver` (orchestrates extracted modules)</li><li>`Player.__init__`, `onPlayBackStarted`, `onAVStarted`, `onPlayBackEnded` (call `history.py`)</li><li>`Monitor.__init__`, `startme`, `onScreensaverActivated`, `onScreensaverDeactivated`, `reallyDeactivateScreensaver`, `onDPMSActivated`</li><li>Window properties: `UMSA.Screensaver.Mode`, `UMSA.Emulator.Running`</li><li>`attach_set_id`/`read_set_id`/`read_software_id` signatures</li><li>`vgm_active()`/`send_vgm_action()` protocol</li></ul> |
| **Tests** | <ul><li>`tests/test_screensaver_history_hooks.py` (52 Kodi-stub tests)</li><li>`tests/test_screensaver_history_repository.py` (51 tests)</li><li>`tests/test_screensaver_addon.py`</li><li>`tests/test_screensaver_exodos_extraction.py`</li><li>**New**: unit tests for `artwork_selector`, `rendering` strategies, `wall_layout`, `temp_video`, `image_validator`</li></ul> |
| **Risk** | Medium — `Saver.get_art_and_call_saver()` is a 400-line loop with tight Kodi control manipulation. Extraction must preserve render timing and control IDs. |
| **Dependencies** | Step 2 (Core `Emulation` extraction clarifies VGM interface); Step 3 (GUI `screensaver_vgm.py` extraction aligns protocol) |
| **Acceptance** | <ul><li>`Saver` < 300 lines (dispatch + orchestration)</li><li>`Player` < 100 lines (callbacks only)</li><li>`Monitor` < 80 lines (lifecycle only)</li><li>All existing tests pass</li><li>Kodi-stub tests for `onAVStarted` deduplication pass</li></ul> |

---

## Step 5: Reassess `umsa_core` Layout — Phase 4.9 `database.py` Reorganisation (Lower Priority)

| Aspect | Detail |
|--------|--------|
| **Goal** | Move non-DB helpers out of `database.py` (69k lines) per Phase 4.9 proposal |
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

- [ ] Step 1: Dead code removed, suite green
- [ ] Step 2: `emulation.py` split, all preparer/finder/extractor/VGM tests added, suite green
- [ ] Step 3: `UMSA` < 1000 lines, workflow modules extracted, suite green, manual smoke pass
- [ ] Step 4: `Saver`/`Player`/`Monitor` split, rendering/history modules extracted, suite green
- [ ] Step 5: `database.py` non-DB helpers moved, re-exports work, boundary tests pass
- [ ] All architecture boundary tests pass throughout (`test_architecture_boundaries.py` — 7 tests)
- [ ] Full suite ≥ 878 passed at each step
- [ ] No Kodi imports in `umsa_core/` (except `umsa_core_kodi.py`)
- [ ] No `gdb`/`gdbc`/`sdb`/`sdbc`/`ggdb` attribute access outside `database.py`