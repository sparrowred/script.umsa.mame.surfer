# Architecture Audit — UMSA MAME Surfer

**Repository state:** git HEAD `cc2efc83855eb2fd10b17e814a507b59d341a76c` (2026-10-23)  
**Audit scope:** `gui.py`, screensaver `ui.py`, `emulation.py`, complete `umsa_core` package, emulator launch path spanning `DBMod`, `Emulation`, `emulator_launcher.py`, `retroplayer_cache.py`  
**Generated:** 2026-10-23 (read-only audit, no production code modified)

---

## Overall Findings

The codebase implements a three-add-on architecture (Frontend, Core, Screensaver) with strict Kodi-import boundaries documented in `docs/architecture.md`. The Core package (`umsa_core/`) is Kodi-independent; only `umsa_core_kodi.py` may import Kodi. The GUI and Screensaver add-ons freely use Kodi APIs.

**Database refactor (Phases 4.0–4.8) is complete:** `DBMod` has delegated most SQL to focused repositories (`GameRepository`, `DatRepository`, `ArtworkRepository`, `StatusRepository`, `EmulatorRepository`, `HistoryRepository`) and the `gamelist_filter` service. `umsa.db` is now read-only with `artwork.db`/`dat.db` attached as schemas. Row-factory contract (`sqlite3.Row` required for repositories) is enforced. Row-leak closure (Phase 4.8) ensures `sqlite3.Row` never crosses the Core-to-add-on boundary. Artwork/DAT source-of-truth refactor (Phases 4.8+) makes `artwork.db` and `dat.db` the authoritative sources for scanned data; `umsa.db` is read-only and attaches them as schemas.

**Structural refactoring (Steps 1–4) is complete:**
- Step 1: Dead code in `UMSA.run_emulator()` removed (92 lines)
- Step 2: `Emulation` (1200 lines) split into `launch_preparer.py`, `rom_finder.py`, `rom_extractor.py`, `chd_extractor.py`, `vgm_player.py`, `vgm_socket.py`; `Emulation` now 557 lines as facade
- Step 3: `gui.py` `UMSA` split into 15 workflow modules under `resources/lib/umsa_gui/`; `UMSA` now 925 lines, `gui.py` adapter 1231 lines
- Step 4: Screensaver `ui.py` split into 11 focused modules under `lib/umsa_screensaver/`; `Saver` 258, `Player` 86, `Monitor` 79 (all class targets met); `ui.py` 522 lines

**Key architectural strengths:**
- Clear add-on boundaries with automated boundary tests (`test_architecture_boundaries.py` — 7/7 pass)
- Repository pattern with caller-owned connections and savepoint-based writes
- Explicit filter-state composition in `gamelist_filter.py` (Kodi-free)
- One-way dependency direction: GUI → Core/adapter; Screensaver → Core/adapter/Kodi; adapter → Core
- All Core modules Kodi-free (verified by boundary tests)
- eXoDOS archive path validation updated to allow intentional symlinks (lexical checks only, no `realpath` containment)

**Key risks and structural concerns:**

| Area | Risk | Evidence |
|------|------|----------|
| `gui.py` `UMSA` class | ~925 lines (down from 2700), retains Kodi window lifecycle, input dispatch, state coordination | 15 workflow modules extracted; `UMSA` remains Kodi dialog coordinator |
| `DBMod` | ~1857 lines (down from 69k); retains mixed queries (`get_random_id`, `get_random_art`, `get_artwork_by_software_id`), cross-db sync (`open_db`), orchestration (`get_all_for_software`, `get_cmd_line_options`, `get_last_played`) | Phase 4.9 reorganisation proposed but not implemented |
| Screensaver `Saver` | 258 lines; `get_art_and_call_saver` delegates to `RenderSession` but retains lifecycle orchestration | 11 focused modules extracted; quirks of original preserved |
| Test infrastructure | `tests/` directory is gitignored; new workflow tests are local-only | 1081 passed, 5 skipped, 18 subtests; 47 GUI workflow tests, 62 screensaver module tests not in repo |

---

## Audit Document Map

| Document | Purpose |
|----------|---------|
| [`core_module_inventory.md`](core_module_inventory.md) | Verified inventory of all 38 `umsa_core` modules with responsibilities, APIs, dependencies, Kodi-import status |
| [`gui_audit.md`](gui_audit.md) | `UMSA` class responsibility map, workflow grouping, extraction candidates, dead code, shared state |
| [`screensaver_audit.md`](screensaver_audit.md) | `Saver`/`Player`/`Monitor` boundaries, rendering vs. playback vs. lifecycle, history hooks, extraction opportunities |
| [`emulation_audit.md`](emulation_audit.md) | Full emulator launch path trace: DB lookup → cmdline assembly → ROM/CHD discovery → emulator prep → process management → GUI callbacks |
| [`refactoring_plan.md`](refactoring_plan.md) | Prioritized, testable steps with scope, dependencies, acceptance criteria, test strategy |

---

## Verified Architectural Findings

1. **`UMSA.run_emulator()` dead code block removed (Step 1 complete).** The legacy body (92 lines, formerly lines 2545–2636) after the `launch_emulator(ctx)` call was deleted. The method now cleanly dispatches to `run_retroplayer()` (Retroplayer) or `launch_emulator()` (external emulators).

2. **Command-line assembly is split**: `DBMod.get_cmd_line_options()` reads from `GameRepository` (Phase 4.4) but assembles the final argument list; `DBMod.create_cmdline()` is pure assembly. `Emulation.prepare_mame_run()` calls `get_cmd_line_options()`. The boundary between "database-backed reads" and "deterministic assembly" is clean at the repository layer but `DBMod` still owns assembly.

