# Test Suite Audit

**Audited:** 2026-10-21  
**Baseline:** 882 passed, 13 failed, 5 skipped, 18 subtests passed  
**Environment:** `.venv-debian-vm/bin/python -m pytest tests/ -q`

---

## Test Suite Inventory by Functional Area

| Area | Test Files | Tests | Status |
|------|------------|-------|--------|
| Architecture boundaries | `test_architecture_boundaries.py` | 7 | ✅ All pass |
| Core database (DBMod, repositories) | `test_database.py`, `test_game_repository.py`, `test_dat_repository.py`, `test_artwork_repository.py`, `test_emulator_repository.py`, `test_status_repository.py`, `test_history_repository.py` | ~200 | ✅ All pass |
| Database migrations & attachments | `test_status_migrations.py`, `test_history_import.py`, `test_data_paths.py`, `test_scan_coordinator.py`, `test_dat_scanner.py`, `test_exodos_scan.py`, `test_gb64_scanner.py`, `test_scan_artwork.py`, `test_exodos_artwork.py` | ~100 | ✅ All pass |
| History persistence | `test_history_repository.py`, `test_history_import.py`, `test_screensaver_history_repository.py`, `test_screensaver_history_hooks.py` | ~100 | ✅ All pass |
| Filters & Gameslist strategies | `test_gamelist_filter.py`, `test_filter_state_accessors.py`, `test_execute_statement_order.py`, `test_gamelist_strategies.py` | 50+ | ⚠️ 2 fail |
| GUI menus, navigation, series | `test_gui_history_navigation.py`, `test_series_sublist_menu.py`, `test_frontend_entrypoint.py` | 30+ | ⚠️ 9 fail |
| Artwork & DAT scanners | `test_artwork_repository.py`, `test_dat_repository.py`, `test_exodos_artwork.py`, `test_dat_scanner.py`, `test_exodos_scan.py`, `test_gb64_scanner.py`, `test_scan_artwork.py` | 100+ | ✅ All pass |
| Screensaver lifecycle & history | `test_screensaver_addon.py`, `test_screensaver_history_hooks.py`, `test_screensaver_history_repository.py`, `test_screensaver_exodos_extraction.py` | 100+ | ✅ All pass |
| Emulator preparation & process | `test_emulation_process.py`, `test_emulation_chd.py`, `test_emulation_vgm_callback.py`, `test_emulator_launcher.py`, `test_process.py` | 30+ | ✅ All pass |
| Database download | `test_umsa_db_download.py` | 7 | ⚠️ 3 fail |
| Kodi adapter | `test_kodi_adapter.py` | 1 | ✅ Pass |
| VGM handling | `test_vgm_header.py`, `test_vgm_header_core_integration.py`, `test_vgmplay_preexit.py`, `test_vgm_preexit_mame.py`, `test_vgm_random_batch.py` | 20+ | ✅ All pass |

---

## Failure Classification

| # | Test | Root Cause | Category | Fix Strategy |
|---|------|------------|----------|--------------|
| 1 | `test_last_saver_distinct_sets_same_software_id` | Test writes to read-only DB connection | Outdated fixture | Set up test data before DBMod creation |
| 2 | `test_last_saver_skips_missing_set` | Test writes to read-only DB connection | Outdated fixture | Set up test data before DBMod creation |
| 3-11 | `test_series_sublist_menu.py` (9 tests) | Missing `umsa_core_kodi` stubs for new inhibition functions | Missing stubs | Add `set_emulator_running`, `is_emulator_running`, `set_screensaver_manual` to stub |
| 12 | `test_download_and_update_umsa_db_creates_directory` | Expects progress 80% for unzip, actual is 99% | Outdated expectation | Update test to match implementation (99%) |
| 13 | `test_download_and_update_umsa_db_uses_correct_url` | Expects timeout=20, actual is 10 | Outdated expectation | Update test to match implementation (timeout=10) |
| 14 | `test_download_and_update_umsa_db_progress_percentages` | Expects 80% in progress calls, actual max is 99% | Outdated expectation | Update test to match implementation |

---

## Detailed Analysis by Test Group

### A. `test_gamelist_strategies.py` (2 failures)

**Failing tests:**
- `test_last_saver_distinct_sets_same_software_id` (line 271)
- `test_last_saver_skips_missing_set` (line 299)

**Root cause:** Tests create DBMod via `_make_dbmod()`, which opens `umsa.db` in **read-only mode** (Phase 4.8 change). Tests then attempt to write via `db.gdbc.execute()` and `db.gdb.commit()`, which fails with `sqlite3.OperationalError: attempt to write a readonly database`.

**Comparison:** `test_last_saver_correct_set_mapping` (line 179) works because it sets up ALL test data via direct sqlite3 connection **before** creating DBMod.

**Fix:** Move test data setup before DBMod creation, or create a separate writable connection for test setup.

**Affected tests:**
- `test_last_saver_distinct_sets_same_software_id` (line 271-296): Tries to INSERT a new set after DBMod creation
- `test_last_saver_skips_missing_set` (line 299-320): Tries to DELETE a set after DBMod creation

### B. `test_series_sublist_menu.py` (9 failures)

