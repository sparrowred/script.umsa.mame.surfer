# UMSA MAME Surfer — Release Plan

**Target:** Readiness-based (approx. 2 months)  
**Generated:** 2026-10-23  
**Based on:** Release quality audit (2026-10-23)  
**HEAD inspected:** `4186b5f5dd3479b19df84215d1fa21a4cbb38f29` (historical audit)
**P0 revalidation HEAD:** `af3bd11598692943e9c8f8a3dbc5ef457a6f5f3f` (2026-10-25)
**P0 round 2 HEAD:** `a74976bf1a1145c61d7b43f01568ef6f33fbb64a` (2026-10-25, GUI shutdown cleanup)

---

## Status Legend

| Label | Meaning |
|-------|---------|
| `OPEN` | Not started |
| `IN PROGRESS` | Actively being worked on |
| `MAINTAINER-VERIFIED` | Maintainer reports manual testing passed |
| `CODE-VERIFIED` | Verified by static analysis / tests in this audit |
| `BLOCKED` | Waiting on dependency |
| `DEFERRED` | Explicitly postponed |

---

## A. Structural Refactoring

| # | Task | Status | Priority | Rationale | Acceptance Criteria | Related Files / Audit |
|---|------|--------|----------|-----------|---------------------|----------------------|
| A1 | Remove dead code in `UMSA.run_emulator()` | ✅ **CODE-VERIFIED** | P0 | Done 2026-10-20 | 92 lines removed; 19 relevant tests pass | `refactoring_plan.md` Step 1, `gui.py:2504-2542` |
| A2 | Extract `Emulation` preparers/finders/extractors/VGM player | ✅ **CODE-VERIFIED** | P1 | 1200+ line god class; isolates emulator-specific logic | `emulation.py` is a 592-line facade (was 1200+); all existing tests pass; 6 modules added | `refactoring_plan.md` Step 2, `emulation_audit.md` |
| A2b | Extract VGM socket transport (`vgm_socket.py`) | ✅ **CODE-VERIFIED** | P1 | VGM TCP transport, Lua log protocol mixed in `Emulation` | `vgm_socket.py` 354 lines created; `emulation.py` 592 lines; all tests pass | `refactoring_plan.md` Step 2c, `emulation_audit.md` |
| A2c | Fix VGM callback signatures and entry points | ✅ **CODE-VERIFIED** | P1 | Restored `play_random_vgm`, fixed thread arg forwarding, one-shot stopped callback | 24 VGM entry-point tests pass; no duplicate stopped notification | `refactoring_plan.md` Step 2f, `emulation_audit.md` |
| A3 | Split `gui.py` `UMSA` into workflow modules | ✅ **CODE-VERIFIED** | P1 | 2600+ line god class; focus/navigation, gamelist, filter, artwork, scans, screensaver/VGM | 15 modules in `resources/lib/umsa_gui/`; `gui.py` remains the Kodi adapter; 1081 tests pass; public API unchanged; first-start DAT scan moved off calling thread | `refactoring_plan.md` Step 3, `gui_audit.md` |
| A4 | Separate Screensaver `Saver`/`Player`/`Monitor` | ✅ **CODE-VERIFIED** | P1 | Monolithic `ui.py` mixed rendering, playback, lifecycle, history | 11 focused modules in `lib/umsa_screensaver/`; `ui.py` retains the Kodi window/playlist/callbacks; 1081 tests pass (62 new); public names re-exported; post-A4 fixes (2026-10-22): playback ownership, `onPlayBackStopped`/`onPlayBackError`, eXoDOS extraction failure handling, `onInit` playlist clear documented, `try/finally` rendering cleanup | `refactoring_plan.md` Step 4, `screensaver_audit.md` |
| A5 | Phase 4.9 `database.py` reorganisation | ✅ **CODE-VERIFIED** (optional) | P1 | ~1857 → ~1673 lines. 4.9.1 inventory complete; 4.9.2 comment cleanup complete; 4.9.3 done (`scan_progress.py`, `game_labels.py`, `cmdline.py` extracted with wrappers). `COUNTRIES`/`get_best_machine_for_set`, `parse_recommended_games`, `build_filter_lists`, `get_cmd_line_options` remain in `database.py` per inventory. | Justified extractions complete; re-exports/wrappers preserved; focused Core tests and boundary tests pass | `refactoring_plan.md` Step 5, `database_refactor/roadmap.md`, `database_refactor/phase_4_9_1_inventory.md` |
| A6 | Optional further `DBMod` decomposition | `DEFERRED` | Post-release | Mixed queries (`get_random_id`, `get_random_art`), cross-db `open_db` | Only if maintenance burden grows | `refactoring_plan.md` Step 6, `dbmod_audit.md` |

