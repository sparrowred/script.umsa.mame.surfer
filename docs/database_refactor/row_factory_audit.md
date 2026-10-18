# Row-Factory and Result-Shape Audit (Phase 4.1)

**Audited code state:** git HEAD `27a852f`; **updated** at git HEAD `ea7d0f7` for
maintainer decisions Q1/Q3/Q7/Q8 (see `README.md`); **updated** at git HEAD `2a2b1af`
for implemented roadmap step 4.0 (boundary guard tests — no `row_factory` change) and
the `get_random_vgm` → `get_random_vgm_batch` rename (`7e47290`); **updated again** for
implemented step 4.2a (the three rows below marked "(Q1 → step 4.2a)" were **removed**
from `database.py` — later committed as `9f2fd40`; they stay in the table for history, and
`get_status_for_set`'s Row shape is untouched); **updated again** for implemented step
4.2b — the row input contract: `GameRepository`, `DatRepository` and `ArtworkRepository`
now reject non-`Row` connections with `ValueError` (`require_row_connection` in
`sqlite.py`), every repository-feeding scanner connection switched to
`connect_sqlite(..., row_factory=sqlite3.Row)`, the tuple/dict fallback code is gone, and
the tuple-compatibility tests are replaced by contract tests (4.2a+4.2b committed together
as `9f2fd40`; step 4.3 as `9041812`); **updated again** for implemented step 4.4 —
`get_parts_for_set_id`/`get_disks` delegates and `get_cmd_line_options`' four inline
SELECTs moved to `GameRepository` with **no row-access change** (both remain
Row-transparent; positional and `.keys()` consumers pin unchanged — see
`tests/test_cmd_line_options.py`). **updated again** for implemented step 4.5 — the
status.db status methods (`get_status_for_set`, `get_further_media`,
`write_status_after_play`, `save_further_media`, `get_latest_by_software`) now delegate
to `StatusRepository`, which requires `sqlite3.Row` at construction and returns rows
transparently (raw `Row` for the two reads — positional `i[1]`…`i[4]` and named
`row['marp']` access both preserved); no public row shape changed. **Scope of the audit
itself:** read-only — no `row_factory` was changed and no query was converted by the
audit.

This document is the compatibility reference for any future result-shape change. The
golden rule it establishes: **`sqlite3.Row` rows support both `row[i]` and `row['col']`;
plain tuples support only `row[i]`. Any method that today returns rows from a `Row`
connection may have callers using either (or both) access styles, so the row type is part
of the method's implicit public contract.**

**Superseding decision (Q7) — implemented in step 4.2b:** for *repository inputs* the
dual-compat rule below is replaced — **all repositories require
`connection.row_factory is sqlite3.Row` and raise `ValueError` otherwise.** The three
existing repositories enforce it in their constructors; every repository created since
applies the same rule on arrival — `StatusRepository` (step 4.5) and
`EmulatorRepository` (step 4.6) both do, so **every repository in the codebase now
enforces the Row input contract** (pinned by per-repository contract tests).
Repository inputs are therefore no longer dual-compatible; §1's dual-compat description
below documents the state *before* 4.2b.

---

## 1. Connection factories and their row configuration

`connect_sqlite` (`umsa_core/sqlite.py`) opens a plain `sqlite3.connect(...)` and only
sets `row_factory` when the caller passes one explicitly. It is the single connection
factory in Core; its **default stays `row_factory=None`** (decision Q7 — do not change
it).

| Connection | Created in | `row_factory` | Lifetime / owner |
|---|---|---|---|
| `DBMod.gdb` (umsa.db) | `_open_persistent_databases`; replaced in `open_db` | `sqlite3.Row` | Persistent; owned by `DBMod`; closed by `close_umsa_db` |
| `DBMod.sdb` (status.db) | `_open_persistent_databases` | `sqlite3.Row` | Persistent; owned by `DBMod`; closed by `close` |
| `open_db` temporary sync connection | `open_db` | `sqlite3.Row` | Worker-owned; becomes `self.gdb` on success |
| `_upgrade_dat_db` (dat.db) | `_upgrade_dat_db` | **default (tuple)** | Worker-owned, closed in `finally` |
| `add_dat_to_db` (umsa.db) | `add_dat_to_db` | **default (tuple)** | Worker-owned, closed in `finally` |
| `add_art_to_db` (umsa.db) | `add_art_to_db` | **default (tuple)** | Worker-owned, closed in `finally` |
| `get_random_vgm_batch` (umsa.db, formerly `get_random_vgm`) | `get_random_vgm_batch` via `connect_sqlite_readonly` (`mode=ro` URI) | **default (tuple)** | Worker-owned, closed in `finally`; called from the VGM playback thread; **stays tuple by decision Q3** (no repository involved) |
| `DatScanner._load_set_mapping` (umsa.db) | `dat_scanner.py` | `sqlite3.Row` | Worker-owned |
| `DatScanner.scan` staging connection (dat.db) | `dat_scanner.py` | `sqlite3.Row` (switched in 4.2b — feeds `DatRepository`) | Worker-owned |
| `GB64Scanner` mapping connection (umsa.db) | `gb64_scanner.py` | **default (tuple)** — positional unpacking, feeds **no** repository (stays tuple) | Worker-owned |
| `GB64Scanner` dat/art connections (dat.db / artwork.db) | `gb64_scanner.py` | `sqlite3.Row` (switched in 4.2b — feed `DatRepository`/`ArtworkRepository`) | Worker-owned |
| `ExodosScanner` mapping connection (umsa.db) | `exodos_scanner.py` | **default (tuple)** — positional unpacking, feeds **no** repository (stays tuple) | Worker-owned |
| `ExodosScanner` dat/art connections (dat.db / artwork.db) | `exodos_scanner.py` | `sqlite3.Row` (switched in 4.2b — feed `DatRepository`/`ArtworkRepository`, and the `art_repo` handed to `exodos_artwork.py`) | Worker-owned |
| `ArtworkScanner` artwork connection (artwork.db) | `artwork_scanner.py` | `sqlite3.Row` (switched in 4.2b — feeds `ArtworkRepository`) | Worker-owned |
| `ArtworkScanner` umsa connection (umsa.db) | `artwork_scanner.py` | **default (tuple)** — swl/set lookups read positionally, feeds **no** repository (stays tuple) | Worker-owned |
| Repository connections (`GameRepository`, `ArtworkRepository`, `DatRepository`) | supplied by caller (three `DBMod` per-call facades on `self.gdb`; the scanner sites above) | **`sqlite3.Row` required** — enforced at construction by `require_row_connection` (4.2b); the repositories never set it themselves | Caller-owned; repositories never close them |

**Construction-site audit for step 4.2b (complete list — all switched/compliant as of
the 4.2b implementation):** the three `DBMod` facades
(`_get_game_repository`, `_get_dat_repository`, `_get_artwork_repository` — already
`Row`); `dat_scanner.py` staging publish; `artwork_scanner.py` staging publish;
`exodos_scanner.py` (dat connection and art connection); `gb64_scanner.py` (dat + art);
`exodos_artwork.py` (receives the `art_repo` constructed by `exodos_scanner`, so it is
compliant transitively). No other
repository constructions exist in production code. The scanners' umsa.db mapping
connections construct **no** repositories and stay tuple. `add_dat_to_db`/`add_art_to_db`
construct **no** repositories and are explicitly out of scope (decision Q7).

**Repository behaviour before 4.2b (historical):** both original repositories worked
under either configuration:

- `DatRepository` query methods index rows **positionally** (`row[0]`, `row[1]`), which
  works with both tuples and `Row`.
- `ArtworkRepository` attempted `dict(row)` first and fell back to positional
  reconstruction; `list_scan_units` deliberately used positional indexing with an
  explanatory comment.

**Implemented in step 4.2b (decision Q7/Q8):** the `Row`-required constructor check now
exists in all three repositories (including `GameRepository`, which had none), via the
shared `require_row_connection(connection, owner)` helper in `sqlite.py`; the dead
fallback code is removed (`dict(row)` positional-reconstruction chains, the named/positional
fallbacks in `get_art_types`/`get_scan_unit_status`, and `list_scan_units` now reads
`row["scan_unit"]`); the tuple-backed repository construction sites are switched to
`connect_sqlite(..., row_factory=sqlite3.Row)`; and the tuple-compatibility tests are
replaced by contract tests: `test_game_repository.py::test_repository_rejects_tuple_connections`,
`test_artwork_repository.py::test_repository_rejects_default_row_factory_connection`,
`test_exodos_artwork.py::test_repository_rejects_default_row_factory_connection`,
plus unit coverage of the helper itself in `test_sqlite.py`. The tuple fixtures in
`test_dat_repository.py` and the repository-feeding connections in
`test_scan_coordinator.py` switched to `Row`. `connect_sqlite()`'s default is unchanged.

---

## 2. DBMod methods grouped by row-access style

Source of truth: the persistent connections are `Row`, so every method below that returns
raw rows returns `sqlite3.Row` objects unless stated otherwise. Methods are named, not
line-numbered (they drift).

### 2.1 Positional access on returned rows (external contract risk)

| Method | Access in DBMod / callers | Risk if rows became dicts/tuples |
|---|---|---|
| `get_all_dbentries(cat)` | `build_filter_lists` uses `entry[0]`, `entry[1]`, `entry[2]`; GUI list-filter loops use `i[0]` | Dicts would break `i[0]`; tuples would break nothing today but lose the named option |
| `get_searchresults(my_search)` | pos-finding loop uses `i[1]`; GUI popup uses `i['name']`, `i['id']` (`popup_gamelist`) | **Both styles used on the same rows.** Tuples break the GUI; dicts break the pos loop |
| `get_parts_for_set_id(set_id)` | `create_cmdline` uses `part[0]`, `part[1]` | Dicts would break |
| `get_disks(swl_name, set_name)` | consumer does `'disk' in disks[0].keys()` (`emulation.py`) | Named access required; tuples would break |
| `get_series(software_id)` | `series_ids[0]['series_id']` named; inner rows returned raw; member loop uses `i[0]`; popup uses `i['id']`/`i['name']` | **Mixed within one method** |
| `get_maker/get_swl/get_year/get_players/get_categories` | rows returned raw; `popup_gamelist` uses `i['name']`, `i['id']` | Named access required (aliased `name as id`) |
| `get_source()` | GUI uses `i['source']` | Named access required |
| `get_further_media(set_id)` | GUI uses `media['youtube']`, `media['marp']` | Named access required |
| `check_series` (internal read) | `series_exists['series_id']` named, then `[0]` on the count | Mixed |
| `get_status_for_set(set_id)` | `i[1]`…`i[4]` positional on the Row | Positional; only internal caller (`get_all_for_software`) |
| `get_status_for_software` | Row returned directly | **Removed in step 4.2a (Q1); no contract needed** |
| `get_info_for_id`, `get_sets_for_machine` | raw Row lists | **Removed in step 4.2a (Q1)** |
| `get_machine_name(machine_id)` | returns `(machine[0], machine[1])` — a plain tuple; `get_random_art` indexes it positionally and the GUI unpacks it | Tuple; stable |
| `get_info_by_set_and_swl` | `db_fetch[0..4]` positional → returns dict | Internal positional only; dict is the public shape |
| `search_single` | Row returned; `parse_recommended_games` uses named `found['id']` etc. | Named access required |
| `execute_statement` (returned list) | pos loop uses named `i['name']`; the list mixes `sqlite3.Row` fetches with plain-dict `prev`/`next` sentinel entries | Consumers must not assume one row type for the whole list — pin in step 4.7's characterisation suite |

### 2.2 Named access only

| Method | Notes |
|---|---|
| `get_machines` | Named access internally; returns `list[dict]` + pos |
| `get_last_played` | Named on both status rows (`i['id']`) and software rows (`software['id']`); returns `list[dict]` |
| `get_random_art` | Named on `rand_art['id']` and merged dicts; returns one merged dict or `None` |
| `get_all_for_software` | Named throughout; returns nested dict lists |
| `get_emulators` / `get_emulator` | Convert to `dict(row)` before returning — public shape is `dict` |
| `get_random_id` | `fetchone()[0]` — single value, shape-free |
| counts (`count_source`, `count_machines_for_swl`, `define_filter` counts, `check_compilation`) | Single scalar via `[0]` |

### 2.3 Methods returning pre-converted dicts (row type erased)

`get_emulators`, `get_emulator`, `get_artwork_for_set(s)` and `get_dat_for_set(s)` (via the
repositories) return plain dicts. These are the **safest** shapes to standardise on and the
pattern new repository methods should copy: convert at the boundary, return an unambiguous
type.

---

## 3. Implicit public contracts that must be preserved

1. **`sqlite3.Row` is duck-typed as both mapping and sequence.** GUI code freely mixes
   `i['name']` (`popup_gamelist`) with `i[0]` (`get_all_dbentries` consumers,
   `build_filter_lists`). Returning plain tuples would break named consumers; returning
   plain dicts would break positional consumers (`row.keys()` still works on dicts, but
   `row[0]` does not).
2. **`get_searchresults` and `get_series` have mixed-style consumers**, so neither pure
   tuple nor pure dict migration is possible without touching callers — the reason
   normalisation is its own step (4.8), never bundled with a SQL move.
3. **`get_disks` consumer calls `.keys()`** on the row — this works for both `Row` and
   `dict`, but not tuple.
4. **Worker-connected methods (`get_random_vgm_batch`, formerly `get_random_vgm`) already
   use tuples** — their public shape is a list of rebuilt dicts (empty on failure), so
   they are insulated; but any *new* code reading those
   rows must use positional access. Confirmed as a permanent non-goal (Q3).
5. **Repositories' input contract was narrowed (Q7, implemented in step 4.2b).** The
   historical dual-compat
   convention (positional indexing or `dict()` with fallback) existed because repositories
   received caller-owned connections of both kinds. Repositories now
   require `Row` and reject anything else with `ValueError`; the fallback code is
   removed and every construction site complies.

---

## 4. Risks of introducing consistent named-column access

- Converting `Row` → `dict` at the façade silently breaks every positional consumer listed
  in §2.1 (`build_filter_lists`, GUI `i[0]` loops, `create_cmdline`, the search pos loop).
- Converting `Row` → `tuple` breaks every named consumer (`popup_gamelist`, GUI media
  code, `get_disks` consumer, `parse_recommended_games`).
- Normalising *inside a repository* is safe only if the repository's documented return
  type is what the façade has always returned (dict/list-of-dict), or if the façade
  performs the historical conversion. A repository that starts returning `Row` where the
  façade previously returned dicts (or vice versa) is a compatibility break even if the
  SQL is identical.
- Changing `connect_sqlite` defaults (e.g. always `Row`) would change the tuple-typed
  worker connections (`add_dat_to_db`, `add_art_to_db`, the scanners' umsa.db mapping
  connections, `get_random_vgm_batch`) — explicitly forbidden (decisions Q3/Q7). The
  scanners' dat/art connections are already `Row` since 4.2b, because they feed
  repositories.

---

## 5. Recommended staged migration

**Stage 0 (this audit):** inventory complete; no changes.

**Stage R — row input contract (roadmap step 4.2b, decided Q7/Q8) — ✅ implemented
(committed as `9f2fd40`):**
all repositories require `connection.row_factory is sqlite3.Row` (clear `ValueError`
otherwise, via `require_row_connection` in `sqlite.py`); every construction site audited
(§1 list) and switched to
`connect_sqlite(..., row_factory=sqlite3.Row)` where it feeds a repository; dead
tuple/dict fallback code removed;
`connect_sqlite()` default unchanged; `add_dat_to_db`/`add_art_to_db` untouched; tuple
compatibility tests replaced by contract tests. Focused repository + scanner regression
suite and the full suite stayed green. Scope strictly limited — not combined with 4.3.

**Stage 1 — pin shapes at new repository boundaries (with roadmap steps 4.3-4.6):**
each new repository method documents its return type explicitly and chooses one of the two
existing conventions:
- *Row-transparent* — return the connection's native rows (default), for façade methods
  whose callers already depend on `Row` duck-typing (`get_all_dbentries`, `get_series`,
  `get_searchresults`, `get_further_media`, the lookup lists, and since step 4.4
  `get_parts_for_set_id`/`get_disks`). Zero behaviour change.
- *Normalised dict* — convert at the boundary, for methods whose public shape is already a
  dict (`get_emulators`, `get_machine_name`'s tuple stays a tuple, `get_info_by_set_and_swl`).
Acceptance: the existing façade methods return byte-identical structures; all current tests
pass unmodified.

**Stage 2 — dual-access safety net:** add regression tests that exercise *both* access
styles on every extracted method's rows (`row[0]` and `row['col']` where the column list is
fixed), so a later conversion is detectable. This is test-only work accompanying each
extraction, not a separate big-bang step.

**Stage 3 — row-leak closure (roadmap step 4.8, fixed — no longer an optional
"separate decision"):** after steps 4.3-4.6, the façade returns only unambiguous shapes
and `sqlite3.Row` never crosses into frontend/screensaver code — all cross-add-on
consumers use named access or plain dicts; positional consumers are adapted
(`build_filter_lists`, the GUI `i[0]` loops, the search pos loop, `get_series`' member
loop; core-internal `create_cmdline`/`get_status_for_set` choices made explicitly;
`execute_statement`'s mixed Row/dict list verified). Touches GUI code; must not be bundled
with any delegation step (see `roadmap.md` step 4.8).

**Do not, in any stage:** change `connect_sqlite`'s default, set `row_factory` globally, or
convert a method's return type in the same commit that moves its SQL into a repository.
