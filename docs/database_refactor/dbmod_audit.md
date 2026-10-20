# DBMod Audit — Remaining Database Responsibilities (Phase 4.1)

**Audited code state:** git HEAD `27a852f` ("add context manager for scan state ownership
to manage shared scan status"); **updated** at git HEAD `ea7d0f7` after roadmap step 4.2
(`GameRepository` delegation), the removal of the three status.db `ALTER TABLE` migrations,
and maintainer decisions Q1–Q9 (`README.md`); **updated** at git HEAD `2a2b1af` for
implemented roadmap step 4.0 (boundary guard tests — no `database.py` change) and the
`get_random_vgm` → `get_random_vgm_batch` rename (`7e47290`); **updated again** for
implemented step 4.2a — the five Q1 methods removed from `database.py` (91 lines) and
step 4.2b — the `sqlite3.Row` repository input contract, both **committed as `9f2fd40`**;
**updated again for implemented step 4.3** (**committed as `9041812`**) — the seven
section 7 reads now **Delegates (4.3)**, and `get_all_for_software` is pure composition
with its two direct reads moved to `GameRepository` (coverage gap closed); **updated
**updated again for implemented step 4.4** (**committed as `4d5e70c`**) — `get_parts_for_set_id` and
`get_disks` are one-line **Delegates (4.4)**, and `get_cmd_line_options`' four inline
SELECTs moved to four focused `GameRepository` reads (the method itself stays as
orchestration).
**updated again for implemented step 4.5** (**committed as `fcdefe5`**) — the status.db
play-history rows in section 9 are now **Delegates (4.5)** over the new
`StatusRepository`, and the `sets` DDL moved to
`status_repository.create_status_tables` (schema unchanged, no migration); **and for
implemented step 4.6** (**committed as `b84341e`**) — the `emu`/`emu_conn` rows in
section 10 are **Delegates (4.6)** over `EmulatorRepository`; **and for implemented step
4.7** (**committed as `479e202` + `10f9fbd` + `da65a62` + `bc631eb`**) — the section 8
query state machine is now driven by the explicit `GamelistFilter` state and the SQL lives
in the Kodi-free `gamelist_filter` service, with every external value bound as a
parameter. Commit-status wording reconciled at HEAD `bc631eb` (tracked tree clean).
**Module under audit:** `script.module.umsa.core/lib/umsa_core/database.py`.
**Scope:** read-only inventory of every SQL-bearing method/helper in `database.py`, grouped by
responsibility, with connection/transaction ownership, callers, result shapes and a
delegation recommendation. No production code was changed by this audit.

Methods are referenced by name; this document carries no line numbers (they drift).
Roadmap step numbers refer to `roadmap.md`.

Legend for the "Delegation" column:

- **Extract** — contains real data access that a focused repository can own; delegate in a
  later phase (roadmap step noted).
- **Keep (facade)** — thin wrapper over an existing repository/scanner, or a public
  compatibility method that should stay in `DBMod` unchanged.
- **Keep (mixed)** — intentionally stays in `DBMod`: a mixed application query that
  combines tables from different domains, active `DBMod` filter state, or path
  resolution; moving it would obscure its purpose (see the module docstring's
  "intentional exceptions" list).
- **Keep (orchestration)** — application logic that *uses* SQL-bearing helpers but is not
  itself a repository concern (command-line building, list windowing, best-machine
  selection).
- **Remove** — decided for removal (decision Q1, roadmap step 4.2a). Rows still marked
  this way are **Removed (4.2a)**: they no longer exist in `database.py`, listed here for
  history.

---

## 1. Module-level helpers (outside `DBMod`)

| Helper | DB / tables | Access | Notes | Delegation |
|---|---|---|---|---|
| `_core_data_paths(db_path)` | — | — | Adapts a legacy directory argument to `CoreDataPaths`. | Keep |
| `parse_recommended_games(rec_text, db)` | via `db.search_single` | read | Parses the "Rec" DAT field; calls `DBMod.search_single` per name and builds popup dicts (`found['id']` named access). | Keep — pure application helper over a DBMod API |
| `build_filter_lists(filter_lists, category, db)` | via `db.get_all_dbentries` | read | Partitions a filter category into active/inactive. Indexes rows **positionally** (`entry[0]`, `entry[1]`, `entry[2]`) — part of the implicit `get_all_dbentries` row contract (see `row_factory_audit.md`); a target of step 4.8. | Keep — application helper; row-contract stakeholder |
| `download_and_update_umsa_db(data_dir, progress, ...)` | — | — | Network download + zip extract; no SQL; `progress` callback injected (GUI passes a dialog updater). | Keep — candidate for step 4.9 |
| `_scan_state_ownership(db, start_what)` | — | — | Context manager owning the shared scan lock and `scan_perc`/`scan_what`/`scan_status`. | Keep — candidate for step 4.9 |
| `run_scan_with_progress(db, scan_method, ...)` | — | — | Runs a `DBMod` scan method in a thread with progress polling; imports exported to the GUI. Its `getattr(db, scan_method)` dispatch only ever receives the GUI's four scan names (`scan_dats`, `scan_exodos_to_db`, `scan_gb64_to_db`, `scan_artwork`). | Keep |
| `split_gamename(complete_name)` | — | — | Pure string helper. | Keep — candidate for step 4.9 |
| `COUNTRIES` | — | — | Country-matching table used by `get_best_machine_for_set`. | Keep — candidate for step 4.9 |

---

## 2. Connection & schema lifecycle (`umsa.db` + `status.db`)

| Method | DB / tables | R/W | Connection | Transaction | Delegation |
|---|---|---|---|---|---|
| `__init__(db_path, nonmame, filter_lists, pref_country)` | both | — | — | — | Keep — constructs persistent state, delegates to `_open_persistent_databases` |
| `_open_persistent_databases(db_path, filter_lists)` | `umsa.db`: sanity `dat`/`dat_set`/`art_set` DDL via repo helpers; `status.db`: DDL via `status_repository.create_status_tables` (sets) and `emulator_repository.create_emulator_tables` (emu/emu_conn) — **no migrations** (the three `ALTER TABLE` migrations for `emu.mode`, `sets.marp`, `sets.youtube` were removed at `ea7d0f7`; see README policy) | DDL + commit | Opens persistent `self.gdb` (umsa.db, `sqlite3.Row`) and `self.sdb` (status.db, `sqlite3.Row`), cursors `self.gdbc`/`self.sdbc` | Commits `gdb` after sanity DDL; commits `sdb` after DDL | Keep. The `sets` DDL moved to `create_status_tables` in step 4.5 and the `emu`/`emu_conn` DDL to `create_emulator_tables` in step 4.6 (both schemas unchanged; no inline `CREATE TABLE` remains in `database.py`). The method itself is lifecycle orchestration |
| `open_db(db_path)` | `umsa.db` + ATTACH `dat.db`, `art.db` | read `dat.dat`/`dat_set`/`art.art_set`, replace `main.dat`/`main.dat_set`/`main.art_set` | Replaces persistent `self.gdb` after closing the previous one (`close_umsa_db`) | Own transaction on `gdb`: DELETE+INSERT…SELECT committed atomically; rollback + detach in `except`/`finally`; on failure closes umsa.db entirely | Keep (mixed) — documented cross-database synchronisation exception (module docstring); owns connection replacement + ATTACH lifecycle |
| `create_dat_tables(db_cursor)` | `dat`, `dat_set` | DDL | Receives caller's cursor | None (caller commits) | Keep (facade) — delegates to `dat_repository.create_dat_tables` |
| `_upgrade_dat_db(db_paths)` | `dat.db` | DDL + commit | **Own short-lived connection** (default tuple rows) | Owns commit + close | Keep — used only by `open_db`/`add_dat_to_db` before ATTACH; could later delegate to `DatRepository` as a classmethod-style schema helper, no urgency |
| `create_art_tables(db_cursor)` | `art_set`, `art_scan_unit` + indexes | DDL | Caller's cursor | None | Keep (facade) — delegates to `artwork_repository.create_artwork_tables` |
| `close_umsa_db()` | — | — | Closes `gdbc`/`gdb`, defensive `getattr`, idempotent | — | Keep — lifecycle |
| `close()` | — | — | Closes both persistent connections, idempotent | — | Keep — lifecycle |
| `close_db()` | — | — | Compatibility wrapper for `close_umsa_db` (the GUI DB-update sequence in `gui.py` depends on status.db staying open) | — | Keep (facade) |

**Callers:** `open_db`/`close_umsa_db`/`close_db` are driven by the GUI update sequence
(`gui.py`, `update_db` flow). `close()` is also called by the screensaver runtime
(`umsa_screensaver/runtime.py`).

---

## 3. Cross-database synchronisation (`ATTACH`, worker-owned connections)

| Method | DB / tables | R/W | Connection | Transaction | Delegation |
|---|---|---|---|---|---|
| `add_dat_to_db(db_path)` | `umsa.db` ← ATTACH `dat.db`; replaces `main.dat`, `main.dat_set` | delete + insert-select | **Own connection** (explicitly "can be threaded" per `add_art_to_db` docstring pattern) | Own transaction; rollback on error; DETACH before close so SQLite never implicitly commits the attached db | Keep (mixed) — documented exception; self-contained unit with its own connection lifecycle |
| `add_art_to_db(db_path)` | `umsa.db` ← ATTACH `art.db`; replaces `main.art_set`; then `SELECT COUNT(*)` for a log line | delete + insert-select + count | **Own connection** (docstring: "can be threaded") | Own transaction; rollback; DETACH; closes | Keep (mixed) — same exception; the count uses positional `fetchone()[0]` on a default-tuple connection |

**Callers:** GUI update flow after scans (`gui.py`). Tests:
`tests/test_database.py` (`test_add_dat_to_db_*`),
`tests/test_scan_artwork.py` (`test_add_art_to_db_*`, incl. failure-preserves-records).

**Risk to preserve:** the DELETE+INSERT…SELECT pair must stay in one transaction so a failed
copy never leaves the target empty. Both test groups above assert this; any delegation must keep
them green without modification.

**Scope note:** both methods are explicitly **out of scope for roadmap step 4.2b** — they
use no repositories and keep their default-tuple worker connections.

---

## 4. Scan wrappers (thin compatibility façade — already delegated)

| Method | Delegates to | Notes |
|---|---|---|
| `_run_scan_with_shared_state(start_what, run)` | `_scan_state_ownership` | Lock-aware run wrapper |
| `scan_gb64_to_db(empty, db_path)` | `GB64Scanner` | Keeps `scan_perc`/`scan_what`/`scan_status` attributes used by `run_scan_with_progress` and the GUI; `empty` argument is a never-read legacy placeholder |
| `scan_exodos_to_db(empty, db_path)` | `ExodosScanner` | Same pattern (lazy import inside `run()`) |
| `scan_dats(datdir, db_path)` | `DatScanner` | Same pattern |
| `scan_artwork(paths, db_path, listdir, source, cancel_event, only_types, resume, **kwargs)` | `ArtworkScanner` | Same pattern; accepts `os.listdir` injectable from the GUI |

All five are **Keep (facade)**: they contain no SQL, only progress/cancellation bridging.
Tests: `test_scan_coordinator.py` (lock arbitration through DBMod), `test_exodos_scan.py`
(wrapper-delegates test), `test_scan_artwork.py`, `test_gb64_scanner.py`, `test_dat_scanner.py`,
`test_run_scan_with_progress.py`.

---

## 5. Repository accessors and thin delegations (umsa.db via `self.gdb`)

| Method | Delegates to | Row/return contract |
|---|---|---|
| `_get_artwork_repository()` | `ArtworkRepository(self.gdb)` | Per-call (never cached) so it cannot pin a connection replaced by `open_db`; never closes `self.gdb` |
| `_get_dat_repository()` | `DatRepository(self.gdb)` | Same contract |
| `_get_game_repository()` | `GameRepository(self.gdb)` | Same contract; added with step 4.2 |
| `get_art_types()` | `ArtworkRepository.get_art_types` | `list[str]` |
| `get_artwork_for_set(set_id)` | `ArtworkRepository.get_artwork_for_set` | `list[dict]` |
| `get_artwork_for_sets(set_ids)` | `ArtworkRepository.get_artwork_for_sets` | `dict[set_id, list[dict]]` |
| `get_dat_for_set(set_id)` | `DatRepository.get_dat_for_set` | `dict[file, entry]` |
| `get_dat_for_sets(set_ids)` | `DatRepository.get_dat_for_sets` | `dict[set_id, dict[file, entry]]`; empty list → `{}` |
| twelve step-4.2 lookups/counts (`get_maker`, `get_swl`, `get_source`, `get_year`, `get_players`, `get_categories`, `get_set_name`, `get_machine_name`, `get_set_ids_for_software`, `count_source`, `count_machines_for_swl`, `search_single`) | `GameRepository.<method>` | One-line facades over `_get_game_repository()`; return shapes unchanged (section 7.1) |
| seven step-4.3 reads (`get_series`, `check_series`, `check_compilation`, `get_all_dbentries`, `get_searchresults`, `get_machines`, `get_info_by_set_and_swl`) | `GameRepository.<method>` | One-line facades over `_get_game_repository()`; return shapes unchanged (sections 7.2–7.4) — implemented in step 4.3 |
| two step-4.4 command-line input reads (`get_parts_for_set_id`, `get_disks`) | `GameRepository.<method>` | One-line facades over `_get_game_repository()`; Row-transparent, shapes/`None` semantics unchanged (section 7.4) — implemented in step 4.4; `get_cmd_line_options` calls the same repository directly (its four inline SELECTs moved as `get_swl_options`, `get_machine_id`, `get_devices_for_machine`, `get_sharedfeat_requirement`) |

All **Keep (facade)** — already the intended end state. Callers: GUI and screensaver
through `DBMod`, plus internal consumers (`get_all_for_software`, `get_random_art`,
`parse_recommended_games`).

**Row contract (implemented in step 4.2b):** the constructors of all repositories
require `row_factory is sqlite3.Row` (decision Q7, enforced via `require_row_connection`
in `sqlite.py`); non-`Row` connections are rejected with `ValueError`, so the historical
dual-compatibility is gone for repository inputs (see `row_factory_audit.md` §1).

---

## 6. Mixed application queries (documented intentional exceptions)

| Method | Tables | Why it stays |
|---|---|---|
| `get_random_id()` | `sets`, `software` + active `filter_join`/`filter_where` | Applies the live filter state; returns a bare id (`fetchone()[0]`, positional). Could accept an *explicit* filter parameter later; for now it reads `DBMod` state — moving it mechanically would just relocate the coupling |
| `get_random_art(art_types)` | `art_set` JOIN `sets`, then `sets`/`swl`/`year`/`maker`/`category`, display info, left-pic lookup via `ArtworkRepository` | Documented exception (module docstring): joins artwork with game tables, depends on `use_filter`/`filter_join`/`filter_where`, resolves paths via `resolve_artwork_path` and `_art_source_roots`. Delegates only the isolated left-image row to the artwork repository |
| `_art_source_roots()` | — | Helper for `get_random_art`; reads `self.nonmame` |
| `get_artwork_by_software_id(software_id, artwork, source_roots)` | `swl`+`sets`, `sets`+`swl`+`art_set` | Documented exception (module docstring): joins `art_set` with game tables and resolves the path; returns `[art_path, machines]`. Callers: GUI; test `test_database.py` |

**Recommendation:** keep all four in `DBMod` for now. If a future phase wants them separated,
the clean boundary is a *mixed-query service* that receives `(connection, filter_state,
source_roots)` as explicit arguments — not a table repository. Do not move them into
`ArtworkRepository` (they are not artwork-table CRUD).

---

## 7. General game/set read queries (`umsa.db`, persistent `self.gdb`)

Every method in this group executes SQL directly on `self.gdbc`, uses the persistent
`umsa.db` connection, performs reads only, and never manages transactions.

**Status (since `ea7d0f7`; 4.0 made no `database.py` change; 4.2a removed the five Q1
methods):** the twelve simple lookups/counts of section 7.1 **delegate** to
`GameRepository` (roadmap step 4.2); the seven reads of sections 7.2–7.4 **delegate**
(step 4.3); `get_parts_for_set_id` and `get_disks` **delegate** (step 4.4). Section 7 has
**no SQL left in `DBMod`**: `get_cmd_line_options` (its four inline SELECTs are now the
repository reads `get_swl_options`, `get_machine_id`, `get_devices_for_machine`,
`get_sharedfeat_requirement`) and `create_cmdline` (pure) remain as *assembly*, not data
access. The five Q1 removal candidates (`get_swl_id`,
`get_info_for_id`, `get_sets_for_machine`) were removed in 4.2a.

### 7.1 Simple lookups and counts

| Method | Tables | Return shape | Callers | Status |
|---|---|---|---|---|
| `get_set_ids_for_software(software_id)` | `sets` | `list[int]` (positional `i[0]`) | Internal: `get_latest_by_software` (its other consumer, `get_status_for_software`, is removed in 4.2a) | Delegates (4.2) ✅ |
| `get_machine_name(machine_id)` | `sets` | `(name, gamename)` tuple via positional `machine[0]`, `machine[1]` | GUI machine-name display; internal: `get_random_art` (indexes the tuple positionally) | Delegates (4.2) ✅ |
| `get_set_name(set_id)` | `sets` | bare `name` or `None` | `emulator_launcher.py` | Delegates (4.2) ✅ |
| `count_source(source)` | `sets`+`software` | `int` | GUI | Delegates (4.2) ✅ |
| `count_machines_for_swl(swl_name)` | `swl_status`+`sets`+`swl` | `int` | GUI | Delegates (4.2) ✅ |
| `get_swl_id(swl_name)` | `swl` | bare `id` | **No callers** (docstring: "TODO: unused") | **Removed (4.2a)** (Q1) |
| `search_single(my_search)` | `software`+`year`+`maker`+`sets` | one `sqlite3.Row` or `None`; consumer uses named access (`parse_recommended_games`) | `parse_recommended_games` | Delegates (4.2) ✅ |

### 7.2 Series / compilation

| Method | Tables | Return shape | Callers |
|---|---|---|---|
| `get_series(software_id)` | `series_seq`, then per-member nested query over `software`/`sets`/`year`/`maker` | `list[sqlite3.Row]` or `None`; rows consumed by `popup_gamelist` via named `i['id']`/`i['name']`; **N+1 query pattern** (one query per series member); first series wins (explicitly pinned) | GUI, `gamelist_strategies.py` |
| `check_series(software_id)` | `series_seq` | `int` or `None` | GUI |
| `check_compilation(software_id)` | `software`+`compilations` (two queries) | `0/1/2` | GUI |

**Delegates (4.3)** ✅ — facade in `database.py`, SQL in `GameRepository`; shapes,
N+1 and first-series-wins behaviour preserved verbatim (golden-pinned).

### 7.3 Search & browse lists

| Method | Tables | Return shape | Callers |
|---|---|---|---|
| `get_searchresults(my_search)` | `sets`+`software`+`year`+`maker` (count + fetch, `LIKE`) | `(results, pos, count)`; results are `sqlite3.Row` list but the pos-finding loop indexes **positionally** `i[1]` while the GUI reads `i['name']`/`i['id']` — both must keep working until step 4.8 | GUI, `gamelist_strategies.py` |
| `get_all_dbentries(cat)` | `swl`/`category`/`year`/`nplayers` + `software` + `sets` (one dynamic SQL per category) | `list[sqlite3.Row]`; **consumed positionally** (`i[0]` in GUI list-filter loops; `entry[0..2]` in `build_filter_lists`) | GUI, `build_filter_lists` |
| `get_maker()` | `maker` | `list[Row]` (`name as id, name`); named access in `popup_gamelist` | GUI | 
| `get_swl()` | `swl` | same | GUI |
| `get_source()` | `sets` | `list[Row]` (`source` column); named `i['source']` in the GUI | GUI |
| `get_year()` | `year` | same pattern | GUI |
| `get_players()` | `nplayers` | same pattern | GUI |
| `get_categories()` | `category` | same pattern | GUI |

The six lookups **delegate (4.2)** ✅; `get_searchresults` and `get_all_dbentries`
**delegate (4.3)** ✅ (Row shapes, `i[1]` pos loop and positional `i[0]` consumers
all preserved — golden-pinned).

### 7.4 Machine / set metadata for emulation

| Method | Tables | Return shape | Callers |
|---|---|---|---|
| `get_machines(swl_name, machine=None)` | `sets`+`swl`+`swl_status`+`year`+`maker` | `(list[dict], pos)` — shapes rows into GUI dicts with named access internally | `gamelist_strategies.py`, internal: `get_best_machine_for_set` |
| `get_parts_for_set_id(set_id)` | `part_set`+`part` | `list[Row]`; consumed **positionally** in `create_cmdline` (`part[0]`, `part[1]`) | internal: `get_cmd_line_options`, `create_cmdline` |
| `get_disks(swl_name, set_name)` | `sets`+`swl`, `part_set` | `list[Row]` (disk column) or `None`; caller does `'disk' in emurun['disks'][0].keys()` (`emulation.py`) — **named access on Row** | `emulator_launcher.py` |
| `get_info_by_set_and_swl(setname, swlname)` | `software`+`sets`+`swl`+`year`+`maker` | `dict` built via **positional** `db_fetch[0..4]` | `gamelist_strategies.py` |
| `get_info_for_id(_id)` | `sets`/`swl`/`year`/`category` | `list[Row]` | **No callers** (docstring: "TODO: unused") — **Removed (4.2a)** (Q1) |
| `get_sets_for_machine(software_id, machine_id)` | `sets`/`swl`/`year`/`maker`/`category` | `list[Row]` | **No callers** (docstring: "TODO: unused") — **Removed (4.2a)** (Q1) |
| `get_cmd_line_options(set_id, set_name, machine_name, swl_name)` | `swl`, `sets`+`swl` (machine id), `device_set`+`device`, `sharedfeature`+`sharedfeature_set`, plus `get_parts_for_set_id` | `list[str]` command line | `emulation.py` (via `prepare_mame_run`) |
| `create_cmdline(parts, devices, setname)` | — (pure) | `(cmd_options, first_device)`; mutates the `parts` list argument in place | internal |

`get_cmd_line_options` is **Keep (orchestration)** (final, since step 4.4): the natural
split the audit proposed — repository exposes the *reads*, assembly stays in `DBMod` —
is exactly what step 4.4 implemented (see below). Do not turn the whole method into a
repository method.

`get_machines` and `get_info_by_set_and_swl` **delegate (4.3)** ✅ — their dict shaping
moved into `GameRepository` (documented in the method docstrings per the roadmap
decision); shapes (`list[dict]` + `pos`, `dict`) are unchanged.

`get_parts_for_set_id` and `get_disks` **delegate (4.4)** ✅ — one-line facades over
`GameRepository`, SQL moved byte-identical (incl. `ORDER BY p.name` and the two-query
`get_disks` flow); Row shapes, positional `part[0]`/`part[1]` consumption and the
`'disk' in row.keys()` contract preserved.

`get_cmd_line_options` performs no SQL itself since step 4.4: one repository instance
serves the four moved reads (`get_swl_options`, `get_machine_id`,
`get_devices_for_machine`, `get_sharedfeat_requirement`) plus both parts fetches, while
the shared-feature chain and the `create_cmdline` call stay in `DBMod`. `create_cmdline`
stays too (pure assembly, no SQL — its positional `part[0]`/`part[1]` indexing is
core-internal until step 4.8 decides otherwise).
`get_best_machine_for_set` stays as orchestration (reorganisation candidate, step 4.9).
Do not turn any of the three into a repository method.

---

## 8. Game-list query state machine & filter composition (`umsa.db` + `DBMod` state)

This group is the query *engine* of the frontend. It combines SQL with instance state:
`use_filter`, `order`, `join`, `where` (set by the `get_by_*` family), and
`filter_join`/`filter_where` (set by `define_filter`). The GUI mutates `use_filter` and
`order` through the accessors `set_filter_enabled`/`set_order` (since step 4.7),
and the screensaver sets `use_filter = False` through the same accessor.

**Implemented in step 4.7:** the composition now lives in the Kodi-free
`umsa_core/gamelist_filter.py`, driven by an explicit `GamelistFilter` state
(`join`/`where`/`order`/`use_filter`/`filter_join`/`filter_where` plus
`where_params`/`filter_where_params`). `DBMod` keeps the mutable attributes as the public
holder and every row below is now a facade: it builds the state, delegates, copies the
clauses back and mirrors the in-place `order` reset. All external values are bound as SQL
parameters — the id lists, the category/year/player/swl/source/maker names, the
`software.name` comparison in the prev/next queries and the random-artwork type list in
`get_random_art`; `DBMod` stores the matched values in the private
`_where_params`/`_filter_where_params` for `get_random_id`/`get_random_art`. Only the
validated `order` whitelist is still interpolated (never a bound value).

| Method | Tables | Behaviour | Delegation |
|---|---|---|---|
| `define_filter(filter_lists)` | `swl`, `category`, `nplayers`, `year`, `sets`, `software` | Builds `filter_join`/`filter_where` (+ `filter_where_params`); skips a join when the filter covers the whole table; returns a display string `"count (percent%)"`. Commits nothing (reads only). **Id lists are bound (`IN (?,…)`)** since step 4.7 | Extracted (4.7) — facade over `gamelist_filter.define_filter`; the decision logic ("all selected → no join") stays visible in the service |
| `execute_statement(set_id, software_id, prevnext)` | `software`+`sets`+`year`+`maker` + filter subselect | Builds `where` from `use_filter`/`join`/`where`/`filter_*`, resolves the current software name, fetches up to 100 rows with `ORDER BY {order}`, retries without filters when empty, then windows the list around the current position with `prev`/`next` sentinel entries. Returns `(slist, pos, result_count)` — the returned list mixes `sqlite3.Row` entries with plain-dict sentinel entries. **`sname` and the filter/selector values are bound; only `order` is interpolated from the validated whitelist.** The pos loop uses named access (`i['name']`); the unexpected-`order` bug is **fixed** (fallback bound in its own commit, `479e202`) | Extracted (4.7) — facade over `gamelist_filter.execute_statement`; the windowing/orchestration moved with the SQL. Known limitation: the selector-only retry loop can run forever when the selector matches nothing |
| `get_by_software(set_id)` | via `execute_statement` | Sets `join`/`where` to `''` and empty params, delegates | Facade over `gamelist_filter.software_query` (4.7) |
| `get_software_for_source(set_id, source)` | via `execute_statement` | `where = 'sets.source = ?'` with `[source]` | Facade over `gamelist_filter.source_query` (4.7) |
| `get_by_cat(cat, set_id)` | via `execute_statement` | `where = 'category.name = ?'` with `[cat]` | Facade over `gamelist_filter.category_query` (4.7) |
| `get_by_year(year, set_id)` | via `execute_statement` | `where = 'year.name = ?'` with `[year]` | Facade over `gamelist_filter.year_query` (4.7) |
| `get_by_players(players, set_id)` | via `execute_statement` | `where = 'nplayers.name = ?'` with `[players]` | Facade over `gamelist_filter.players_query` (4.7) |
| `get_by_maker(maker, set_id)` | `maker` (clone resolution — three parameterised reads, then a bound `maker.id IN (?,…)` list) then via `execute_statement` | Resolves the cloneof chain first; where/params bound | Facade over `gamelist_filter.maker_query` (4.7) |
| `get_by_swl(swl_name, set_id)` | via `execute_statement` | `where = 'swl.name = ?'` with `[swl_name]` | Facade over `gamelist_filter.swl_query` (4.7) |
| `get_last_played(order)` | **status.db** `sets` + **umsa.db** per-set software info (N+1) | Cross-connection query + aggregation in Python; formats results as GUI list dicts; `order` interpolated into the status SQL and used as a dict key. Returns `(results, 0)` | Keep (mixed) — deliberately combines both databases and does presentation formatting; would become pure orchestration once status reads live in `StatusRepository` (step 4.5 — done; this method stayed, its status-side read is a multi-row aggregation rather than one of the four extracted single-set reads) |
| `get_best_machine_for_set(swl_name, detail, swl_machine_id)` | — (uses `get_machines`) | Pure selection logic over machine rows + `COUNTRIES` | Keep (orchestration) — no SQL of its own; candidate for step 4.9 |
| `get_all_for_software(software_id)` | `sets`+5 joins (per software with same name), then per-set status via `get_status_for_set`, best machine, latest via `get_latest_by_software`, dat via `get_dat_for_sets`, art via `get_artwork_for_sets` | The frontend's main orchestration: builds nested set lists, resolves machines, injects `last_played`, returns `(return_list, pos_machine, pos_set, all_dat, all_art)`. **Pure composition as of step 4.3:** all four umsa.db reads go through `GameRepository` (`get_sets_for_software`, `get_software_name`, `get_software_ids_for_name`, `get_machine_name`); no `self.gdbc` remains (structurally pinned by a test) | Keep (orchestration). Direct reads moved to `GameRepository` in step 4.3 ✅ — coverage gap closed |

**Callers of the family:** GUI (`execute_statement` for prev/next, `get_by_*` for
selection) and `gamelist_strategies.py` (all six `get_by_*`, `get_software_for_source`,
`get_last_played`).

---

## 9. `status.db` — play history and per-set media

All methods use the persistent `self.sdb`/`self.sdbc` connection (`sqlite3.Row`), except
where noted. Since step 4.5 the SQL lives in `StatusRepository` (per-call
`_get_status_repository()`); the repository runs each write in its own savepoint and only
commits a transaction it started, which is behaviour-identical for today's callers (no
method joins an outer transaction).