---

## B. Python Style & Static Analysis

| # | Task | Status | Priority | Rationale | Acceptance Criteria | Related Files / Audit |
|---|------|--------|----------|-----------|---------------------|----------------------|
| B1 | Triage `BLE001` (blind `except Exception:`) | `IN PROGRESS` | P0 | Reproduced baseline at `af3bd11`: 108 (not historical 106). Round 1 fixed the high-risk `emulator_launcher.py` startup paths; 105 remained. Round 2 at `a74976b` logs every `gui.py` `exit()` cleanup step; 107 remained. Round 3 logs the DAT/artwork scanner cleanup and predicate boundaries; 109 remain (all catch-and-log, no silent handlers). Round 4 makes GB64 predicate failures abort and logs mapping/schema/final close failures; 112 remain. Round 5 makes DBMod cleanup independent and logged; 115 remain | Continue per-module triage; all remaining handlers justified and diagnosable; do not mass-replace | `static_analysis_audit.md`, `emulator_launcher.py`, `gui.py`, `dat_scanner.py`, `artwork_scanner.py`, `gb64_scanner.py`, `database.py` |
| B2 | Triage `S110` (`except Exception: pass`) | `IN PROGRESS` | P0 | Reproduced baseline at `af3bd11`: 54. Round 1 removed all 25 in `emulator_launcher.py`; round 2 removed the 5 in `gui.py` `exit()`; round 3 removed the 7 in `dat_scanner.py`/`artwork_scanner.py`; round 4 removed the 2 in `gb64_scanner.py`; round 5 removed the 5 in `database.py`, leaving 10 | All silent catches replaced with logging/narrow catches or intentionally documented | `static_analysis_audit.md` |
| B3 | Fix 1 `SIM118` (`key in dict.keys()`) | `OPEN` | P1 | Redundant `.keys()` call | Use `key in dict` | `static_analysis_audit.md` |
| B4 | Fix 1 `SIM102` (collapsible nested `if`) | `OPEN` | P1 | Readability | Merge `if` conditions | `static_analysis_audit.md` |
| B5 | Fix 1 `PLW1510` (`subprocess.run` without `check=True`) | ✅ **CODE-VERIFIED** | P0 | Location corrected: `umsa_core/emulation.py` terminal fallback (`emulation_start == 2`), not CHD extraction. Now `check=False` explicit, non-zero logged, `OSError` wrapped in `ProcessLaunchError` with cause | Success/non-zero/launch-failure regression tests pass; managed paths unchanged | `static_analysis_audit.md`, `tests/test_emulation_process.py`, `tests/test_emulator_launcher.py` |
| B6 | Convert `UP031` (`%` formatting → f-strings) | `OPEN` | P1 | 10 remain at `af3bd11` (`gui.py` 1, `umsa_gui/` 9); historical count was 16 | All clear candidates converted; SQL/MAME/logging exceptions preserved | `python_style_audit.md` |
| B6a | — `gamelist_strategies.py` (0 remaining; 8 were converted) | ✅ **CODE-VERIFIED** | P1 | | | `python_style_audit.md` |
| B6b | — `gui.py` (1: line 516) | `OPEN` | P1 | | | `python_style_audit.md` |
| B6c | — `emulator_launcher.py` (0 remaining) | ✅ **CODE-VERIFIED** | P1 | | | `python_style_audit.md` |
| B6d | — screensaver `ui.py` (0 remaining) | ✅ **CODE-VERIFIED** | P1 | The screensaver add-on is `UP031`-clean | | `python_style_audit.md`, `screensaver_audit.md` |
| B6e | — `emulation.py` (0 remaining) | ✅ **CODE-VERIFIED** | P1 | | | `python_style_audit.md` |
| B6f | — `umsa_gui/` package (9: `artwork_presenter.py` 2, `filter_ui.py` 2, `media_list.py` 2, `software_selector.py` 3) | `OPEN` | P1 | | | `python_style_audit.md` |
| B6g | — `database.py` (0 remaining at `af3bd11`; historical 6) | ✅ **CODE-VERIFIED** | P1 | | | `python_style_audit.md` |
| B7 | Fix 1 `UP030` (explicit `.format()` index) | `OPEN` | P1 | `launch_preparer.py:134` | Convert to f-string | `python_style_audit.md` |
| B8 | Fix 6 `UP007` (union syntax `X \| Y`) | `OPEN` | P1 | Python 3.10+ | All `Union[X, Y]` → `X \| Y` | `static_analysis_audit.md` |
| B9 | Fix 5 `SIM115` (context managers for `open()`) | `OPEN` | P1 | Resource leaks | All `open()` in `with` blocks | `static_analysis_audit.md` |
| B10 | Fix 4 `F841` (unused variables) | `OPEN` | P1 | Dead code indicator | Remove or use variables | `static_analysis_audit.md` |
| B11 | Fix `F401` (unused imports) | `OPEN` | P1 | 21 remain at `af3bd11`; most are intentional compat re-exports | Remove unused imports or add explicit re-export lists | `static_analysis_audit.md` |
| B12 | Fix 2 `TRY203` (useless try/except) | ✅ **CODE-VERIFIED** | P1 | Both were redundant `except Exception: raise` wrappers in `emulator_launcher.py` | Removed; Ruff reports 0 `TRY203` after round 1 | `static_analysis_audit.md` |
| B13 | Run Ruff `--fix` with review | `OPEN` | P2 | Automated cleanup | 25 safe fixes at `af3bd11` (`F401` 21, `I001` 3, `PLR1730` 1); further hidden fixes require `--unsafe-fixes` | `static_analysis_audit.md` |
| B14 | Confirm no pre-existing test failures remain | ✅ **CODE-VERIFIED** | P0 | Regression guard | 0 failures; 5 skipped (real-MAME only) | `static_analysis_audit.md` |

