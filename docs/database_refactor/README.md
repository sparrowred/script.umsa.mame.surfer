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

## Current status (steps 4.0, 4.2, 4.2a, 4.2b, 4.3, 4.4, 4.5 and 4.6 implemented; decisions Q1–Q9 settled)

Code state: git HEAD `8bb8a8d` ("fix(database): save_further_media single-INSERT with
both values; ensure rollback on failure" — the Q4 bugfix, **committed** since the
earlier draft of this document called it uncommitted); the tracked tree carries
**uncommitted** step-4.5 and step-4.6 changes — `database.py` (status + emulator
delegation + two schema-helper calls) plus the new untracked `status_repository.py`
and `emulator_repository.py`, and the new (gitignored) `tests/test_emulator_repository.py`
— deliberately not committed because the maintainer has not asked for a commit. History: steps 4.2a+4.2b were
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
returns a list of dicts) and `2a2b1af`. Phase 4.0 itself only adds a test file and these
documentation updates; `tests/` and `docs/` are gitignored, so HEAD is unchanged by them.

`DBMod` (`script.module.umsa.core/lib/umsa_core/database.py`) still owns:

- the persistent `umsa.db` and `status.db` connections and their lifecycle
  (both `status.db` schemas are now applied via repository schema helpers —
  `create_status_tables` since 4.5, `create_emulator_tables` since 4.6);
- cross-database synchronisation via `ATTACH DATABASE` (`open_db`,
  `add_dat_to_db`, `add_art_to_db`);
- all remaining direct SQL for filter composition, plus the cross-connection
  `get_last_played`;
- command-line *assembly* (`create_cmdline`, `get_cmd_line_options`'s argument
  building — their reads come from the repository since step 4.4);
- thin facades over the already-extracted repositories and scanners.

Already extracted (Phases 2/3/4.2–4.6):

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
| [`roadmap.md`](roadmap.md) | Prioritised, incremental implementation plan: boundary checks (4.0), decided removals (4.2a), the `sqlite3.Row` contract (4.2b), repository extensions (4.3-4.6), the history/legacy-file migration (4.6.1a, planned), the filter service (4.7), row-leak closure (4.8) and the database.py reorganisation proposal (4.9) — what each step extracts, contract, required tests, dependencies, risk, acceptance criteria, and what deliberately stays in `DBMod`. |
| [`history_persistence_audit.md`](history_persistence_audit.md) | **Planned — nothing implemented.** Phase 4.6.1a: the GUI `lastgames.txt` contract (path, format, ordering, pointer, five insert sites, exit-only save defect, failure handling) and the `filter_*.txt` contract (five-line format, id-string values, Load/Save dialogs, crash/silent-failure modes) with every call site; the precise `load_lastsaver()` status (live but always-empty consumer, no writer ever existed — not an import source); the screensaver lifecycle and candidate display boundaries; four purpose-specific `status.db` tables covered by **one** `PRAGMA user_version` migration; the **one-time import + cleanup sequence** (per-file all-or-nothing validation, commit-before-delete, terminal marker states `completed`/`completed_discards`/`completed_no_source`/`failed`, no-reimport, cleanup-only recovery, unknown-file preservation); the verified Core userdata inventory; the Core/Kodi boundary, facade API and notification; the dependency on Phase 4.7; and open questions Q1–Q7 with recommendations. |

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

### Planned, not implemented (see `history_persistence_audit.md`)

- [ ] Step 4.6.1a — **one** `status.db` schema migration covering all three concepts:
  `gui_lastgames` (immediate persistence after a successful display), `filter_selections`
  (all `filter_*.txt`), plus `screensaver_history` (last 100, starts empty) and a
  `status_meta` import marker — a single `PRAGMA user_version` 0 → 1 increment via
  `umsa_core/status_migrations.py`, add-only (existing play history, emulator config and
  further-media data preserved); `history_repository.py` + DBMod facades; then the
  **one-time legacy import and cleanup** (discover configured paths, per-file
  all-or-nothing validation, malformed files discarded whole and recorded, data + marker
  + pending-delete list committed together, *then* `lastgames.txt`/`filter_*.txt` deleted
  — including invalid ones — with a Kodi-side notification naming discarded files);
  startup checks marker → import once / cleanup only / report stored failure, never
  re-import after a terminal state, explicit retry only after `failed`; unknown files
  never deleted. **Blocked on open questions Q1–Q7.**
- [ ] Step 4.6.2 — screensaver display history writes into the same migration's
  `screensaver_history` table (feature starts empty; hooks at the render /
  `onPlayBackStarted` boundaries). **Blocked on open question Q4** (duplicates,
  ordering, display boundary, identifier).
- Note: `load_lastsaver()` stays untouched legacy read-side code with one live but
  always-empty consumer (`M_LSSAVER`); no writer of `lastsaver.txt` exists in any
  revision — it is **not** an import source, and a stray `lastsaver.txt` would be an
  *unknown* file: preserved and listed, never auto-deleted.