| Method | Tables | R/W | Return | Callers | Delegation |
|---|---|---|---|---|---|
| `get_status_for_set(set_id)` | `sets` (status.db) | read | dict with formatted `time_played`/`last_nice` or `None`; **positional** `i[1]`…`i[4]` on the Row; includes the `options` column read (column and shape preserved per Q1) | internal: `get_all_for_software` | Delegates (4.5) ✅ — SQL in `StatusRepository.get_status_for_set` returns the raw Row; the dict building, elapsed-time formatting and `make_time_nice` stay here (presentation) |
| `get_status_for_software(software_id)` | `sets` (status.db) after `get_set_ids_for_software` (umsa.db) | read | `sqlite3.Row` `(COUNT(play_count), COUNT(time_played))` | **No callers** | **Removed (4.2a)** (Q1); no replacement API |
| `get_further_media(set_id)` | `sets` (status.db) | read | `Row(marp, youtube)`; caller uses named access (`media['youtube']`) | GUI | Delegates (4.5) ✅ — Row-transparent repository read, no dict/tuple conversion |
| `save_further_media(set_id, marp, youtube)` | `sets` (status.db) | update-or-insert + savepoint commit | `None` | GUI (marp only today) | Delegates (4.5) ✅. **Q4 prerequisite (committed as `8bb8a8d`):** one INSERT writes both values for a missing row (the historical second INSERT collided on the `sets.id` PK); the single-INSERT logic moved into `StatusRepository.save_further_media` unchanged, with the update-only-supplied-values semantics preserved |
| `write_options(set_id, options)` | `sets` (status.db) | update + commit | `None` | **No callers** | **Removed (4.2a)** (Q1); the `options` **column and its reads stay** |
| `write_status_after_play(set_id, played_seconds)` | `sets` (status.db) | read-modify-write + savepoint commit | `None` | GUI, `emulator_launcher.py` | Delegates (4.5) ✅ — the SELECT plus INSERT/UPDATE moved to `StatusRepository.write_status_after_play` inside one savepoint (one atomic unit); timestamp format `%Y-%m-%d %H:%M` and the arithmetic preserved verbatim |
| `get_latest_by_software(software_id)` | `sets` (status.db) + umsa.db via `get_set_ids_for_software` | read | set id or `None` | internal: `get_all_for_software` | Delegates (4.5) ✅ — orchestration stays here (umsa.db set-id lookup), the status-side query is `StatusRepository.get_latest_by_set_ids` (same `ORDER BY last_played DESC LIMIT 1`, empty id list → `None`) |
| `make_time_nice(timestamp, now=None)` | — | — | formatted duration string | GUI, `emulator_launcher.py`, internal | Keep — pure helper, no SQL (candidate for step 4.9) |