---

## C. Kodi API Compatibility

| # | Task | Status | Priority | Rationale | Acceptance Criteria | Related Files / Audit |
|---|------|--------|----------|-----------|---------------------|----------------------|
| C1 | Scenario A — screensaver inhibition during emulator | ✅ **MAINTAINER-VERIFIED** | P0 | Shared Kodi screensaver-inhibition lifecycle was tested successfully | Emulator runs beyond idle timeout with no competing screensaver; idle resumes after exit. **Narrow scope:** per-emulator startup/return matrix remains open (Area 1) | `kodi_api_compatibility.md` Scenarios |
| C2 | Scenario B — manual screensaver blocks idle | ✅ **MAINTAINER-VERIFIED** | P0 | Shared Kodi screensaver-inhibition lifecycle was tested successfully | Manual screensaver active beyond timeout; no competing idle; C-key handoff works; idle resumes after exit | `kodi_api_compatibility.md` Scenarios |
| C3 | Scenario C — automatic screensaver unaffected | ✅ **MAINTAINER-VERIFIED** | P0 | Shared Kodi screensaver-inhibition lifecycle was tested successfully | Kodi-launched screensaver works; `UMSA.Screensaver.Manual` not set | `kodi_api_compatibility.md` Scenarios |
| C4 | Verify `special://` paths use `xbmcvfs.translatePath()` | ✅ **CODE-VERIFIED** | P0 | `os.path` fails on `special://` URIs | Only untranslated `special://` constant is `temp_video.py:19`, resolved via `temp_dir` → `vfs.translatePath()`; all other paths translated | `kodi_api_compatibility.md` |
| C5 | `DialogProgress`/`DialogProgressBG` on Kodi 20+ | ✅ **MAINTAINER-VERIFIED** | P1 | Modal dialog behavior | Exercised by the confirmed GUI navigation and database-refactor smoke tests; dialogs display, update and dismiss cleanly on Estuary | `kodi_api_compatibility.md` |
| C6 | `Player.onAVStarted` fires once per video | ✅ **MAINTAINER-VERIFIED** | P1 | History recording accuracy | Confirmed for screensaver video playback; exactly one `onAVStarted` per video and duplicate suppression works | `kodi_api_compatibility.md` |
| C7 | Retroplayer `GameInfoTag` metadata | `OPEN` | P1 | Game metadata display | Tracked in **Area 2** (Retroplayer end-to-end); not independently verified | `kodi_api_compatibility.md` |
| C8 | Verify no deprecated APIs in codebase | ✅ **CODE-VERIFIED** | P1 | Audit complete | No deprecated/removed APIs found for Kodi 20+ | `kodi_api_compatibility.md` |
| C9 | Document minimum Kodi version as 20 (Nexus) | `OPEN` | P1 | Clear requirement | `README.md` must state Kodi 20+; it currently does not, while all `addon.xml` declare `xbmc.python` 3.0.0 | `README.md` |

