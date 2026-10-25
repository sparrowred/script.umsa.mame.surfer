# Static Analysis & Code Quality Audit

**Audited:** 2026-10-23 (historical audit at HEAD `4186b5f5dd3479b19df84215d1fa21a4cbb38f29`)
**P0 revalidation:** 2026-10-25 at HEAD `af3bd11598692943e9c8f8a3dbc5ef457a6f5f3f`
**P0 round 2 (GUI shutdown cleanup):** 2026-10-25 at HEAD `a74976bf1a1145c61d7b43f01568ef6f33fbb64a`
**P0 round 3 (Core scanner cleanup hardening):** 2026-10-25
**Tools:** Ruff (primary), mypy (limited), Architecture boundary tests (AST-based)  
**Scope:** All production Python in three add-ons

---

## Tooling Inventory

| Tool | Version | Config | Status |
|------|---------|--------|--------|
| **Ruff** | 0.16.10 (via `.venv-debian-vm`) | default | ✅ Active — 227 baseline / 196 after P0 round 1 / 193 after P0 round 2 / 188 after P0 round 3 (default rules) |
| **mypy** | 1.x (via `.venv-debian-vm`) | `mypy.ini` / default | ⚠️ Partial — single modules only with `--follow-imports=skip` |
| **pytest** | 9.x | default | ✅ Active — P0 round 1 rerun: 1130 passed, 0 failed, 5 skipped; P0 round 2 full suite: 1141 passed, 5 skipped; P0 round 3 full suite: 1145 passed, 5 skipped |
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

### P0 rounds 1-2 — reproduced baseline and current result

Command (production roots only):

```bash
.venv-debian-vm/bin/python -m ruff check \
    plugin.program.umsa.mame.surfer \
    screensaver.umsa.mame.surfer \
    script.module.umsa.core \
    --select BLE001,S110,PLW1510 --statistics
```

| Rule | Baseline at `af3bd11` | After round 1 | After round 2 at `a74976b` | After round 3 |
|------|----------------------|---------------|----------------------------|---------------|
| **BLE001** | 108 | 105 | 107 | 109 |
| **S110** | 54 | 29 | 24 | 17 |
| **PLW1510** | 1 | **0** | **0** | **0** |
| **Total reported rows** | **163** | **134** | **131** | **126** |
| **Unique exception source locations** | **108** | **105** | **107** | **109** |

**Counting note:** the baseline reported 162 `BLE001`+`S110` rows but only 108
unique file/line locations, because every `S110` location was also a `BLE001`
location. Do not add the two rule counts as if they were independent sites.
After round 3, the 109 `BLE001` rows are 109 unique locations; `S110` remains a
subset of those locations.

`BLE001` increased by 2 in round 2 because `UMSA.exit()` now catches and logs
failures from two operations that previously had no handler at all
(`_save_lastgames()` and the VGM stop request). The 5 `S110` sites in
`gui.py`'s `exit()` were replaced with logged handlers, so `S110` fell by 5.

In round 3, the 7 `except Exception: pass` sites in `dat_scanner.py` and
`artwork_scanner.py` now log their cleanup/rollback failures, so `S110` fell by
7. `BLE001` rose by 2 because the newly instrumented close/rollback handlers in
those two scanners are themselves broad catch-and-log boundaries.

The historical totals (BLE001=106, S110=54, PLW1510=1) were **not reproduced**
at `af3bd11`; the reproduced baseline was BLE001=108, S110=54, PLW1510=1.
Under Ruff's default rule set the reproduced baseline was 227 findings across
19 codes (the historical audit recorded 225); after round 1 it is 196 findings
across 18 codes, after round 2 it is 193 findings (rechecked at `a74976b`), and
after round 3 it is 188 findings.

### Current findings by rule (after round 3)

Non-`BLE001`/`S110` counts were last rechecked in round 1 and were unchanged by
the round 2/3 edits.

