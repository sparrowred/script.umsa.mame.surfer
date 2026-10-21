# UMSA MAME Surfer — Release Plan

**Target:** Readiness-based (approx. 2 months)  
**Generated:** 2026-10-21  
**Based on:** Release quality audit (2026-10-21)

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
| A2 | Extract `Emulation` preparers/finders/extractors/VGM player | `CODE-VERIFIED` | P1 | 1200+ line god class; isolates emulator-specific logic | `emulation.py` 557 lines (was 1200+); all existing tests pass; new modules added | `refactoring_plan.md` Step 2, `emulation_audit.md` |
| A2b | Extract VGM socket transport (`vgm_socket.py`) | `CODE-VERIFIED` | P1 | VGM TCP transport, Lua log protocol mixed in `Emulation` | `vgm_socket.py` 339 lines created; `emulation.py` 557 lines; all 887 tests pass | `refactoring_plan.md` Step 2c, `emulation_audit.md` |
| A3 | Split `gui.py` `UMSA` into workflow modules | ✅ **CODE-VERIFIED** | P1 | 2600+ line god class; focus/navigation, gamelist, filter, artwork, scans, screensaver/VGM | `UMSA` 925 lines; 15 modules in `resources/lib/umsa_gui/` (largest `software_selector.py` 303 lines); 966 tests pass; public API unchanged; first-start DAT scan moved off the calling thread. **Manual Kodi smoke test still open (C-series)** | `refactoring_plan.md` Step 3, `gui_audit.md` |
| A4 | Separate Screensaver `Saver`/`Player`/`Monitor` | `OPEN` | P1 | 1200 line `ui.py` mixes rendering, playback, lifecycle, history | `Saver` < 300 lines; `Player` < 100; `Monitor` < 80; 7 focused modules; all tests pass | `refactoring_plan.md` Step 4, `screensaver_audit.md` |
| A5 | Phase 4.9 `database.py` reorganisation | `OPEN` | P1 | 1820 lines (down from 69k); non-DB helpers still in `DBMod` | `database.py` < 30k lines; `scan_progress.py`, `game_labels.py`, `cmdline.py` created; re-exports work; boundary tests pass | `refactoring_plan.md` Step 5, `database_refactor/roadmap.md` |
| A6 | Optional further `DBMod` decomposition | `DEFERRED` | Post-release | Mixed queries (`get_random_id`, `get_random_art`), cross-db `open_db` | Only if maintenance burden grows | `refactoring_plan.md` Step 6, `dbmod_audit.md` |

---

## B. Python Style & Static Analysis

| # | Task | Status | Priority | Rationale | Acceptance Criteria | Related Files / Audit |
|---|------|--------|----------|-----------|---------------------|----------------------|
| B1 | Fix 102 `BLE001` (blind `except Exception:`) | `OPEN` | P0 | Hides real errors; 10 in `emulator_launcher.py` alone | All `except Exception:` replaced with specific types + logging | `static_analysis_audit.md`, `emulator_launcher.py`, `gui.py`, `ui.py` |
| B2 | Fix 52 `S110` (`except Exception: pass`) | `OPEN` | P0 | Silent failures mask bugs | All silent catches replaced with logging or removed | `static_analysis_audit.md` |
| B3 | Fix 1 `E722` (bare `except:`) | `OPEN` | P0 | Catches `SystemExit`, `KeyboardInterrupt` | Replace with specific exception type | `static_analysis_audit.md` |
| B4 | Fix 1 `B006` (mutable default arg) | `OPEN` | P0 | Shared mutable state across calls | Change to `arg=None` pattern | `static_analysis_audit.md` |
| B5 | Fix 1 `PLW1510` (`subprocess.run` without `check=True`) | `OPEN` | P0 | Failures not raised | Add `check=True` or explicit error handling | `static_analysis_audit.md` |
| B6 | Convert 24 `UP031` (`%` formatting → f-strings) | `OPEN` | P1 | Consistency, readability | All clear candidates converted; SQL/MAME/logging exceptions preserved | `python_style_audit.md` |
| B6a | — `gamelist_strategies.py` (8) | ✅ **CODE-VERIFIED** | P1 | | | `python_style_audit.md` |
| B6b | — `gui.py` (6) | `OPEN` | P1 | | | `python_style_audit.md` |
| B6c | — `emulator_launcher.py` (4) | `OPEN` | P1 | | | `python_style_audit.md` |
| B6d | — `ui.py` (3) | `OPEN` | P1 | | | `python_style_audit.md` |
| B6e | — `emulation.py` (2) | `OPEN` | P1 | | | `python_style_audit.md` |
| B7 | Fix 1 `UP030` (explicit `.format()` index) | `OPEN` | P1 | `emulation.py:1091` | Convert to f-string | `python_style_audit.md` |
| B8 | Fix 6 `UP007` (union syntax `X \| Y`) | `OPEN` | P1 | Python 3.10+ | All `Union[X, Y]` → `X \| Y` | `static_analysis_audit.md` |
| B9 | Fix 6 `SIM115` (context managers for `open()`) | `OPEN` | P1 | Resource leaks | All `open()` in `with` blocks | `static_analysis_audit.md` |
| B10 | Fix 4 `F841` (unused variables) | `OPEN` | P1 | Dead code indicator | Remove or use variables | `static_analysis_audit.md` |
| B11 | Fix 2 `F401` (unused imports) | `OPEN` | P1 | Clean code | Remove unused imports | `static_analysis_audit.md` |
| B12 | Fix 2 `TRY203` (useless try/except) | `OPEN` | P1 | Redundant | Remove unnecessary try/except | `static_analysis_audit.md` |
| B13 | Run Ruff `--fix` with review | `OPEN` | P2 | Automated cleanup | 4 auto-fixable + 18 unsafe-fixable reviewed | `static_analysis_audit.md` |
| B14 | Document 13 pre-existing test failures | ✅ **CODE-VERIFIED** | P0 | Known limitations | Documented in this plan | `static_analysis_audit.md` |

