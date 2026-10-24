# Release Quality Audit — UMSA MAME Surfer

**Repository state:** git HEAD `4186b5f5dd3479b19df84215d1fa21a4cbb38f29` (audited 2026-10-23)  
**Scope:** All three add-ons (Frontend, Core, Screensaver), tests, tooling, packaging  
**Generated:** 2026-10-23 (read-only audit, no production code modified)

---

## Executive Summary

The UMSA MAME Surfer project is a three-add-on Kodi ecosystem (Frontend GUI, Shared Core, Screensaver) with a strict Kodi-independent Core boundary. The database refactor (Phases 4.0–4.8) is complete: `DBMod` has delegated most SQL to focused repositories and the `gamelist_filter` service. Architecture boundary tests pass. Structural refactoring Steps 1–4 (A1–A4) are complete: dead code removal, Emulation extraction, GUI workflow split, and Screensaver split.

**Current test status:** 1081 passed, 5 skipped, 18 subtests passed (verified 2026-10-23 at HEAD `4186b5f`)  
**Architecture boundary tests:** 7/7 passed  
**Lint (Ruff, repo root):** 225 issues across 19 rule codes  
**Type check (mypy):** Clean on `vgm_header.py` (per-module, `--follow-imports=skip`); the package `__init__` still drags in pre-existing `persistence.py` errors

---

## Key Findings by Area

### 1. Python Style & String Formatting (`python_style_audit.md`)
- **16** instances of legacy `%` formatting (UP031): `database.py` 6, `umsa_gui/software_selector.py` 3, `umsa_gui/artwork_presenter.py` 2, `umsa_gui/filter_ui.py` 2, `umsa_gui/media_list.py` 2, `gui.py` 1. `gamelist_strategies.py`, `emulator_launcher.py`, `emulation.py` and the screensaver add-on are clean
- **1** instance of explicit `.format()` positional index (UP030) in `launch_preparer.py:134`
- **f-strings** are already the dominant style in newer code
- **Recommendation:** Convert clear candidates to f-strings; preserve `%` in SQL placeholders, MAME format strings, and logging lazy interpolation

### 2. Static Analysis & Code Quality (`static_analysis_audit.md`)
- **225** Ruff issues across 19 rule codes
- Top issues: `BLE001` (blind `except Exception:`) — 106 occurrences; `S110` (silent `except …: pass`) — 54; `F401` (unused import) — 17
- **19** safe fixes (`F401` 17, `I001` 2); 17 further hidden fixes only with `--unsafe-fixes`
- **1** mypy error remains when the package `__init__` is followed into `persistence.py` (pre-existing var-annotated); per-module `vgm_header.py` check is clean
- Architecture boundary tests (7) pass — validates Kodi-free Core and connection encapsulation

### 3. Kodi API Compatibility (`kodi_api_compatibility.md`)
- **Declared minimum:** `xbmc.python` 3.0.0 = **Kodi 20 (Nexus)**
- **Confirmed compatible (capability-guarded):**
  - `InfoTagVideo.setUniqueID`/`getUniqueID` (@python_v20) — used in `ui.py` with `hasattr` guards
  - `ListItem.setInfo` with `type='game'` + `getGameInfoTag()` — used in `retroplayer_cache.py`
- **No confirmed deprecated/removed APIs** found in current codebase for Kodi 20+
- **Runtime status:** `special://` path handling is code-verified (C4); `DialogProgress`/`DialogProgressBG` and `Player.onAVStarted` were confirmed by the maintainer (C5/C6); Retroplayer `GameInfoTag` (C7) remains open under **Area 2**

### 4. Structural Refactoring Status (`refactor_audit/` + this audit)
| Step | Description | Status |
|------|-------------|--------|
| 1 | Remove dead code in `UMSA.run_emulator()` | ✅ **Done** (2026-10-20) |
| 2 | Extract `Emulation` emulator-specific prep | ✅ **Done** (2026-10-21) — 6 modules extracted |
| 2b | Extract VGM socket transport (`vgm_socket.py`) | ✅ **Done** (2026-10-21) |
| 2c | Fix VGM callback signatures and entry points | ✅ **Done** (2026-10-21) |
| 3 | Split `gui.py` `UMSA` into workflow modules | ✅ **Done** (2026-10-21) — 15 modules in `umsa_gui/` |
| 4 | Separate Screensaver `Saver`/`Player`/`Monitor` | ✅ **Done** (2026-10-22) — 11 modules in `lib/umsa_screensaver/` |
| 5 | Phase 4.9 `database.py` reorganisation | 📋 **Deferred** (optional; ~1857 lines, down from 69k) |
| 6 | Optional further `DBMod` decomposition | 📋 **Deferred** |

**Completed:** Database refactor Phases 4.0–4.8 (repositories, `gamelist_filter`, row-leak closure, artwork/DAT source-of-truth, history migration)