| Code | Count | Description | Fixable |
|------|-------|-------------|---------|
| **BLE001** | 109 | Blind `except Exception:` — catches too broadly | ❌ |
| **S110** | 17 | `try: ... except Exception: pass` — silent failure | ❌ |
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
| **Total** | **188** | | **25 safe fixes** |

> `E722` (bare `except:`), `B006` (mutable default) and `TRY203` were reported
> by earlier audits; `E722`/`B006` are absent and the 2 `TRY203` findings were
> removed in round 1 (`emulator_launcher.py`).

### High-Priority Findings (Correctness Risk)

#### 1. BLE001 / S110 — Blind Exception Handling (remaining after round 3)

Remaining findings grouped by module and functional risk. Counts are Ruff
reported rows; the `S110` rows are the same source locations as `BLE001` rows,
so the unique location counts are the `BLE001` counts.

| Module | BLE001 | S110 | Unique locations | Risk / status |
|--------|--------|------|------------------|---------------|
| `emulator_launcher.py` | 25 | 0 | 25 | Medium-low. Round 1 removed every silent pass and the high-risk startup paths. Remaining broad handlers are logged UI progress/close/notification, media pause, optional output, and best-effort status/artwork boundaries. |
| `gui.py` | 7 | 0 | 7 | Low. Round 2 made every `exit()` cleanup step log its failure and continue; the 7 broad catches cover save, VGM stop/label, scan stop, thread check/join, and database close. |
| `umsa_gui/emulator_setup.py` | 4 | 2 | 4 | Low-medium. Emulator output list and final notification UI; failures do not affect emulator execution. |
| `umsa_gui/optional_plugins.py` | 1 | 0 | 1 | Low. Intentional optional PDF-plugin import fallback. |
| `umsa_gui/scan_orchestrator.py` | 1 | 1 | 1 | Low. Progress-dialog close cleanup. |
| `umsa_gui/screensaver_vgm.py` | 2 | 0 | 2 | Low. VGM label updates already log the failure at debug level. |
| `umsa_gui/startup_import.py` | 1 | 0 | 1 | Low. Legacy import failure is logged at error level and retried next start by design. |
| `umsa_core/artwork_scanner.py` | 10 | 0 | 10 | Medium. Discovery/status failures log; cancellation-predicate and final close/cleanup failures now log and abort/continue safely. |
| `umsa_core/dat_scanner.py` | 10 | 0 | 10 | Medium. Parse/publish and predicate failures abort without publishing; rollback/staging/close failures are logged. |
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

**Round 2 changes in `gui.py` (`UMSA.exit()`):** each best-effort shutdown step
now has its own handler that logs a concise error and lets later cleanup run:
`_save_lastgames()`, `send_vgmaction(b'exit')`, `clear_vgm_info()`, the scan-stop
request, the scan-thread check and bounded `join(timeout=5)`, and `ggdb.close()`.
The final `close()` is still unconditional. Current remaining locations at
`a74976b` are `gui.py:1171`, `1178`, `1182`, `1189`, `1197`, `1199`, `1204` —
all `BLE001` with zero `S110`.

**Round 3 changes in the Core scanners:** `DatScanner._cancelled()` no longer
swallows predicate failures. A raising predicate logs and aborts the scan
without publishing, preserving previously published DAT rows; rollback and
staging/close failures are logged independently. `ArtworkScanner` treats a
raising predicate as an abort with the established summary shape, closes both
cursors and both connections on every exit path, and logs each final cleanup
failure without masking an active exception. Both scanners have zero `S110`
locations after round 3.

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

### P0 round 3 verification (2026-10-25, server-side scan hardening)

| Command | Result |
|---------|--------|
| `pytest tests/test_dat_scanner.py tests/test_scan_artwork.py tests/test_scan_coordinator.py tests/test_sqlite.py -q` | **70 passed** |
| `pytest tests/ -q` | **1145 passed, 5 skipped, 18 subtests passed** |
| `ruff check .../dat_scanner.py .../artwork_scanner.py --select BLE001,S110 --statistics` | **20 BLE001, 0 S110** |
| `ruff check plugin.program.umsa.mame.surfer screensaver.umsa.mame.surfer script.module.umsa.core --select BLE001,S110,PLW1510 --statistics` | **109 BLE001, 17 S110, 0 PLW1510** (126 rows) |
| `ruff check . --statistics` | **188 findings** (down from 193) |