---

## D. Tests & Runtime Verification

| # | Task | Status | Priority | Rationale | Acceptance Criteria | Related Files / Audit |
|---|------|--------|----------|-----------|---------------------|----------------------|
| D1 | Document pre-existing test failures | ✅ **CODE-VERIFIED** | P0 | Known limitations | The 13 failures reported by an earlier audit are no longer present; current run has no failures (5 skipped) | `test-suite-audit.md` |
| D2 | Core regression test suite passes | ✅ **CODE-VERIFIED** | P0 | No Kodi needed | All Core tests pass: `test_database.py`, `test_game_repository.py`, `test_dat_repository.py`, `test_artwork_repository.py`, `test_emulator_repository.py`, `test_status_repository.py`, `test_history_repository.py`, `test_emulation_process.py`, `test_emulation_chd.py`, `test_emulation_vgm_callback.py`, `test_process.py`, `test_sqlite.py`, `test_scan_coordinator.py` | `test-suite-audit.md` |
| D3 | Integration test suite passes (Kodi stubs) | ✅ **CODE-VERIFIED** | P0 | Frontend/Screensaver integration | All integration tests pass: `test_frontend_entrypoint.py`, `test_emulator_launcher.py`, `test_screensaver_addon.py`, `test_screensaver_history_hooks.py`, `test_screensaver_history_repository.py`, `test_gui_history_navigation.py` | `test-suite-audit.md` |
| D4 | Architecture boundary tests pass | ✅ **CODE-VERIFIED** | P0 | Kodi-free Core | 7/7 tests pass | `test_architecture_boundaries.py` |
| D5 | Full suite passes, no new failures | ✅ **CODE-VERIFIED** | P0 | Regression guard | Historical: 1081 passed, 5 skipped, 18 subtests (HEAD `4186b5f`). P0 round 1: **1130 passed, 5 skipped, 18 subtests** on rerun at `af3bd11`; the first run hit one transient DNS failure in local-only `test_umsa_db_download.py`, not reproducible. P0 round 2: **1141 passed, 5 skipped, 18 subtests** at `a74976b` | `test-suite-audit.md`, `static_analysis_audit.md` |
| D6 | Unit tests for Emulation extraction (A2) | ✅ **CODE-VERIFIED** | P1 | New modules need coverage | `test_emulation_process.py`, `test_emulation_chd.py`, `test_emulation_vgm_callback.py`, `test_vgmplay_preexit.py`, `test_lua_socket_log.py`, `test_vgm_player_entrypoints.py` (24 tests), `test_random_vgm_player.py`, `test_vgmplay_port.py` | `refactoring_plan.md` Step 2 |
| D6 | Unit tests for GUI workflow modules (A3) | ✅ **CODE-VERIFIED** | P1 | New modules need coverage | `tests/test_umsa_gui_workflows.py` (47 tests) covers all 15 `umsa_gui` modules; `tests/test_gui_oninit_first_start.py` (5 tests). **Local-only** (`tests/` gitignored) | `refactoring_plan.md` Step 3 |
| D6 | Unit tests for Screensaver modules (A4) | ✅ **CODE-VERIFIED** | P1 | New modules need coverage | `tests/test_screensaver_ui_modules.py` (62 tests) covers the extracted modules; existing Kodi-stub tests pass (139). **Local-only** (`tests/` gitignored) | `refactoring_plan.md` Step 4 |
| D6 | Unit tests for Core reorg modules (A5) | ✅ **CODE-VERIFIED** | P1 | Extracted modules are covered by local Core tests | `test_run_scan_with_progress.py` (`scan_progress.py`), `test_game_labels.py` (`game_labels.py`), `test_cmd_line_options.py` (`cmdline.py`, including the non-mutating `parts` contract), `test_umsa_db_download.py` (4.9a); **Local-only** (`tests/` gitignored) | `refactoring_plan.md` Step 5, `database_refactor/phase_4_9_1_inventory.md` |

