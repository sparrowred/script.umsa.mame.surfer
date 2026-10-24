# Phase 4.9.1 — `database.py` Inventory and Documentation

**Baseline:** git HEAD `9b62f4b2be99bbad3b35db7c64dacfa1f567d11e` (2026-10-24), working
tree clean (`git status --short` returned no entries).

**Scope:** analysis and documentation only. No Python source, test, configuration or
`.gitignore` change was made. No Phase 4.9 extraction was performed and nothing was
committed or pushed.

**Method:** every symbol in `script.module.umsa.core/lib/umsa_core/database.py` was read
at this HEAD, then cross-checked against the current production call sites in the
frontend, screensaver and Core. Old audit line counts and stale delegation summaries were
not trusted; where an older audit section conflicts with the current tree, the conflict is
recorded rather than silently rewritten.

**Verification:** the candidate-focused test group was executed during this inventory:

```bash
.venv-debian-vm/bin/python -m pytest \
  tests/test_database.py tests/test_run_scan_with_progress.py \
  tests/test_scan_coordinator.py tests/test_cmd_line_options.py \
  tests/test_umsa_db_download.py tests/test_architecture_boundaries.py -q
# -> 87 passed
```

---

## 1. Current responsibility inventory

`database.py` is 1857 lines at this HEAD. The groups below cover every module-level
function/constant and every `DBMod` method.

### 1.1 Module-level helpers

| Symbol | Location | Responsibility | Callers | Notes |
|---|---|---|---|---|
| `_core_data_paths(db_path)` | module function | Adapt a legacy database-directory argument to `CoreDataPaths` | Internal `DBMod` only | Pure path adapter. |
| `parse_recommended_games(rec_text, db)` | module function | Parse the DAT `Rec` field into popup dicts; calls `db.search_single` per name | GUI `umsa_gui/media_list.py` | Duck-types the `DBMod` API (`search_single`). Not pure: one DB lookup per recommended game. |
| `build_filter_lists(filter_lists, category, db)` | module function | Partition one filter category into `active`/`inactive` dicts using `db.get_all_dbentries` | GUI `umsa_gui/filter_ui.py` | Duck-types `DBMod.get_all_dbentries`; relies on its dict entry shape. |
| `_scan_state_ownership(db, start_what)` | context manager | Acquire the process-wide scan lock, then own `db.scan_perc`/`db.scan_what`/`db.scan_status` | Internal: `run_scan_with_progress`, `DBMod._run_scan_with_shared_state` | Mutates `DBMod` state; depends on `scan_coordinator` and the DBMod progress attributes. |
| `run_scan_with_progress(db, scan_method, scan_args, progress, title, sleep)` | module function | Run a named `DBMod` scan method on a worker thread while polling progress | GUI `umsa_gui/scan_orchestrator.py`; tests | Uses `getattr(db, scan_method)` (only the four scan wrapper names are passed), injected `progress`/`sleep`, and the shared scan state. |
| `COUNTRIES` | module constant | Country/region keyword groups used by `get_best_machine_for_set` | Internal only | Pure data; no other module imports it. |
| `split_gamename(complete_name)` | module function | Split a MAME description into game name and detail/version | GUI `gui.py`, `umsa_gui/gamelist_actions.py`, `umsa_gui/software_selector.py`; tests | Pure regex/string helper, no DB or filesystem. |

### 1.2 Connection lifecycle, schemas and reopening

| Symbol | Responsibility |
|---|---|
| `DBMod.__init__` | Initialise public filter/order/scan state, then open persistent databases; clean up on partial failure. |
| `_open_persistent_databases` | Resolve `CoreDataPaths`, ensure source DBs exist, open read-only `umsa.db` (`sqlite3.Row`), attach `artwork.db`/`dat.db`, open `status.db`, define the initial filter, run `status_migrations.apply_migrations`. |
| `open_db` | Reopen `umsa.db` and reattach `artwork.db`/`dat.db` after a database update; leaves `status.db` open; closes the previous `umsa.db` first; cleans up partial attachments. |
| `_ensure_source_databases` | Create/upgrade `artwork.db` and `dat.db` with their authoritative repository schema helpers. |
| `_attach_source_databases` | Attach `artwork.db` as `art` and `dat.db` as `dat` read-only via URI. |
| `close_umsa_db` / `close` / `close_db` | Idempotent connection teardown; `close_db` is the historical compatibility wrapper for closing only `umsa.db`. |
| `create_dat_tables` / `create_art_tables` | Compatibility wrappers over `dat_repository.create_dat_tables` and `artwork_repository.create_artwork_tables`; also used as scanner initialisation callbacks. |

