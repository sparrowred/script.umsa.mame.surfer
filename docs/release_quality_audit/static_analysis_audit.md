# Static Analysis & Code Quality Audit

**Audited:** 2026-10-23 (historical audit at HEAD `4186b5f5dd3479b19df84215d1fa21a4cbb38f29`)
**P0 revalidation:** 2026-10-25 at HEAD `af3bd11598692943e9c8f8a3dbc5ef457a6f5f3f`
**Tools:** Ruff (primary), mypy (limited), Architecture boundary tests (AST-based)  
**Scope:** All production Python in three add-ons

---

## Tooling Inventory

| Tool | Version | Config | Status |
|------|---------|--------|--------|
| **Ruff** | 0.16.10 (via `.venv-debian-vm`) | default | ✅ Active — 227 baseline / 196 after P0 round 1 (default rules) |
| **mypy** | 1.x (via `.venv-debian-vm`) | `mypy.ini` / default | ⚠️ Partial — single modules only with `--follow-imports=skip` |
| **pytest** | 9.x | default | ✅ Active — 1130 passed, 0 failed, 5 skipped (P0 round 1 rerun) |
| **Architecture boundary tests** | Custom (AST) | `tests/test_architecture_boundaries.py` | ✅ 7/7 passed |

### Configuration Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Ruff config (if present), mypy config |
| `mypy.ini` | mypy config — `follow_imports = skip` for Core |
| `pytest.ini` | pytest config — `testpaths = tests` |
| `requirements-dev.txt` | Dev dependencies: `Kodistubs`, `pytest`, `pytest-cov`, `ruff`, `mypy`, `Pillow` |

---

## Ruff Findings

### P0 round 1 — reproduced baseline and current result

Command (production roots only):

```bash
.venv-debian-vm/bin/python -m ruff check \
    plugin.program.umsa.mame.surfer \
    screensaver.umsa.mame.surfer \
    script.module.umsa.core \
    --select BLE001,S110,PLW1510 --statistics
```

| Rule | Baseline at `af3bd11` | After round 1 |
|------|----------------------|---------------|
| **BLE001** | 108 | 105 |
| **S110** | 54 | 29 |
| **PLW1510** | 1 | **0** |
| **Total reported rows** | **163** | **134** |
| **Unique exception source locations** | **108** | **105** |

**Counting note:** the baseline reported 162 `BLE001`+`S110` rows but only 108
unique file/line locations, because every `S110` location was also a `BLE001`
location. Do not add the two rule counts as if they were independent sites.
After round 1, the 105 `BLE001` rows are 105 unique locations; `S110` remains a
subset of those locations.

The historical totals (BLE001=106, S110=54, PLW1510=1) were **not reproduced**
at `af3bd11`; the reproduced baseline was BLE001=108, S110=54, PLW1510=1.
Under Ruff's default rule set the reproduced baseline was 227 findings across
19 codes (the historical audit recorded 225); after round 1 it is 196 findings
across 18 codes.

### Current findings by rule (after round 1)

| Code | Count | Description | Fixable |
|------|-------|-------------|---------|
| **BLE001** | 105 | Blind `except Exception:` — catches too broadly | ❌ |
| **S110** | 29 | `try: ... except Exception: pass` — silent failure | ❌ |
| **F401** | 21 | Unused import | ✅ |
| **UP031** | 10 | Legacy `%` formatting → prefer f-strings | ❌ |
| **UP007** | 6 | Union syntax `Union[X, Y]` → `X \| Y` (Python 3.10+) | ❌ |
| **SIM115** | 5 | `open()` without context manager | ❌ |
| **SIM113** | 4 | `enumerate()` instead of manual index | ❌ |
| **F841** | 4 | Unused variable | ❌ |
| **I001** | 3 | Unsorted imports | ✅ |
| **SIM102** | 1 | Collapsible `if` statements | ❌ |
| **UP030** | 1 | Explicit `.format()` positional index | ❌ |
| **PLR1730** | 1 | Replace `if` with `min`/`max` | ✅ |
| **SIM118** | 1 | `key in dict.keys()` | ❌ |
| **PERF402** | 1 | Manual list copy | ❌ |
| **EXE002** | 1 | Shebang on non-executable file | ❌ |
| **C413** | 1 | Unnecessary `sorted()` call | ❌ |
| **RUF046** | 1 | Unnecessary `int()` cast | ❌ |
| **RUF059** | 1 | Unused unpacked variable | ❌ |
| **Total** | **196** | | **25 safe fixes** |