**Schema note:** both `status.db` schemas now live with their repositories —
`sets` in `status_repository.create_status_tables(cursor)` (step 4.5) and
`emu`/`emu_conn` in `emulator_repository.create_emulator_tables(cursor)` (step
4.6), both called by `_open_persistent_databases`, which holds **no inline DDL
and no migrations** (the three `ALTER TABLE` migrations were removed at
`ea7d0f7` — README policy); the on-disk schemas are unchanged.

**Still here (not moved by 4.5):** `get_last_played` (cross-connection query + GUI
presentation over both databases), `get_all_for_software` (orchestration),
`make_time_nice` (pure formatting helper).

---

## 10. `status.db` — emulator configuration

| Method | Tables | R/W | Return | Delegation |
|---|---|---|---|---|
| `get_emulators(source=None, swl_name=None)` | `emu` JOIN `emu_conn` (or plain `emu`) | read | `list[dict]` (converted via `dict(row)`) | Delegates (4.6) ✅ — SQL (incl. aliases, `ORDER BY`, `source` > `swl_name` precedence) moved verbatim to `EmulatorRepository.get_emulators` |
| `get_emulator(emu_id=None, emu_conn_id=None)` | `emu` (or via `emu_conn`) | read | `dict` or `None` | Delegates (4.6) ✅ — `emu_id` > `emu_conn_id` precedence kept; the no-argument case (no callers) returns `None`, documented in `roadmap.md` |
| `save_emulator(emu_info, reconfigure, source, swl_name)` | `emu` + `emu_conn` | insert/update + commit, then maybe `connect_emulator` | `None`; insert reads the generated id from the insert cursor | Delegates (4.6) ✅ — modeled as one repository method preserving the observable sequence (emu-row savepoint → commit → separate `connect_emulator` unit); the unreachable update + `reconfigure=False` branch now uses `emu_info['id']` instead of a stale `lastrowid` (documented decision, pinned by a test) |
| `connect_emulator(emu_id, source, swl_name)` | `emu_conn` | insert + commit | `None`; logs when neither key given | Delegates (4.6) ✅ — same logging/no-op for neither-key; no unconditional commit of a caller's pending transaction (ownership convention) |
| `delete_emulator_connection(emu_conn_id)` | `emu_conn` | read + delete + commit | emu id if it was the last connection, else `None` | Delegates (4.6) ✅ — read-modify-write unit in one savepoint; string ids keep working (affinity) |
| `delete_emulator(emu_id)` | `emu_conn`, `emu` | delete + commit ×2 | `None` | Delegates (4.6) ✅ — connections-first order **and** the two-phase commit preserved deliberately (failure atomicity unchanged: a failed emulator delete leaves the connections removed), pinned by a trigger test |

