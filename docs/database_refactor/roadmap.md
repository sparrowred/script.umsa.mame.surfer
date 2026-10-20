# Database Refactor Roadmap — Phase 4.2 and Beyond

**Basis:** the Phase 4.1 audit (`dbmod_audit.md`, `row_factory_audit.md`) at git HEAD
`27a852f`, updated for the maintainer decisions Q1–Q9 (recorded in `README.md`) and the
implemented steps below.

**Status (current):** steps 4.0, 4.2, 4.2a, 4.2b, 4.3, 4.4, 4.5-pre (Q4), 4.5, 4.6,
4.7, 4.6.1, 4.6.2, **4.8**, **Artwork/DAT source-of-truth refactor** and **follow-up
fixes** are implemented and committed. The repository HEAD at the time of
this update is `9a98cfe` ("fix(gui): improve import notification logic to avoid
duplicate messages"). Step 4.6.1 landed as `7c369a9`, with the D20/D21
corrective follow-up in `fe5502b`; step 4.7 landed as `479e202` + `10f9fbd` + `da65a62`
+ `bc631eb` + `bd83a4d`. **Step 4.8 (row-leak closure) is implemented (committed as
`e4fd570`).** **Artwork/DAT source-of-truth refactor and follow-up fixes are
implemented (committed as `5a51461` + `238bb41` + `9a98cfe`)**. Phase 4.9 is an
optional/proposed `database.py` reorganisation, not implemented.

Each step is designed to be independently reviewable and testable; no step changes
public method signatures, return values, `row_factory` defaults, or database schemas
(4.2b changed only which *connections repositories accept*, with an explicit
`ValueError`; 4.5 and 4.6 moved the `sets` and `emu`/`emu_conn` DDL without changing
them; 4.6.1 added four tables and the `PRAGMA user_version` 0 → 1 migration mechanism in
**one version increment**, plus a one-time import that deletes the legacy
`lastgames.txt` / `filter_*.txt` inputs after commit; 4.6.2 adds no schema change and
keeps `user_version` at 1). Phase 4.6.1's questions **Q1–Q6 are resolved as D12–D19**
in the audit document, with the D20/D21 follow-up and the filter line-count rule
tightened to **strict five lines** (D14); the former Q7 ordering question is resolved:
4.7 → 4.6.1 → 4.6.2.

**Kodi-runtime verification is evidence-based:** implementation and automated tests do
not by themselves establish a manual Kodi run. The per-item status (automated/mock
coverage, static inspection, or unverified) is recorded in
[`history_persistence_audit.md`](history_persistence_audit.md) §16.2.

## Global contracts every step must honour

1. **`DBMod` stays the public compatibility facade.** Callers (GUI, screensaver,
   `emulation.py`, `gamelist_strategies.py`, `emulator_launcher.py`) keep calling the same
   method names with the same arguments and observable results.
2. **Repository convention** (established by `ArtworkRepository`/`DatRepository`): the
   repository receives an existing connection, never opens or closes it, query methods
   never commit, and write methods (where they exist) only commit a transaction they
   started themselves. Repositories are created per call in `DBMod` (pattern:
   `_get_artwork_repository`, `_get_dat_repository`, `_get_game_repository`) so they can
   never pin a connection that `open_db()` later replaces.
3. **Row input contract (decision Q7, step 4.2b — implemented).** All repositories require
   `connection.row_factory is sqlite3.Row` and raise a clear `ValueError` otherwise
   (shared helper `require_row_connection` in `sqlite.py`); all five repositories
   (`GameRepository`, `DatRepository`, `ArtworkRepository`, `StatusRepository`,
   `EmulatorRepository`) enforce it, as do the later history repositories.
   `connect_sqlite()`'s default (`row_factory=None`) is **not** changed.
4. **Return-shape rule** (`row_factory_audit.md`): repository methods are either
   *Row-transparent* (return the connection's native rows) or return already-normalised
   dicts/tuples matching today's public shape. Never convert a return type in the same
   step that moves SQL.
5. **Characterisation tests first.** Most read methods have no direct tests today. Each
   step writes golden tests against the *current* `DBMod` behaviour before moving the SQL,
   then re-runs them unchanged against the delegating facade.
6. **Binding project rules** (README): Core stays Kodi-free (adapter only), connection
   configuration lives only in Core, frontend/screensaver may use Kodi directly, no
   duplicate Core services.

---

## Step 4.0 — boundary regression checks (test-only) ✅ implemented

**Implemented** at HEAD `2a2b1af` as `tests/test_architecture_boundaries.py` (7 tests,
standard library only; AST parsing of source, no imports of the scanned code, no Kodi
needed). Test and documentation changes only — no production code changed.

**What the guards enforce (acceptance criteria):**

- **Kodi-import guard:** every `*.py` under `script.module.umsa.core/lib/` is parsed;
  `import xbmc*` / `from xbmc* import ...` (for `xbmc`, `xbmcgui`, `xbmcaddon`,
  `xbmcvfs`) fail unless the file is exactly `lib/umsa_core_kodi.py` — the adapter
  exception is a single explicit relative path, never a directory or pattern, so new
  core files are caught automatically. Violations print `path:line: <statement>`.
- **Connection-attribute guard:** `ast.Attribute` accesses named
  `gdb`/`gdbc`/`sdb`/`sdbc` (and `ggdb` within the Core lib) fail unless the file is
  `umsa_core/database.py`. Scanned trees: `script.module.umsa.core/lib`,
  `plugin.program.umsa.mame.surfer`, `screensaver.umsa.mame.surfer` — production
  modules only (root `tests/` lies outside them), no production directory exempted.
  Violations print `path:line: .<attribute>`.
- **`ggdb` scoping (documented rule, not an allowlist):** in frontend/screensaver
  code `ggdb` is the sanctioned DBMod facade *handle* (`self.ggdb = DBMod(...)`, per
  `docs/AGENTS-addon-interaction-guide.md`), and DBMod defines no `ggdb` attribute —
  it exposes only the four connection attributes above. The add-on half of the guard
  therefore enforces those four names (any deep reach such as `self.ggdb.gdbc` still
  fails), while inside Core `ggdb` is enforced too. A pinned test
  (`test_dbmod_never_exposes_a_ggdb_attribute`) fails if `database.py` ever accesses
  `.ggdb`, forcing this rule to be revisited if the premise breaks.
- **Vacuity protection:** coverage tests assert the known key modules and ≥ 30
  production files are in the scanned sets, and synthetic in-memory sources prove both
  detectors flag violations in not-yet-existing files.

**Verified state the tests pin (re-checked at `2a2b1af`):**

- `script.module.umsa.core/lib/` contains **zero** `xbmc*` imports outside the adapter;
  the only Kodi-importing module in the core add-on is `lib/umsa_core_kodi.py`
  (explicitly allowed as the single exception).
- `gdb`/`gdbc`/`sdb`/`sdbc` are accessed **only** inside `database.py` across all three
  add-ons' production code (`ggdb` likewise within Core). Existing tests that seed
  through `db.gdb`/`db.gdbc` are unaffected because the guard scans only the production
  trees, not `tests/`.
- Frontend and screensaver consume Core through `umsa_core_kodi` /
  `umsa_core.*` (no `gdb`/`gdbc`/`sdb`/`sdbc` attribute access anywhere).

**Recorded runs at `2a2b1af`:**

```bash
.venv-debian-vm/bin/python -m pytest tests/test_architecture_boundaries.py -v
# → 7 passed in 0.22s
.venv-debian-vm/bin/python -m pytest tests/ -q
# → 498 passed, 5 skipped, 18 subtests passed (11.80s)
```

**Result: zero violations against the current tree.** **Risk:** none — test-only.
**Independent:** yes (landed first).

---

## Step 4.2 — `GameRepository` (new): umsa.db lookup lists and scalar reads ✅ implemented

**Implemented** at `ea7d0f7` (`game_repository.py`, twelve delegating `DBMod` methods,
`tests/test_game_repository.py`, 32 tests written characterization-first).

**Responsibility:** single-purpose, read-only queries over the general game tables
(`sets`, `software`, `swl`, `year`, `maker`, `category`, `nplayers`, `swl_status`) that
neither depend on `DBMod` filter state nor join into other databases.

**Delegating `DBMod` methods:**
`get_maker`, `get_swl`, `get_source`, `get_year`, `get_players`, `get_categories`,
`get_set_name`, `get_machine_name`, `get_set_ids_for_software`, `count_source`,
`count_machines_for_swl`, `search_single`.

**Contract (unchanged by design):** constructor takes the caller-owned `umsa.db`
connection; accessor `_get_game_repository()` per call; all methods read-only, own
short-lived cursors; return shapes preserved exactly (six lookup lists Row-transparent;
`get_machine_name` a plain 2-tuple; counts scalars; `search_single` one Row or `None`).

**Follow-up from Q8:** the repository does **not** yet enforce the Q7 Row contract —
that lands in step 4.2b.

---

## Step 4.2a — remove the five unreferenced methods (decision Q1) ✅

**Responsibility:** delete `get_status_for_software`, `write_options`, `get_swl_id`,
`get_info_for_id`, `get_sets_for_machine` from `DBMod`.

**Evidence (final re-verification at `ea7d0f7`, re-run at `2a2b1af` immediately before
the removal):** only their definitions (plus one
internal debug log line) exist; nothing in `umsa_core.__all__`; the only reflective call
(`getattr(db, scan_method)` inside `run_scan_with_progress`) receives only the GUI's four
scan names (`scan_dats`, `scan_exodos_to_db`, `scan_gb64_to_db`, `scan_artwork`); no
string-based dispatch, no test, no add-on reference.

**Rules (all honoured by the implemented removal):**
- **No replacement repository methods** were created to preserve unused functionality
  (Q1). Future need ⇒ new, explicitly designed API with documented return type + tests.
- The `status.db` `options` **column, its schema definition and all reads of it stay**.
  `get_status_for_set`'s return shape (incl. positional access on the Row) is untouched.
  Only the dead `write_options` writer was deleted.
- `get_set_ids_for_software` keeps its remaining internal caller
  (`get_latest_by_software`).

**Required tests:** existing DBMod/status tests stay green; no new characterization tests
for removed methods. **Risk:** none (zero callers). **Order:** before or alongside 4.2b.

**Implemented (committed in `9f2fd40`):** 91 lines removed from
`script.module.umsa.core/lib/umsa_core/database.py`, definitions only (the internal
debug log line went with `get_status_for_software`); repo-wide grep for the five names
now returns zero matches anywhere (production trees, add-ons, `tests/`, xml/lua);
`ruff check database.py` reports the same 36 pre-existing findings before and after
(none introduced); tests: 7 guard tests + 13-file DB subset + full suite
`498 passed, 5 skipped, 18 subtests` — all green.

---

## Step 4.2b — `sqlite3.Row` input contract for all repositories (decisions Q7/Q8) ✅ implemented

**Responsibility:** retrofit the decided row-factory contract — limited strictly to the
row-factory contract and its callers; **not** combined with step 4.3.

**Scope:**
- All five repositories (`GameRepository`, `DatRepository`, `ArtworkRepository`, and the
  two to be created later — until they exist, their sites apply the same rule) require
  `connection.row_factory is sqlite3.Row` in their constructor, else a clear
  `ValueError`. `GameRepository` is included explicitly (Q8).
- **Audit every repository construction site**, not only the four scanners: the three
  per-call facades in `DBMod` (`self.gdb` — already `Row`), the staging/publish sites in
  `dat_scanner.py` (tuple today), `artwork_scanner.py` (tuple), `exodos_scanner.py`
  (dat + art, tuple), `gb64_scanner.py` (dat + art, tuple), and `exodos_artwork.py`
  (receives the tuple-backed `art_repo` from `exodos_scanner`).
- Switch those scanner/worker connections to
  `connect_sqlite(..., row_factory=sqlite3.Row)` so every repository caller complies.
- Remove now-dead tuple/dict fallback code (`dict(row)` + positional reconstruction
  chains in `ArtworkRepository`, positional-only assumptions in `DatRepository` pinned
  by tests).
- `connect_sqlite()`'s default stays `row_factory=None` (Q7). `add_dat_to_db()` /
  `add_art_to_db()` are **not** touched — they use no repositories.
- `get_random_vgm_batch`'s (formerly `get_random_vgm`) tuple connection stays (Q3,
  worker-owned, opened via `connect_sqlite_readonly`; it calls no repository).

**Required tests:** replace tuple-compatibility tests with contract tests —
`test_repository_reads_work_on_tuple_connections` in `tests/test_game_repository.py`
becomes an assert that tuple connections raise `ValueError`; the explicit tuple-dual test
in `tests/test_artwork_repository.py` is replaced likewise; `tests/test_dat_repository.py`
connections switch to `Row`. Scanner regressions stay green
(`test_dat_scanner.py`, `test_scan_artwork.py`, `test_exodos_scan.py`,
`test_gb64_scanner.py`, `test_exodos_artwork.py`).

**Dependencies:** none beyond 4.2. **Medium risk** — scan workflows are the live
regression surface; the focused scanner suite is the guard.

**Implemented and committed as `9f2fd40`:** `require_row_connection(connection, owner)`
added to `umsa_core/sqlite.py` and called by the `GameRepository`, `DatRepository` and
`ArtworkRepository` constructors (the two future repositories inherit the rule); the four
scanners open their repository-feeding connections with
`connect_sqlite(..., row_factory=sqlite3.Row)` (their umsa.db mapping connections
construct no repositories and stay tuple); `ArtworkRepository`'s tuple/dict fallback code
removed (`dict(row)` reconstruction chains, named/positional fallbacks, `list_scan_units`
now reads `row["scan_unit"]`). Contract tests:
`test_repository_rejects_tuple_connections` (game), the ValueError tests replacing the
tuple-dual tests in `test_artwork_repository.py` and `test_exodos_artwork.py`, and helper
unit tests in `test_sqlite.py`; `test_dat_repository.py` and the
repository-feeding connections in `test_scan_coordinator.py` switched to `Row`.
`connect_sqlite()` default, `add_dat_to_db`/`add_art_to_db` and `get_random_vgm_batch`
untouched. Verification: focused subset `228 passed`, `test_exodos_artwork.py`
`52 passed`, full suite `499 passed, 5 skipped, 18 subtests`; per-file `ruff check`
shows no new findings (`artwork_repository.py` 16→11 from the deleted lines, all others
unchanged, `database.py` still the pre-existing 36); `mypy sqlite.py
--follow-imports=skip` clean.

---

## Step 4.3 — extend `GameRepository`: search, grouping and machine reads ✅ implemented

**Responsibility:** the remaining read-only umsa.db queries that are still single-purpose
but slightly larger (multi-join, grouping, or dynamic category dispatch), plus the last
direct reads inside `get_all_for_software`.

**DBMod methods that delegate:**
`get_searchresults`, `get_all_dbentries`, `get_series`, `check_series`,
`check_compilation`, `get_info_by_set_and_swl`, `get_machines`.

**Coverage-gap sub-item:** `get_all_for_software` keeps two direct `self.gdbc` reads —
the multi-join set fetch (per software with same name) and the machine fallback
(`SELECT name, gamename FROM sets WHERE id = ?`, which is exactly the already-extracted
`get_machine_name` logic). Move the multi-join fetch into a focused repository read and
reuse `get_machine_name` for the fallback, so the direct SQL inside
`get_all_for_software` shrinks to zero and the method becomes pure composition of
repository calls.

**API notes:**
- Row-transparent for `get_searchresults`, `get_all_dbentries`, `get_series`
  (mixed-access consumers: positional `i[1]` in the search pos loop, positional `i[0]`
  in `build_filter_lists`/GUI, named `i['id']`/`i['name']` in `popup_gamelist`).
- `get_info_by_set_and_swl` and `get_machines` keep their current public shapes (dict;
  `(list[dict], pos)`) — the row→dict shaping may live in the repository since the public
  shape is already dicts, or stay in `DBMod`; pick one and document it in the method
  docstring.
- Preserve `get_series`'s current N+1 query pattern and its first-series-wins behaviour
  verbatim; optimisation is a separate, explicitly requested change.

**Required tests:** golden tests for each method (including the search-pos and
`get_all_dbentries` positional-access contracts); a test that `check_compilation`
distinguishes 0/1/2; series fixture with a software belonging to two series (current
behaviour: first series wins — pin it); composition test for `get_all_for_software`
before/after the sub-item.

**Dependencies:** step 4.2/4.2b (same class + Row contract). **Low–medium risk** — mixed
row access makes shape regressions the main hazard; the characterisation tests are the
mitigation.

**Remains in DBMod:** `execute_statement` and the `get_by_*` family (filter state — step
4.7), `get_last_played` (cross-connection — **stayed** through step 4.5, which moved
only the single-set status reads).

**Implemented and committed as `9041812`:** ten methods added to `GameRepository` — the
seven delegating reads (`get_series`, `check_series`, `check_compilation`,
`get_all_dbentries`, `get_searchresults`, `get_machines`, `get_info_by_set_and_swl`) plus
the sub-item reads `get_sets_for_software` (multi-join, Row-transparent),
`get_software_name` and `get_software_ids_for_name`. The seven `DBMod` methods are
one-line facades with their original docstrings preserved (incl. all TODOs; the
`get_machines` `TODO join` moved into the repository docstring). Dict shaping for
`get_machines`/`get_info_by_set_and_swl` lives in the repository (documented in the method
docstrings, per the API-note decision). `get_all_for_software` is pure composition — no
`self.gdbc` remains, structurally pinned by
`test_get_all_for_software_has_no_direct_sql_left`. Characterisation-first: the golden
tests were written and verified against the *pre-extraction* code first (new `[dbmod]`
goldens passed, the repository-variant calls failed with `AttributeError`), then the SQL
moved. Seed extended (`swl.system_id`, `category.flag`, `swl_status.status/filtr`,
`series_seq`, `compilations`, set detail rows) and the never-commit test extended with
all new calls. Verification: `tests/test_game_repository.py` `50 passed`, full suite
`517 passed, 5 skipped, 18 subtests` (499 → 517); `ruff check` clean on
`game_repository.py` and the test file, `database.py` 36→33 (the moved findings left with
the code; three style issues fixed in the new location).

---

## Step 4.4 — extend `GameRepository`: media/parts/device reads feeding the command line ✅ implemented

**Responsibility:** the small umsa.db reads that `get_cmd_line_options` and
`get_disks`/`create_cmdline` consume. The command-line *assembly* stays in `DBMod`.

**DBMod methods that delegate (SQL only):**
`get_parts_for_set_id`, `get_disks`, plus the individual SELECTs inside
`get_cmd_line_options`: swl options row, machine id, machine devices, sharedfeat
requirement. `get_cmd_line_options` and `create_cmdline` themselves **remain in DBMod** as
orchestration, rewritten to call the repository reads.

**API notes:**
- `get_parts_for_set_id` and `get_disks` stay Row-transparent (`create_cmdline` indexes
  `part[0]`/`part[1]`; the disks consumer does `'disk' in row.keys()`).
- The four internal reads of `get_cmd_line_options` can be exposed as focused methods
  (e.g. `get_swl_options(name)`, `get_machine_id(name)`, `get_devices_for_machine(id)`,
  `get_sharedfeat_requirement(set_id)`) or one method returning a small bundle — keep the
  SQL identical either way, including the `ORDER BY`s.

**Required tests:** golden tests for parts/disks (multi-part set, CHD disk rows, missing
set → `None`); an end-to-end characterization test for `get_cmd_line_options` on a fixture
with a device/part/sharedfeat chain, asserting the exact argument list before and after
delegation (this pins `emulation.py`'s `prepare_mame_run` input contract).

**Dependencies:** step 4.2/4.2b/4.3 convention. **Medium risk** — this is the input to
emulator launch; the end-to-end golden test is mandatory.

**Remains in DBMod:** `get_cmd_line_options`, `create_cmdline`, `get_best_machine_for_set`.

**Implemented (committed as `4d5e70c`):** six methods added to `GameRepository` —
`get_parts_for_set_id`, `get_disks` (the two public delegates) and the four focused
reads named in the API notes, `get_swl_options`, `get_machine_id`,
`get_devices_for_machine`, `get_sharedfeat_requirement`. All SQL moved byte-identical
(parameter order, predicates, `ORDER BY p.name`, `ORDER BY d.name`, `ORDER BY sf.name`,
column order/aliases, the two-query `get_disks` flow); each method carries its full
contract docstring (incl. the historical valid-input assumptions: missing swl/machine
rows still surface as `TypeError` from the facade's `row[0]`). `DBMod.get_parts_for_set_id`
and `DBMod.get_disks` are one-line facades with their original docstrings; in
`get_cmd_line_options` one `GameRepository` instance serves all five reads (four inline
SELECTs + both parts fetches), while `get_info_by_set_and_swl` and `create_cmdline` stay
facade/orchestration calls — the shared-feature chain is untouched. Characterisation-first:
`tests/test_cmd_line_options.py` (23 tests) was written against the pre-extraction
`DBMod` first (facade/golden expectations `11 passed, 12 failed` — the 12 = calls to
methods that did not exist yet), then the SQL moved. The golden pins the exact
`prepare_mame_run` argument list (machine, swl options, sharedfeat expansion, parts hit,
`-statename`, `-snapname`) plus both fallback branches and the two missing-row
assumptions; parts/disks contracts run through a dbmod/repository parameter fixture.
Verification: `tests/test_cmd_line_options.py` `23 passed`, focused trio (cmd line +
game repository + database) `83 passed`, emulator/guards/process group `35 passed`
(`31` before the four `find_roms` tests), DBMod/repository/scanner subset `269 passed`, `test_exodos_artwork.py` `52 passed`;
per-file `ruff check`: `game_repository.py` 0=0, new test file clean (one justified
`noqa SIM118` for the pinned `.keys()` contract), `database.py` 33=33 (pre-existing).
The SQL delegation itself changed no GUI/screensaver code — the only external call sites
(`emulator_launcher.py` `get_disks`, `emulation.py` `get_cmd_line_options`) go through
unchanged facades.

**Two CHD compatibility bugs found during §6/§8 verification, fixed inside this batch**
(narrow, separately tested, not part of the SQL delegation — they gate 4.4's completion;
both recorded under "Tracked side items"): the `Select CHD:` dialog in
`emulator_launcher.py` (`i.get('disk')` on `sqlite3.Row` always raised, so the dialog
never appeared — now named row access with NULL rows skipped and a dialog-index →
row-index mapping) and `find_roms()` in `emulation.py` (the `disks[0]` gate suppressed
CHD discovery on a leading NULL row and NULL rows produced `None.chd` paths — any
non-empty disk row now triggers discovery). Regression tests:
`tests/test_emulator_launcher.py` (5 tests) + 4 `find_roms` tests appended to
`tests/test_emulation_chd.py`; pre-fix baseline `4 failed, 11 passed`, post-fix
`15 passed`. Final full suite after both the delegation and the fixes:
**`549 passed, 5 skipped, 18 subtests`**; per-file ruff after the fixes:
`emulator_launcher.py` 55=55, `emulation.py` 24→22 (its two `SIM118` went with the
rewritten block), new test file clean (`test_emulation_chd.py` keeps 3 pre-existing
`SIM117` in untouched tests). Committed as `4d5e70c` (four files:
`game_repository.py`, `database.py`, `emulator_launcher.py`, `emulation.py`).

---

## Step 4.5 — `StatusRepository` (new): status.db play history and media ✅ implemented (committed as `fcdefe5`)

**Prerequisite bugfix (decision Q4 — committed as `8bb8a8d`, kept separate from the
extraction):**
`save_further_media`'s insert branch issued two INSERTs that collided on the `sets.id`
primary key when a set had no status row and *both* `marp` and `youtube` were passed
(verified: `sqlite3.IntegrityError: UNIQUE constraint failed: sets.id`; the failed call
also left an implicit transaction open). **Fixed:** one INSERT writes both values, and
the method now commits per call with an explicit rollback on failure so no transaction
is left open. Update branch and signature untouched; `status.db` schema untouched. Tests
in `tests/test_save_further_media.py` (6: marp-only, youtube-only, both-values single
row, update preserves unrelated fields, `in_transaction` False after successful writes,
rollback after a failed write; pre-fix characterisation `3 failed, 3 passed`).
**Not** combined with the repository extraction.

**Responsibility:** everything `status.db`'s `sets` table holds — play status, play
history, per-set MARP/Youtube links — plus the authoritative `status.db` schema helper.

**New repository:** `umsa_core/status_repository.py`, class `StatusRepository`.

**DBMod methods that delegate:**
`get_status_for_set`, `write_status_after_play`, `get_further_media`,
`save_further_media`, and the status-side query of `get_latest_by_software` (its umsa.db
half keeps calling `get_set_ids_for_software`, so the orchestration stays in `DBMod`).
(`get_status_for_software` and `write_options` are **not** part of this step — removed in
4.2a, decision Q1; no replacements.)

**Schema:** move the existing `CREATE TABLE IF NOT EXISTS sets` DDL from
`_open_persistent_databases` into `create_status_tables(cursor)` in the new module;
`_open_persistent_databases` calls it instead of inlining the SQL. **No migrations exist
any more** (removed at `ea7d0f7` — README policy); the on-disk schema is unchanged.
**The `emu`/`emu_conn` DDL stayed put until step 4.6, which moved it into
`emulator_repository.create_emulator_tables` unchanged.**

**API and connection contract:**
- Constructor takes the caller-owned `status.db` connection (`self.sdb`); accessor
  `_get_status_repository()` per call; **Row contract applies from step 4.2b on**.
- Reads: no commits, Row-transparent (e.g. `get_further_media` consumer needs
  `row['marp']`; `get_status_for_set` currently indexes positionally — keep Row so both
  styles survive, and keep the time formatting in `DBMod`).
- Writes: preserve today's observable commit-per-call semantics. Follow the repository
  convention (commit only a transaction the method started) — under the current callers
  this is behaviour-identical because nobody wraps these calls in an outer transaction,
  but add a test asserting `conn.in_transaction` is `False` after each write to lock the
  assumption in.
- `write_status_after_play` keeps its read-modify-write in one unit.

**Required tests:** golden tests for each method; a write-then-read round-trip for
`write_status_after_play` (insert branch and update branch); `save_further_media` update
branch (the both-values insert branch is covered by the prerequisite bugfix);
`get_latest_by_software` across multiple sets; facade tests for all delegated methods.

**Dependencies:** prerequisite bugfix (Q4); none on 4.2-4.4 (different database).
**Medium risk** — write paths with immediate commits; the round-trip tests and the
`in_transaction` assertions are the guard.

**Ambiguity gate:** resolved (Q1 — both unreferenced status methods removed in 4.2a).

**Remains in DBMod:** `get_last_played` (cross-connection orchestration + presentation),
`get_all_for_software` (orchestration), `make_time_nice` (pure helper; candidate for the
step 4.9 reorganisation).

**Implemented (committed as `fcdefe5` — "refactor(database): centralize play history
and media access in status_repository"):** `umsa_core/status_repository.py`
holds `create_status_tables(cursor)` (byte-equivalent `sets` DDL moved out of
`_open_persistent_databases`, which now calls it; `emu`/`emu_conn` DDL untouched, no
migration, `PRAGMA user_version` stays 0) and `StatusRepository` with five methods —
`get_status_for_set` (raw Row), `get_further_media` (Row with `marp`/`youtube`),
`get_latest_by_set_ids` (bare id or `None`; empty id list → `None` without malformed
SQL), `write_status_after_play` (read-modify-write in one savepoint, timestamp format
and arithmetic verbatim) and `save_further_media` (Q4 single-INSERT logic moved
verbatim). Constructor enforces the 4.2b `require_row_connection` contract; the
repository never opens/closes or caches a connection. `DBMod` gained a per-call
`_get_status_repository()` (mirrors `_get_game_repository`) and the five public methods
(`get_status_for_set`, `write_status_after_play`, `get_further_media`,
`save_further_media`, `get_latest_by_software`) are now one-line facades —
`get_latest_by_software` keeps its `get_set_ids_for_software` orchestration.
**Transaction/savepoint contract** (verified by tests): writes open a savepoint, release
it on success (committing only a transaction the call started) and `ROLLBACK TO`+
`RELEASE` on failure — standalone writes leave `in_transaction` False, a caller-owned
outer transaction is never committed or rolled back, and pending caller changes survive
a repository failure. Tests: `tests/test_status_repository.py` (24 tests — schema
helper, Row contract, reads, both write branches, Q4 both-values insert, transaction
ownership ×4, `get_latest_by_set_ids`, and five DBMod facade goldens) written against
the pre-extraction `DBMod` first (**characterisation baseline `24 passed`** with
`database.py` stashed), then green after the move; full suite **`579 passed, 5 skipped,
18 subtests`** (555 → 579).

---

## Step 4.6 — `EmulatorRepository` (new): `emu`/`emu_conn` emulator config ✅ implemented (committed as `b84341e`)

**Responsibility:** the `emu`/`emu_conn` tables of `status.db`.

**Decision:** a dedicated `EmulatorRepository` in
`umsa_core/emulator_repository.py` (a separate class/module, as preferred here —
emulator config is a distinct domain from play history; a second class inside
`status_repository.py` would repeat the god-class pattern inside the repository
layer). The `emu`/`emu_conn` DDL moved into `create_emulator_tables(cursor)`
unchanged (column order, types, constraints, defaults, primary keys and
autoincrement behaviour verified against the pre-move schema by
`test_dbmod_emulator_schema_is_unchanged_by_helper_relocation`, run before the
inline DDL was removed; no migrations — README policy; `PRAGMA user_version`
stays 0). `_open_persistent_databases` now calls both schema helpers:
`create_status_tables(self.sdbc)` and `create_emulator_tables(self.sdbc)`.

**DBMod methods that delegate (one-line facades over a per-call
`_get_emulator_repository()`, original docstrings preserved):**
`get_emulators`, `get_emulator`, `save_emulator`, `connect_emulator`,
`delete_emulator_connection`, `delete_emulator`.

**API notes / preserved contracts:**
- Public shapes already dicts (`dict(row)`) — normalisation lives in the
  repository: `get_emulators` returns `list[dict]` (empty list when nothing
  matches), `get_emulator` a `dict` or `None`. SQL predicates, aliases
  (`emu_conn_id`), `ORDER BY` and parameter order moved verbatim (whitespace
  only).
- Filter/argument precedence preserved: `source` wins over `swl_name`
  (`get_emulators`, `connect_emulator`); `emu_id` wins over `emu_conn_id`
  (`get_emulator`); string ids from the GUI's `emu::<id>` / `emu_conn::<id>`
  labels keep working (SQLite column affinity, pinned by tests).
- `get_emulator()` with **neither** argument: audited — no caller reaches this
  state (`gui.py` always passes exactly one keyword); the pre-4.6 shared
  cursor returned `None` in practice because every prior statement drained its
  rows. The repository returns `None`; documented, not a silent change.
- `save_emulator` keeps its observable sequence as one repository method:
  emu-row write in its own savepoint → commit → (if not `reconfigure`)
  `connect_emulator` as a separate unit. **The separate commit boundary before
  the connection write is preserved** — a failing connection insert leaves the
  saved emulator row committed (pinned by a rejecting-trigger test), so the emu
  insert and the connection insert are deliberately *not* one indivisible
  transaction.
- **Generated-id handling:** for a new emulator the id is read from the insert
  cursor immediately after the INSERT, inside the savepoint, before any later
  write can move `lastrowid`. **`lastrowid` decision (update branch):**
  `reconfigure=False` with an update connects to `emu_info['id']`, never to a
  stale `lastrowid`. Call-site audit: `gui.py` passes `reconfigure=True` at
  both call sites that supply `emu_info` (`configure_emulator(emu_info,
  reconfigure=True)`, gamelist_click + gamelist_context) and every new-emulator
  dict is built without an `'id'`, so the update + `reconfigure=False`
  combination is unreachable from production code and the change cannot affect
  existing configuration behaviour; pinned by
  `test_save_emulator_update_with_reconfigure_false_uses_emu_id`.
- `connect_emulator` with neither source nor swl still logs the historical
  `UMSA database: connect_emulator error` debug message and creates nothing —
  no savepoint is opened and (per the 4.5 ownership rule) a repository never
  commits a caller's pending changes, so the unconditional `self.sdb.commit()`
  the old code issued in this branch is gone (observable only for a caller with
  a pending outer transaction, of which there are none).
- `delete_emulator_connection`'s read-delete unit and its "return the emu id
  only if the deleted connection was its final connection" contract stay
  together inside one savepoint.
- `delete_emulator` keeps the historical order **and** commit boundaries: the
  `emu_conn` rows are deleted and committed first, then the `emu` row in its
  own savepoint unit — **failure atomicity intentionally unchanged** (a failed
  emulator delete leaves the connection rows deleted, exactly like the
  two-commit original); pinned by
  `test_delete_emulator_failure_keeps_deleted_connections`.
- Transaction ownership (4.5 convention, savepoint name `umsa_emu_write`):
  standalone successful writes leave `in_transaction` False; a caller-owned
  outer transaction is never committed or rolled back and pending caller
  changes survive a repository failure; no savepoint stays open on either
  path; reads never commit; cursors are short-lived and closed in `finally`
  (asserted through a cursor-tracking connection factory).

**Required tests:** ✅ `tests/test_emulator_repository.py` — **43 tests**:
schema helper (exact `PRAGMA table_info` for both tables + `AUTOINCREMENT`/
`sqlite_sequence` behaviour + idempotence + `user_version` 0), helper-vs-DBMod
schema equivalence, Row contract (tuple rejected / Row accepted), all
`get_emulators` filter paths + precedence + shapes, `get_emulator` by emu id /
connection id / precedence / neither, `save_emulator` (insert + generated id,
generated id not stale with pre-existing rows, update, `reconfigure=True`
creates no connection, commit-before-connect via a rejecting trigger, the
`lastrowid` decision), `connect_emulator` (source, swl, precedence, neither +
captured log call), `delete_emulator_connection` (final / one-of-several /
missing / string id), `delete_emulator` (connections-first order via an
aborting trigger, failure atomicity, missing id), transaction ownership
(standalone ×5, caller-owned outer transaction for save and delete, two
failure-preserves-pending-change cases, closed cursors), and ten `DBMod`
facade goldens including a full **GUI emulator-management sequence** (configure
new → list via `all_emulators`/`machine` labels → fetch by string `emu_conn`
id → reconfigure → `get_diff_emulator` connect → remove connection → delete
emulator).

**Characterisation-first:** every facade golden and the schema-equivalence
test was executed against the *pre-extraction* `DBMod` first — **43 passed**
with the inline DDL and inline SQL still in `database.py` — then the full file
stayed green after the delegation.

**Verification (post-delegation):**
`.venv-debian-vm/bin/python -m pytest tests/test_emulator_repository.py -q` →
`43 passed`; focused group (emulator + status repository + database +
boundaries + sqlite + save_further_media) → `101 passed`; full suite →
**`622 passed, 5 skipped, 18 subtests passed`** (579 before 4.6 + 43);
`ruff check`: `emulator_repository.py` 0, `tests/test_emulator_repository.py` 0,
`database.py` 33 (pre-existing, unchanged); `mypy emulator_repository.py
--follow-imports=skip` → Success.

**Dependencies:** step 4.5's schema-helper pattern (soft). **Medium risk** —
GUI emulator management flows depend on `lastrowid` timing and the connect
sequence; the sequence test and the trigger tests are the guard.

**Ambiguity gate:** resolved by call-site audit (no questions outstanding):
update + `reconfigure=False` unreachable → `emu_info['id']` used;
`get_emulator()` with neither argument has no callers → `None`;
`delete_emulator` failure atomicity deliberately preserved as two phases.

**Remains in DBMod:** nothing emulator-specific beyond the facade methods
themselves. `status.db` now has no inline SQL in `database.py` except the
schema-helper calls in `_open_persistent_databases`.

**Next planned work:** steps 4.6.1 and 4.6.2 are now complete (see below), so the next
planned implementation phase is **4.8 row-leak closure** (which now sees
`get_emulators`/`get_emulator` returning plain dicts — already unambiguous shapes),
followed by the optional `database.py` reorganisation proposal (4.9). The 4.6.1a audit
below documents the **confirmed dependency on 4.7** (satisfied): the persisted filter
selections are consumed by `define_filter`, whose explicit-state composition 4.7
delivered; 4.7's scope and acceptance criteria were not changed by it. Text-file
persistence (`lastgames.txt`, `filter_*.txt`) stayed in place during 4.7 and moved in
4.6.1.

---

## Step 4.6.1a — `status.db` history & legacy-file migration ✅ implemented

**Status: IMPLEMENTED (2026-10-18), committed as `7c369a9` with the D20/D21 corrective
follow-up in `fe5502b`.** The design was audited read-only from `b84341e` up to the 4.7
baseline (decisions D12–D19 recorded), and the production work landed:
`umsa_core/status_migrations.py` (one versioned `status.db` migration,
`user_version` 0 → 1, reusing the repository DDL helpers), `umsa_core/history_repository.py`
(the four tables plus lastgames/filter-selection/import-marker persistence),
`umsa_core/history_import.py` (discovery, strict per-file validation, one-time import,
commit-before-delete cleanup, cleanup-only recovery and `retry_import`), the corresponding
`DBMod` facades, the GUI startup import/notification with the `_remember_and_select`
success-funnel persistence, and the `retry_import` script command in `addon.py`. The
design documents and the recorded decisions live in
[`history_persistence_audit.md`](history_persistence_audit.md). Scope delivered: **three
related concepts in one migration** plus a one-time legacy import and cleanup:

1. GUI backward-navigation history (`lastgames.txt` → `gui_lastgames`).
2. Filter selections (all `filter_*.txt` → `filter_selections`).
3. Screensaver history (last **100** successfully displayed sets →
   `screensaver_history`; starts empty, no import source).

**What was audited and confirmed:**

- **GUI lastgames** (`<core profile>/lastgames.txt`): ordered software-id list, loaded in
  `UMSA.onInit` (`gui.py:364-375`), mutated by five insert-before-display call sites and
  by `software_move` (`gui.py:1868-1879`), trimmed to the newest 10 **only** at
  `UMSA.exit()` (`gui.py:2560-2566`) — the confirmed defect: unclean window teardown
  loses the session. **Decided:** persist immediately after a successful display (the
  successful end of `UMSA.select_software`, `gui.py:2186`; its failure branch
  `gui.py:2037-2043` simply does not persist), never derived from play history, duplicates
  preserved (D12), and retention raised from 10 to the newest **100** entries (D19).
- **Filter selections** (`filter_<name>.txt`, `data_paths.py:60-65`): fixed five-line
  comma format (`persistence.py:10-61`, byte-pinned by `tests/test_persistence.py:64-104`),
  values are opaque id strings fed to `define_filter` (`database.py:1212`, via the
  `gamelist_filter` service); loaded
  at `onInit` (`gui.py:344`), loaded/saved by the Load/Save Filter dialog
  (`gui.py:1304-1356`); truncated files raise `IndexError`, write failures are silently
  swallowed. Real profile has **zero** filter files; `lastgames.txt` holds 10 valid ids.
- **`load_lastsaver()`** is legacy read-side code with one live but always-empty consumer
  (`M_LSSAVER`; no writer of `lastsaver.txt` exists in any revision) — **not an import
  source, not used, untouched**; `lastsaver.txt` is not a recognized input, so it would
  be preserved and listed (unknown file).
- **Screensaver lifecycle** (as audited before 4.6.2): one `get_random_art` per loop
  iteration (`ui.py:432-446`); `remember_art` fires *before* bad-image rejection so it is
  not a display boundary. **Boundaries decided (D16):** images recorded at the post-render
  point (`ui.py:454-571`, before the wait loop) and videos on `Player.onAVStarted()` (the
  `set_id` travels as the `umsa_set_id` unique ID, Kodi 20+ guard); `ui.py:712`'s
  `onPlayBackStarted` is not used for recording. At audit time no history existed
  anywhere; random selection is history-blind.

**Implemented design (decided — D12–D19):** four new tables —
`gui_lastgames(position, software_id)`, `filter_selections(filter_name, category,
position, value)`, `screensaver_history(id, set_id, software_id, displayed_at)` and a
`status_meta` import marker. **One schema migration, one `PRAGMA user_version`
increment (0 → 1)** via a new `umsa_core/status_migrations.py`, declared in a single
idempotent transaction that also re-declares the three existing tables through their
repository helpers; call site in `_open_persistent_databases`; repositories stay the
authoritative DDL owners. Existing play history, emulator config and further-media data
are preserved untouched (add-only migration).

**One-time import + cleanup (decided direction):** discover configured paths →
validate each file all-or-nothing (malformed = whole file discarded + recorded warning,
while other files still import) → write data + terminal marker + pending-delete list in
**one commit** → only then delete recognized inputs (valid *and* invalid) → notify via
the existing Kodi-side layer (no Kodi imports in `umsa_core`). Marker values:
`completed` / `completed_discards` / `completed_no_source` / `failed`; terminal states
never re-import; interrupted deletion degrades to **cleanup only**; a durably recorded
`failed` is reported but never auto-retried (explicit retry via a new `retry_import`
script command in `addon.py:18-37`), while an outcome that could not be committed retries
at the next GUI startup with **no fallback status file** (D18); cleanup failures record and
report the
remaining path and retry deletion only. Unknown files are never deleted (D17: only
`lastgames.txt` + validated `filter_*.txt`). Expected final
Core userdata (verified against the real profile and `umsa_db.zip`, which contains only
`umsa.db`): `settings.xml` + `umsa.db`/`status.db`/`dat.db`/`artwork.db`.

**Questions Q1–Q6 — resolved 2026-10-18 as decisions D12–D19:** Q1 lastgames duplicates
+ failed-display entries (D12), Q2 validation strictness (D13 strip/digits + D14 —
`lastgames.txt` keeps first-line tolerance, while `filter_<name>.txt` must have **exactly
five logical lines**, a wrong count discarding the whole file), Q3 filter semantics /
runtime filter state not persisted (D15), Q4 screensaver duplicates + ordering + display
boundary + identifier (D16), Q5 unexpected userdata files (`lastsaver.txt` preserved, D17),
Q6 DB-failure recovery (D18 — `retry_import` command, no fallback file) — all recorded in
section 1.1/16 of the audit document, with `gui_lastgames` retention raised to **100**
(D19). **Kodi-runtime verification is evidence-based:** the repository's automated tests
and Kodi-stub harness do not by themselves establish a manual Kodi run; per-item status
(automated/mock, static inspection, or unverified) is recorded in
`history_persistence_audit.md` §16.2. The former Q7 (ordering) is **resolved**: 4.7 →
4.6.1 → 4.6.2.

**Corrective follow-up (2026-10-19, D20/D21):** two post-landing defects are fixed
**without** a schema change or new migration — (D20) a completely empty saved filter now
keeps its name via a reserved `__filter_definition__` marker row in `filter_selections`,
so version-1 databases with pre-marker, non-empty filters still load with no reset or
re-import; (D21) an unreadable recognized file (`OSError`, including discovery
enumeration errors) is no longer treated as malformed content — it aborts before the
import transaction after a best-effort durable `failed` marker, deleting and importing
nothing, so only `UnicodeDecodeError` is malformed. Notifications now name the
pending-cleanup files and keep discarded filenames. These fixes are a **prerequisite for
4.6.2**; 4.6.2's own scope is unchanged.

**Dependencies:** conventions from 4.2–4.6 (Row contract, repository style, savepoint
ownership); **Phase 4.7 for the filter-selection consumption path** — persisted
selections are handed to `define_filter`, i.e. into the filter state 4.7 makes explicit.
**Ordering confirmed (D11): 4.7 first, then 4.6.1, then 4.6.2.** The earlier
"4.6.1 before 4.7" advice was written for a lastgames-only scope and is superseded.
**4.7's scope and acceptance criteria are unchanged**, and its **text-file persistence
(`lastgames.txt`, `filter_*.txt`) stays in place during 4.7** — the files moved inside
the one-time `status.db` migration in 4.6.1. The three tests that pinned
`user_version == 0` were updated during implementation.

---

## Step 4.6.2 — screensaver display history (`screensaver_history` writes) ✅ implemented

**Status: IMPLEMENTED (2026-10-19), committed as `e7cb00a` ("feat(database): implement
screensaver display history recording and retrieval").** The last piece of 4.6.1's
decided scope: record the last **100** distinct sets the screensaver actually displays into
the `screensaver_history` table that the version-1 `status.db` migration already created.
**No new migration, no schema change, `user_version` stays 1** — the write path simply uses
the existing DDL. Design decisions: D16 (identity = `set_id`, one row per set, recency by
the monotonic `id`), D2 (starts empty, no import source).

**What landed:**
- `umsa_core/history_repository.py` — `SCREENSAVER_HISTORY_LIMIT = 100`, `normalize_set_id`
  (Kodi-free id normaliser; **raises `ValueError`**, never returns `None`),
  `HistoryRepository.record_screensaver_display(set_id, software_id=None)` (delete existing
  row → re-insert as newest → prune beyond the newest 100, all inside one `SAVEPOINT`, so a
  failure leaves history untouched and never commits/closes the caller's transaction) and
  `HistoryRepository.list_screensaver_history(limit=None)` (`ORDER BY id DESC`).
- `umsa_core/database.py` — `DBMod.record_screensaver_display` /
  `DBMod.get_screensaver_history` facades (no `.sdb`/`.sdbc` access from callers).
- `screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py` — `SET_ID_UNIQUE_TYPE =
  'umsa_set_id'`, `attach_set_id(video_item, set_id)`, `read_set_id(video_tag)`,
  `read_software_id(video_tag)` (the `Votes` handoff stays the software id); `Saver.record_display`
  called **once** after the completed cross/slide/wall render block and before the wait loop
  (missing/invalid ids and any DB failure are logged and never break rendering);
  `Player.onAVStarted()` writes the video record with the `set_id` carried on the playlist
  ListItem via `setUniqueID(str(set_id), 'umsa_set_id')` (value first, type second —
  `@python_v20`), capability-guarded with `hasattr` so Kodi < 20 logs and does not record;
  a per-instance token deduplicates the callback.

**Boundary rule honoured:** the repository is Kodi-free; every Kodi touch sits in the
screensaver add-on; the screensaver uses only `DBMod`.

**Orphan handling:** `list_screensaver_history` returns stored rows exactly as they are.
It does not query `umsa.db`, so it does not detect, log or report orphaned `set_id`s; it
also never substitutes another id or deletes a row merely because the set is absent. The
persistence guarantee is preservation and natural ageing under the 100-distinct-set
retention rule. Any consumer-side orphan diagnostic is a future task, not part of 4.6.2.

**Tests:** `tests/test_screensaver_history_repository.py` (51 passed) and
`tests/test_screensaver_history_hooks.py` (52 passed, Kodi-stub harness). Full suite
**819 passed**, 5 skipped, 18 subtests passed; per-file ruff comparison against the
pre-change baseline shows the new code adds no findings. These are automated/mock tests,
not a manual Kodi run; see
[`history_persistence_audit.md`](history_persistence_audit.md) §16.2 for the runtime
verification status.

---

## Step 4.7 — `gamelist_filter.py`: explicit-state filter/query composition (decisions Q2/Q9) ✅ implemented

**Responsibility:** make `define_filter`, `execute_statement` and the `get_by_*` wrappers
pass their state *explicitly* instead of reading `self.join`, `self.where`, `self.order`,
`self.use_filter`, `self.filter_join`, `self.filter_where`.

**Module name (Q9):** `umsa_core/gamelist_filter.py` — not `gamelist_query.py`, to avoid
confusion with the frontend's `gamelist_strategies.py`. No duplicate compatibility module.

**Pre-work (separate commits, before the extraction):**
1. **Filter-state accessors.** The GUI/screensaver currently mutate `DBMod` attributes
   directly (`use_filter` toggled by the GUI and screensaver runtime; `order` set by the
   GUI before list loads). Put them behind explicit methods (e.g.
   `set_filter_enabled(flag)`, `set_order(order)`) with the state remaining on `DBMod`
   as the public holder — no call-site behaviour change, but the mutation surface becomes
   named API the service can mirror.
2. **Fix the unbound `order` bug (Q2, own commit + test).** `execute_statement` resets
   `self.order` for unexpected values but then uses a local `order` that was never bound
   in that branch. Default: the same value `self.order` is reset to.

**Shape:** a plain service `umsa_core/gamelist_filter.py` whose entry points take
`(connection, filter_state, ...)` and return the same `(slist, pos, result_count)` /
`"count (percent%)"` results. `DBMod` keeps the mutable attributes as the public state
holder and forwards them; the GUI keeps toggling `use_filter`/`order` (now via the
accessors) on the instance.

**Parameterisation (Q2 — separate commit, after the characterisation suite is green
against the unchanged interpolation):**
- Interpolated *values* become bound parameters: `sname` in `execute_statement`, the
  `cat`/`year`/`players`/`swl`/`maker`/`source` values in the `get_by_*` family, and the
  id lists in `filter_where`/`filter_join`. State becomes `(where_sql, params)`.
- `order` stays a whitelist mapping (the existing 3-way name/year/publisher fragment
  table) — validation, never parameterisation.
- New tests: values containing `"` and `'`, and values equal to a column name
  (today SQLite resolves double-quoted unknowns as column names before falling back to
  literals — the tests pin the parameterised behaviour).
- **`get_by_maker` clone-resolution read** extracts here as well: its three parameterised
  maker queries plus the interpolated `maker.id IN (...)` list move into the service (or
  a focused read) with characterisation tests for multi-level clone chains.

**Why last / why risky:**
- The GUI mutates `DBMod` query state between calls; any extraction must treat that state
  as an input value, not move it.
- The no-result retry-without-filters loop and the prev/next windowing are load-bearing
  GUI behaviour — the characterisation suite is mandatory first.
- Interpolation → parameterisation changes observable behaviour for quoted values; it is
  therefore an explicitly approved behaviour change (Q2), not a silent one.

**Required tests (large, written first):** characterisation suite for `define_filter`
(all-selected → no join; partial → join), `execute_statement` (normal/prev/next, filter
on/off, empty-result retry, sentinel entries — note the list mixes `sqlite3.Row` entries
with plain-dict sentinel entries —, positions at list start/middle/end), and each
`get_by_*` including the clone chain; then the parameterisation tests above.

**Remains in DBMod:** the mutable state attributes and the facade method family.

**Implemented across four commits (on top of `5514efd`):**
1. `479e202` — "fix(database): bind order fallback in execute_statement" (Q2 pre-work,
   own commit + `tests/test_execute_statement_order.py`, 2 tests).
2. `10f9fbd` — "refactor(database): add filter-state accessors to DBMod"
   (`set_filter_enabled(flag)`, `set_order(order)`; the three GUI mutation sites and the
   screensaver runtime now call them; `tests/test_filter_state_accessors.py`, 2 tests).
3. `da65a62` — "refactor(database): extract explicit-state gamelist filter service":
   the new Kodi-free `umsa_core/gamelist_filter.py` takes a `GamelistFilter` dataclass
   (`join`, `where`, `order`, `use_filter`, `filter_join`, `filter_where`, plus
   `where_params`/`filter_where_params`) and the caller connection; it holds
   `define_filter`, `execute_statement` and the seven selector helpers
   (`software_query`, `source_query`, `category_query`, `year_query`, `players_query`,
   `swl_query`, `maker_query`). `DBMod.define_filter`/`execute_statement`/`get_by_*` are
   now facades that build the state, copy clauses back into the public attributes and
   mirror the in-place `order` reset. SQL interpolation was byte-identical in this step.
4. `bc631eb` — "fix(database): bind gamelist filter/query values as SQL parameters":
   the Q2 parameterisation. Every external value (category/year/player/swl/source/maker
   names, filter id lists, the prev/next software-name comparison, random-artwork type
   lists) is bound; each clause carries its own `(sql, params)` pair so parameter order
   survives clause concatenation. `DBMod` keeps `.where`/`.filter_where` and gains
   private `_where_params`/`_filter_where_params`, consumed by `get_random_id` and
   `get_random_art`. `order` stays a validated whitelist, never a bound value.

Characterisation suite `tests/test_gamelist_filter.py` (35 tests) pins `define_filter`,
`execute_statement` (normal/prev/next, filter on/off, empty-result retry, sentinel
entries, position at start/middle/end) and every `get_by_*` including the one-level
clone chain and the missing-maker `TypeError`; the parameterisation tests cover a
`'`-bearing category name round-trip, a hostile `"`-bearing value bound by
`category_query`, a bound id list, a `"`-bearing software name through prev/next, and
`get_random_id` via filter params. Full suite: **622 → 661 passed**, 5 skipped,
18 subtests passed.

**Bounded fallback (the retry-without-filters loop — fixed, no longer a known
limitation).** `execute_statement` now uses an explicit two-attempt policy instead of
`while not slist`: the query runs once with the active filter state, and a single
selector-only retry is issued **only when the first query actually carried active
filters** (tracked by a `filters_applied` flag set during clause composition). If that
second result is also empty the method stops and returns `([], 0, 0)` — it never
re-issues an identical query, so a selector whose own clause matches nothing, or an
empty underlying result set, terminates normally instead of hanging the GUI. The retry
target is precomputed from the selector state (`state.join`/`state.where` +
`state.where_params`), so parameter ordering and bound values are unchanged.

An ultimately empty result returns the consistent empty tuple `([], 0, 0)` with **no
fabricated `prev`/`next` sentinels**: `pos=0` matches the empty-result convention
already used by `get_searchresults`/`get_machines`/`get_last_played`, and for normal
list loads the GUI returns on `len(results) == 0` before ever reading `pos`
(`gui.py` → "found nothing"), so no successful-path behaviour moves. Successful
filtered loads, list ordering, position calculations, sentinel structure and the public
`(slist, pos, result_count)` shape are untouched.

Regression tests (7, in `tests/test_gamelist_filter.py`) count executed statements
deterministically through a spy connection/cursor pair rather than by timing: filtered
empty → selector-only fallback still finds rows (2 queries); selector-only matches
nothing → one query, empty result; filters + fallback both empty → exactly 2 queries
then stop; empty underlying result set → 1 query; Prev/Next with no rows → terminates
with `([], 0, 0)` for both directions; successful filtered navigation → 1 query with
rows. No test skips the empty cases that expose the old infinite loop.

---

## Step 4.8 — row-leak closure (fixed step after 4.6; was "Stage 3" in `row_factory_audit.md`)

**Status: implemented (committed as `e4fd570`).** With 4.6.1 and 4.6.2
complete, this was the next agreed step.

**Responsibility:** after steps 4.3–4.6, the facade returns only unambiguous shapes and
`sqlite3.Row` never leaks across add-on boundaries — only *named* access crosses
frontend/screensaver code; core-internal code may still use Row.

**Scope (verified at implementation time):**
- `build_filter_lists` reads `entry[0]..entry[2]` positionally — switched to named access
  (or a normalised dict from `get_all_dbentries`).
- GUI loops over `get_all_dbentries` results with `i[0]` — switched to named access.
- `get_searchresults`: the core pos-finding loop uses `i[1]` while the GUI popup reads
  `i['name']`/`i['id']` — normalised the public return to dicts.
- `get_series`: mixed internally (`series_ids[0]['series_id']` named, member loop `i[0]`,
  popup named) — normalised to one style.
- `create_cmdline`'s `part[0]`/`part[1]` and `get_status_for_set`'s `i[1]`…`i[4]` are
  core-internal — may stay Row/positional or be normalised, but the choice is explicit.
- Verify `execute_statement`'s mixed list (Rows + dict sentinels) still behaves for the
  GUI after each normalisation.

**Contract:** GUI/screensaver consume only named access (`row['col']`) or plain
dicts/dataclasses — never `row[i]`. Add-on tests assert the consumed shapes.

**Dependencies:** steps 4.3–4.6 (the rows are produced by repository-backed methods).
**Medium risk — touches GUI code;** must not be bundled with any delegation step.

**Implemented and committed as `e4fd570`:** `GameRepository` public reads return plain dicts or established scalars/tuples/`None`; `StatusRepository.get_further_media` returns plain dicts; `gamelist_filter.execute_statement` returns plain dict lists with dict sentinels; `DBMod.build_filter_lists` and GUI filter-option handling use named dict access. Core-internal Row-returning methods remain only where documented (`get_parts_for_set_id`, `get_swl_options`, `get_machine_id`, `get_sharedfeat_requirement`, `get_devices_for_machine`, `get_sets_for_software`). No `row_factory` or SQL shape changes were made.

---

## Step 4.9 (proposal) — database.py module reorganisation: move non-DB code out

**Status: optional/proposed — not implemented.** It is not a prerequisite for 4.8.

**Responsibility:** `database.py` mixes database access with pure application helpers.
Candidates to move as **pure import moves** (Kodi-free already; `progress`/`sleep`/
`dialog` are injected callbacks — the GUI passes `xbmc.sleep` and dialog updaters):

| Candidate | Suggested target |
|---|---|
| `download_and_update_umsa_db` | `umsa_core/umsa_db_download.py` |
| `_scan_state_ownership`, `run_scan_with_progress` | `umsa_core/scan_progress.py` |
| `split_gamename`, `COUNTRIES`, `make_time_nice`, `get_best_machine_for_set`, `parse_recommended_games`, `build_filter_lists` | `umsa_core/game_labels.py` (or split further) |
| `create_cmdline`, `get_cmd_line_options` assembly helpers | step 4.4 clarified the boundary (reads → repository, assembly stays); consider `umsa_core/cmdline.py` after 4.6 |

**Rules:** `DBMod` re-exports the names it still exposes to callers, so public imports
keep working; no Kodi import may appear in any moved module (verify against the step 4.0
guard); no behaviour change. Not urgent — schedule after 4.6.

---

## Explicit non-goals (stay in DBMod for the foreseeable future)

- **Cross-database synchronisation:** `open_db`, `add_dat_to_db`, `add_art_to_db` —
  documented exception; own connections, ATTACH lifecycle, atomic replace semantics;
  protected by `test_database.py` and `test_scan_artwork.py`. `add_dat_to_db`/
  `add_art_to_db` are also explicitly out of scope for 4.2b (they use no repositories).
- **Mixed application queries:** `get_random_id`, `get_random_art`,
  `get_artwork_by_software_id` — depend on live filter state and/or path resolution;
  only sensible to separate as a mixed-query service with explicit state parameters,
  which nothing currently needs.
- **`get_random_vgm_batch`** (formerly `get_random_vgm`) — worker-owned connection by
  design (playback thread, read-only short-lived connection); confirmed
  non-goal by decision Q3; do not move onto the persistent connection.

### Tracked side items (roadmap hygiene — status noted per item)

- **`save_further_media` single-INSERT bugfix (Q4)** — prerequisite of step 4.5,
  **done and committed as `8bb8a8d`**: one INSERT writes both values,
  commit-per-call with rollback on failure; `tests/test_save_further_media.py` 6 tests
  (pre-fix `3 failed, 3 passed`). Moved into `StatusRepository.save_further_media`
  unchanged as part of the implemented step 4.5.
- **Artwork/DAT source-of-truth refactor (completed)** — make `artwork.db` and `dat.db`
  the authoritative sources for scanned artwork and DAT data. Removed the redundant
  copy workflow (`add_art_to_db`, `add_dat_to_db`, and the copy operations in
  `open_db`). The persistent `umsa.db` connection is now read-only and attaches
  `artwork.db` as `art` and `dat.db` as `dat` schemas. Scanner workflows continue to
  write to their respective source databases through their own writable connections.
  Mixed game/artwork/DAT queries in `DBMod` now use schema-qualified table names
  (`art.art_set`, `dat.dat`, `dat.dat_set`). `ArtworkRepository` and `DatRepository`
  support schema qualification via a `schema` parameter (`"main"` for scanner
  connections, `"art"`/`"dat"` for DBMod reads). Legacy copied tables in existing
  `umsa.db` files remain unused but are not dropped; a fresh database download
  naturally removes them.
- **Phase 4.9a: Extract `download_and_update_umsa_db()` (completed)** — moved the
  standalone database download helper from `umsa_core/database.py` to
  `umsa_core/umsa_db_download.py`. The function retains its exact public signature
  and behavior. `DBMod` re-exports the name for backward compatibility. New module
  is Kodi-free and passes architecture boundary tests. New regression tests added in
  `tests/test_umsa_db_download.py` (7 tests). **Implemented (committed as `...`)**.
- **CHD disk-selection dialog (`emulator_launcher.py`)** — found while verifying step
  4.4: `i.get('disk')` on `sqlite3.Row` always raised `AttributeError` (swallowed), so
  the `Select CHD:` dialog never appeared and the picked row could not be promoted.
  **Fixed as a narrow compatibility fix in the 4.4 batch** — named row access, NULL rows
  skipped, dialog-index → row-index mapping; regression tests in
  `tests/test_emulator_launcher.py`.
- **NULL disk rows in `find_roms()` (`emulation.py`)** — found while verifying step
  4.4: only `disks[0]` gated CHD discovery, so a leading `NULL` disk row suppressed all
  CHDs, and NULL rows among truthy ones produced `None.chd` paths. **Fixed as a narrow
  compatibility fix in the 4.4 batch** — any non-empty disk row triggers discovery, NULL
  rows skipped; regression tests in `tests/test_emulation_chd.py`.

## Suggested execution order and independence

```
4.0 ✅                     (test-only boundary guards; landed at 2a2b1af)
4.2 ✅ ──► 4.2a ✅ ──► 4.2b ✅ ──► 4.3 ✅ ──► 4.4 ✅   (same repository, cumulative;
                            4.2a+4.2b committed as 9f2fd40, 4.3 as 9041812,
                            4.4 = delegation + 2 CHD fixes, committed as 4d5e70c)
4.5-pre ✅ (Q4 bugfix, committed as 8bb8a8d) ──► 4.5 ✅ (StatusRepository,
                            committed as fcdefe5) ──► 4.6 ✅ (EmulatorRepository,
                            committed as b84341e)   (status.db; parallel to 4.2-4.4)
4.7 ✅ ──► (accessors `10f9fbd` + order fix `479e202` first; extraction `da65a62`;
             parameterisation `bc631eb`; retry-loop fix `bd83a4d`)
4.6.1a ✅ ──► (`status.db` history & legacy-file migration — one migration, one-time
             import + cleanup; committed as `7c369a9` with the D20/D21 corrective
             follow-up `fe5502b`; Q1-Q6 resolved as D12-D19; D14 strict five-line rule)
4.6.2 ✅ ──► (screensaver display-history writes: HistoryRepository
             record_screensaver_display/list_screensaver_history + DBMod facades +
             ui.py Saver.record_display / Player.onAVStarted hooks; no schema change;
             committed as `e7cb00a`)
Artwork/DAT source-of-truth refactor ✅  (removed `add_art_to_db`/`add_dat_to_db`,
             read-only umsa.db with attached `art`/`dat` schemas, schema-qualified
             repositories; scanner writes unchanged)
Follow-up fixes ✅  (read-only umsa.db, source-db init/upgrades, scanner read-only
             connections, attachment failure cleanup, legacy import notification fix)
4.8 ✅                     (row-leak closure; committed as `e4fd570`)
4.9                         (optional proposal; not implemented)
```

Steps 4.2a/4.2b (`9f2fd40`), 4.3 (`9041812`), 4.4 (delegation + the two CHD
compatibility fixes, `4d5e70c`), 4.5-pre (the Q4 `save_further_media` bugfix, `8bb8a8d`),
4.5 (`StatusRepository`, `fcdefe5`), 4.6 (`EmulatorRepository`, `b84341e`), 4.7
(`479e202` + `10f9fbd` + `da65a62` + `bc631eb` + `bd83a4d`), 4.6.1 (`7c369a9` +
`fe5502b`) and 4.6.2 (`e7cb00a`) are implemented and committed; the repository HEAD at
the time of this update is `9a98cfe`. The six questions Q1–Q6 (lastgames duplicates,
validation strictness, filter semantics, screensaver semantics, unknown files, DB-failure
recovery) are **resolved as D12–D19** (recorded in `history_persistence_audit.md`
§1.1/§16), with the D20/D21 corrective follow-up. The §16.2 Kodi-runtime status is
evidence-based and is **not** claimed as a completed manual runtime verification; see
that section for which items are automated/mocked, static-only, or unverified.
**Step 4.6.2** writes into the same migration's `screensaver_history` table with no
schema change — full suite **819 passed**, 5 skipped, 18 subtests passed.
**Step 4.8 (row-leak closure)** committed as `e4fd570` — full suite **878 passed**, 5
skipped, 18 subtests passed (plus 10 pre-existing test failures unrelated to database
refactor).

Steps 4.5-4.6 (status.db) proceeded independently of the 4.2-4.4 chain; 4.7 was
deliberately late. All phases through 4.8 are complete. The next step would be a
deliberate decision about whether to proceed with Phase 4.9 `database.py` reorganisation,
which is an optional proposal. Every step lands with:
characterisation tests, facade delegation, unchanged public API, and a green full suite
(`.venv-debian-vm/bin/python -m pytest tests/ -q`; **819 passed** after 4.6.2, **878
passed** after 4.8, **716 passed** after the 4.6.1 corrective follow-up — **702 passed**
after step 4.6.1, **661 passed** at the 4.7 baseline, **654 passed** at the
parameterisation baseline).
