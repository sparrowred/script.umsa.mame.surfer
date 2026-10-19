# Database Refactor — `DBMod` to Repositories

This directory is the long-term reference for the ongoing refactor that gradually moves
database access out of the `umsa_core.database.DBMod` god class into focused repositories,
while `DBMod` remains the public compatibility facade for the GUI, the screensaver and the
emulation layer.

## Binding project rules (honoured by every step)

Recorded here because they constrain this refactor directly (source:
`docs/architecture.md`, `AGENTS.md`):

1. **Core is Kodi-free.** Nothing under `script.module.umsa.core/lib/umsa_core/` may
   import `xbmc*` — not directly, not lazily, not through another project module.
   `lib/umsa_core_kodi.py` is the **only** module in the core add-on allowed to import
   Kodi; add Kodi-specific needs there (current model: logging, paths, settings, VGM
   window properties), never inside `umsa_core/`.
2. **Frontend and screensaver may use Kodi directly** in their own add-ons
   (`plugin.program.umsa.mame.surfer/resources/lib/*`,
   `screensaver.umsa.mame.surfer/lib/*`). Core must not import them.
3. **Database/connection configuration lives exclusively in Core.** All SQLite
   connections go through `umsa_core.sqlite.connect_sqlite`; no add-on opens raw
   connections or reaches into `DBMod`'s `gdb`/`gdbc`/`sdb`/`sdbc`/`ggdb` internals.
4. **Reuse Core services** in frontend/screensaver instead of re-implementing them.

## Current status (steps 4.0, 4.2, 4.2a, 4.2b, 4.3, 4.4, 4.5, 4.6, 4.7 and 4.6.1 implemented; refactor decisions Q1–Q9 settled; phase 4.6.1a questions Q1–Q6 resolved as D12–D19)