This group is stateful by definition and must remain in `DBMod`. The `ATTACH` handling
and the read-only `umsa.db` reopen are documented mixed-database exceptions.

### 1.3 Repository accessors and repository delegation

| Accessors | Delegated methods |
|---|---|
| `_get_artwork_repository` (schema `art`) | `get_art_types`, `get_artwork_for_set`, `get_artwork_for_sets` |
| `_get_dat_repository` (schema `dat`) | `get_dat_for_set`, `get_dat_for_sets` |
| `_get_game_repository` (plain `umsa.db`) | `get_set_ids_for_software`, `get_series`, `check_series`, `check_compilation`, `get_maker`, `get_swl`, `get_source`, `get_year`, `get_players`, `get_categories`, `get_parts_for_set_id`, `get_disks`, `get_all_dbentries`, `search_single`, `get_searchresults`, `get_machine_name`, `count_source`, `count_machines_for_swl`, `get_machines`, `get_set_name`, `get_info_by_set_and_swl`, `get_set_info_by_id` |
| `_get_status_repository` (`status.db`) | `get_further_media`, `save_further_media`, `write_status_after_play`, `get_latest_by_software`'s status half |
| `_get_emulator_repository` (`status.db`) | `get_emulators`, `get_emulator`, `save_emulator`, `connect_emulator`, `delete_emulator_connection`, `delete_emulator` |
| `_get_history_repository` (`status.db`) | `load_lastgames`, `save_lastgames`, `list_filter_names`, `load_filter_selections`, `save_filter_selections`, `record_screensaver_display`, `get_screensaver_history`, `get_import_marker` |

There are two presentation/orchestration wrappers in this group:

- `get_status_for_set` reads a raw status row through `StatusRepository` and builds the
  public dict (`time_played`, `last_nice`, `options`, …). The formatting is `DBMod`
  presentation, not repository SQL.
- `get_latest_by_software` combines the `umsa.db` set-id lookup with
  `StatusRepository.get_latest_by_set_ids`.

`run_legacy_import`, `retry_legacy_import` and `discover_legacy_paths` are direct
delegations to `history_import` using `self.sdb` and `self.db_paths`.

### 1.4 Mixed-database and state-dependent queries that remain in `DBMod`

| Method | Why it stays |
|---|---|
| `get_random_id` | Uses the active `filter_join`/`filter_where` state and its bound parameters. |
| `has_artwork` | Joins `art.art_set` with `sets` and uses the active filter before trying an unfiltered fallback. |
| `get_random_art` | Joins `art.art_set` with `sets`, honours the active filter, reads game/machine metadata, and resolves the non-MAME left image via `ArtworkRepository` and the filesystem/root configuration. |
| `get_artwork_by_software_id` | Joins `art.art_set` with `swl`/`sets` and resolves the resulting artwork path. |
| `get_last_played` | Reads `status.db` rows, performs an N+1 `umsa.db` software lookup, aggregates in Python and formats GUI list entries. |
| `get_all_for_software` | Main frontend orchestration: composes `GameRepository` reads with status, best-machine selection, DAT and artwork data. |
| `get_random_vgm_batch` | Worker-owned short-lived read-only `umsa.db` connection on the VGM playback thread (decision Q3). |

`_art_source_roots` is a small helper for `get_random_art`; it is not a standalone
service.

### 1.5 Scan progress and scan-state coordination

`_scan_state_ownership`, `run_scan_with_progress`, `DBMod._run_scan_with_shared_state`
and the four `DBMod.scan_*` wrappers form one group. The scan wrappers contain no SQL:
they inject progress/cancellation callbacks into the scanner modules and bridge the
historical `scan_perc`/`scan_what`/`scan_status` attributes. The lock itself is owned by
`scan_coordinator`; `database.py` owns only the DBMod-facing progress state.

### 1.6 Game labels, formatting, parsing and filter-list construction

`split_gamename`, `COUNTRIES`, `DBMod.make_time_nice`, `DBMod.get_best_machine_for_set`,
`parse_recommended_games` and `build_filter_lists`. `make_time_nice` is also used by the
public `DBMod` method surface (`emulator_launcher.py` calls
`ctx.ggdb.make_time_nice(...)`) and internally by `get_status_for_set`/`get_last_played`.

### 1.7 Emulator command-line and option assembly

`DBMod.create_cmdline` is pure assembly over caller-supplied `parts`/`devices` rows.
`DBMod.get_cmd_line_options` reads through `GameRepository` (software-list options,
machine id, devices, parts, shared-feature requirement), builds the command line,
expands the shared-feature chain and appends `-statename`/`-snapname`. Its only
production caller is `launch_preparer.py` via `ggdb.get_cmd_line_options(...)`.