---

## C. Kodi API Compatibility

| # | Task | Status | Priority | Rationale | Acceptance Criteria | Related Files / Audit |
|---|------|--------|----------|-----------|---------------------|----------------------|
| C1 | Execute Scenario A (Emulator idle timeout) | `OPEN` | P0 | Verify screensaver inhibition during emulator | Kodi 20+: emulator runs beyond idle timeout; no competing screensaver; idle resumes after exit | `kodi_api_compatibility.md` Scenarios |
| C2 | Execute Scenario B (Manual screensaver) | `OPEN` | P0 | Verify manual screensaver blocks idle | Kodi 20+: manual screensaver active beyond timeout; no competing idle; C-key handoff works; idle resumes after exit | `kodi_api_compatibility.md` Scenarios |
| C3 | Execute Scenario C (Automatic screensaver) | `OPEN` | P0 | Verify automatic mode unaffected | Kodi 20+: Kodi-launched screensaver works; `UMSA.Screensaver.Manual` not set | `kodi_api_compatibility.md` Scenarios |
| C4 | Verify `special://` paths use `xbmcvfs.translatePath()` | `OPEN` | P0 | `os.path` fails on `special://` URIs | All `special://` paths go through `translatePath()` before `os.path` ops | `kodi_api_compatibility.md` |
| C5 | Test `DialogProgress`/`DialogProgressBG` on Kodi 20+ | `OPEN` | P1 | Modal dialog behavior | Dialogs display, update, dismiss cleanly on Estuary skin | `kodi_api_compatibility.md` |
| C6 | Confirm `Player.onAVStarted` fires once per video | `OPEN` | P1 | History recording accuracy | Exactly one `onAVStarted` per screensaver video; deduplication works | `kodi_api_compatibility.md` |
| C7 | Test Retroplayer `GameInfoTag` metadata | `OPEN` | P1 | Game metadata display | `type='game'` metadata populates correctly on Kodi 20+ | `kodi_api_compatibility.md` |
| C8 | Verify no deprecated APIs in codebase | ✅ **CODE-VERIFIED** | P1 | Audit complete | No deprecated/removed APIs found for Kodi 20+ | `kodi_api_compatibility.md` |
| C9 | Document minimum Kodi version as 20 (Nexus) | `OPEN` | P1 | Clear requirement | README.md states Kodi 20+ required | `README.md` |

---

## D. Tests & Runtime Verification