Code state: git **HEAD `bd83a4d`** ("fix: retry-loop for filters" — the bounded
retry-without-filters follow-up fix to step 4.7, with 7 count-based regression tests);
before it `bc631eb` ("fix(database): bind gamelist filter/query values as
SQL parameters") closed the step-4.7 batch. The last docs commit is `5514efd` ("update
docs"), and the step-4.7 code commits sit on top of
`b84341e` ("refactor(database): move emulator configuration to
emulator_repository" — step 4.6). **Steps 4.5, 4.6 and 4.7 are committed**: `fcdefe5`
("refactor(database): centralize play history and media access in status_repository" —
`status_repository.py` new + `database.py` status delegation + schema-helper call),
`b84341e` (`emulator_repository.py` new + `database.py` emulator delegation +
schema-helper call + `tests/test_emulator_repository.py`, gitignored), and step 4.7 as
`479e202` (bind the `order` fallback), `10f9fbd` (filter-state accessors),
`da65a62` (gamelist_filter extraction) and `bc631eb` (parameterisation), with the retry-loop
fix as `bd83a4d`; the full suite is **661 passed, 5 skipped, 18 subtests passed** at that
HEAD. The tracked tree
is **clean** (`git status` empty) — nothing is pending. Documentation history: this
directory first tracked as `ec400f4` ("add docs/database_refactor"), refreshed as
`5514efd` (both docs-only, after `b84341e`). Code history: steps 4.2a+4.2b were
committed together as `9f2fd40`
("database: enforce row, clean up" — the five Q1 method removals, 91 lines, plus the
`sqlite3.Row` repository input contract: `require_row_connection` in `sqlite.py`, the
three repository constructors, the four scanners' repository-feeding connections,
fallback-code removal, contract tests) and step 4.3 as `9041812` ("refactor: database to
game_repository" — ten new repository methods, the seven section-7 facades,
`get_all_for_software` pure composition), step 4.4 as `4d5e70c` ("refactor: streamline
database queries and improve disk handling in emulator launch"). Earlier commits after
the `ea7d0f7` state the
audits were last updated at: `7e47290` ("vgmplay: batch retrieval of random VGM entries",
renamed `get_random_vgm()` to `get_random_vgm_batch()` — now `connect_sqlite_readonly`,
returns a list of dicts), `2a2b1af` and the Q4 fix `8bb8a8d`. Phase 4.0 itself only adds
a test file; `tests/` is gitignored and `docs/*` is ignored **except
`docs/database_refactor/`**, which is tracked (see the retention note below), so
documentation updates *do* move HEAD.

`DBMod` (`script.module.umsa.core/lib/umsa_core/database.py`) still owns:

- the persistent `umsa.db` and `status.db` connections and their lifecycle
  (both `status.db` schemas are now applied via repository schema helpers —
  `create_status_tables` since 4.5, `create_emulator_tables` since 4.6);
- cross-database synchronisation via `ATTACH DATABASE` (`open_db`,
  `add_dat_to_db`, `add_art_to_db`);
- the mutable gamelist query state (`join`/`where`/`order`/`use_filter`/`filter_join`/
  `filter_where` and the private `_where_params`/`_filter_where_params`) plus its
  facades over the extracted `gamelist_filter` service (step 4.7), and the
  cross-connection `get_last_played`;
- command-line *assembly* (`create_cmdline`, `get_cmd_line_options`'s argument
  building — their reads come from the repository since step 4.4);
- thin facades over the already-extracted repositories and scanners.

Already extracted (Phases 2/3/4.2–4.7):

- `dat_repository.py` — authoritative DAT schema + `DatRepository` (caller-owned
  connection, savepoint-based atomic publish/replace);
- `artwork_repository.py` — authoritative artwork schema + `ArtworkRepository` (same
  conventions);
- `game_repository.py` — read-only `GameRepository` over the general game tables
  (`sets`, `software`, `swl`, `year`, `maker`, `category`, `nplayers`, `swl_status`,
  plus `part`, `part_set`, `device`, `device_set`, `sharedfeature`,
  `sharedfeature_set` since step 4.4); twelve lookup/scalar reads moved out of `DBMod`
  in roadmap step 4.2, the seven section-7 reads (`get_searchresults`,
  `get_all_dbentries`, `get_series`, `check_series`, `check_compilation`,
  `get_info_by_set_and_swl`, `get_machines`) in step 4.3, and the media/parts/device
  reads   (`get_parts_for_set_id`, `get_disks`, `get_swl_options`, `get_machine_id`,
  `get_devices_for_machine`, `get_sharedfeat_requirement`) in step 4.4 — each public
  `DBMod` method a one-line facade over a per-call `_get_game_repository()`, plus the
  three `get_all_for_software` orchestration reads (`get_sets_for_software`,
  `get_software_name`, `get_software_ids_for_name`);
- `status_repository.py` — authoritative `status.db` `sets` schema helper
  (`create_status_tables`) + `StatusRepository` (caller-owned `status.db`
  connection, `sqlite3.Row` input contract, savepoint-based write ownership)
  since step 4.5; `DBMod.get_status_for_set`, `write_status_after_play`,
  `get_further_media`, `save_further_media` and the status half of
  `get_latest_by_software` delegate to it;
- `emulator_repository.py` — authoritative `status.db` `emu`/`emu_conn` schema
  helper (`create_emulator_tables`) + `EmulatorRepository` (same conventions)
  since step 4.6; `DBMod.get_emulators`, `get_emulator`, `save_emulator`,
  `connect_emulator`, `delete_emulator_connection` and `delete_emulator`
  delegate to it (transaction ownership and the historical commit order of
  `save_emulator`/`delete_emulator` are preserved, including the documented
  `lastrowid` decision for the unreachable update + `reconfigure=False` path);
- `gamelist_filter.py` — explicit-state gamelist filter/query composition since step 4.7:
  the `GamelistFilter` dataclass (`join`/`where`/`order`/`use_filter`/`filter_join`/
  `filter_where` + `where_params`/`filter_where_params`), `define_filter`,
  `execute_statement` and the seven selector helpers (`software_query`, `source_query`,
  `category_query`, `year_query`, `players_query`, `swl_query`, `maker_query`). It is
  Kodi-free, takes the caller connection and an explicit state, owns only short-lived
  cursors, never commits or closes the connection, and binds every external value;
  `DBMod.define_filter`, `execute_statement` and every `get_by_*` are facades that build
  the state, copy the clauses back into the public attributes and mirror the in-place
  `order` reset;
- `dat_scanner.py`, `artwork_scanner.py`, `gb64_scanner.py`, `exodos_scanner.py` —
  self-contained scan workflows with worker-owned connections and shared scan-lock
  coordination;
- `dat_parser.py`, `exodos_parser.py`, `gb64_parser.py`, `scan_coordinator.py`,
  `sqlite.py`, `data_paths.py`.

Also done since the Phase 4.1 audit: the three ad-hoc `ALTER TABLE` migrations
(`emu.mode`, `sets.marp`, `sets.youtube`) were **removed** from
`DBMod._open_persistent_databases` (policy below), and the refactor decisions Q1–Q9 were
settled by the maintainer (next section).

Phase 4.1 was **inspection and planning only**. Step 4.2 added
`game_repository.py` + `tests/test_game_repository.py` (golden tests written against
the pre-move `DBMod` first, then re-run unchanged against both facade and repository)
and changed only the twelve delegating `DBMod` methods; no schema, return shape or
public API changed. Step 4.3 followed the same characterisation-first recipe for the
seven section-7 reads and the `get_all_for_software` coverage gap (also no schema,
shape or API change; the dict shaping for `get_machines`/`get_info_by_set_and_swl` moved
into the repository per the roadmap's documented decision). Step 4.4 applied it again to
the command-line input reads, pinning the exact `prepare_mame_run` argument list in
`tests/test_cmd_line_options.py` before the SQL moved (byte-identical queries, same
valid-input assumptions, no schema/shape/API change).

## Decisions (settled by the maintainer — 2026-10-18)

These replace the former "Open questions" gate. Every roadmap step below assumes them:

1. **Q1 — Unreferenced methods: remove uniformly.** `get_status_for_software`,
   `write_options`, `get_swl_id`, `get_info_for_id`, `get_sets_for_machine` **were
   removed in step 4.2a** (91 lines; no replacement repository methods created).
   Verification first at `ea7d0f7`, re-run at `2a2b1af` before the removal: only their
   definitions and one internal debug log line (inside `get_status_for_software`) exist;
   none is exported via `umsa_core.__all__`; the only dynamic dispatch
   (`getattr(db, scan_method)` in `run_scan_with_progress`) ever receives the four scan
   method names the GUI passes (`scan_dats`, `scan_exodos_to_db`, `scan_gb64_to_db`,
   `scan_artwork`) — none of the five; no string-based or reflective references anywhere
   (production trees, add-ons, `tests/`, xml/lua). After the removal a repo-wide grep
   for the five names returns zero matches. **No replacement repository methods were
   created** to preserve them; if a use case appears later, design a new API with a
   documented return type and tests. The `status.db` `options` **column and all reads of
   it stay** — `get_status_for_set`'s result shape is unchanged (only the dead
   `write_options` *writer* went away).
2. **Q2 — SQL parameterisation is in scope for step 4.7, as a separate commit after the
   characterisation suite is green against the unchanged interpolation.** Interpolated
   *values* (`sname`, `cat`, `year`, `players`, `swl`, `maker`, `source`, and the id
   lists in `filter_where`/`filter_join`) become bound parameters — state becomes
   `(where_sql, params)`. `order` stays a whitelist mapping (no parameterisation). The
   latent unbound-local bug for `order` in `execute_statement` is fixed beforehand in
   its own commit with a test; its default is the same value `self.order` is reset to.
   New tests cover values containing `"` and `'` and values equal to a column name.
3. **Q3 — `get_random_vgm_batch` (formerly `get_random_vgm`) stays worker-owned.**
   Confirmed non-goal: it keeps its own short-lived connection on the VGM playback
   thread (since `7e47290` opened via `connect_sqlite_readonly` and returns a batch
   list; still default tuple rows, still no repository involved).
4. **Q4 — `save_further_media` fixed separately before Phase 4.5.** When no status row
   exists and both `marp` and `youtube` are passed, a single INSERT must write both
   (the old second INSERT raised `sqlite3.IntegrityError: UNIQUE constraint failed:
   sets.id` — verified at `ea7d0f7` and again pre-fix). Separate bugfix commit with a
   regression test for both values; existing update behaviour preserved; **not**
   combined with the repository extraction. **Implemented and committed as `8bb8a8d`**
   as a standalone change: one INSERT for both values, commit-per-call with rollback on
   failure; `tests/test_save_further_media.py` (6 tests, pre-fix `3 failed, 3 passed`).
   The fixed single-INSERT body moved into `StatusRepository.save_further_media`
   unchanged when step 4.5 landed.
5. **Q6 — `status.db` manual-recreation policy confirmed.** Old-schema `status.db` files
   are not auto-upgraded during the development phase (see the policy section below).
6. **Q7 — Roadmap step 4.2b implemented.** All repositories
   require `connection.row_factory is sqlite3.Row` and raise a clear `ValueError`
   otherwise (shared helper `require_row_connection` in `sqlite.py`, called by each
   constructor); every repository construction site was audited (not just the four
   scanners) and the repository-feeding connections now open with
   `connect_sqlite(..., row_factory=sqlite3.Row)`; tuple/dict fallback code removed;
   `connect_sqlite()`'s default **not** changed;
   `add_dat_to_db()`/`add_art_to_db()` **not** touched (they use no repositories; nor are
   the scanners' umsa.db mapping connections, which also construct none).
   Limited to the row-factory contract and its callers; not combined with step 4.3.
7. **Q8 — GameRepository included in 4.2b.** `test_repository_reads_work_on_tuple_connections`
   was replaced by `test_repository_rejects_tuple_connections`, asserting tuple
   connections are rejected with `ValueError` (plus `test_exodos_artwork`'s and
   `test_artwork_repository`'s tuple tests replaced likewise, and helper-level coverage in
   `test_sqlite.py`).
8. **Q9 — Step 4.7 module is named `gamelist_filter.py`** (filter/query-state
   composition), deliberately not `gamelist_query.py`, to avoid confusion with the
   frontend's `gamelist_strategies.py`. No duplicate compatibility module.

## Documents

| File | Purpose |
|---|---|
| [`dbmod_audit.md`](dbmod_audit.md) | Complete inventory of every remaining SQL-bearing method/helper in `database.py`, grouped by responsibility: connection lifecycle, cross-database sync, scan facades, repository delegations, mixed application queries, game/set reads, filter composition, status.db play history, emulator config. Records tables, read/write behaviour, connection/transaction ownership, callers, result shapes, and the recommended future owner of each method. Referenced by method name (no line numbers). |
| [`row_factory_audit.md`](row_factory_audit.md) | Result-shape and row-access audit: which connections are `sqlite3.Row` vs default tuples, which methods/callers use positional vs named row access (including mixed-style consumers), the implicit public contracts, and the staged strategy — now including the implemented `sqlite3.Row` input requirement for repositories (step 4.2b, done) and the fixed row-leak closure step (4.8). Read-only; nothing was converted by the audit itself. |
| [`roadmap.md`](roadmap.md) | Prioritised, incremental implementation plan: boundary checks (4.0), decided removals (4.2a), the `sqlite3.Row` contract (4.2b), repository extensions (4.3-4.6), the history/legacy-file migration (4.6.1, implemented) and the screensaver history (4.6.2, implemented), the filter service (4.7), row-leak closure (4.8) and the database.py reorganisation proposal (4.9) — what each step extracts, contract, required tests, dependencies, risk, acceptance criteria, and what deliberately stays in `DBMod`. |
| [`history_persistence_audit.md`](history_persistence_audit.md) | **Implemented (2026-10-18).** Phase 4.6.1a: the GUI `lastgames.txt` contract (path, format, ordering, pointer, five insert sites, exit-only save defect, failure handling) and the `filter_*.txt` contract (five-line format, id-string values, Load/Save dialogs, crash/silent-failure modes) with every call site; the precise `load_lastsaver()` status (live but always-empty consumer, no writer ever existed — not an import source); the screensaver lifecycle and the decided display boundaries (D16: images post-render, videos `onAVStarted`); four purpose-specific `status.db` tables covered by **one** `PRAGMA user_version` migration; the **one-time import + cleanup sequence** (per-file all-or-nothing validation, commit-before-delete, terminal marker states `completed`/`completed_discards`/`completed_no_source`/`failed`, no-reimport, cleanup-only recovery, unknown-file preservation); the verified Core userdata inventory; the Core/Kodi boundary, facade API and notification; the dependency on Phase 4.7, the confirmed 4.7 → 4.6.1 → 4.6.2 ordering (D11); and the six questions Q1–Q6 — **resolved 2026-10-18 as decisions D12–D19** (recorded in §1.1 and §16 of that document, including `gui_lastgames` retention of **100** and the strict five-line filter rule of D14), with the §16.2 Kodi-runtime verification items checked during implementation. |

## Phase checklist

### Completed (verified in the current tree)

- [x] DAT tables + schema centralised in `DatRepository` (`dat_repository.py`); `DBMod.get_dat_for_set(s)` delegate.
- [x] Artwork tables + schema centralised in `ArtworkRepository` (`artwork_repository.py`); `DBMod.get_art_types`/`get_artwork_for_set(s)` delegate.
- [x] DAT, artwork, GB64 and eXoDOS scan workflows extracted to dedicated scanner modules; `DBMod.scan_*` are thin wrappers with shared scan-lock state.
- [x] Connection factory centralised (`sqlite.py:connect_sqlite`; default `row_factory=None` stays).
- [x] Cross-database `ATTACH` synchronisation made atomic and documented as an intentional `DBMod` exception.
- [x] Phase 4.1 audit of remaining responsibilities (this directory).
- [x] Step 4.2 — `GameRepository` with twelve delegating facade methods (`game_repository.py`, `tests/test_game_repository.py`).
- [x] Removal of the three status.db `ALTER TABLE` migrations (`emu.mode`, `sets.marp`, `sets.youtube`); `CREATE TABLE IF NOT EXISTS` already defines all three columns (policy below).
- [x] Step 4.0 — boundary regression checks (`tests/test_architecture_boundaries.py`,
  7 tests): AST Kodi-import guard for `script.module.umsa.core/lib/` with the
  single-file adapter exception for `lib/umsa_core_kodi.py`, and the
  connection-attribute guard (`gdb`/`gdbc`/`sdb`/`sdbc` only in `database.py`, `ggdb`
  likewise in Core) across all three add-ons' production trees. See
  [Boundary guards](#boundary-guards-step-40-implemented) below.
- [x] Step 4.2a — the five unreferenced `DBMod` methods removed (Q1):
  `get_status_for_software`, `write_options`, `get_swl_id`, `get_info_for_id`,
  `get_sets_for_machine` (91 lines deleted, definitions only — zero references
  re-verified first; no replacements created; `options` column/reads untouched;
  all tests green).
- [x] Step 4.2b — `sqlite3.Row` input contract (Q7/Q8): `require_row_connection`
  helper in `sqlite.py` enforced by the `GameRepository`/`DatRepository`/
  `ArtworkRepository` constructors; the four scanners open repository-feeding
  connections with `row_factory=sqlite3.Row`; `ArtworkRepository`'s tuple/dict
  fallbacks deleted; tuple-compat tests replaced by contract tests (game, artwork,
  exodos_artwork, `test_sqlite.py`) with `test_dat_repository.py` and
  `test_scan_coordinator.py` repository connections switched to `Row`.
  `connect_sqlite()` default, `add_dat_to_db`/`add_art_to_db` and
  `get_random_vgm_batch` untouched.
- [x] Step 4.3 — `GameRepository` extension (search, series/compilation, browse lists,
  machine/set metadata) + the `get_all_for_software` coverage gap: ten new repository
  methods, the seven `DBMod` reads as one-line facades, `get_all_for_software` pure
  composition (no `self.gdbc`, structurally pinned by a test); golden tests written and
  verified against the pre-extraction code first, composition test, extended seed and
  never-commit list; full suite 517 passed.
- [x] Step 4.4 — `GameRepository` media/parts/device reads: six new repository methods
  (`get_parts_for_set_id`, `get_disks`, `get_swl_options`, `get_machine_id`,
  `get_devices_for_machine`, `get_sharedfeat_requirement`); `DBMod.get_parts_for_set_id`
  and `DBMod.get_disks` one-line facades; `get_cmd_line_options` performs its four inline
  SELECTs plus both parts fetches through one repository instance while keeping the
  assembly (`create_cmdline`, shared-feature chain, `get_info_by_set_and_swl`) in
  `DBMod`; end-to-end golden test `tests/test_cmd_line_options.py` (23 tests) written
  against the pre-extraction `DBMod` first (11 passed, 12 failed — the 12 = not-yet-
  existing repository methods), pinning the exact `prepare_mame_run` argument list.
  Also in the 4.4 batch (narrow compatibility fixes required before completion): the
  `Select CHD:` dialog in `emulator_launcher.py` (Row named access, NULL skip,
  dialog-index → row-index mapping) and `find_roms()` NULL-disk handling in
   `emulation.py` — regression tests `15 passed` (`4 failed, 11 passed` pre-fix),
   full suite **549 passed**; ruff: `emulator_launcher.py` 55=55, `emulation.py` 24→22.
- [x] Step 4.5 — `StatusRepository` for status.db play history + `sets` schema helper:
  `status_repository.py` with `create_status_tables(cursor)` (byte-equivalent `sets`
  DDL moved out of `_open_persistent_databases`, which now calls it; `emu`/`emu_conn`
  untouched, `user_version` stays 0) and five repository methods
  (`get_status_for_set`, `get_further_media`, `get_latest_by_set_ids`,
  `write_status_after_play`, `save_further_media` — the Q4 single-INSERT logic moved
  verbatim); `require_row_connection` enforced; savepoint write ownership (release =
  commit only if the call started the tx; rollback-to preserves caller pending changes);
  five `DBMod` facades over a per-call `_get_status_repository()`, with
  `get_latest_by_software` keeping its umsa.db orchestration; new
  `tests/test_status_repository.py` (24 tests) written against the pre-extraction
  `DBMod` first (characterisation baseline **24 passed** with `database.py` stashed),
  full suite **579 passed**; ruff/mypy clean on the new file, `database.py` findings
  unchanged at 33.
- [x] Step 4.6 — `EmulatorRepository` for status.db emulator config + `emu`/`emu_conn`
  schema helper: `emulator_repository.py` with `create_emulator_tables(cursor)`
  (DDL byte-equivalent to the inline `_open_persistent_databases` SQL — verified by a
  schema-equivalence test executed before the inline DDL was removed; `user_version`
  stays 0) and six repository methods (`get_emulators`, `get_emulator`,
  `save_emulator`, `connect_emulator`, `delete_emulator_connection`,
  `delete_emulator`); `require_row_connection` enforced; savepoint write ownership
  (`umsa_emu_write`) with the historical commit order of `save_emulator`
  (emu-row commit → connection insert) and `delete_emulator` (connections commit →
  emulator delete) deliberately preserved; six `DBMod` facades over a per-call
  `_get_emulator_repository()`; documented `lastrowid` decision for the unreachable
  update + `reconfigure=False` path and for `get_emulator()` with neither argument;
  new `tests/test_emulator_repository.py` (43 tests) written against the
  pre-extraction `DBMod` first (characterisation baseline **43 passed**), full suite
  **622 passed**; ruff/mypy clean on the new file, `database.py` findings unchanged
  at 33.
- [x] Step 4.7 — `gamelist_filter.py` explicit-state filter/query composition +
  parameterisation (Q2/Q9), as four commits: `479e202` (bind the `order` fallback;
  `tests/test_execute_statement_order.py`), `10f9fbd` (filter-state accessors
  `set_filter_enabled`/`set_order`, GUI+screensaver call sites converted;
  `tests/test_filter_state_accessors.py`), `da65a62` (extraction: `GamelistFilter`
  dataclass + `define_filter`/`execute_statement`/selector helpers, `DBMod` facades,
  interpolation unchanged) and `bc631eb` (bind all external values; private
  `_where_params`/`_filter_where_params` feeding `get_random_id`/`get_random_art`).
  Characterisation + parameterisation suite `tests/test_gamelist_filter.py` (35 tests);
  full suite **622 → 661 passed**; new module Kodi-free and ruff-clean apart from the
  pre-existing `int(round())` style. The retry-without-filters loop is now **bounded**:
  at most one selector-only retry — issued only when the first query actually carried
  active filters — then a prompt `([], 0, 0)` return with no fabricated `prev`/`next`
  sentinels (7 count-based regression tests; the old unbounded loop is no longer an
  accepted limitation).

### Implemented (step 4.6.1)

- [x] Step 4.6.1 — **one** `status.db` schema migration covering all three concepts:
  `gui_lastgames` (immediate persistence after a successful display), `filter_selections`
  (all `filter_*.txt`), plus `screensaver_history` (last 100, starts empty) and a
  `status_meta` import marker — a single `PRAGMA user_version` 0 → 1 increment via
  `umsa_core/status_migrations.py`, add-only (existing play history, emulator config and
  further-media data preserved); `history_repository.py` + DBMod facades; then the
  **one-time legacy import and cleanup** (discover configured paths, per-file
  all-or-nothing validation, malformed files discarded whole and recorded, data + marker
  + pending-delete list committed together, *then* `lastgames.txt`/`filter_*.txt` deleted
  — including invalid ones — with a Kodi-side notification naming discarded files);
  never re-import after a terminal state, explicit retry only after `failed` (new
  `retry_import` script command, `addon.py`); unknown files never deleted (D17).
  **Implemented as:** `status_migrations.py` (`CURRENT_VERSION = 1`, reuses
  `create_status_tables`/`create_emulator_tables`/`create_history_tables`, joins a caller
  transaction), `history_repository.py` (`create_history_tables` + `HistoryRepository`
  lastgames/filter/marker), `history_import.py` (discovery, validation, one-time import,
  cleanup-only and `failed`-marker fallback, `retry_import`), the `DBMod` facades
  (`load_lastgames`/`save_lastgames`/`list_filter_names`/`load_filter_selections`/
  `save_filter_selections`/`get_import_marker`/`run_legacy_import`/`retry_legacy_import`/
  `discover_legacy_paths`), the GUI startup import/notification + `_remember_and_select`
  funnel (entry only after a successful display), and the `retry_import` command in
  `addon.py`. **Line-count rule corrected during implementation:** `filter_<name>.txt`
  now requires **exactly five logical lines**; a wrong count discards the whole file
  (D14, superseding the earlier "keep tolerance" wording). `lastgames.txt` keeps the
  legacy first-line-only tolerance. **Q1–Q6 resolved as D12–D19**
  (`history_persistence_audit.md` §1.1/§16); ordering 4.7 → 4.6.1 → 4.6.2 (D11) with 4.7
  and 4.6.1 complete.
  - **Corrective follow-up (2026-10-19), D20/D21 — no schema change.** (a) A saved filter
    now keeps its name even with five empty categories: `save_filter_selections` writes a
    reserved definition-marker row (`category = '__filter_definition__'`) in the same
    `filter_selections` table, replaced atomically on every save, never a selectable
    category and never part of a public filter dictionary. Version-1 databases with
    pre-marker, non-empty filters keep working with no reset or re-import. (b) An
    unreadable recognized file (`OSError`, including discovery enumeration errors) is no
    longer treated as malformed content: the attempt aborts before the import transaction,
    a best-effort durable `failed` marker is recorded, and no file is deleted or partially
    imported. Only `UnicodeDecodeError` remains malformed input. Startup and
    `retry_import` notifications now name the pending-cleanup filenames and keep the
    discarded filenames. These corrections are a **prerequisite for 4.6.2**.

### Planned, not implemented (see `history_persistence_audit.md`)

- [x] Step 4.6.2 — screensaver display history writes into the same migration's
  `screensaver_history` table (feature starts empty; hooks at the render /
  `onAVStarted` boundaries). **Resolved by D16:** unique sets with recency move-up (one
  row per `set_id`, `software_id` alongside), ordered by monotonic `id`, images recorded
  post-render, videos on `Player.onAVStarted()` via the `umsa_set_id` unique ID
  (Kodi 20+ guard), orphans kept and reported. **Done** (2026-10-19, in the working tree:
  `HistoryRepository.record_screensaver_display`/`list_screensaver_history`, the `DBMod`
  facades and the `ui.py` `Saver.record_display` / `Player.onAVStarted` hooks; no schema
  change, `user_version` stays 1; new tests 51 + 52, full suite **819 passed**).
- Note: `load_lastsaver()` stays untouched legacy read-side code with one live but
  always-empty consumer (`M_LSSAVER`); no writer of `lastsaver.txt` exists in any
  revision — it is **not** an import source, and a stray `lastsaver.txt` would be an
  *unknown* file: preserved and listed, never auto-deleted.

### Decided, not yet implemented (see roadmap)

- [x] Step 4.7 — `gamelist_filter.py`: explicit-state filter/query composition, parameterisation (Q2), filter-state accessors, `get_by_maker` clone-resolution read. **Done** (see above).
- [ ] Step 4.8 — row-leak closure: facade returns only unambiguous shapes; named access only across add-on boundaries.
- [ ] Step 4.9 (proposal) — move non-DB code out of `database.py` (download, scan progress, labels/selection helpers, cmdline helpers).
- [ ] Removal of duplicate artwork copying — agreed scope: make `artwork.db` the single
  source of truth, migrate all artwork readers and the mixed game/artwork queries onto
  it, then remove the redundant copy workflow and the obsolete `umsa.db.art_set`
  dependency. Planned side item, not implemented (see roadmap "Tracked side items").

### Planned next step

**Steps 4.5 (`StatusRepository`, committed as `fcdefe5`), 4.6 (`EmulatorRepository`,
committed as `b84341e`) and 4.7 (the explicit-state gamelist filter/query composition,
committed as `479e202` + `10f9fbd` + `da65a62` + `bc631eb`, plus the **bounded
retry-without-filters loop** fix with its 7 count-based regression tests, committed as
`bd83a4d`) are done** (Q4 prerequisite committed separately first as `8bb8a8d`; tree clean
at HEAD `bd83a4d`, with `tests/test_status_repository.py` (24 tests),
`tests/test_emulator_repository.py` (43 tests) and `tests/test_gamelist_filter.py` (35
tests), full suite **661 passed**, 5 skipped, 18 subtests passed). **Step 4.6.1** (one
`status.db` migration for
GUI lastgames + filter selections + screensaver history, plus the one-time legacy import
and cleanup) is **implemented** (2026-10-18): `status_migrations.py`,
`history_repository.py`, `history_import.py`, the `DBMod` facades, the GUI startup wiring
and the `retry_import` script command, with the strict five-line filter rule (D14) and the
D18 recovery semantics. Its design questions **Q1–Q6 are resolved as D12–D19**
(`history_persistence_audit.md` §1.1/§16, including `gui_lastgames` retention of **100**),
with the §16.2 Kodi-runtime items verified during implementation. Its ordering
**4.7 → 4.6.1 → 4.6.2** holds — the migration depended on **Phase 4.7**, now satisfied
(persisted selections are consumed by `define_filter`, whose explicit-state
composition 4.7 delivered). **Step 4.6.2** (screensaver display history writes) **is
implemented** (2026-10-19, in the working tree — no schema change; new tests 51 + 52, full
suite **819 passed**, 5 skipped, 18 subtests passed); it proceeded independently of the
completed 4.2–4.7 chain.
Steps 4.0, 4.2, 4.2a, 4.2b,
4.3, 4.4, 4.5-pre, 4.5, 4.6, 4.7, 4.6.1 and 4.6.2 are done.
See [`roadmap.md`](roadmap.md) for the full contracts.

## Boundary guards (step 4.0 implemented)

Test file: `tests/test_architecture_boundaries.py` (7 tests, standard library only —
`ast` + `pathlib`; parses sources, never imports them, no Kodi needed).

**Enforced boundaries and acceptance criteria:**

1. **Kodi import guard.** Every `*.py` file under `script.module.umsa.core/lib/` is
   parsed with `ast`; `import xbmc*` and `from xbmc* import ...` (any of `xbmc`,
   `xbmcgui`, `xbmcaddon`, `xbmcvfs`) fail unless the file **is**
   `lib/umsa_core_kodi.py`. The exception is by exact relative path only — no
   directory or pattern exemption — so a second adapter or a new Kodi-importing core
   module fails automatically. Each violation is reported as
   `path:line: <import statement>`.
2. **Connection-attribute guard.** `ast.Attribute` accesses named `gdb`, `gdbc`,
   `sdb`, `sdbc` (and `ggdb` within `script.module.umsa.core/lib/`) fail unless the
   file is `umsa_core/database.py`. All three add-ons' production trees are scanned
   (`script.module.umsa.core/lib`, `plugin.program.umsa.mame.surfer`,
   `screensaver.umsa.mame.surfer`); root `tests/` sits outside them, so test code is
   excluded by construction with no production directory exempted. Violations are
   reported as `path:line: .<attribute>`.
3. **`ggdb` scoping rule (documented, not an allowlist).** Outside Core, `ggdb` is the
   sanctioned DBMod *facade handle* on GUI objects (`self.ggdb = DBMod(...)`;
   `docs/AGENTS-addon-interaction-guide.md` documents `ggdb.method(...)` as normal GUI
   access), and no object in the repository defines a `ggdb` connection attribute —
   DBMod defines only the four above. A pinned test
   (`test_dbmod_never_exposes_a_ggdb_attribute`) fails if `database.py` ever accesses
   `.ggdb`, forcing the rule to be revisited if that premise breaks. Deep reaches
   through the handle (`self.ggdb.gdbc`, `handle.gdb`, …) are caught by the four-name
   rule in every add-on, so no connection access escapes the guard.
4. **Vacuity protection.** Coverage tests assert the scanned sets contain the known
   key modules (`database.py`, `umsa_core_kodi.py`, `gui.py`, `runtime.py`, the
   entry points) and ≥ 30 production files, and synthetic in-memory sources prove both
   detectors flag violations in files that do not exist yet.

**Result at HEAD `2a2b1af`, re-verified at HEAD `5514efd` (the full suite below includes
the guard tests): no violations — the current production tree passes both
guards.**

## `status.db` schema and migration policy (confirmed — Q6)

The three ad-hoc column-existence checks + `ALTER TABLE` migrations that used to live in
`DBMod._open_persistent_databases` (`emu.mode`, `sets.marp`, `sets.youtube`) have been
**removed**. The `CREATE TABLE IF NOT EXISTS` definitions for `sets`, `emu` and
`emu_conn` are now the only schema path for `status.db`, and they already include all
three columns. **Confirmed policy (Q6):** a pre-existing local `status.db` that lacks the
current columns is **not** upgraded automatically — during development it may simply be
recreated manually. No code anywhere may reintroduce column-existence checks or
`ALTER TABLE` fallbacks for these three fields.

No versioned migration mechanism exists yet (`PRAGMA user_version` stays `0` on
`status.db`; three test files currently pin that). Implementing one is a **future
task** (both schema helpers — 4.5's
`create_status_tables` and 4.6's `create_emulator_tables` — landed without adding
one) and must follow this policy. A concrete **plan** for it — proposed module
`umsa_core/status_migrations.py` with **one** migration entry (single version increment
0 → 1 declaring the finalized schema: the existing three tables re-declared idempotently
plus `gui_lastgames`, `filter_selections`, `screensaver_history` and the `status_meta`
marker), call site in `_open_persistent_databases`, and the one-time legacy import with
commit-before-delete cleanup — is specified, but **not implemented**, in
[`history_persistence_audit.md`](history_persistence_audit.md)
(sections 7-11):

1. Future `status.db` schema changes must be ordered, explicit migration versions keyed
   on SQLite's `PRAGMA user_version` — never ad-hoc column-existence checks embedded in
   normal initialization.
2. Migrations run against the actual `status.db` connection, never `umsa.db`.
3. Each pending migration is applied exactly once, in version order, and the stored
   version is advanced only after the migration succeeds.
4. Transaction and failure behaviour is deliberate and documented (e.g. one transaction
   per migration, no partial application, failure surfaces to the caller).
5. Tests cover a fresh database (migrations skipped or baseline version set) *and* a
   database opened at each previous schema version.
6. Migration failures are never silently swallowed, and a missing column is never used as
   evidence of a particular historical version.

The same rules apply to both `status.db` schema helpers (4.5 `sets`, 4.6
`emu`/`emu_conn`); any future schema change must land together with its
versioned migration mechanism in the same change.

## Validation (executed at HEAD `8bb8a8d` + step-4.5/4.6 working tree — those steps are now committed as `fcdefe5` + `b84341e`; steps 4.7 re-verified at HEAD `bc631eb`, then the full suite re-run at HEAD `bd83a4d` after the retry-loop fix; steps 4.0, 4.2a, 4.2b, 4.3, 4.4, the Q4 fix, 4.5, 4.6 and 4.7)

Python from `.venv-debian-vm` (single consistent venv across all docs):

```bash
# Phase 4.0 boundary guards (step 4.0 deliverable)
.venv-debian-vm/bin/python -m pytest tests/test_architecture_boundaries.py -v
# → 7 passed  (no Kodi imports outside the adapter; no connection-attribute
#   accesses outside database.py — zero violations against the current tree)

# DBMod/repository/scanner subset (13 files: every test that constructs DBMod or a repository,
# plus the scanner, sqlite and screensaver-addon layers)
.venv-debian-vm/bin/python -m pytest tests/test_cmd_line_options.py tests/test_database.py \
  tests/test_game_repository.py tests/test_dat_repository.py tests/test_artwork_repository.py \
  tests/test_dat_scanner.py tests/test_scan_artwork.py tests/test_gb64_scanner.py \
  tests/test_exodos_scan.py tests/test_scan_coordinator.py tests/test_run_scan_with_progress.py \
  tests/test_sqlite.py tests/test_screensaver_addon.py -q
# → 269 passed  (246 at the step-4.3 state + the 23 step-4.4 cmd-line tests)

# Repository-feeding end-to-end tests not in the subset
.venv-debian-vm/bin/python -m pytest tests/test_exodos_artwork.py -q
# → 52 passed  (tuple test replaced by the ValueError contract test)

# Step 4.4 end-to-end golden tests for get_cmd_line_options (new file)
.venv-debian-vm/bin/python -m pytest tests/test_cmd_line_options.py -q
# → 23 passed  (pre-extraction characterisation run: 11 passed, 12 failed — the 12 =
#   calls to repository methods that did not exist yet; all green after the move)

# Focused group: command-line + repository + database facades
.venv-debian-vm/bin/python -m pytest tests/test_cmd_line_options.py \
  tests/test_game_repository.py tests/test_database.py -q
# → 83 passed

# Emulator-launch contract + boundary guards + process runner (step 4.4 §8)
.venv-debian-vm/bin/python -m pytest tests/test_emulation_process.py \
  tests/test_emulation_chd.py tests/test_emulation_vgm_callback.py \
  tests/test_architecture_boundaries.py tests/test_process.py -q
# → 35 passed  (31 before the 4 find_roms NULL-disk tests were added)

# CHD compatibility regression tests (step 4.4 batch, new file + find_roms tests)
.venv-debian-vm/bin/python -m pytest tests/test_emulator_launcher.py \
  tests/test_emulation_chd.py -q
# → 15 passed  (pre-fix baseline with the two fixes stashed: 4 failed, 11 passed —
#   the 4 = the dialog-never-shown and leading-NULL-suppression behaviours)

# Q4 save_further_media regression tests (new file; separate standalone fix)
.venv-debian-vm/bin/python -m pytest tests/test_save_further_media.py -v
# → 6 passed  (pre-fix characterisation against the old code: 3 failed, 3 passed —
#   the 3 = both-values insert IntegrityError, in_transaction True after that
#   successful call, and no rollback after a failed write)

# Step 4.5 StatusRepository tests (new file: schema helper, Row contract, reads,
# write branches, Q4 both-values insert, savepoint/transaction ownership, facades)
.venv-debian-vm/bin/python -m pytest tests/test_status_repository.py -v
# → 24 passed  (characterisation baseline with database.py stashed via git stash:
#   also 24 passed — the 24 were written against the pre-extraction DBMod first)

# Step 4.5 facade + schema + transaction-related regression group
.venv-debian-vm/bin/python -m pytest tests/test_status_repository.py \
  tests/test_save_further_media.py tests/test_database.py \
  tests/test_architecture_boundaries.py tests/test_sqlite.py -q
# → 34 passed

# Step 4.6 EmulatorRepository tests (new file: schema helper + schema equivalence,
# Row contract, read filters/precedence, save/connect/delete paths incl. trigger-
# based ordering and commit-boundary tests, savepoint/transaction ownership with a
# cursor-tracking connection, ten DBMod facade goldens incl. the GUI management
# sequence)
.venv-debian-vm/bin/python -m pytest tests/test_emulator_repository.py -q
# → 43 passed  (characterisation baseline run BEFORE the delegation, with the inline
#   DDL and inline SQL still in database.py: also 43 passed)

# Step 4.6 facade + schema + transaction-related regression group
.venv-debian-vm/bin/python -m pytest tests/test_emulator_repository.py \
  tests/test_status_repository.py tests/test_database.py \
  tests/test_architecture_boundaries.py tests/test_sqlite.py \
  tests/test_save_further_media.py -q
# → 101 passed

# Step 4.7 pre-work tests (new files)
.venv-debian-vm/bin/python -m pytest tests/test_execute_statement_order.py \
  tests/test_filter_state_accessors.py -q
# → 4 passed  (order-fallback fix: pre-fix run fails with UnboundLocalError;
#   accessor tests cover set_order/set_filter_enabled)

# Step 4.7 characterisation + parameterisation + bounded-fallback suite (new file;
# written against the pre-extraction DBMod first, re-run unchanged against the
# delegating facade)
.venv-debian-vm/bin/python -m pytest tests/test_gamelist_filter.py -q
# → 35 passed  (define_filter all/partial/per-category; execute_statement
#   normal/prev/next, filter on/off, empty-result retry, sentinel entries,
#   start/middle/end windowing; every get_by_* incl. one-level clone chain and
#   missing-maker TypeError; parameterisation: quote-bearing category round-trip,
#   hostile value bound by category_query, bound id list, quote-bearing software name
#   through prev/next, get_random_id via filter params;
#   bounded fallback: filtered-empty → selector-only fallback, selector-only empty,
#   filters + fallback both empty, empty underlying result set, empty Prev/Next in
#   both directions, successful filtered navigation — each asserting the exact
#   number of executed gamelist SELECTs via a spy connection, not timing)

# Full suite baseline (after step 4.7 — commits 479e202 + 10f9fbd + da65a62 + bc631eb,
# plus the bounded retry-loop fix committed as bd83a4d)
.venv-debian-vm/bin/python -m pytest tests/ -q
# → 661 passed, 5 skipped, 18 subtests passed  (at HEAD bd83a4d, tracked tree clean)
#   (622 before 4.7 + 35 gamelist_filter tests + 4 pre-work tests; 654 passed with the
#    28-test suite at HEAD bc631eb; skipped: VGM real-MAME tests, gated by
#    VGM_MAME_TESTS=1)

# Lint on the changed files — no new findings (HEAD vs working tree, per file)
.venv-debian-vm/bin/python -m ruff check <file>
#   sqlite.py 2=2  dat_repository.py 7=7
#   artwork_repository.py 16→11 (fallback lines deleted)  dat_scanner.py 16=16
#   artwork_scanner.py 11=11  exodos_scanner.py 4=4
#   gb64_scanner.py 14=14
#   database.py 36→33 (step 4.3 moved its three style findings out with the code;
#   still 33 after step 4.4, after the Q4 fix, after step 4.5 and after step 4.6;
#   33→32 after step 4.7 — remaining are pre-existing — AGENTS.md "Lint (many
#   pre-existing issues)" deliberately not churned)
#   gamelist_filter.py 2 (both carried verbatim from the moved code: the pre-existing
#   `int(round(...))` RUF046 and one `.format`→f-string suggestion; not churned)
#   game_repository.py 0=0 (the three moved style findings fixed in the new
#   location in 4.3; still 0 after step 4.4)
#   status_repository.py 0=0 (auto-fixed once during writing — import sort — then
#   clean; tests/test_status_repository.py: All checks passed!)
#   emulator_repository.py 0=0 (clean on the first pass; tests/
#   test_emulator_repository.py: All checks passed! after one RUF015 was fixed in
#   a test helper)
#   emulator_launcher.py 55=55 (CHD dialog fix keeps the file's existing
#   try/except style — no new findings)
#   emulation.py 24→22 (the rewritten find_roms block lost its two SIM118;
#   no new findings)
#   tests/test_emulator_launcher.py: All checks passed!
#   tests/test_emulation_chd.py: 3 pre-existing SIM117 in untouched tests (93/146/159)
#   tests/test_save_further_media.py: All checks passed!

# Type check on the new helper
.venv-debian-vm/bin/python -m mypy script.module.umsa.core/lib/umsa_core/sqlite.py \
  --follow-imports=skip
# → Success: no issues found in 1 source file

# Type check on the step-4.5 repository (skip imports: __init__ drags in pre-existing
# var-annotated errors in persistence.py, per AGENTS.md)
.venv-debian-vm/bin/python -m mypy script.module.umsa.core/lib/umsa_core/status_repository.py \
  --follow-imports=skip
# → Success: no issues found in 1 source file

# Type check on the step-4.6 repository (same skip-imports rationale)
.venv-debian-vm/bin/python -m mypy script.module.umsa.core/lib/umsa_core/emulator_repository.py \
  --follow-imports=skip
# → Success: no issues found in 1 source file

# Step 4.6.1 — migration, history repository and one-time import (new files)
.venv-debian-vm/bin/python -m pytest tests/test_status_migrations.py \
  tests/test_history_repository.py tests/test_history_import.py -q
# → 54 passed  (5 migration version/txn cases; 17 repository DDL/round-trip/marker
#   cases incl. the 100-cap + duplicate lastgames, the by-name Years/Players
#   mapping and the D20 empty-filter definition marker; 32 import cases incl.
#   strict five-line filter validation, commit-before-delete ordering,
#   malformed-discard, cleanup-only after a terminal marker, failed-marker
#   fallback, the retry_import command, and the D20/D21 follow-up
#   empty-filter-name and unreadable-vs-malformed cases)
```

The step 4.0 runs (guards, subset, full suite, lint) were executed for that documentation
update; the step 4.2a runs (subset, full suite, `database.py` lint comparison) were
re-executed after the removal; the step 4.2b runs (subset, exodos end-to-end, full suite,
per-file lint comparison, `sqlite.py` mypy) were re-executed after the contract change;
the step 4.3 runs (`tests/test_game_repository.py` `50 passed`, full suite, per-file lint
comparison) were re-executed after the extraction — the pre-extraction characterisation
run showed `40 passed, 9 failed` (the 9 = calls to repository methods that did not exist
yet) and all green after the move; the step 4.4 runs (cmd-line golden `23 passed`, focused trio `83 passed`,
emulator/guards/process `31 passed` → `35 passed` after the CHD tests, 13-file subset
`269 passed`, exodos `52 passed`, full suite `540 passed` → **`549 passed`** after the
CHD regression tests → **`555 passed`** after the Q4 fix, per-file lint comparison)
were re-executed after the delegation, again after the two CHD compatibility fixes and
again after the Q4 `save_further_media` fix, with the pre-extraction baseline
`11 passed, 12 failed`, the pre-fix CHD baseline `4 failed, 11 passed` and the pre-fix
Q4 baseline `3 failed, 3 passed`; the step 4.5 runs (`tests/test_status_repository.py`
`24 passed` both against the pre-extraction `DBMod` (characterisation, via
`git stash push -- database.py` then `git stash pop`) and after the move, the 34-test
group, the 13-file subset `269 passed`, exodos `52 passed`, full suite
**`579 passed`**, per-file lint comparison, `status_repository.py` mypy) were re-executed
after the extraction; the step 4.6 runs (`tests/test_emulator_repository.py`
`43 passed` both against the pre-extraction `DBMod` — inline DDL and inline SQL
still present — and after the delegation, the 101-test group, full suite
**`622 passed`**, per-file lint comparison, `emulator_repository.py` mypy) were
re-executed after the extraction; the step 4.7 runs (the `4 passed` pre-work files,
`tests/test_gamelist_filter.py` `28 passed` against both the pre-extraction `DBMod` and
the delegating facade, full suite **`654 passed`**, per-file lint comparison) were
re-executed across the extraction and parameterisation commits; the step 4.7 bounded
retry-loop fix was then executed as `tests/test_gamelist_filter.py` `35 passed` plus a
full suite **`661 passed`**, 5 skipped, 18 subtests run (now at HEAD `bd83a4d`, tracked
tree clean); the step 4.6.1 runs (`tests/test_status_migrations.py` `5 passed`,
`tests/test_history_repository.py` `12 passed`,
`tests/test_history_import.py` `23 passed`, the `test_database.py` facade cases, plus a
full suite **`702 passed`**, 5 skipped, 18 subtests run) were executed against the new
migration/repository/import modules in the working tree, and the per-file lint comparison
showed no new findings beyond the one deliberately broad startup guard in `gui.py`.
The 2026-10-19 corrective follow-up (D20/D21) was executed as
`tests/test_history_repository.py` `17 passed` + `tests/test_history_import.py`
`32 passed` + the focused trio (`tests/test_status_migrations.py`,
`tests/test_history_repository.py`, `tests/test_history_import.py`) `54 passed`, plus a
full suite **`716 passed`**, 5 skipped, 18 subtests run; `history_repository.py`/
`history_import.py` mypy and ruff stayed clean, `addon.py` ruff clean, and `gui.py`'s
ruff findings were unchanged from HEAD apart from the pre-existing executable-mode
`EXE002`.
Only the guard test file is new from 4.0; `tests/test_cmd_line_options.py`,
`tests/test_emulator_launcher.py`, `tests/test_save_further_media.py`,
`tests/test_status_repository.py`, `tests/test_emulator_repository.py`,
`tests/test_gamelist_filter.py`, `tests/test_execute_statement_order.py`,
`tests/test_filter_state_accessors.py`, `tests/test_status_migrations.py`,
`tests/test_history_repository.py` and `tests/test_history_import.py` are new
(4 further tests were appended to the existing `tests/test_emulation_chd.py`) —
steps 4.2a/4.2b/4.3/4.5/4.6/4.7/4.6.1 modified production code and existing tests as
described above.

**Retention note (tests ignored; this docs directory tracked):** `.gitignore` ignores
`tests` (bare pattern, any depth) and `docs/*`, **with `!docs/database_refactor/`
re-including this directory** — so this documentation is committed (first as `ec400f4`,
refreshed as `5514efd`), while everything else under `docs/` and all of `tests/` stay
local-only; the rules are deliberate and documented in `AGENTS.md` (`AGENTS.md` also
forbids modifying `.gitignore`). No test file is tracked by git
(`git ls-files | grep test` → 0) — this includes the pre-existing suite. Regression
tests are therefore retained the same way as every other test: in the local `tests/`
tree, alongside the venv. Force-adding ignored files or changing the ignore rules is a
maintainer decision, not part of any refactor step.

## Related documents

- `docs/architecture.md` — canonical add-on boundaries and Kodi import rules (Core stays Kodi-free).
- `docs/REFACTORING_STATUS.md` — the earlier three-add-on split (historical context).
- `script.module.umsa.core/lib/umsa_core/database.py` module docstring — the in-code list of intentional `DBMod` exceptions this audit builds on.