---

## E. Standalone Core CLI Example

| # | Task | Status | Priority | Rationale | Acceptance Criteria | Related Files / Audit |
|---|------|--------|----------|-----------|---------------------|----------------------|
| E1 | Create `examples/search_game.py` | `OPEN` | P2 | Demonstrate Kodi-free Core usage | Imports work without Kodi; read-only DB connection; game search returns results; runnable from CLI | `core_cli_example.md` |
| E2 | Add unit tests for CLI example | `OPEN` | P2 | Coverage | Tests mock DB, verify search logic | `core_cli_example.md` |
| E3 | Add `examples/README.md` | `OPEN` | P2 | Documentation | Explains DB setup, PYTHONPATH, usage | `core_cli_example.md` |
| E4 | Verify Kodi-free imports | `OPEN` | P2 | Core independence | `grep -r "xbmc" examples/` returns nothing | `core_cli_example.md` |

---

## F. Documentation, Packaging & Release Preparation

| # | Task | Status | Priority | Rationale | Acceptance Criteria | Related Files / Audit |
|---|------|--------|----------|-----------|---------------------|----------------------|
| F1 | Update README.md with Kodi 20+ requirement | `OPEN` | P1 | Clear minimum version | README states "Kodi 20 (Nexus) or later required" | `kodi_api_compatibility.md` C9 |
| F2 | Verify add-on metadata versions | `OPEN` | P1 | Consistent versioning | All three `addon.xml` have matching version | `addon.xml` files |
| F3 | Prepare release notes / changelog | `OPEN` | P1 | User communication | Summarizes database refactor, screensaver/emulator fixes, bug fixes | `CHANGELOG.md` or release notes |
| F4 | Fresh installation test | `OPEN` | P1 | Upgrade readiness | Clean Kodi profile: add-on installs, downloads DB, starts correctly | Manual test |
| F5 | Upgrade test (existing profile) | `OPEN` | P1 | User migration | Existing profile: DB migration runs, legacy files imported/cleaned, screensaver history works | `database_refactor/history_persistence_audit.md` |
| F6 | Exclude development files from release package | `OPEN` | P1 | Clean distribution | `.git`, `docs/`, `tests/`, `__pycache__`, `.venv*`, `.mypy_cache`, `.ruff_cache` excluded | `addon.xml` packaging |
| F7 | Final release-candidate verification | `OPEN` | P0 | Final gate | All P0/P1 tasks complete; smoke test on Kodi 20+ | This plan |

---

## Dependency Graph

```
A1 (done)
  │
  ├─ A2 (Emulation extraction) (done)
  │     │
  │     └─ D6 (A2 unit tests)
  │
  ├─ A3 (GUI workflow split) (done)
  │     │
  │     └─ D6 (A3 unit tests)
  │
  └─ A4 (Screensaver split) (done)
        │
        └─ D6 (A4 unit tests)

A5 (Core reorg: scan_progress.py, game_labels.py, cmdline.py) → COMPLETE / optional

B1-B2 (Correctness fixes) → IN PROGRESS; B5 fixed in P0 round 1
B3-B4, B6-B13 (Style fixes) → Can run in parallel

C1-C3 (Runtime scenarios) → MAINTAINER-VERIFIED (screensaver-inhibition lifecycle)
C4-C8 (Compatibility) → Code audit done; C7 tracked in Area 2
C9 (Kodi 20 requirement in README) → Open documentation prerequisite

E1-E4 (CLI example) → Independent, post-release OK

F1-F7 (Release prep) → Three open manual areas (emulator matrix, Retroplayer, clean install/upgrade) must close first
```

---

## Recommended Next Actions (Ranked)

