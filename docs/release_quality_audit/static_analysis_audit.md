# Static Analysis & Code Quality Audit

**Audited:** 2026-10-23 (at HEAD `4186b5f5dd3479b19df84215d1fa21a4cbb38f29`)  
**Tools:** Ruff (primary), mypy (limited), Architecture boundary tests (AST-based)  
**Scope:** All production Python in three add-ons

---

## Tooling Inventory

| Tool | Version | Config | Status |
|------|---------|--------|--------|
| **Ruff** | 0.x (via `.venv-debian-vm`) | `pyproject.toml` / default | ✅ Active — 225 issues |
| **mypy** | 1.x (via `.venv-debian-vm`) | `mypy.ini` / default | ⚠️ Partial — single modules only with `--follow-imports=skip` |
| **pytest** | 9.x | `pytest.ini` / default | ✅ Active — 1081 passed, 0 failed, 5 skipped |
| **Architecture boundary tests** | Custom (AST) | `tests/test_architecture_boundaries.py` | ✅ 7/7 passed |

### Configuration Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Ruff config (if present), mypy config |
| `mypy.ini` | mypy config — `follow_imports = skip` for Core |
| `pytest.ini` | pytest config — `testpaths = tests` |
| `requirements-dev.txt` | Dev dependencies: `Kodistubs`, `pytest`, `pytest-cov`, `ruff`, `mypy`, `Pillow` |

---

## Ruff Findings (225 issues, 19 rule codes)

### By Severity/Category

| Code | Count | Description | Fixable |
|------|-------|-------------|---------|
| **BLE001** | 106 | Blind `except Exception:` — catches too broadly | ❌ |
| **S110** | 54 | `try: ... except Exception: pass` — silent failure | ❌ |
| **F401** | 17 | Unused import | ✅ |
| **UP031** | 16 | Legacy `%` formatting → prefer f-strings | ❌ |
| **UP007** | 6 | Union syntax `Union[X, Y]` → `X \| Y` (Python 3.10+) | ❌ |
| **SIM115** | 5 | `open()` without context manager | ❌ |
| **SIM113** | 4 | `enumerate()` instead of manual index | ❌ |
| **F841** | 4 | Unused variable | ❌ |
| **I001** | 2 | Unsorted imports | ✅ |
| **TRY203** | 2 | Useless `try`/`except` | ❌ |
| **SIM102** | 1 | Collapsible `if` statements | ❌ |
| **UP030** | 1 | Explicit `.format()` positional index | ❌ |
| **SIM118** | 1 | `key in dict.keys()` | ❌ |
| **PERF402** | 1 | Manual list copy | ❌ |
| **EXE002** | 1 | Shebang on non-executable file | ❌ |
| **PLW1510** | 1 | `subprocess.run()` without `check=True` | ❌ |
| **C413** | 1 | Unnecessary `sorted()` call | ❌ |
| **RUF046** | 1 | Unnecessary `int()` cast | ❌ |
| **RUF059** | 1 | Unused unpacked variable | ❌ |
| **Total** | **225** | | **19 safe fixes** (`F401` 17, `I001` 2); 17 more via `--unsafe-fixes` |

> `E722` (bare `except:`) and `B006` (mutable default) were reported by an
> earlier audit and are no longer present at this HEAD.

### High-Priority Findings (Correctness Risk)

#### 1. BLE001 / S110 — Blind Exception Handling (160 combined)

**Most critical locations:**

| File | Lines | Pattern | Risk |
|------|-------|---------|------|
| `emulator_launcher.py` | 51, 60, 86, 91, 99, 127, 134, 147, 174, 189 | `except Exception: pass` | Emulator launch failures silently ignored |
| `gui.py` | Multiple | `except Exception: pass` | UI actions, dialog cleanup, VGM handling |
| `ui.py` (screensaver) | Multiple | `except Exception: pass` | Render loop, video callbacks, history recording |
| `retroplayer_cache.py` | 103, 107, 139, 144 | `except Exception: pass` | Retroplayer launch failures silent |

**Example (emulator_launcher.py:49-52):**
```python
try:
    ctx.emulation.send_vgmaction(b'exit')
except Exception:
    pass  # BLE001 + S110 — VGM stop failure silently ignored
```

**Recommendation:** Replace with specific exception types or at minimum log the error:
```python
try:
    ctx.emulation.send_vgmaction(b'exit')
except (OSError, RuntimeError) as e:
    xbmc.log(f"VGM stop failed: {e}", xbmc.LOGWARNING)
```

#### 2. PLW1510 — `subprocess.run()` without `check=True` (1 occurrence)

In `emulation.py` / CHD extraction path — failures not raised.

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
.venv-debian-vm/bin/python -m ruff check . --select BLE001,S110,PLW1510
# → Must not increase from baseline (BLE001=106, S110=54, PLW1510=1)
```

### Recommended (P1 — Should Pass)

```bash
# 5. Ruff style issues not increasing (UP031, UP007, etc.)
.venv-debian-vm/bin/python -m ruff check . --statistics
# → UP031 count ≤ 16, UP007 ≤ 6, etc.

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
| Ruff correctness issues | 161 (BLE001=106, S110=54, PLW1510=1) | **No increase**; P1: reduce BLE001/S110 |
| Ruff style issues | 63 (UP031=16, UP007=6, SIM115=5, F841=4, etc.) | P1: UP031 → 0 |
| Mypy (`vgm_header.py` only) | Clean | Clean |
| Pre-existing test failures | 0 (13 historical resolved) | No new |
| Full suite | 1081 passed | ≥ 1081, no new failures |

---

## Recommended Actions Before Release

| Priority | Action | Owner |
|----------|--------|-------|
| P0 | Close the 3 open manual areas (emulator matrix, Retroplayer, clean install/upgrade) | Maintainer |
| P0 | Fix BLE001/S110 in `emulator_launcher.py` (10 occurrences) | Dev |
| P0 | Fix PLW1510 | Dev |
| P1 | Convert UP031 (16 f-string candidates) | Dev |
| P1 | Fix UP007 (6 union syntax), SIM115 (5 context managers) | Dev |
| P1 | Reduce BLE001/S110 by adding specific exception types + logging | Dev |
| P2 | Run full Ruff `--fix` with review | Dev |
| P2 | Implement standalone `umsa_core` CLI example | Dev |
| P2 | Mypy config cleanup for Core package | Dev |