### 5. Standalone `umsa_core` CLI Example (`core_cli_example.md`)
- **Feasible:** Yes — Core is Kodi-free, exposes `connect_sqlite`, `GameRepository`, `CoreDataPaths`, `parse_vgm_header`, etc.
- **Prerequisites:** `PYTHONPATH` to `script.module.umsa.core/lib`, downloaded `umsa.db`
- **Proposed example:** Search game by name → print ID, name, year, maker
- **Status:** Not yet implemented

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Blind `except Exception:` hides real errors | High | High | Fix BLE001 (106) / S110 (54) incrementally; add logging |
| Kodi 20+ API assumptions untested in CI | Medium | High | C1–C3 confirmed; finish the 3 open manual areas (emulator matrix, Retroplayer, clean install/upgrade) |
| `umsa_core` import drags `persistence.py` mypy errors | Low | Low | `--follow-imports=skip`; type-check `vgm_header.py` only |
| Large `database.py` / `gui.py` hinder maintenance | Medium | Medium | A1–A4 complete; A5 (database) explicitly deferred, not a release blocker |

---

## Recommended Implementation Order

1. **P0 — Release Blockers**
   - Close the 3 open manual areas: full emulator startup matrix, Retroplayer end-to-end (incl. `GameInfoTag`), clean install + upgrade
   - Fix the high-risk blind excepts (`BLE001` 106 / `S110` 54), starting with `emulator_launcher.py`, `gui.py`, `ui.py`
   - Add the Kodi 20+ requirement to `README.md` (C9/F1)

2. **P1 — Should Fix Before Release**
   - Convert clear f-string candidates (UP031) — 16 cases
   - Fix `PLW1510` (1), `UP030` (1), `TRY203` (2)
   - Run full test suite + architecture boundary tests after each change

3. **P2 — Important but Deferrable**
   - Implement standalone `umsa_core` CLI example
   - Full Ruff `--fix` cleanup with review (19 fixable)

4. **Post-Release**
   - Optional / deferred Phase 4.9 `database.py` reorganisation (A5)

---

## Evidence Categories

| Category | Source |
|----------|--------|
| ✅ Verified by static source inspection | This audit (grep, read, Ruff, pytest) |
| ✅ Confirmed by tests executed during audit | `test_architecture_boundaries.py` (7), Ruff (225 across 19 codes), pytest (1081 passed, 5 skipped, 18 subtests — verified 2026-10-23 at HEAD `4186b5f`) |
| 📋 Maintainer-confirmed manual smoke tests | GUI navigation, screensaver modes (Cross/Slide/Wall), video playback, VGM controls, playback history, DB refactor Phases 4.0–4.8, screensaver inhibition — **recorded in `release-plan.md`** |
| 📜 Historical results from previous commits | Database refactor Phases 4.0–4.8 test counts (recorded in `docs/database_refactor/`); Step 4.7 full suite 661 passed; Step 4.6.2 full suite 819 passed |
| ❓ Unverified / proposed | 3 open manual areas (emulator matrix, Retroplayer E2E, clean install/upgrade), standalone CLI example, Step 5 (A5) refactoring |

---

## Audit Document Map

| Document | Purpose |
|----------|---------|
| [`python_style_audit.md`](python_style_audit.md) | String formatting inventory, conversion candidates, exceptions |
| [`static_analysis_audit.md`](static_analysis_audit.md) | Ruff/mypy findings, tooling config, quality gate recommendations |
| [`kodi_api_compatibility.md`](kodi_api_compatibility.md) | Kodi 20+ API audit, capability guards, runtime verification scenarios |
| [`core_cli_example.md`](core_cli_example.md) | Feasibility, prerequisites, proposed implementation, test plan |
| [`release-plan.md`](release-plan.md) | Consolidated checklist with status, priority, acceptance criteria |

---

## Verification Commands Executed (2026-10-23 at HEAD `4186b5f`)

```bash
# Architecture boundary tests (7 passed)
.venv-debian-vm/bin/python -m pytest tests/test_architecture_boundaries.py -v

# Ruff lint (225 issues, 19 fixable)
.venv-debian-vm/bin/python -m ruff check . --statistics

# Full test suite (1081 passed, 5 skipped, 18 subtests)
.venv-debian-vm/bin/python -m pytest tests/ -q

# Ruff f-string candidates (16 real UP031)
.venv-debian-vm/bin/python -m ruff check . --select UP031

# Mypy on Core modules (clean with --follow-imports=skip)
.venv-debian-vm/bin/python -m mypy script.module.umsa.core/lib/umsa_core/vgm_header.py --follow-imports=skip
```

---

## Confirmation

- ✅ No production code modified
- ✅ No tests modified
- ✅ No configuration files changed
- ✅ Only documentation under `docs/` updated
- ✅ All recommendations supported by observed implementation details
- ✅ Maintainer-confirmed manual smoke tests vs independently verified clearly distinguished
- ✅ Three open manual areas explicitly listed and not claimed as complete