### 1.8 Database download/update handling

There is no download implementation left in `database.py`. It imports
`download_and_update_umsa_db` from `umsa_core.umsa_db_download` (line 65) and thereby
keeps the old import path working. The download module itself contains only the network
download and zip extraction helper.

### 1.9 Compatibility wrappers and re-exports

- `create_dat_tables` / `create_art_tables` — historical schema-entry methods, used
  internally as scanner callbacks.
- `close_db` — compatibility wrapper for the historical GUI update sequence.
- `download_and_update_umsa_db` — module-level compatibility re-export (Phase 4.9a).
- The `get_by_*` methods and `_get_*_repository` accessors are `DBMod`-internal state
  coordination, not external compatibility escapes.

---

## 2. Phase 4.9 candidate evaluation

The candidates below are evaluated against the current code, not against the original
proposal text.

### 2.1 Scan progress and scan-state coordination

| Aspect | Finding |
|---|---|
| Current location | `_scan_state_ownership` (module), `run_scan_with_progress` (module), `_run_scan_with_shared_state` and the four `scan_*` wrappers (class). |
| Existing helper | `scan_coordinator.ScanLockContext` / `scan_coordinator` already own the process-wide lock. There is no `scan_progress.py` yet. |
| Internal callers | `run_scan_with_progress` uses `_scan_state_ownership`; `_run_scan_with_shared_state` calls it for every scan wrapper. |
| External callers | `umsa_gui/scan_orchestrator.py` imports `run_scan_with_progress` **from `umsa_core.database`**; `tests/test_run_scan_with_progress.py` and `tests/test_scan_coordinator.py` do the same. |
| Dependencies | `threading`, injected `progress`/`sleep`, the process-wide scan lock, and the duck-typed `DBMod` attributes `scan_perc`/`scan_what`/`scan_status`. |
| Public constraints | Function signature, return value (scan summary or `None`), callback signatures (`progress(percent, title, message)`, `sleep(1000)`), scan-state attribute names, and `getattr(db, scan_method)` dispatch. |
| Verdict | **Justified extraction, low risk, but only as a pure move plus a `database.py` re-export.** `scan_progress.py` can own the context manager and `run_scan_with_progress`; `DBMod._run_scan_with_shared_state` can import the context manager, or remain a one-line facade. Do not redesign the scan state in the same step. |

### 2.2 Game-label and application helpers

| Candidate | Current location | Existing provider | Callers | Dependencies | Verdict |
|---|---|---|---|---|---|
| `split_gamename` | module function | None | `gui.py`, `umsa_gui/gamelist_actions.py`, `umsa_gui/software_selector.py`, tests | Pure regex; no DB/FS | **Justified.** Highest-value, zero-risk label extraction. External imports currently target `umsa_core.database`, so a re-export (or a coordinated call-site migration) is required. |
| `make_time_nice` | `DBMod` method | None | `emulator_launcher.py` via `ggdb`; internal status/last-played presentation; tests | Pure time formatting | **Optional.** A module-level function plus a one-line `DBMod` facade preserves the public method. Benefit is small; do not move it alone for line-count reasons. |
| `COUNTRIES` | module constant | None | Internal `get_best_machine_for_set` only | Pure data | **Only with `get_best_machine_for_set`.** Moving the constant alone creates an import without reducing the class. |
| `get_best_machine_for_set` | `DBMod` method | `get_machines` + `COUNTRIES` | Internal `get_all_for_software` only; no direct external caller | Calls `self.get_machines`; preserves several historical selection rules (`famicom_flop`, original/compatible, country matching) | **Keep for now.** No external caller and no direct unit test; extraction would require passing machine rows or a DB handle and risks changing a delicate selection rule. Revisit only with focused characterisation tests. |
| `parse_recommended_games` | module function | `DBMod.search_single` | `umsa_gui/media_list.py` | Duck-typed `DBMod` dependency | **Possible, low value.** A pure move plus re-export is safe, but it would not make the helper DB-independent. Defer unless a label/application module is created for other reasons. |
| `build_filter_lists` | module function | `DBMod.get_all_dbentries` | `umsa_gui/filter_ui.py` | Duck-typed `DBMod` dependency and entry dict shape | **Possible, low value.** Same trade-off as `parse_recommended_games`; also couples to the filter-entry contract. Defer or place in a separate filter-list helper rather than a general label module. |