The round 3 scanner tests are local-only (`tests/` is gitignored, like the rest
of the suite).

### P0 round 2 verification (2026-10-25, HEAD `a74976b`)

| Command | Result |
|---------|--------|
| `pytest tests/test_gui_shutdown.py -v` | **11 passed** |
| `pytest tests/test_gui_shutdown.py tests/test_gui_history_navigation.py tests/test_umsa_gui_workflows.py tests/test_gui_oninit_first_start.py tests/test_frontend_entrypoint.py tests/test_architecture_boundaries.py -q` | **94 passed** |
| `pytest tests/ -q` | **1141 passed, 5 skipped, 18 subtests passed** |
| `ruff check plugin.program.umsa.mame.surfer/resources/lib/gui.py --select BLE001,S110 --statistics` | **7 BLE001, 0 S110** |
| `ruff check plugin.program.umsa.mame.surfer screensaver.umsa.mame.surfer script.module.umsa.core --select BLE001,S110,PLW1510 --statistics` | **107 BLE001, 24 S110, 0 PLW1510** (131 rows) |
| `ruff check . --statistics` | **193 findings** (down from 196) |

The round 2 GUI shutdown regression tests are local-only (`tests/` is
gitignored, like the rest of the suite).

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
#   (BLE001=105, S110=29, PLW1510=0; 105 unique locations);
#   after round 2 at a74976b: 131 rows
#   (BLE001=107, S110=24, PLW1510=0; 107 unique locations);
#   after round 3: 126 rows
#   (BLE001=109, S110=17, PLW1510=0; 109 unique locations).
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
| Ruff correctness issues | Baseline 163 rows / 108 unique locations (BLE001=108, S110=54, PLW1510=1); after round 1 134 rows / 105 locations (BLE001=105, S110=29, PLW1510=0); after round 2 at `a74976b` 131 rows / 107 locations (BLE001=107, S110=24, PLW1510=0); after round 3 126 rows / 109 locations (BLE001=109, S110=17, PLW1510=0; +2 BLE001 from logged scanner cleanup, -7 S110) | **No new silent failures**; continue B1/B2 triage |
| Ruff style issues | 62 (default rules minus BLE001/S110/PLW1510) | P1: UP031 → 0 |
| Mypy (`vgm_header.py` only) | Clean | Clean |
| Pre-existing test failures | 0 (13 historical resolved); one transient network failure in round 1, not reproducible | No new |
| Full suite | 1130 passed, 5 skipped, 18 subtests (round 1 rerun) | ≥ 1130, no new failures |

---

## Recommended Actions Before Release

| Priority | Action | Owner |
|----------|--------|-------|
| P0 | Close the 3 open manual areas (emulator matrix, Retroplayer, clean install/upgrade) | Maintainer |
| P0 | Continue B1/B2 triage (remaining BLE001=109, S110=17 after round 3); `emulator_launcher.py` startup risks, `gui.py` shutdown cleanup and the DAT/artwork scanner cleanup paths are fixed and their broad handlers log; the rest are UI/scan/socket boundaries | Dev |
| ~~P0~~ | ~~Fix PLW1510~~ ✅ **Fixed in round 1** at `emulation.py` terminal fallback with regression tests | Dev |
| P1 | Convert UP031 (10 f-string candidates) | Dev |
| P1 | Fix UP007 (6 union syntax), SIM115 (5 context managers) | Dev |
| P1 | Reduce remaining BLE001/S110 by adding specific exception types + logging | Dev |
| P2 | Run full Ruff `--fix` with review | Dev |
| P2 | Implement standalone `umsa_core` CLI example | Dev |
| P2 | Mypy config cleanup for Core package | Dev |