**Callers:** the GUI emulator management flows and `gamelist_strategies.py`.

**Transaction note (resolved by step 4.6):** each write used to commit immediately; the
extraction moved writes under the `ArtworkRepository`/`DatRepository` convention ("only
commit a transaction the method started", savepoint `umsa_emu_write`). Verified
behaviour-compatible: no caller wraps these in an outer transaction, standalone writes
leave `in_transaction` False, and the historical commit boundaries of `save_emulator`
(emu row committed before the connection insert) and `delete_emulator` (connections
committed before the emulator delete) are preserved as deliberate separate units — all
pinned by `tests/test_emulator_repository.py`.

---

## 11. Worker-owned connection query

| Method | DB | Connection | Rows | Callers |
|---|---|---|---|---|
| `get_random_vgm_batch(db_path, limit=100)` (formerly `get_random_vgm`) | `umsa.db` | **Own short-lived read-only connection** via `connect_sqlite_readonly` (URI `mode=ro`) — **default tuple rows**, unlike the persistent `Row` connections | Positional on the fetched rows; returns a list of rebuilt `{'name', 'gamename'}` dicts (empty list on open/query failure or missing `vgmplay` swl) | `emulation.py` (`play_random_vgm_thread`, a background playback thread) |

**Decision (Q3): confirmed keep worker-owned.** It is called from a playback thread while
the main thread may hold writes on `self.gdb`; SQLite connections must not be shared
across threads without serialized access. Moving it onto the persistent connection would
be a concurrency behaviour change — out of scope, recorded as an explicit non-goal in
`roadmap.md`. It calls no repository and is untouched by step 4.2b.

---

## 12. Methods with no external callers — removed in step 4.2a (Q1)

Verification at `ea7d0f7`, re-run at `2a2b1af` immediately before the removal (replaces
the Phase 4.1 open question):

- `get_status_for_software`
- `write_options`
- `get_swl_id` (docstring "TODO: unused")
- `get_info_for_id` (docstring "TODO: unused")
- `get_sets_for_machine` (docstring "TODO: unused")

Evidence for removal:

- Repo-wide search (production code, add-ons, tests, Lua, XML): only the definitions in
  `database.py` plus one internal debug log line in `get_status_for_software`.
- None is exported through `umsa_core.__all__`.
- The only dynamic dispatch in the module (`getattr(db, scan_method)` inside
  `run_scan_with_progress`) ever receives the GUI's four scan names
  (`scan_dats`, `scan_exodos_to_db`, `scan_gb64_to_db`, `scan_artwork`) — never any of
  the five. No string-based or reflective references exist.
- No test constructs or calls them.

**Decision (Q1): remove uniformly in roadmap step 4.2a — executed** (91 lines deleted
from `database.py`, committed in `9f2fd40`; a repo-wide grep for the five names
afterwards returns zero matches anywhere). No replacement repository
methods were created to preserve unused functionality; a future use case must introduce an
explicitly designed API with a documented return type and tests. The `status.db`
`options` column, its schema definition and all reads of it (notably
`get_status_for_set`) are preserved unchanged.

---

## 13. Summary: what stays in DBMod and why

**Stays as facade (thin delegation, no SQL of its own):**
`create_dat_tables`, `create_art_tables`, all `scan_*` wrappers, `get_art_types`,
`get_artwork_for_set(s)`, `get_dat_for_set(s)`, `close_db`, the `get_by_*` wrappers
(now facades over `gamelist_filter` selector helpers since step 4.7),
`get_by_software`, `get_software_for_source`, `define_filter` (facade over
`gamelist_filter.define_filter` since 4.7), the twelve step-4.2 `GameRepository`
lookups, the seven step-4.3 reads (sections 7.2–7.4), and the two step-4.4
command-line input facades (`get_parts_for_set_id`, `get_disks`).

**Stays as lifecycle/orchestration:** `__init__`, `_open_persistent_databases`, `open_db`,
`close*`, `_run_scan_with_shared_state`, `execute_statement` (windowing/orchestration
facade over `gamelist_filter` since 4.7), `get_last_played`,
`get_all_for_software` (pure composition since step 4.3), `get_best_machine_for_set`,
`get_cmd_line_options` (reads via `GameRepository` since step 4.4; assembly in `DBMod`),
`create_cmdline` (pure), `make_time_nice`, `_art_source_roots`,
`_get_*_repository`, `get_latest_by_software` (cross-connection orchestration).

**Stays as documented mixed queries:** `get_random_id`, `get_random_art` (both now feed
the bound `_filter_where_params` into the filter subselect since step 4.7),
`get_artwork_by_software_id`, cross-database `open_db` (reattaches `art`/`dat` schemas
without copying data).

**Removed (step 4.2a, Q1):** `get_status_for_software`, `write_options`, `get_swl_id`,
`get_info_for_id`, `get_sets_for_machine` — no longer present in `database.py`.

**Removed (artwork/DAT source-of-truth refactor):** `add_dat_to_db`, `add_art_to_db` —
the cross-database copy operations are no longer needed. The persistent `umsa.db`
connection is now read-only and attaches `artwork.db` as `art` and `dat.db` as `dat`
schemas. All artwork/DAT reads use the attached schemas (`art.art_set`, `dat.dat`,
`dat.dat_set`). `ArtworkRepository` and `DatRepository` support schema qualification
via a `schema` parameter (`"main"` for scanner connections, `"art"`/`"dat"` for DBMod
reads).

**Extract candidates, in recommended order:** status.db play history (section 9 → step
4.5 — **done**, `StatusRepository`) → emulator config (section 10 → step 4.6 —
**done**, `EmulatorRepository`) → filter/query
composition (section 8 → step 4.7 — **done**, `gamelist_filter`). Row-leak closure (step
4.8) and
the non-DB reorganisation (step 4.9) follow. See `roadmap.md`. (Steps 4.3 — sections
7.2–7.4 plus the `get_all_for_software` direct reads — and 4.4 — the section 7.4
command-line input reads and `get_cmd_line_options`' four inline SELECTs — are
implemented; section 7 carries no direct SQL in `DBMod` any more; section 9 carries
none either since 4.5, section 10 none since 4.6, and section 8's filter/query SQL now
lives in `gamelist_filter` since 4.7 — only the
presentation/orchestration facades remain.)