**Grouping recommendation:** if Phase 4.9 proceeds, create a small `game_labels.py` for
the genuinely pure pieces (`split_gamename`, `COUNTRIES`, and optionally the extracted
body of `make_time_nice`). Do not force `parse_recommended_games` /
`build_filter_lists` into it merely because the old proposal listed them together; they
depend on `DBMod` query APIs and are better left in `database.py` until there is a
concrete reason to move them.

### 2.3 Command-line assembly

| Candidate | Current location | Existing provider | Callers | Dependencies | Verdict |
|---|---|---|---|---|---|
| `create_cmdline` | `DBMod` method | None | Internal `get_cmd_line_options` only; tests exercise it through the latter | Pure assembly; positional `device[0]`/`device[1]` and `part[0]`/`part[1]` access on Core-internal rows | **Justified, low risk.** Move to `cmdline.py` as a module function and keep a one-line `DBMod.create_cmdline` compatibility facade (or update the single internal call). No public external caller was found. |
| `get_cmd_line_options` | `DBMod` method | `GameRepository` reads + `create_cmdline` | `launch_preparer.py` via `ggdb` | Persistent DB state, repository reads, shared-feature chain, logging, `Dictionary`-free assembly | **Keep in `DBMod`.** It is orchestration over repository reads and the public emulator-launch input contract. Extracting the whole method would either move DB access into an assembly module or create a larger input bundle. If desired later, extract only the pure tail assembly after characterisation. |

### 2.4 `umsa_db_download.py` and the compatibility import

| Aspect | Finding |
|---|---|
| Current state | `umsa_core/umsa_db_download.py` exists (32 lines) and contains `download_and_update_umsa_db`. `database.py` imports it at line 65, so `from umsa_core.database import download_and_update_umsa_db` still works. |
| Duplicate implementation | None. `database.py` contains no second definition. |
| Production callers | `umsa_gui/scan_orchestrator.py` still imports the name **from `umsa_core.database`** (through the re-export). Tests import from `umsa_core.umsa_db_download` directly. |
| Public constraints | Preserve the function signature/behaviour and the old import path while any caller still uses it. |
| Verdict | **Already completed (Phase 4.9a).** No extraction work remains. Optional follow-up: migrate `scan_orchestrator.py` to import from `umsa_core.umsa_db_download` directly, then decide whether the `database.py` re-export should stay for compatibility. That call-site migration is not required by Phase 4.9.1. |

---

## 3. `DBMod` facade review

`DBMod` remains the supported public handle used by the frontend (`self.ggdb`), the
screensaver (`self.umsa.ggdb`), `launch_preparer.py` and the emulation layer. The facade
is therefore not judged only by "does it forward one call?".

### 3.1 Pure forwarding methods — keep

These methods are one-line (or near one-line) delegates but are the supported public
interface and keep connection ownership inside Core:

`get_art_types`, `get_artwork_for_set`, `get_artwork_for_sets`, `get_dat_for_set`,
`get_dat_for_sets`, `get_set_ids_for_software`, `get_series`, `check_series`,
`check_compilation`, `get_further_media`, `save_further_media`, `get_emulators`,
`get_emulator`, `save_emulator`, `connect_emulator`, `delete_emulator_connection`,
`delete_emulator`, `load_lastgames`, `save_lastgames`, `list_filter_names`,
`load_filter_selections`, `save_filter_selections`, `record_screensaver_display`,
`get_screensaver_history`, `get_import_marker`, `write_status_after_play`,
`get_maker`, `get_swl`, `get_source`, `get_year`, `get_players`, `get_categories`,
`get_parts_for_set_id`, `get_disks`, `get_all_dbentries`, `search_single`,
`get_searchresults`, `get_machine_name`, `count_source`, `count_machines_for_swl`,
`get_machines`, `get_set_name`, `get_info_by_set_and_swl`, `get_set_info_by_id`.

Removing them would force add-on code to construct repositories or touch connections,
violating the existing Core boundary. Keep them even when they look trivial.

### 3.2 Stateful / coordinating methods — keep

- `set_filter_enabled`, `set_order`, `define_filter`, `execute_statement` and every
  `get_by_*` mutate or read `DBMod`'s public query state. The SQL/composition lives in
  `gamelist_filter.py`; the state holder stays here.
- `get_status_for_set`, `get_latest_by_software`, `get_last_played` and
  `get_all_for_software` combine repositories or apply presentation logic.
- All lifecycle methods (`__init__`, `_open_persistent_databases`, `open_db`, `close*`)
  own persistent connections and are inherently stateful.
- `_get_*_repository` accessors are per-call constructors that prevent a repository from
  pinning a connection replaced by `open_db`; keep them internal.

