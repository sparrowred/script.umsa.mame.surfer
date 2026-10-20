# Architecture Audit — UMSA MAME Surfer

**Repository state:** git HEAD `9a98cfe` (2026-10-19)  
**Audit scope:** `gui.py`, screensaver `ui.py`, `emulation.py`, complete `umsa_core` package, emulator launch path spanning `DBMod`, `Emulation`, `emulator_launcher.py`, `retroplayer_cache.py`  
**Generated:** 2026-10-20 (read-only audit, no production code modified)

---

## Overall Findings

The codebase implements a three-add-on architecture (Frontend, Core, Screensaver) with strict Kodi-import boundaries documented in `docs/architecture.md`. The Core package (`umsa_core/`) is Kodi-independent; only `umsa_core_kodi.py` may import Kodi. The GUI and Screensaver add-ons freely use Kodi APIs.

**Database refactor (Phases 4.0–4.8) is complete:** `DBMod` has delegated most SQL to focused repositories (`GameRepository`, `DatRepository`, `ArtworkRepository`, `StatusRepository`, `EmulatorRepository`, `HistoryRepository`) and the `gamelist_filter` service. `umsa.db` is now read-only with `artwork.db`/`dat.db` attached as schemas. Row-factory contract (`sqlite3.Row` required for repositories) is enforced. Row-leak closure (Phase 4.8) ensures `sqlite3.Row` never crosses the Core-to-add-on boundary.

**Key architectural strengths:**
- Clear add-on boundaries with automated boundary tests (`test_architecture_boundaries.py`)
- Repository pattern with caller-owned connections and savepoint-based writes
- Explicit filter-state composition in `gamelist_filter.py` (Kodi-free)
- One-way dependency direction: GUI → Core/adapter; Screensaver → Core/adapter/Kodi; adapter → Core

**Key risks and structural concerns:**

| Area | Risk | Evidence |
|------|------|----------|
| `gui.py` `UMSA` class | ~2700 lines, god-class patterns: mixes Kodi window lifecycle, input handling, database orchestration, emulator launch prep, artwork/media management, scan coordination, screensaver/VGM communication | Single class owns 60+ instance attributes, 100+ methods |
| Emulator launch path | Split across `UMSA.run_emulator()` (legacy body after `launch_emulator()` return), `emulator_launcher.py`, `retroplayer_cache.py`, `Emulation.prepare_mame_run()`, `DBMod.get_cmd_line_options()`/`create_cmdline()` — ownership of command-line assembly vs. DB lookup vs. process execution is diffuse | `run_emulator()` has 130 lines of dead code after `launch_emulator(ctx)` return (lines 2545–2636) |
| `emulation.py` `Emulation` class | ~1200 lines, handles MAME, VGM, CHD, eXoDOS, GB64, WHDLoad, Demul, FS-UAE, Flycast, MARP, Retroplayer — each with custom prep/extract logic | 20+ `prepare_*`/`find_*`/`extract_*` methods, emulator-specific logic mixed with process management |
| Screensaver `ui.py` | `Saver` (887 lines), `Player` (170 lines), `Monitor` (70 lines) in one file; `Saver.get_art_and_call_saver()` is a 400-line loop mixing rendering, artwork resolution, bad-image checking, history recording, wait loops | No separation between rendering, playback, lifecycle, history |
| `DBMod` | Still holds 69k lines; retains mixed queries (`get_random_id`, `get_random_art`, `get_artwork_by_software_id`), cross-db sync (`open_db`), orchestration (`get_all_for_software`, `get_cmd_line_options`, `get_last_played`) | Phase 4.9 reorganisation proposed but not implemented |

---

## Audit Document Map

| Document | Purpose |
|----------|---------|
| [`core_module_inventory.md`](core_module_inventory.md) | Verified inventory of all 31 `umsa_core` modules with responsibilities, APIs, dependencies, Kodi-import status |
| [`gui_audit.md`](gui_audit.md) | `UMSA` class responsibility map, workflow grouping, extraction candidates, dead code, shared state |
| [`screensaver_audit.md`](screensaver_audit.md) | `Saver`/`Player`/`Monitor` boundaries, rendering vs. playback vs. lifecycle, history hooks, extraction opportunities |
| [`emulation_audit.md`](emulation_audit.md) | Full emulator launch path trace: DB lookup → cmdline assembly → ROM/CHD discovery → emulator prep → process management → GUI callbacks |
| [`refactoring_plan.md`](refactoring_plan.md) | Prioritized, testable steps with scope, dependencies, acceptance criteria, test strategy |

---

## Verified Architectural Findings

1. **`UMSA.run_emulator()` has a dead code block** (lines 2545–2636) after the `launch_emulator(ctx)` call returns. The legacy body duplicates `emulator_launcher.py` logic and should be removed.