> `E722` (bare `except:`), `B006` (mutable default) and `TRY203` were reported
> by earlier audits; `E722`/`B006` are absent and the 2 `TRY203` findings were
> removed in round 1 (`emulator_launcher.py`).

### High-Priority Findings (Correctness Risk)

#### 1. BLE001 / S110 — Blind Exception Handling (remaining after round 1)

Remaining findings grouped by module and functional risk. Counts are Ruff
reported rows; the `S110` rows are the same source locations as `BLE001` rows,
so the unique location counts are the `BLE001` counts.

| Module | BLE001 | S110 | Unique locations | Risk / status |
|--------|--------|------|------------------|---------------|
| `emulator_launcher.py` | 25 | 0 | 25 | Medium-low. Round 1 removed every silent pass and the high-risk startup paths. Remaining broad handlers are logged UI progress/close/notification, media pause, optional output, and best-effort status/artwork boundaries. |
| `gui.py` | 5 | 5 | 5 | Medium. Shutdown/cleanup only (`exit()` path); failures are still silent and should be made diagnosable in a later focused round. |
| `umsa_gui/emulator_setup.py` | 4 | 2 | 4 | Low-medium. Emulator output list and final notification UI; failures do not affect emulator execution. |
| `umsa_gui/optional_plugins.py` | 1 | 0 | 1 | Low. Intentional optional PDF-plugin import fallback. |
| `umsa_gui/scan_orchestrator.py` | 1 | 1 | 1 | Low. Progress-dialog close cleanup. |
| `umsa_gui/screensaver_vgm.py` | 2 | 0 | 2 | Low. VGM label updates already log the failure at debug level. |
| `umsa_gui/startup_import.py` | 1 | 0 | 1 | Low. Legacy import failure is logged at error level and retried next start by design. |
| `umsa_core/artwork_scanner.py` | 8 | 2 | 8 | Medium. Scan discovery/status paths mostly log; remaining entries are close/cleanup boundaries. |
| `umsa_core/dat_scanner.py` | 10 | 5 | 10 | Medium. Parse/publish failures are logged and abort the scan; remaining entries are rollback/close cleanup. |
| `umsa_core/database.py` | 5 | 5 | 5 | Low. Connection cleanup; failed open cleanup re-raises the original exception. |
| `umsa_core/exodos_artwork.py` | 9 | 0 | 9 | Low-medium. Cleanup/status failures are logged and surfaced in scan summaries. |
| `umsa_core/exodos_scanner.py` | 4 | 0 | 4 | Low-medium. Cancellation/progress callback boundaries. |
| `umsa_core/game_labels.py` | 2 | 0 | 2 | Low. Bad timestamp/input normalization. |
| `umsa_core/gb64_scanner.py` | 11 | 2 | 11 | Medium. Scan logging and cleanup boundaries. |
| `umsa_core/vgm_player.py` | 3 | 1 | 3 | Low. Callback failures are logged; one optional label update is silent. |
| `umsa_core/vgm_socket.py` | 14 | 6 | 14 | Low. Socket shutdown/close cleanup and logging on connection failure. |
| `screensaver` add-on | 0 | 0 | 0 | Clean for BLE001/S110. |

