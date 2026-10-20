# Python Style & String Formatting Audit

**Audited:** 2026-10-21  
**Tools:** Ruff (UP031, UP030), manual grep inspection  
**Scope:** All production Python in `plugin.program.umsa.mame.surfer/`, `screensaver.umsa.mame.surfer/`, `script.module.umsa.core/`

---

## Summary

| Pattern | Count | Primary Locations |
|---------|-------|-------------------|
| `%` formatting (UP031) | 24 | `gamelist_strategies.py` (8), `gui.py` (6), `emulator_launcher.py` (4), `retroplayer_cache.py` (3), `ui.py` (3) |
| Explicit `.format()` index (UP030) | 1 | `emulation.py:1091` |
| f-strings (dominant) | 100+ | Throughout newer code |

---

## Detailed Inventory by File

### `plugin.program.umsa.mame.surfer/resources/lib/gamelist_strategies.py` (8 UP031)

| Line | Current | Suggested | Notes |
|------|---------|-----------|-------|
| 15 | `"Complete list (%d)" % (count,)` | `f"Complete list ({count})"` | Clear candidate |
| 28 | `"swl: %s (%d)" % (swl_name, count)` | `f"swl: {swl_name} ({count})"` | Clear candidate |
| 40 | `"Category: %s (%d)" % (category, count)` | `f"Category: {category} ({count})"` | Clear candidate |
| 53 | `"Year: %s (%d)" % (year, count)` | `f"Year: {year} ({count})"` | Clear candidate |
| 64 | `"Players: {} ({})".format(nplayers, count)` | `f"Players: {nplayers} ({count})"` | Already `.format()` — convert to f-string |
| 75 | `"Publisher: %s (%d)" % (publisher, count)` | `f"Publisher: {publisher} ({count})"` | Clear candidate |
| 142 | `"%d results for %s" % (count, searchold)` | `f"{count} results for {searchold}"` | Clear candidate |
| 207 | `"%d results for %s" % (count, searchold)` | `f"{count} results for {searchold}"` | Clear candidate |

### `plugin.program.umsa.mame.surfer/resources/lib/gui.py` (6 UP031)

| Line | Current | Suggested | Notes |
|------|---------|-----------|-------|
| 618 | `'%d results for %s' % (result_count, searchold)` | `f"{result_count} results for {searchold}"` | Clear candidate |
| 642 | `'%s (%d)' % (source[:-4], count_source)` | `f"{source[:-4]} ({count_source})"` | Clear candidate |
| 667 | `'Softwarelist %s' % (swl_name,)` | `f"Softwarelist {swl_name}"` | Clear candidate |
| 1014 | `'Emulators for source {} ({})'.format(source[:-4], count_source)` | `f"Emulators for source {source[:-4]} ({count_source})"` | Already `.format()` |
| 1073 | `'Softwarelist {}'.format(swl_name)` | `f"Softwarelist {swl_name}"` | Already `.format()` |
| 1111 | `'Media ({},{})'.format(vidman[0], vidman[1])` | `f"Media ({vidman[0]},{vidman[1]})"` | Already `.format()` |

### `plugin.program.umsa.mame.surfer/resources/lib/emulator_launcher.py` (4 UP031)

| Line | Current | Suggested | Notes |
|------|---------|-----------|-------|
| 59 | `'Emulator: {}'.format(emu_infos.get('name', ''))` | `f"Emulator: {emu_infos.get('name', '')}"` | Clear candidate |
| 107 | `'Select CHD:'` | No change — no interpolation | False positive? |
| 171 | `'Select file: '` | No change — no interpolation | False positive? |
| 291 | `'{} error'.format(emu_infos.get("name", ""))` | `f"{emu_infos.get('name', '')} error"` | Clear candidate |

*Note: Lines 107/171 appear to be false positives — no `%` formatting present.*

### `plugin.program.umsa.mame.surfer/resources/lib/retroplayer_cache.py` (3 UP031)

| Line | Current | Suggested | Notes |
|------|---------|-----------|-------|
| 33 | `'error'` | No change — string literal | False positive? |
| 77 | `'check rom in cache deadend?'` | No change — string literal | False positive? |
| 143 | `'seems we can not find the rom?'` | No change — string literal | False positive? |

*These appear to be false positives from Ruff — string literals without `%`.*

### `screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py` (3 UP031)

| Line | Current | Suggested | Notes |
|------|---------|-----------|-------|
| 559 | `'UMSA SSaver: invalid launch request: {}'.format(error)` | `f"UMSA SSaver: invalid launch request: {error}"` | Clear candidate |
| 859 | `'UMSA SSaver: onPlayBackStarted: time: {}, start {}, end {}'.format(total_time, timecount1, timecount2)` | f-string | Clear candidate |
| 1108 | `'UMSA SSaver Player: onPlayBackStarted: time: {}, start {}, end {}'.format(...)` | f-string | Clear candidate |

### `script.module.umsa.core/lib/umsa_core/emulation.py` (1 UP030 + 2 UP031)

| Line | Current | Suggested | Notes |
|------|---------|-----------|-------|
| 1091 | `'-rom={0}'.format(self.emurun['set_name'])` | `f"-rom={self.emurun['set_name']}"` | UP030 — explicit index unnecessary |
| 1096 | `'Error running Demul -listroms'` | No change | False positive? |
| 1158 | `'UMSA Emu run_emulator: demul - section {}'.format(section)` | f-string | Clear candidate |

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
| **High** | `gamelist_strategies.py` (8), `gui.py` (6) | Low | Very low — simple UI strings |
| **High** | `emulator_launcher.py` (4), `ui.py` (3) | Low | Low — UI/log strings |
| **Medium** | `emulation.py` (1 UP030 + 2) | Low | Low — but verify MAME args unchanged |
| **Skip** | `retroplayer_cache.py` (3 false positives) | N/A | N/A |

---

## Recommended Conversion Command

```bash
# Preview changes for clear candidates
.venv-debian-vm/bin/python -m ruff check . --select UP031 --diff

# Apply safe conversions (review each)
.venv-debian-vm/bin/python -m ruff check . --select UP031 --fix

# For UP030 (explicit format index)
.venv-debian-vm/bin/python -m ruff check . --select UP030 --fix
```

---

## Verification After Conversion

1. Run full test suite: `.venv-debian-vm/bin/python -m pytest tests/ -q`
2. Run architecture boundary tests: `.venv-debian-vm/bin/python -m pytest tests/test_architecture_boundaries.py -v`
3. Manual Kodi smoke test: menu navigation, gamelist display, emulator launch

---

## Status

| File | UP031 | UP030 | Status |
|------|-------|-------|--------|
| `gamelist_strategies.py` | 8 | 0 | ⏳ Open |
| `gui.py` | 6 | 0 | ⏳ Open |
| `emulator_launcher.py` | 4* | 0 | ⏳ Open |
| `retroplayer_cache.py` | 3* | 0 | ❌ False positives |
| `ui.py` | 3 | 0 | ⏳ Open |
| `emulation.py` | 2 | 1 | ⏳ Open |
| **Total real** | **24** | **1** | |

*False positives excluded from total.*