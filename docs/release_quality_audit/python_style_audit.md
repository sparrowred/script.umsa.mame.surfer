# Python Style & String Formatting Audit

**Audited:** 2026-10-23 (at HEAD `4186b5f5dd3479b19df84215d1fa21a4cbb38f29`)  
**Tools:** Ruff (UP031, UP030), manual grep inspection  
**Scope:** All production Python in `plugin.program.umsa.mame.surfer/`, `screensaver.umsa.mame.surfer/`, `script.module.umsa.core/`

---

## Summary

| Pattern | Count | Locations |
|---------|-------|-----------|
| `%` formatting (UP031) | 16 | `database.py` 6, `umsa_gui/software_selector.py` 3, `umsa_gui/artwork_presenter.py` 2, `umsa_gui/filter_ui.py` 2, `umsa_gui/media_list.py` 2, `gui.py` 1 |
| Explicit `.format()` index (UP030) | 1 | `launch_preparer.py:134` |
| f-strings (dominant) | 100+ | Throughout newer code |

Ruff reports 16 `UP031` and 1 `UP030`, matching the table above. The screensaver
add-on and `gamelist_strategies.py` are clean (the 8 historical `gamelist_strategies.py`
conversions are done).

---

## Detailed Inventory by File

### `script.module.umsa.core/lib/umsa_core/database.py` (6 UP031)

| Line | Suggested | Notes |
|------|-----------|-------|
| 1030 | f-string | SQL-adjacent string — verify placeholder intent before changing |
| 1032 | f-string | Same |
| 1034 | f-string | Same |
| 1036 | f-string | Same |
| 1048 | f-string | Same |
| 1379 | f-string | Same |

### `plugin.program.umsa.mame.surfer/resources/lib/umsa_gui/software_selector.py` (3 UP031)

Lines 59, 68, 213 — clear UI/log string candidates.

### `plugin.program.umsa.mame.surfer/resources/lib/umsa_gui/artwork_presenter.py` (2 UP031)

Lines 131, 217 — clear UI/log string candidates.

### `plugin.program.umsa.mame.surfer/resources/lib/umsa_gui/filter_ui.py` (2 UP031)

Lines 35, 56 — clear UI/log string candidates.

### `plugin.program.umsa.mame.surfer/resources/lib/umsa_gui/media_list.py` (2 UP031)

Lines 32, 40 — clear UI/log string candidates.

### `plugin.program.umsa.mame.surfer/resources/lib/gui.py` (1 UP031)

Line 516 — clear UI/log string candidate.

### `script.module.umsa.core/lib/umsa_core/launch_preparer.py` (1 UP030)

Line 134 — explicit positional index can be implicit.

---

## Exceptions — Do Not Convert

### 1. SQL Parameter Placeholders
```python
# In database.py, game_repository.py, etc.
cursor.execute("SELECT * FROM sets WHERE id = ?", (set_id,))
# The ? is SQL placeholder, not Python % formatting
```

### 2. MAME Command-Line Format Strings
```python
# In emulation.py — MAME's own format syntax
args = ['-videodriver', 'dummy', '-video', 'none', '-volume', '1',
        '-seconds_to_run', str(int(actual_sec)), ...]
# %g, %d, %i in MAME configs are MAME syntax, not Python
```

### 3. Logging Lazy Interpolation
```python
# Current pattern in gui.py, emulation.py, ui.py
xbmc.log(f"UMSA gui: message {var}", xbmc.LOGDEBUG)
# vs lazy (preferred for performance when log level filters out):
xbmc.log("UMSA gui: message %s", var, xbmc.LOGDEBUG)
# Recommendation: Keep f-strings for consistency; lazy only if perf-critical
```

### 4. External Command Templates
```python
# In emulation.py — terminal command construction
torun = [self.terminal, '-e', run]
# run contains shell-escaped strings — not Python formatting
```

### 5. Regular Expressions
```python
# Pattern strings — not interpolation
pattern = r'^(\d+)-(\d+)$'
```

---

## Conversion Priority

| Priority | Files | Est. Effort | Risk |
|----------|-------|-------------|------|
| **High** | `database.py` (6) | Low | Medium — SQL-adjacent strings; verify intent |
| **High** | `umsa_gui/` package (9) | Low | Low — UI/log strings |
| **High** | `gui.py` (1) | Low | Low — UI/log string |
| **Medium** | `launch_preparer.py` (1 UP030) | Low | Low — verify MAME args unchanged |
| **Done** | `gamelist_strategies.py` (8 historical) | N/A | N/A |
| **Done** | screensaver add-on (0) | N/A | N/A |

---

## Recommended Conversion Command

```bash
# Preview changes for clear candidates
.venv-debian-vm/bin/python -m ruff check . --select UP031 --diff

# Apply safe conversions (review each)
.venv-debian-vm/bin/python -m ruff check . --select UP031 --fix

# Some conversions are only available as unsafe fixes
.venv-debian-vm/bin/python -m ruff check . --select UP031,UP030 --fix --unsafe-fixes

# For UP030 (explicit format index)
.venv-debian-vm/bin/python -m ruff check . --select UP030 --fix
```

At this HEAD `ruff check . --select UP031,UP030` reports 17 findings with 8
hidden unsafe fixes. The repo-wide `--fix` total is 19 safe fixes, plus 17
additional hidden fixes with `--unsafe-fixes`.

---

## Verification After Conversion

1. Run full test suite: `.venv-debian-vm/bin/python -m pytest tests/ -q`
2. Run architecture boundary tests: `.venv-debian-vm/bin/python -m pytest tests/test_architecture_boundaries.py -v`
3. Manual Kodi smoke test: menu navigation, gamelist display, emulator launch (maintainer-confirmed for GUI navigation)

---

## Status

| File | UP031 | UP030 | Status |
|----------|-------|-------|--------|
| `gamelist_strategies.py` | 0 (8 converted) | 0 | ✅ **COMPLETE** |
| `gui.py` | 1 | 0 | ⏳ Open |
| `umsa_gui/` package | 9 | 0 | ⏳ Open |
| `database.py` | 6 | 0 | ⏳ Open |
| `launch_preparer.py` | 0 | 1 | ⏳ Open |
| `emulator_launcher.py` | 0 | 0 | ✅ Clean |
| `emulation.py` | 0 | 0 | ✅ Clean |
| screensaver add-on | 0 | 0 | ✅ Clean |
| **Total** | **16** | **1** | |