3. **Process management is in `ProcessRunner` (Core)** — clean, Kodi-free, used by `Emulation.start_managed_process()`. `Emulation.run()` still uses raw `subprocess.Popen` for fallback/terminal modes.

4. **Screensaver history recording** is correctly placed: `Saver.record_display()` (images, post-render) and `Player.onAVStarted()` (videos, stream-available) both call `DBMod.record_screensaver_display()` → `HistoryRepository`. No Kodi imports in Core.

5. **`gamelist_filter.py` is the filter/query composition service** — Kodi-free, explicit `GamelistFilter` state, all values parameterised. `DBMod` facades mirror state back to public attributes for GUI compatibility.

6. **`retroplayer_cache.py` is GUI-side only** — uses `xbmcvfs.copy`, `xbmcgui.ListItem`, Batocera mapping. Correctly separated from Core.

7. **No circular imports** detected across add-on boundaries. Core imports only standard library and internal Core modules.

8. **eXoDOS symlink handling updated (2026-10-22):** `temp_video.py` no longer resolves symlinks for root-containment check. Lexical validation rejects absolute paths and `..` traversal in `relative_path`; the constructed archive path is passed directly to `ZipFile`, allowing the OS to follow intentional symlinks inside the configured eXoDOS tree.

9. **VGM playback entry points verified (2026-10-21):** All entry points traced; `Emulation.play_random_vgm()` restored; thread argument forwarding fixed; one-shot stopped callback guard prevents duplicate notifications.

---

## Recommended Implementation Order

| Step | Area | Rationale | Status |
|------|------|-----------|--------|
| 1 | Remove dead code in `UMSA.run_emulator()` (lines 2545–2636) | Trivial, no behavior change, unblocks cleaner audit of launch path | ✅ **Done** (2026-10-20) |
| 2 | Extract `Emulation` emulator-specific prep (`prepare_mame_run`, `prepare_exodos_run`, `prepare_marp_run`, `other_emulator`, `find_roms`, `extract_rom`, `extract_chd`) into a `LaunchPreparer` or per-emulator modules | Isolates deterministic command-line/ROM discovery from process execution; enables unit testing without Kodi | ✅ **Done** (2026-10-21) — 6 new modules |
| 2b | Extract VGM socket transport into `vgm_socket.py` | Separates TCP/Lua log protocol from `Emulation` lifecycle | ✅ **Done** (2026-10-21) |
| 2c | Fix VGM callback signatures and entry points | Restored `Emulation.play_random_vgm()`, fixed thread argument forwarding, one-shot stopped callback guard | ✅ **Done** (2026-10-21) |
| 3 | Split `gui.py` `UMSA` into focused GUI workflow modules (menu handling, gamelist strategies already extracted, filter UI, artwork/media display, scan orchestration) | Reduces god-class; retains `UMSA` as Kodi dialog coordinator | ✅ **Done** (2026-10-21) — 15 modules in `umsa_gui/` |
| 4 | Separate `Saver` rendering loop from `Player` playback callbacks and `Monitor` lifecycle — `screensaver/rendering.py`, `screensaver/history.py`, `screensaver/temp_video.py`, etc. | Improves testability of artwork selection/validation and history recording | ✅ **Done** (2026-10-22) — 11 modules in `lib/umsa_screensaver/` |
| 5 | Reassess `umsa_core` module layout after boundaries settle (Phase 4.9 `database.py` reorganisation: `scan_progress.py`, `game_labels.py`, `cmdline.py`) | Only meaningful once launch-path and GUI extractions clarify what stays in `DBMod` | ⏳ **Open** |

---

## Existing Tests to Extend

| Step | Tests to Extend |
|------|-----------------|
| 1 (dead code removal) | `tests/test_frontend_entrypoint.py`, `tests/test_emulator_launcher.py` — verify `launch_emulator` still called, no legacy path |
| 2 (launch prep extraction) | `tests/test_emulation_process.py`, `tests/test_emulation_chd.py`, `tests/test_emulator_launcher.py`, `tests/test_cmd_line_options.py` (23 golden tests pinning `prepare_mame_run` input) |
| 3 (GUI workflow extraction) | `tests/test_gamelist_filter.py` (35 tests), `test_filter_state_accessors.py`; new tests for extracted modules |
| 4 (screensaver split) | `tests/test_screensaver_history_hooks.py` (52 Kodi-stub tests), `tests/test_screensaver_addon.py` |
| 5 (Core reorg) | Architecture boundary tests (`test_architecture_boundaries.py` — 7 tests), full suite (1081 passed) |

---

## Uncertainties / Runtime Behavior Not Verifiable Statically

- **Kodi window lifecycle timing**: `onInit`/`onFocus`/`onAction`/`onClick` sequence and focus management — only verifiable in Kodi runtime
- **Video playback callbacks**: `Player.onAVStarted` vs `onPlayBackStarted` ordering, `getTotalTime()` availability — tested with Kodi stubs only
- **MAME Lua socket protocol**: `vgmplay.lua` ↔ `Emulation._lua_log_reader` — integration tested with real MAME (`VGM_MAME_TESTS=1`) but not in CI
- **Screensaver mode transitions**: `Monitor.onScreensaverActivated`/`Deactivated` interaction with `UMSA` window property `UMSA.Screensaver.Mode`
- **Retroplayer session lifecycle**: `run_retroplayer()` calls `ctx.exit()` but TODO notes uncertainty about play-session end detection
- **eXoDOS symlink playback**: Real-world symlink-backed archive extraction and playback — tested in unit tests with symlinks, not in Kodi runtime

---

## Confirmation

- ✅ No production code modified
- ✅ No tests modified
- ✅ No configuration files changed
- ✅ Only `docs/refactor_audit/` files updated
- ✅ All recommendations supported by observed implementation details
- ✅ Proposals clearly labelled vs. verified facts