1. **Close the 3 open manual areas** — (1) full emulator startup matrix, (2) Retroplayer end-to-end (incl. C7), (3) clean installation and upgrade — *Requires Kodi 20+ environment*
2. **B1, B2** — Continue robustness triage. P0 round 1 result: BLE001 108→105, S110 54→29, PLW1510 1→0 (high-risk launcher startup paths fixed). P0 round 2 at `a74976b`: BLE001 105→107 (two formerly uncaught `exit()` operations now log), S110 29→24 (`gui.py` shutdown silent passes removed). P0 round 3: BLE001 107→109 (logged scanner cleanup boundaries), S110 24→17 (`dat_scanner.py`/`artwork_scanner.py` silent passes removed). P0 round 4: BLE001 109→112 (four logged GB64 cleanup boundaries, predicate handler now re-raises), S110 17→15 (`gb64_scanner.py` silent closes removed). P0 round 5: BLE001 112→115 (split detach handlers and outer UMSA cleanup guard), S110 15→10 (`database.py` silent closes removed). B1/B2 remain open across `umsa_gui/` and Core scanners/sockets — *Small per-module rounds*
3. **B6** — Convert f-string candidates (10 UP031 at `af3bd11`: `gui.py` 1, `umsa_gui/` 9; `database.py` is now clean) — *Quick wins, low risk*
4. **E1-E4** — CLI example — *Post-release OK*
5. **F1-F7** — Release prep — *After the manual areas and P0 fixes are complete*

---

## Evidence Summary

| Category | Verified In This Audit |
|----------|------------------------|
| Architecture boundaries | 7/7 tests pass (P0 round 1 rerun at `af3bd11`) |
| Core regression tests | All pass (historical 2026-10-23; P0 round 1 grouped run 64 passed) |
| Integration tests (stubs) | All pass (historical 2026-10-23; P0 round 1 grouped run 78 passed) |
| Full test suite | Historical: **1081 passed, 5 skipped, 18 subtests** (HEAD `4186b5f`). P0 round 1: **1130 passed, 5 skipped, 18 subtests** on rerun at `af3bd11`. P0 round 2: focused GUI/architecture run **94 passed**, full suite **1141 passed, 5 skipped, 18 subtests** at `a74976b`. P0 round 3: focused scanner/database run **70 passed**, full suite **1145 passed, 5 skipped, 18 subtests**. P0 round 4: focused GB64/database run **119 passed**, full suite **1150 passed, 5 skipped, 18 subtests**. P0 round 5: focused DBMod/repository/architecture run **240 passed**, full suite **1159 passed, 5 skipped, 18 subtests** |
| Ruff (production roots) | Reproduced baseline at `af3bd11`: **BLE001=108, S110=54, PLW1510=1** (163 rows / 108 unique exception locations). After round 1: **BLE001=105, S110=29, PLW1510=0** (134 rows / 105 locations). After round 2 at `a74976b`: **BLE001=107, S110=24, PLW1510=0** (131 rows / 107 locations). After round 3: **BLE001=109, S110=17, PLW1510=0** (126 rows / 109 locations). After round 4: **BLE001=112, S110=15, PLW1510=0** (127 rows / 112 locations). After round 5: **BLE001=115, S110=10, PLW1510=0** (125 rows / 115 locations). Default rules: 227→196→193→188→189→187 findings |
| Ruff historical baseline | The 2026-10-23 audit's 225 findings / BLE001=106 / S110=54 totals were **not reproduced** at `af3bd11`; see `static_analysis_audit.md` |
| `subprocess.run()` fix | Terminal fallback in `umsa_core/emulation.py`; non-zero logged, `OSError` wrapped in `ProcessLaunchError` with cause; 3 core regression tests + 2 launcher failure cases pass |
| Ruff auto-fixable | 25 safe fixes at `af3bd11` (not reviewed/applied in this round) |
| Mypy (`vgm_header.py`) | Clean (per-module, `--follow-imports=skip`) |
| Kodi API audit | No deprecated/removed APIs found |
| Kodi 20+ specific APIs | Capability-guarded (`setUniqueID`, `getGameInfoTag`) |
| Structural refactoring | Steps 1-4 done (A1, A2, A2b, A2c, A3, A4); Step 5 (A5) DEFERRED / optional |