**Root cause:** Test stubs for `umsa_core_kodi` (lines 313-324) are missing the new inhibition functions added in the screensaver inhibition fix:
- `set_emulator_running`
- `is_emulator_running` 
- `set_screensaver_manual`

The real `gui.py` imports these (lines 54-57 in gui.py), but the test stub only provides the old functions.

**Fix:** Add the three missing functions to the `umsa_core_kodi` stub in `_make_gui_stubs`.

### C. `test_umsa_db_download.py` (3 failures)

**Implementation** (`umsa_db_download.py:13-32`):
- `timeout=10` (line 24)
- Download progress: 0-99% (line 29)
- Unzip progress: `progress(99, title, 'unzip file...')` (line 31)

**Test expectations (outdated):**
1. `test_download_and_update_umsa_db_uses_correct_url` (line 82): Expects `timeout=20`, actual is `timeout=10`
2. `test_download_and_update_umsa_db_creates_directory` (line 65): Expects `progress(80, ..., 'unzip file...')`, actual is `progress(99, ..., 'unzip file...')`
3. `test_download_and_update_umsa_db_progress_percentages` (line 150): Expects `80 in progress_calls`, but download only reaches 99% then unzip is also 99%

**Decision needed:** Tests appear to have outdated expectations. The implementation seems intentional (99% for both download completion and unzip). Need maintainer confirmation on whether tests or implementation should change.

---

## Safe Consolidation Candidates

| Tests | Reason | Consolidation Approach |
|-------|--------|------------------------|
| `test_last_saver_uses_database_history`, `test_last_saver_newest_first_ordering`, `test_last_saver_correct_set_mapping`, `test_last_saver_distinct_sets_same_software_id`, `test_last_saver_skips_missing_set` | Same fixture pattern, same strategy under test | Parameterized test matrix with different data scenarios |
| `test_series_from_main_menu_populates_sublist_menu`, `test_series_from_main_menu_allows_left_navigation`, `test_series_from_existing_submenu_continues_to_work` | Same GUI setup, different navigation paths | Shared fixture + parameterized navigation actions |
| `test_download_and_update_umsa_db_creates_directory`, `test_download_and_update_umsa_db_uses_correct_url`, `test_download_and_update_umsa_db_progress_percentages` | Same function, different contract aspects | Single parametrized test with multiple assertions |

---

## Tests Requiring Maintainer Decision

| Test | Ambiguity | Options |
|------|-----------|---------|
| `test_umsa_db_download.py` (3 tests) | Tests expect timeout=20, progress 80% for unzip; implementation uses timeout=10, progress 99% | 1. Update tests to match implementation (recommended)<br>2. Change implementation to match tests<br>3. Both are valid contracts; need maintainer intent |
| `test_series_sublist_menu.py` (8 failures) | FakeGGDB missing methods (`get_by_software`, etc.) | 1. Update FakeGGDB to match DBMod interface<br>2. Tests test GUI behavior, not DBMod; keep fake minimal |

---

## Missing Regression Coverage

| Behavior | Current Coverage | Gap |
|----------|------------------|-----|
| 100-entry persistent game history vs latest 10 in GUI | `test_gui_history_navigation.py` covers pointer logic | Persistence layer (100 vs 10) not explicitly tested |
| Failed history insertion rollback | `_remember_and_select` tests cover rollback | DB-level rollback on constraint failure not tested |
| Screensaver C-key handoff (software ID vs set ID) | `test_screensaver_history_hooks.py` covers history recording | GUI handoff path not fully tested |
| Screensaver inhibition (emulator + manual) | New feature, no tests yet | Need tests for `set_emulator_running`, `set_screensaver_manual` coordination |
| Row-leak closure at boundaries | `test_architecture_boundaries.py` checks static | Runtime row type not verified |
| Database reopen failure cleanup | `test_database.py` covers some | `open_db` failure cleanup not explicitly tested |
| Migration success notifications | `test_history_import.py` covers import | GUI notification on successful migration not tested |
| Unreachable legacy code removal | Step 1 done | Verified by test removal |

---

## Recommended Next Actions

1. **Fix `test_gamelist_strategies.py`** — Move test data setup before DBMod creation (low risk, clear fix)
2. **Fix `test_series_sublist_menu.py`** — Add missing `umsa_core_kodi` stubs (low risk, clear fix)
3. **Clarify `test_umsa_db_download.py` expectations with maintainer** — Tests vs implementation mismatch
4. **Consolidate `last_saver` tests** — Parameterize the 5 related tests
4. **Consolidate `test_series_sublist_menu.py`** — Shared GUI fixture + parametrize navigation
5. **Add missing regression tests** for screensaver inhibition, 100-entry history, row-leak closure

---

## Verification Commands

```bash
# Full suite
.venv-debian-vm/bin/python -m pytest tests/ -q

# Specific failing groups
.venv-debian-vm/bin/python -m pytest tests/test_gamelist_strategies.py -v
.venv-debian-vm/bin/python -m pytest tests/test_series_sublist_menu.py -v
.venv-debian-vm/bin/python -m pytest tests/test_umsa_db_download.py -v

# Architecture boundaries (must always pass)
.venv-debian-vm/bin/python -m pytest tests/test_architecture_boundaries.py -v

# Ruff statistics
.venv-debian-vm/bin/python -m ruff check . --statistics
```