### Decided, not yet implemented (see roadmap)

- [ ] Step 4.7 — `gamelist_filter.py`: explicit-state filter/query composition, parameterisation (Q2), filter-state accessors, `get_by_maker` clone-resolution read.
- [ ] Step 4.8 — row-leak closure: facade returns only unambiguous shapes; named access only across add-on boundaries.
- [ ] Step 4.9 (proposal) — move non-DB code out of `database.py` (download, scan progress, labels/selection helpers, cmdline helpers).
- [ ] Removal of duplicate artwork copying — agreed scope: make `artwork.db` the single
  source of truth, migrate all artwork readers and the mixed game/artwork queries onto
  it, then remove the redundant copy workflow and the obsolete `umsa.db.art_set`
  dependency. Planned side item, not implemented (see roadmap "Tracked side items").

### Planned next step

**Steps 4.5 (`StatusRepository`) and 4.6 (`EmulatorRepository`) are done** (Q4
prerequisite committed separately first as `8bb8a8d`; both extractions are
uncommitted working-tree code, with `tests/test_status_repository.py` (24 tests),
`tests/test_emulator_repository.py` (43 tests) and the full suite green at
**622 passed**). **Step 4.6.1a** (one `status.db` migration for GUI lastgames + filter
selections + screensaver history, plus the one-time legacy import and cleanup) is
**planning only** — `history_persistence_audit.md`; no code, schema, migration, tests or
user files were changed (the real profile on this machine was inspected read-only), and
open questions Q1–Q7 block implementation. Its ordering recommendation was **revised**
when filter selections joined the scope: it now depends on **Phase 4.7** (persisted
selections are consumed by `define_filter`, whose explicit-state composition is 4.7's
job) and is recommended **after** 4.7 — the schema/import pieces are code-disjoint and
could land earlier, which is open question Q7; **4.7's scope and acceptance criteria are
unchanged** either way. Subject to that decision,
**Step 4.7** — `gamelist_filter.py` (filter/query composition,
Q2 parameterisation) — remains the next implementation step; it proceeds independently of the completed
4.2–4.6 chain. Steps 4.0, 4.2, 4.2a, 4.2b, 4.3, 4.4, 4.5-pre, 4.5 and 4.6 are done.
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

**Result at HEAD `2a2b1af`: no violations — the current production tree passes both
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

## Validation (executed at HEAD `8bb8a8d` + uncommitted step-4.5/4.6 working tree; steps 4.0, 4.2a, 4.2b, 4.3, 4.4, the Q4 fix, 4.5 and 4.6)

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

# Full suite baseline (after step 4.6)
.venv-debian-vm/bin/python -m pytest tests/ -q
# → 622 passed, 5 skipped, 18 subtests passed
#   (579 before 4.6 + 43 emulator_repository tests; skipped: VGM real-MAME tests,
#    gated by VGM_MAME_TESTS=1)

# Lint on the changed files — no new findings (HEAD vs working tree, per file)
.venv-debian-vm/bin/python -m ruff check <file>
#   sqlite.py 2=2  dat_repository.py 7=7
#   artwork_repository.py 16→11 (fallback lines deleted)  dat_scanner.py 16=16
#   artwork_scanner.py 11=11  exodos_scanner.py 4=4
#   gb64_scanner.py 14=14
#   database.py 36→33 (step 4.3 moved its three style findings out with the code;
#   still 33 after step 4.4, after the Q4 fix, after step 4.5 and after step 4.6 —
#   remaining are pre-existing — AGENTS.md "Lint (many pre-existing issues)"
#   deliberately not churned)
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
re-executed after the extraction.
Only the guard test file is new from 4.0; `tests/test_cmd_line_options.py`,
`tests/test_emulator_launcher.py`, `tests/test_save_further_media.py`,
`tests/test_status_repository.py` and `tests/test_emulator_repository.py` are new
(4 further tests were appended to the existing `tests/test_emulation_chd.py`) —
steps 4.2a/4.2b/4.3/4.5/4.6 modified production code and existing tests as described above.

**Retention note (tests/docs are gitignored):** `.gitignore` ignores `tests` (bare
pattern, any depth) and `docs/`; the rule is deliberate and documented in `AGENTS.md`
(local-only suite/docs; `AGENTS.md` also forbids modifying `.gitignore`). No test file
is tracked by git (`git ls-files | grep test` → 0) — this includes the pre-existing
suite. Regression tests are therefore retained the same way as every other test: in the
local `tests/` tree, alongside the venv. Force-adding ignored files or changing the
ignore rules is a maintainer decision, not part of any refactor step.

## Related documents

- `docs/architecture.md` — canonical add-on boundaries and Kodi import rules (Core stays Kodi-free).
- `docs/REFACTORING_STATUS.md` — the earlier three-add-on split (historical context).
- `script.module.umsa.core/lib/umsa_core/database.py` module docstring — the in-code list of intentional `DBMod` exceptions this audit builds on.