**Round 1 changes in `emulator_launcher.py`:** all `except Exception: pass`
handlers now log with the operation that failed. Expected data/lookup errors in
disk/extracted-file selection use narrow `(KeyError, IndexError, TypeError)`
catches. The two redundant `except Exception: raise` wrappers were removed.
Startup failures (`OSError`, including `ProcessLaunchError`) are logged at error
level, close the progress dialog, clear the emulator-running property in the
existing `finally`, and re-raise. Optional UI/cleanup handlers remain broad on
purpose but are no longer silent.

#### 2. PLW1510 — `subprocess.run()` without `check=True` (fixed in round 1)

The finding was in `umsa_core/emulation.py:286` in `Emulation.run()`, branch
`emulation_start == 2` (terminal fallback) — **not** in CHD extraction. CHD
extraction uses `Popen` in `chd_extractor.py` and was not changed.

The fallback now calls `subprocess.run(torun, check=False)` explicitly, logs a
non-zero return code at error level, and wraps `OSError` in
`ProcessLaunchError` raised `from` the original exception. Successful terminal
arguments, working directory behavior, and the managed `emulation_start` 0/1
paths are unchanged. Regression tests were added in
`tests/test_emulation_process.py` (success, non-zero, launch failure/cause) and
`tests/test_emulator_launcher.py` (launch failure cleanup for managed and
fallback modes).

#### 3. F841 — Unused Variables (4 occurrences)

Dead code — may indicate incomplete refactoring.

#### 4. F401 — Unused Imports (17 occurrences)

Most are intentional compatibility re-exports; either remove or make them
explicit re-exports so Ruff stops flagging them.

---

## Mypy Findings

### Core Package (with `--follow-imports=skip`)

```bash
.venv-debian-vm/bin/python -m mypy script.module.umsa.core/lib/umsa_core/vgm_header.py --follow-imports=skip
# → Success: no issues found in 1 source file
```

```bash
.venv-debian-vm/bin/python -m mypy script.module.umsa.core/lib/umsa_core/sqlite.py --follow-imports=skip
# → Success: no issues found in 1 source file
```

```bash
.venv-debian-vm/bin/python -m mypy script.module.umsa.core/lib/umsa_core/status_repository.py --follow-imports=skip
# → Success: no issues found in 1 source file
```

```bash
.venv-debian-vm/bin/python -m mypy script.module.umsa.core/lib/umsa_core/emulator_repository.py --follow-imports=skip
# → Success: no issues found in 1 source file
```

### Core Package Import Drag

```bash
.venv-debian-vm/bin/python -m mypy script.module.umsa.core/lib/umsa_core/__init__.py --follow-imports=skip
# → Errors from persistence.py var-annotated issues (pre-existing)
```

**Root cause:** `umsa_core/__init__.py` imports `persistence.py` which has var-annotated type errors. The `--follow-imports=skip` prevents transitive checking but the import itself triggers the error.

**Workaround:** Type-check individual modules with `--follow-imports=skip`; avoid checking `__init__.py` directly.

### GUI/Screensaver Add-ons

Cannot type-check without Kodi stubs (`Kodistubs` package). Requires Kodi runtime environment.

---

## Architecture Boundary Tests (7/7 Passed)

| Test | Purpose | Status |
|------|---------|--------|
| `test_no_kodi_imports_in_core_outside_the_adapter` | No `xbmc*` imports in `umsa_core/` except `umsa_core_kodi.py` | ✅ |
| `test_adapter_is_the_only_documented_kodi_exception` | Adapter is exactly one file | ✅ |
| `test_kodi_guard_detects_both_import_forms_and_ignores_local_imports` | Guard detects `import xbmc` and `from xbmc import ...` | ✅ |
| `test_connection_attributes_accessed_only_in_database_py` | `gdb`/`gdbc`/`sdb`/`sdbc` only in `database.py` | ✅ |
| `test_connection_guard_flags_new_modules_and_respects_the_facade_handle` | Synthetic violations detected; `ggdb` facade allowed | ✅ |
| `test_dbmod_never_exposes_a_ggdb_attribute` | `DBMod` doesn't access `.ggdb` | ✅ |
| `test_guard_scans_every_production_root_and_key_modules` | All 3 add-ons scanned, ≥30 files | ✅ |