### 3.3 Mixed queries — keep

`get_random_id`, `has_artwork`, `get_random_art`, `get_artwork_by_software_id`,
`get_random_vgm_batch`, `get_last_played` and `get_all_for_software` remain legitimate
`DBMod` responsibilities (documented mixed queries / worker-owned connection /
orchestration). See `roadmap.md` §"Explicit non-goals".

### 3.4 Compatibility wrappers — keep, with one candidate for later cleanup

- `create_dat_tables` and `create_art_tables` are used as scanner callbacks inside the
  scan wrappers, so they are not removable merely because the repository helpers exist.
- `close_db` is only reachable from tests at this HEAD; the GUI update flow uses
  `close_umsa_db`. It is a documented compatibility wrapper and should not be removed
  without a separate call-site/test migration decision.
- `download_and_update_umsa_db` is a working compatibility re-export, not dead code.
- No method was found that is both unreferenced and safe to remove in this phase.

### 3.5 Summary of facade decisions

| Decision class | Methods |
|---|---|
| Keep — public supported facade | All pure forwarders in §3.1 |
| Keep — state/connection ownership | Lifecycle, scan wrappers, `_get_*`, filter state and `get_by_*` |
| Keep — mixed/orchestration | `get_random_id`, `has_artwork`, `get_random_art`, `get_artwork_by_software_id`, `get_random_vgm_batch`, `get_last_played`, `get_all_for_software`, `get_status_for_set`, `get_latest_by_software`, `get_cmd_line_options` |
| Remove now | None |
| Optional later cleanup | `close_db` after its test call sites are reviewed; `database.py` download re-export after `scan_orchestrator.py` migrates its import |

---

## 4. Justified vs deferred extraction work

### 4.1 Justified by the current code

1. **`scan_progress.py`** — `_scan_state_ownership` + `run_scan_with_progress` as a pure
   move, with `database.py` re-exports and the existing scan-state contract unchanged.
2. **`game_labels.py`** — `split_gamename` (highest confidence), plus `COUNTRIES` and
   optionally the body of `make_time_nice` if that module is created. Keep a `DBMod`
   method facade for `make_time_nice` and a `database.py` re-export for the module-level
   names.
3. **`cmdline.py`** — `create_cmdline` only, keeping a compatibility facade for the
   internal/external method contract. Leave `get_cmd_line_options` in `DBMod`.

### 4.2 Already completed

- **Phase 4.9a** — `download_and_update_umsa_db` lives in `umsa_db_download.py`;
  `database.py` only re-exports it.

### 4.3 Unnecessary / should remain in `DBMod`

- Connection lifecycle, `ATTACH` handling, repository accessors and delegation facades.
- Filter state and `get_by_*` family.
- `get_best_machine_for_set` (no external caller, delicate selection logic).
- `get_cmd_line_options` (orchestration over repository reads).
- Mixed queries `get_random_id`, `has_artwork`, `get_random_art`,
  `get_artwork_by_software_id`, `get_last_played`, `get_all_for_software`.
- Worker-owned `get_random_vgm_batch`.

### 4.4 Deferred pending further evidence

- `parse_recommended_games` and `build_filter_lists` — safe pure moves are possible, but
  both duck-type `DBMod` query methods and have low line-count benefit.
- `make_time_nice` — only worth moving as part of a real `game_labels.py` module, with
  the `DBMod` method preserved.
- Migrating `scan_orchestrator.py` to import the download helper directly.

---

## 5. Open questions for the next Phase 4.9 decision

1. Should Phase 4.9 proceed at all, or is the current 1857-line facade acceptable now
   that repositories and `gamelist_filter` own the SQL?
2. If it proceeds, is the recommended order `scan_progress.py` → `game_labels.py`
   (`split_gamename` first) → `cmdline.py` acceptable?
3. Should `parse_recommended_games` / `build_filter_lists` stay in `database.py`, or be
   moved into a separate application-helper module with their `DBMod` arguments?
4. Should `scan_orchestrator.py` be migrated to import
   `download_and_update_umsa_db` from `umsa_core.umsa_db_download` directly before the
   re-export is considered for removal?
5. Should `close_db` remain indefinitely as a documented compatibility wrapper, or be
   removed in a later test/call-site cleanup?

---

## 6. Documentation impact

This inventory is referenced from:

- `docs/refactor_audit/core_module_inventory.md`
- `docs/refactor_audit/refactoring_plan.md`
- `docs/database_refactor/README.md`
- `docs/database_refactor/roadmap.md`
- `docs/database_refactor/dbmod_audit.md`
- `docs/release_quality_audit/release-plan.md`
