# Python Style & String Formatting Audit

**Audited:** 2026-10-27 (at HEAD `41a415b6ee8d1bb19b817a9f71db599638173342`)
**Tools:** Ruff (UP031, UP030), manual grep inspection  
**Scope:** All production Python in `plugin.program.umsa.mame.surfer/`, `screensaver.umsa.mame.surfer/`, `script.module.umsa.core/`

---

## Summary

| Pattern | Current count | Status |
|---------|---------------|--------|
| `%` formatting (UP031) | **0** | ✅ Resolved |
| Explicit `.format()` positional index (UP030) | **0** | ✅ Resolved |
| f-strings (dominant) | 100+ | Throughout newer code |

Ruff reports **0 `UP031` and 0 `UP030`** across the three production roots
at `41a415b`. The screensaver add-on, `gamelist_strategies.py` and
`database.py` are clean.

### Historical counts (superseded)

The 2026-10-23 audit at `4186b5f` listed 16 `UP031` (including six
`database.py` entries) and 1 `UP030`. That inventory was already stale by
`8f5191e`, where Ruff reported 10 `UP031` (`gui.py` 1, `umsa_gui/` 9) and 1
`UP030`. The `database.py` entries no longer produced findings and were the
main source of the old 16-vs-10 discrepancy. At `41a415b` the actual
inventory before the P1 edits was 10 `UP031` and 1 `UP030`; all eleven are
now fixed.

---

## Resolved findings at `41a415b`

| File | Rule | Lines before | Resolution |
|------|------|--------------|------------|
| `plugin.program.umsa.mame.surfer/resources/lib/gui.py` | UP031 | 516 | Search-result label converted to an f-string |
| `.../resources/lib/umsa_gui/artwork_presenter.py` | UP031 | 131, 217 | Play-time label and history summary converted to f-strings |
| `.../resources/lib/umsa_gui/filter_ui.py` | UP031 | 35, 56 | Filter count label converted to an f-string |
| `.../resources/lib/umsa_gui/media_list.py` | UP031 | 32, 40 | Video/manual labels converted to f-strings |
| `.../resources/lib/umsa_gui/software_selector.py` | UP031 | 59, 68, 213 | Set-list and video labels converted to f-strings |
| `script.module.umsa.core/lib/umsa_core/launch_preparer.py` | UP030 | 134 | Explicit `{0}` positional index made implicit (`{}`); Demul arguments unchanged |

`database.py` has no current findings. The six historical entries were not
reproducible at `41a415b` and are removed from the active inventory.

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

## Verification

Run the rule check against all production roots:

```bash
.venv-debian-vm/bin/python -m ruff check \
    plugin.program.umsa.mame.surfer \
    screensaver.umsa.mame.surfer \
    script.module.umsa.core \
    --select UP030,UP031
# → All checks passed!
```

Measured at `41a415b` after the P1 edits:

| Check | Result |
|-------|--------|
| Ruff `UP030,UP031` | **0 findings** (was UP031=10, UP030=1) |
| Ruff `BLE001,S110,PLW1510` | **BLE001=122, S110=0, PLW1510=0** (unchanged) |
| Ruff default rules | **173 findings** (was 184) |
| Focused GUI/emulator tests | **62 passed** (`test_umsa_gui_workflows.py`, `test_emulator_launcher.py`) |
| Architecture boundary tests | **7 passed** |
| Full suite | **1171 passed, 5 skipped, 18 subtests, 11 failed** — the 11 failures are the pre-existing `test_gui_shutdown.py` baseline, reproduced at the starting commit with the production edits reverted |

No manual Kodi smoke test was performed as part of this P1 change.

---

## Status

| File | UP031 | UP030 | Status |
|----------|-------|-------|--------|
| `gamelist_strategies.py` | 0 | 0 | ✅ **COMPLETE** |
| `gui.py` | 0 | 0 | ✅ **COMPLETE** |
| `umsa_gui/` package | 0 | 0 | ✅ **COMPLETE** |
| `database.py` | 0 | 0 | ✅ **COMPLETE** (historical 6 were stale) |
| `launch_preparer.py` | 0 | 0 | ✅ **COMPLETE** |
| `emulator_launcher.py` | 0 | 0 | ✅ Clean |
| `emulation.py` | 0 | 0 | ✅ Clean |
| screensaver add-on | 0 | 0 | ✅ Clean |
| **Total** | **0** | **0** | |