**Implementation:** Pure AST parsing (`ast` module) — no imports, no Kodi runtime needed.

---

## Test Suite Status

### P0 round 1 verification (2026-10-25, HEAD `af3bd11`)

| Command | Result |
|---------|--------|
| `pytest tests/test_emulation_process.py tests/test_emulator_launcher.py -v` | **12 passed** |
| `pytest tests/test_emulation_process.py tests/test_emulation_chd.py tests/test_emulation_vgm_callback.py tests/test_process.py tests/test_sqlite.py tests/test_scan_coordinator.py -q` | **64 passed** |
| `pytest tests/test_emulator_launcher.py tests/test_frontend_entrypoint.py tests/test_gui_history_navigation.py tests/test_umsa_gui_workflows.py -q` | **78 passed** |
| `pytest tests/test_architecture_boundaries.py -v` | **7 passed** |
| `pytest tests/ -q` (first run) | 1129 passed, **1 failed**, 5 skipped, 18 subtests — transient DNS failure in local-only `test_umsa_db_download.py::test_download_and_update_umsa_db_preserves_existing_dir` |
| `pytest tests/ -q` (rerun) | **1130 passed, 5 skipped, 18 subtests** |

The first full-suite failure was `socket.gaierror: Temporary failure in name
resolution` while the test tried to reach `umsa.info`; the same test file passed
in isolation (7 passed) and the full-suite rerun passed. It is not caused by the
round-1 changes.

### Historical audit run (2026-10-23, HEAD `4186b5f`)

| Suite | Passed | Failed | Skipped | Notes |
|-------|--------|--------|---------|-------|
| Full suite | 1081 | 0 | 5 | No failures; 5 skips are real-MAME integration only |
| `test_architecture_boundaries.py` | 7 | 0 | 0 | All passed |
| `test_frontend_entrypoint.py` | 7 | 0 | 0 | Updated for new imports |
| `test_emulator_launcher.py` | 5 | 0 | 0 | Disk selection logic |
| `test_screensaver_addon.py` | 19 | 0 | 0 | Request handling, runtime |
| `test_screensaver_history_hooks.py` | 52 | 0 | 0 | Kodi-stub history tests |
| `test_screensaver_history_repository.py` | 51 | 0 | 0 | DB history logic |
| `test_gui_history_navigation.py` | 17 | 0 | 0 | Updated for new imports |

### Historical Pre-existing Failures (from an earlier audit)

An earlier run reported 13 failures in these files. All now pass at this HEAD;
the table is kept only for chronology.

| Test File | Then | Likely Cause |
|-----------|------|--------------|
| `test_gamelist_strategies.py` | 2 | Readonly DB in test fixture |
| `test_series_sublist_menu.py` | 9 | Stub `FakeGGDB` missing methods |
| `test_umsa_db_download.py` | 3 | Progress callback assertion mismatch |

**Status:** Resolved; the current full suite has 0 failures (5 skipped).

---

## Recommended Quality Gates for Release

### Minimum (P0 — Must Pass)