2. **Command-line assembly is split**: `DBMod.get_cmd_line_options()` reads from `GameRepository` (Phase 4.4) but assembles the final argument list; `DBMod.create_cmdline()` is pure assembly. `Emulation.prepare_mame_run()` calls `get_cmd_line_options()`. The boundary between "database-backed reads" and "deterministic assembly" is clean at the repository layer but `DBMod` still owns assembly.

3. **Process management is in `ProcessRunner` (Core)** — clean, Kodi-free, used by `Emulation.start_managed_process()`. `Emulation.run()` still uses raw `subprocess.Popen` for fallback/terminal modes.

4. **Screensaver history recording** is correctly placed: `Saver.record_display()` (images, post-render) and `Player.onAVStarted()` (videos, stream-available) both call `DBMod.record_screensaver_display()` → `HistoryRepository`. No Kodi imports in Core.

5. **`gamelist_filter.py` is the filter/query composition service** — Kodi-free, explicit `GamelistFilter` state, all values parameterised. `DBMod` facades mirror state back to public attributes for GUI compatibility.

6. **`retroplayer_cache.py` is GUI-side only** — uses `xbmcvfs.copy`, `xbmcgui.ListItem`, Batocera mapping. Correctly separated from Core.

7. **No circular imports** detected across add-on boundaries. Core imports only standard library and internal Core modules.

---

## Recommended Implementation Order

| Step | Area | Rationale |
|------|------|-----------|
| 1 | Remove dead code in `UMSA.run_emulator()` (lines 2545–2636) | Trivial, no behavior change, unblocks cleaner audit of launch path |
| 2 | Extract `Emulation` emulator-specific prep (`prepare_mame_run`, `prepare_exodos_run`, `prepare_marp_run`, `other_emulator`, `find_roms`, `extract_rom`, `extract_chd`) into a `LaunchPreparer` or per-emulator modules | Isolates deterministic command-line/ROM discovery from process execution; enables unit testing without Kodi |
| 3 | Split `gui.py` `UMSA` into focused GUI workflow modules (menu handling, gamelist strategies already extracted, filter UI, artwork/media display, scan orchestration) | Reduces god-class; retains `UMSA` as Kodi dialog coordinator |
| 4 | Separate `Saver` rendering loop from `Player` playback callbacks and `Monitor` lifecycle — consider `screensaver/rendering.py`, `screensaver/playback.py`, `screensaver/history.py` | Improves testability of artwork selection/validation and history recording |
| 5 | Reassess `umsa_core` module layout after boundaries settle (Phase 4.9 `database.py` reorganisation: `umsa_db_download.py`, `scan_progress.py`, `game_labels.py`, `cmdline.py`) | Only meaningful once launch-path and GUI extractions clarify what stays in `DBMod` |

---

## Existing Tests to Extend

| Step | Tests to Extend |
|------|-----------------|
| 1 (dead code removal) | `tests/test_frontend_entrypoint.py`, `tests/test_emulator_launcher.py` — verify `launch_emulator` still called, no legacy path |
| 2 (launch prep extraction) | `tests/test_emulation_process.py`, `tests/test_emulation_chd.py`, `tests/test_emulator_launcher.py`, `tests/test_cmd_line_options.py` (23 golden tests pinning `prepare_mame_run` input) |
| 3 (GUI workflow extraction) | `tests/test_gamelist_filter.py` (35 tests), `test_filter_state_accessors.py`; new tests for extracted modules |
| 4 (screensaver split) | `tests/test_screensaver_history_hooks.py` (52 Kodi-stub tests), `tests/test_screensaver_addon.py` |
| 5 (Core reorg) | Architecture boundary tests (`test_architecture_boundaries.py` — 7 tests), full suite (878 passed) |

---

## Uncertainties / Runtime Behavior Not Verifiable Statically

- **Kodi window lifecycle timing**: `onInit`/`onFocus`/`onAction`/`onClick` sequence and focus management — only verifiable in Kodi runtime
- **Video playback callbacks**: `Player.onAVStarted` vs `onPlayBackStarted` ordering, `getTotalTime()` availability — tested with Kodi stubs only
- **MAME Lua socket protocol**: `vgmplay.lua` ↔ `Emulation._lua_log_reader` — integration tested with real MAME (`VGM_MAME_TESTS=1`) but not in CI
- **Screensaver mode transitions**: `Monitor.onScreensaverActivated`/`Deactivated` interaction with `UMSA` window property `UMSA.Screensaver.Mode`
- **Retroplayer session lifecycle**: `run_retroplayer()` calls `ctx.exit()` but TODO notes uncertainty about play-session end detection

---

## Confirmation

- ✅ No production code modified
- ✅ No tests modified
- ✅ No configuration files changed
- ✅ Only `docs/refactor_audit/` files created
- ✅ All recommendations supported by observed implementation details
- ✅ Proposals clearly labelled vs. verified facts