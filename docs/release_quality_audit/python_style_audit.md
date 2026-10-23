1: # Python Style & String Formatting Audit
2: 
3: **Audited:** 2026-10-23 (at HEAD `cc2efc83855eb2fd10b17e814a507b59d341a76c`)  
4: **Tools:** Ruff (UP031, UP030), manual grep inspection  
5: **Scope:** All production Python in `plugin.program.umsa.mame.surfer/`, `screensaver.umsa.mame.surfer/`, `script.module.umsa.core/`
6: 
7: ---
8: 
9: ## Summary
10: 
11: | Pattern | Count | Primary Locations |
16: |---------|-------|-------------------|
17: | `%` formatting (UP031) | 16 | `gui.py` (6), `emulator_launcher.py` (4), `retroplayer_cache.py` (3), `ui.py` (3) |
17: | Explicit `.format()` index (UP030) | 1 | `emulation.py:1091` |
18: | f-strings (dominant) | 100+ | Throughout newer code |
18: 
19: ---
19: 
20: ## Detailed Inventory by File
21: 
22: ### `plugin.program.umsa.mame.surfer/resources/lib/gamelist_strategies.py` (8 UP031 — **ALL CONVERTED ✅**)
22: 
23: | Line | Original | Converted | Status |
|------|---------|-----------|--------|
| 15 | `"Complete list (%d)" % (count,)` | `f"Complete list ({count})"` | ✅ Done |
| 28 | `"swl: %s (%d)" % (swl_name, count)` | `f"swl: {swl_name} ({count})"` | ✅ Done |
| 40 | `"Category: %s (%d)" % (category, count)` | `f"Category: {category} ({count})"` | ✅ Done |
| 53 | `"Year: %s (%d)" % (year, count)` | `f"Year: {year} ({count})"` | ✅ Done |
| 64 | `"Players: {} ({})".format(nplayers, count)` | `f"Players: {nplayers} ({count})"` | ✅ Done |
| 75 | `"Publisher: %s (%d)" % (publisher, count)` | `f"Publisher: {publisher} ({count})"` | ✅ Done |
| 142 | `"source: %s (%d)" % (source, result_count)` | `f"source: {source} ({result_count})"` | ✅ Done |
| 207 | `'%d results for %s' % (result_count, searchold)` | `f"{result_count} results for {searchold}"` | ✅ Done |
| 223 | `'%d results for %s' % (result_count, searchold)` | `f"{result_count} results for {searchold}"` | ✅ Done |
23: 
24: **Verification:** All 9 gamelist_strategies tests pass; Ruff UP031 passes for this file.
24: 
25: ### `plugin.program.umsa.mame.surfer/resources/lib/gui.py` (6 UP031)
26: 
27: | Line | Current | Suggested | Notes |
|------|---------|-----------|-------|
28: | 618 | `'%d results for %s' % (result_count, searchold)` | `f"{result_count} results for {searchold}"` | Clear candidate |
| 29: | 642 | `'%s (%d)' % (source[:-4], count_source)` | `f"{source[:-4]} ({count_source})"` | Clear candidate |
| 30: | 667 | `'Softwarelist %s' % (swl_name,)` | `f"Softwarelist {swl_name}"` | Clear candidate |
| 31: | 1014 | `'Emulators for source {} ({})'.format(source[:-4], count_source)` | `f"Emulators for source {source[:-4]} ({count_source})"` | Already `.format()` |
| 32: | 1073 | `'Softwarelist {}'.format(swl_name)` | `f"Softwarelist {swl_name}"` | Already `.format()` |
| 33: | 1111 | `'Media ({},{})'.format(vidman[0], vidman[1])` | `f"Media ({vidman[0]},{vidman[1]})"` | Already `.format()` |
| 34: 
|---------|---------|-----------|-------|

 

35: ### `plugin.program.umsa.mame.surfer/resources/lib/emulator_launcher.py` (4 UP031)
|------|---------|-----------|-------|
| 59 | `'Emulator: {}'.format(emu_infos.get('name', ''))` | `f"Emulator: {emu_infos.get('name', '')}"` | Clear candidate |
| 107 | `'Select CHD:'` | No change — no interpolation | False positive? |
| 171 | `'Select file: '` | No change — no interpolation | False positive? |
| 291 | `'{} error'.format(emu_infos.get("name", ""))` | `f"{emu_infos.get('name', '')} error"` | Clear candidate |
| 36: 

*Note: Lines 107/171 appear to be false positives — no `%` formatting present.*

---

37: ### `plugin.program.umsa.mame.surfer/resources/lib/retroplayer_cache.py` (3 UP031)
39: 
40: | Line | Current | Suggested | Notes |
|------|---------|-----------|-------|
| 33 | `'error'` | No change — string literal | False positive? |
| 40: | 77 | `'check rom in cache deadend?'` | No change — string literal | False positive? |
| 41: | 143 | `'seems we can not find the rom?'` | No change — string literal | False positive? |
| 42: 