---

## Maintainer-Confirmed Manual Smoke Tests (Recorded 2026-10-23)

The maintainer explicitly confirmed the following scenarios as successful on Kodi:

| Scenario | Status | Notes |
|----------|--------|-------|
| GUI navigation | ✅ MAINTAINER-VERIFIED | Menu, gamelist, filter, software selection, artwork display |
| Screensaver modes (Cross, Slide, Wall) | ✅ MAINTAINER-VERIFIED | Rendering loops, transitions, wait timing |
| Screensaver video playback and random selection | ✅ MAINTAINER-VERIFIED | Playlist, extraction, `onAVStarted` history |
| VGM controls | ✅ MAINTAINER-VERIFIED | Volume, next, stop from screensaver and GUI |
| Playback history | ✅ MAINTAINER-VERIFIED | GUI lastgames, screensaver history, filter selections |
| Database refactor Phases 4.0–4.8 | ✅ MAINTAINER-VERIFIED | Functional in Kodi runtime |
| Shared Kodi screensaver inhibition (emulator/screensaver lifecycle) | ✅ MAINTAINER-VERIFIED | Covers C1–C3 only; the per-emulator startup matrix is still open (Area 1) |

*These are maintainer-confirmed manual smoke-test results. They apply only to the scenarios listed above — not a claim that the entire add-on has passed all manual tests.*

---

## Manual Test Areas Remaining OPEN (Explicitly Not Completed)

The maintainer explicitly stated these three areas have **not** been completed:

| # | Area | Acceptance Criteria | Expected Evidence |
|---|------|---------------------|-------------------|
| 1 | **Full emulator startup matrix** | Individually verify each supported emulator launch path (MAME, SWL, eXoDOS, GB64, MARP, Demul, FS-UAE, Flycast, Retroplayer) and return-to-Kodi behavior | Per-emulator launch log, clean exit, Kodi focus restored, no orphaned processes |
| 2 | **Retroplayer end-to-end** | Verify launch, metadata handoff (`GameInfoTag`), gameplay entry, and return to Kodi | Game launches, metadata displays, session ends cleanly, `ctx.exit()` behavior verified |
| 3 | **Clean installation and upgrade** | Verify installation in a clean Kodi profile and upgrading an existing installation/profile | Fresh profile: add-on installs, DB downloads, starts correctly; Upgrade: DB migration runs, legacy files imported/cleaned, screensaver history works |

*Do not mark these completed based on code inspection, automated tests, or adjacent smoke tests. They require explicit manual verification on Kodi 20+.*

---

## Sign-Off Checklist for Release

- [ ] All P0 tasks complete
- [ ] All P1 tasks complete or explicitly deferred with rationale (A5 complete; optional)
- [x] Runtime scenarios C1-C3 verified (screensaver-inhibition lifecycle, maintainer-confirmed)
- [x] No new test failures introduced (P0 round 1 rerun: 1130 passed, 5 skipped; P0 round 2 full suite: 1141 passed, 5 skipped; P0 round 3 full suite: 1145 passed, 5 skipped; P0 round 4 full suite: 1150 passed, 5 skipped; P0 round 5 full suite: 1159 passed, 5 skipped)
- [x] Architecture boundary tests pass (7/7)
- [x] Ruff silent-failure baseline reduced (P0 round 1: default rules 227→196; BLE001 108→105, S110 54→29, PLW1510 1→0. P0 round 2: default rules 196→193; BLE001 105→107 from two newly logged `exit()` operations, S110 29→24. P0 round 3: default rules 193→188; BLE001 107→109 from logged scanner cleanup boundaries, S110 24→17. P0 round 4: default rules 188→189; BLE001 109→112 from four logged GB64 cleanup boundaries and the predicate handler re-raising, S110 17→15. P0 round 5: default rules 189→187; BLE001 112→115 from split DBMod detach/close handlers and the outer UMSA cleanup guard, S110 15→10; PLW1510 0; B1/B2 still open)
- [ ] Release notes prepared
- [ ] Fresh install + upgrade tests pass (open manual area 3)
- [ ] Full emulator startup matrix verified (open manual area 1)
- [ ] Retroplayer end-to-end verified (open manual area 2)
- [ ] Release candidate tagged