| # | Task | Status | Priority | Rationale | Acceptance Criteria | Related Files / Audit |
|---|------|--------|----------|-----------|---------------------|----------------------|
| D1 | Document 13 pre-existing test failures | ✅ **CODE-VERIFIED** | P0 | Known limitations | Failures listed in this plan; no new failures introduced | `static_analysis_audit.md` |
| D2 | Core regression test suite passes | `OPEN` | P0 | No Kodi needed | `test_database.py`, `test_game_repository.py`, `test_dat_repository.py`, `test_artwork_repository.py`, `test_emulator_repository.py`, `test_status_repository.py`, `test_history_repository.py`, `test_emulation_process.py`, `test_emulation_chd.py`, `test_emulation_vgm_callback.py`, `test_process.py`, `test_sqlite.py`, `test_scan_coordinator.py` all pass | `static_analysis_audit.md` |
| D3 | Integration test suite passes (Kodi stubs) | `OPEN` | P0 | Frontend/Screensaver integration | `test_frontend_entrypoint.py`, `test_emulator_launcher.py`, `test_screensaver_addon.py`, `test_screensaver_history_hooks.py`, `test_screensaver_history_repository.py`, `test_gui_history_navigation.py` all pass | `static_analysis_audit.md` |
| D4 | Architecture boundary tests pass | ✅ **CODE-VERIFIED** | P0 | Kodi-free Core | 7/7 tests pass | `test_architecture_boundaries.py` |
| D5 | Full suite ≥ 882 passed, no new failures | ✅ **CODE-VERIFIED** | P0 | Regression guard | 966 passed, 5 skipped, 18 subtests — no failures left (the 13 known failures from the audit snapshot are gone) | `static_analysis_audit.md` |
| D6 | Add unit tests for Step A2 (Emulation extraction) | `OPEN` | P1 | New modules need coverage | Preparers, finders, extractors, VGM player each have unit tests | `refactoring_plan.md` Step 2 |
| D6 | Add unit tests for Step A3 (GUI workflow modules) | ✅ **CODE-VERIFIED** | P1 | New modules need coverage | `tests/test_umsa_gui_workflows.py` (47 tests) covers all 15 modules of `umsa_gui` with a fake `UMSA` instance; `tests/test_gui_oninit_first_start.py` (5 tests) pins the first-start scan thread. **Local-only files** (`tests/` is gitignored) | `refactoring_plan.md` Step 3 |
| D6 | Add unit tests for Step A4 (Screensaver modules) | `OPEN` | P1 | New modules need coverage | 7 screensaver modules each have unit tests | `refactoring_plan.md` Step 4 |
| D6 | Add unit tests for Step A5 (Core reorg modules) | `OPEN` | P1 | New modules need coverage | `scan_progress.py`, `game_labels.py`, `cmdline.py` each have tests | `refactoring_plan.md` Step 5 |

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
  ├─ A2 (Emulation extraction)
  │     │
  │     ├─ A5 (Core reorg: cmdline.py)
  │     │
  │     └─ D6 (A2 unit tests)
  │
  ├─ A3 (GUI workflow split)
  │     │
  │     └─ D6 (A3 unit tests)
  │
  └─ A4 (Screensaver split)
        │
        └─ D6 (A4 unit tests)

B1-B5 (Correctness fixes) → Can start immediately, independent
B6-B13 (Style fixes) → Can run in parallel with A2-A5

C1-C3 (Runtime scenarios) → Require Kodi 20+ environment
C4-C8 (Compatibility) → Code audit done; runtime verification needed

E1-E4 (CLI example) → Independent, post-release OK

F1-F7 (Release prep) → After A2-A5, C1-C3, D1-D5 complete
```

---

## Recommended Next Actions (Ranked)

1. **B1, B2, B3, B4, B5** — Fix correctness issues (BLE001, S110, E722, B006, PLW1510) — *Immediate, independent*
2. **A2** — Extract `Emulation` preparers/finders/extractors/VGM — *Unblocks A5, reduces god class*
3. **B6** — Convert f-string candidates (24 UP031) — *Quick wins, low risk*
4. **A5** — Move non-DB helpers out of `database.py` — *Reduces `DBMod` complexity*
5. **A3** — Split `gui.py` workflow modules — ✅ *done (CODE-VERIFIED), manual smoke test still open*
6. **A4** — Split screensaver `ui.py` — *Medium impact, depends on A2/A3 for VGM protocol*
7. **C1, C2, C3** — Kodi runtime verification — *Requires Kodi 20+ environment*
8. **D6** — Add unit tests for new modules — *Parallel with A2-A5*
9. **E1-E4** — CLI example — *Post-release OK*
10. **F1-F7** — Release prep — *After all above complete*

---

## Evidence Summary

| Category | Verified In This Audit |
|----------|------------------------|
| Architecture boundaries | 7/7 tests pass |
| Core regression tests | ~200 pass (sampled) |
| Integration tests (stubs) | 140 pass (sampled) |
| Full test suite | 966 passed, 5 skipped, 18 subtests (re-verified 2026-10-21 after the A3 final verification; the audit snapshot recorded 882 passed with 13 pre-existing failures — the suite is green now) |
| Ruff correctness issues | 157 (BLE001/S110/E722/B006/PLW1510) |
| Ruff style issues | 60 (UP031, UP007, etc.) |
| Mypy (Core modules) | Clean (per-module, `--follow-imports=skip`) |
| Kodi API audit | No deprecated/removed APIs found |
| Kodi 20+ specific APIs | Capability-guarded (`setUniqueID`, `getGameInfoTag`) |
| Structural refactoring | Steps 1-3 done (A1, A2, A2b, A3); Steps 4-5 planned |

---

## Maintainer-Reported Evidence (Not Independently Verified)

- Database refactor Phases 4.0–4.8 functional
- Screensaver/emulator lifecycle fixes working
- Recent Kodi smoke tests behaved as expected
- No major issues observed during ongoing testing

*Recorded as maintainer-reported; not a substitute for automated/runtime verification in this audit.*

---

## Sign-Off Checklist for Release

- [ ] All P0 tasks complete
- [ ] All P1 tasks complete or explicitly deferred with rationale
- [ ] Runtime scenarios C1-C3 verified on Kodi 20+
- [ ] No new test failures introduced
- [ ] Architecture boundary tests pass
- [ ] Ruff correctness baseline maintained (no increase)
- [ ] Release notes prepared
- [ ] Fresh install + upgrade tests pass
- [ ] Release candidate tagged