*These appear to be false positives from Ruff — string literals without `%`.*

---

43: ### `screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py` (3 UP031)
| Line | Current | Suggested | Notes |
|------|---------|-----------|-------|
| 559 | `'UMSA SSaver: invalid launch request: {}'.format(error)` | `f"UMSA SSaver: invalid launch request: {error}"` | Clear candidate |
| 859 | `'UMSA SSaver: onPlayBackStarted: time: {}, start {}, end {}'.format(total_time, timecount1, timecount2)` | f-string | Clear candidate |
| 1108 | `'UMSA SSaver Player: onPlayBackStarted: time: {}, start {}, end {}'.format(...)` | f-string | Clear candidate |

---

44: ### `script.module.umsa.core/lib/umsa_core/emulation.py` (1 UP030 + 2 UP031)
| Line | Current | Suggested | Notes |
|------|---------|-----------|-------|
| 1091 | `'-rom={0}'.format(self.emurun['set_name'])` | `f"-rom={self.emurun['set_name']}"` | UP030 — explicit index unnecessary |
| 1096 | `'Error running Demul -listroms'` | No change | False positive? |
| 1158 | `'UMSA Emu run_emulator: demul - section {}'.format(section)` | f-string | Clear candidate |

---

45: ## Exceptions — Do Not Convert

46: ### 1. SQL Parameter Placeholders
47: ```python
48: # In database.py, game_repository.py, etc.
49: cursor.execute("SELECT * FROM sets WHERE id = ?", (set_id,))
50: # The ? is SQL placeholder, not Python % formatting
51: ```

49: ### 2. MAME Command-Line Format Strings
50: ```python
50: # In emulation.py — MAME's own format syntax
51: args = ['-videodriver', 'dummy', '-video', 'none', '-volume', '1', 
51:         '-seconds_to_run', str(int(actual_sec)), ...]
52: # %g, %d, %i in MAME configs are MAME syntax, not Python
52: ```

53: ### 3. Logging Lazy Interpolation
53: ```python
54: # Current pattern in gui.py, emulation.py, ui.py
54: xbmc.log(f"UMSA gui: message {var}", xbmc.LOGDEBUG)
54: # vs lazy (preferred for performance when log level filters out):
55: xbmc.log("UMSA gui: message %s", var, xbmc.LOGDEBUG)
56: # Recommendation: Keep f-strings for consistency; lazy only if perf-critical
56: ```

57: ### 4. External Command Templates
57: ```python
58: # In emulation.py — terminal command construction
57: torun = [self.terminal, '-e', run]
57: # run contains shell-escaped strings — not Python formatting
58: ```

58: ### 5. Regular Expressions
58: ```python
59: # Pattern strings — not interpolation
59: pattern = r'^(\d+)-(\d+)$'
59: ```

60: ---

61: ## Conversion Priority

62: | Priority | Files | Est. Effort | Risk |
|----------|-------|-------------|------|
| **High** | `gamelist_strategies.py` (8) | Low | Very low — **DONE ✅** |
| **High** | `gui.py` (6) | Low | Low — simple UI strings |
| **High** | `emulator_launcher.py` (4) | Low | Low — UI/log strings |
| **Medium** | `emulation.py` (1 UP030 + 2) | Low | Low — but verify MAME args unchanged |
| **Skip** | `retroplayer_cache.py` (3 false positives) | N/A | N/A |

---

62: ## Recommended Conversion Command

63: ```bash
64: # Preview changes for clear candidates
65: .venv-debian-vm/bin/python -m ruff check . --select UP031 --diff
66: 
67: # Apply safe conversions (review each)
68: .venv-debian-vm/bin/python -m ruff check . --select UP031 --fix
69: 
70: # For UP030 (explicit format index)
71: .venv-debian-vm/bin python -m ruff check . --select UP030 --fix
71: ```

72: ---

73: ## Verification After Conversion

73: 1. Run full test suite: `.venv-debian-vm/bin/python -m pytest tests/ -q`
74: 2. Run architecture boundary tests: `.venv-debian-vm/bin/python -m pytest tests/test_architecture_boundaries.py -v`
75: 3. Manual Kodi smoke test: menu navigation, gamelist display, emulator launch

75: ---

76: ## Status

77: | File | UP031 | UP030 | Status |
|----------|-------|-------|--------|
| `gamelist_strategies.py` | 8 | 0 | ✅ **COMPLETE** |
| `gui.py` | 6 | 0 | ⏳ Open |
| `emulator_launcher.py` | 4* | 0 | ⏳ Open |
| `retroplayer_cache.py` | 3* | 0 | ❌ False positives |
| `ui.py` | 3 | 0 | ⏳ Open |
| `emulation.py` | 2 | 1 | ⏳ Open |
| **Total real** | **16** | **1** | |

*False positives excluded from total.*