```bash
# 1. Architecture boundaries (zero tolerance)
.venv-debian-vm/bin/python -m pytest tests/test_architecture_boundaries.py -v

# 2. Core regression tests (no Kodi needed)
.venv-debian-vm/bin/python -m pytest tests/test_database.py tests/test_game_repository.py \
    tests/test_dat_repository.py tests/test_artwork_repository.py \
    tests/test_emulator_repository.py tests/test_status_repository.py \
    tests/test_history_repository.py tests/test_emulator_repository.py \
    tests/test_emulation_process.py tests/test_emulation_chd.py \
    tests/test_emulation_vgm_callback.py tests/test_process.py \
    tests/test_sqlite.py tests/test_scan_coordinator.py -q

# 3. Frontend/Screensaver integration tests (Kodi stubs)
.venv-debian-vm/bin/python -m pytest tests/test_frontend_entrypoint.py \
    tests/test_emulator_launcher.py tests/test_screensaver_addon.py \
    tests/test_screensaver_history_hooks.py tests/test_screensaver_history_repository.py \
    tests/test_gui_history_navigation.py -q

# 4. No new Ruff correctness issues (BLE001, S110, PLW1510)
.venv-debian-vm/bin/python -m ruff check \
    plugin.program.umsa.mame.surfer \
    screensaver.umsa.mame.surfer \
    script.module.umsa.core \
    --select BLE001,S110,PLW1510
# → At HEAD af3bd11: baseline 163 reported rows (BLE001=108, S110=54,
#   PLW1510=1; 108 unique locations); after round 1: 134 rows
#   (BLE001=105, S110=29, PLW1510=0; 105 unique locations).
```

### Recommended (P1 — Should Pass)

```bash
# 5. Ruff style issues not increasing (UP031, UP007, etc.)
.venv-debian-vm/bin/python -m ruff check . --statistics
# → At af3bd11: UP031 = 10 (was 16 historically), UP007 = 6, etc.

# 6. Mypy on Core modules (individual, skip imports)
for f in sqlite.py vgm_header.py status_repository.py emulator_repository.py game_repository.py; do
  .venv-debian-vm/bin/python -m mypy script.module.umsa.core/lib/umsa_core/$f --follow-imports=skip
done
```

### Ideal (P2 — Nice to Have)

```bash
# 7. Full Ruff cleanup (reviewed --fix)
.venv-debian-vm/bin/python -m ruff check . --fix

# 8. Full test suite
.venv-debian-vm/bin/python -m pytest tests/ -q
# → 0 failures, 5 skipped (real-MAME integration only)
```

---

## Summary

| Metric | Current | Release Target |
|--------|---------|----------------|
| Architecture boundary tests | 7/7 ✅ | 7/7 ✅ |
| Core regression tests | ~200 passed | All pass |
| Integration tests (stubs) | 140 passed | All pass |
| Ruff correctness issues | Baseline 163 rows / 108 unique locations (BLE001=108, S110=54, PLW1510=1); after round 1 134 rows / 105 locations (BLE001=105, S110=29, PLW1510=0) | **No increase**; continue B1/B2 triage |
| Ruff style issues | 62 (default rules minus BLE001/S110/PLW1510) | P1: UP031 → 0 |
| Mypy (`vgm_header.py` only) | Clean | Clean |
| Pre-existing test failures | 0 (13 historical resolved); one transient network failure in round 1, not reproducible | No new |
| Full suite | 1130 passed, 5 skipped, 18 subtests (round 1 rerun) | ≥ 1130, no new failures |

---

## Recommended Actions Before Release

| Priority | Action | Owner |
|----------|--------|-------|
| P0 | Close the 3 open manual areas (emulator matrix, Retroplayer, clean install/upgrade) | Maintainer |
| P0 | Continue B1/B2 triage (remaining BLE001=105, S110=29 after round 1); `emulator_launcher.py` startup risks are fixed, its remaining 25 handlers are logged UI/cleanup boundaries | Dev |
| ~~P0~~ | ~~Fix PLW1510~~ ✅ **Fixed in round 1** at `emulation.py` terminal fallback with regression tests | Dev |
| P1 | Convert UP031 (10 f-string candidates) | Dev |
| P1 | Fix UP007 (6 union syntax), SIM115 (5 context managers) | Dev |
| P1 | Reduce remaining BLE001/S110 by adding specific exception types + logging | Dev |
| P2 | Run full Ruff `--fix` with review | Dev |
| P2 | Implement standalone `umsa_core` CLI example | Dev |
| P2 | Mypy config cleanup for Core package | Dev |