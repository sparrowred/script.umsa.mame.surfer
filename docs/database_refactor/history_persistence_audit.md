# Phase 4.6.1a — `status.db` history & legacy-file migration: audit and plan

**Status: PLANNED — NOTHING IMPLEMENTED.** No production code, schema, migration, test or
user file was changed by this audit or by this document. Every schema, API, migration,
import and cleanup step below is a *proposal* pending the maintainer answers in
section 16.

**Scope of this update:** the finalized direction for moving three related but distinct
concepts into `status.db`, all under **one** versioned schema migration, followed by
**one** durable one-time import of the legacy `lastgames.txt` / `filter_*.txt` files and
their cleanup:

1. GUI backward-navigation history (`lastgames.txt` → `gui_lastgames`).
2. Filter selections (all `filter_*.txt` files → `filter_selections`).
3. Screensaver display history (new, last 100 successfully displayed sets →
   `screensaver_history`; starts empty, **no import**).

Basis: read-only inspection of the working tree at git HEAD `b84341e`, `git log -S`
history searches, plus verification against the **real Kodi profile on this machine**
(`/home/opencode/.kodi/userdata/addon_data/script.module.umsa.core/`) and the contents of
the distributed `umsa_db.zip` (section 12). Line references are to that tree.

Scope restrictions that bound this document: documentation/audit updates only; no
production-code changes; no migrations or schema changes; no tests added or modified; no
deletion or rewriting of actual user files; no implementation of the screensaver
history; no Phase 4.7 work.

---

## 1. Decisions locked by this update

These are settled by the maintainer's instructions and are **no longer open**. They
supersede the earlier revision of this document (which had three migrations v1/v2/v3 and
kept the legacy files as permanent backups).

| # | Decision |
|---|---|
| **D1** | **One schema migration.** GUI lastgames + filter selections + screensaver history ship in **one migration, one `PRAGMA user_version` increment**. They are not split into three migrations. |
| **D2** | **Screensaver history:** last **100** successfully displayed sets, **starts empty**, **no import source**. `load_lastsaver()` stays untouched legacy read-side code and is not used as an active data source. |
| **D3** | **One-time import**, then terminal: discover configured paths → read+validate every known source → preserve order/valid selections → discard (never partially import) malformed files with a warning → record a terminal outcome durably → **commit data + marker** → **only then delete** the recognized inputs → notify the user (mentioning discarded files). |
| **D4** | **No re-import, ever, after a terminal outcome.** Interrupted cleanup after a successful commit degrades to *cleanup only*. A stored failure is reported but never auto-retried; retry is explicit. |
| **D5** | **Files are not permanent backups** — recognized inputs are deleted after the outcome is durably recorded (valid or invalid). A separate backup already exists outside userdata, so deletion is not treated as data-loss. |
| **D6** | **Unknown files are preserved.** Only explicitly recognized migration inputs (and confirmed-obsolete Core-userdata files) may be deleted; no wildcard cleanup. Unclear files are listed for the maintainer before any scope decision. |
| **D7** | **GUI lastgames persists immediately** after a game has been successfully displayed (not at GUI shutdown), and neither lastgames nor screensaver history may be derived from play history (`sets.last_played`/`time_played`/`play_count`). |
| **D8** | **Three concepts stay separate** — different tables, different writers, different lifecycles: navigation history, filter selections, screensaver history. |
| **D9** | **No Kodi imports in `umsa_core`.** The import/migration logic is Kodi-free Core code; the user notification is issued through the existing Kodi-side layer (section 13). |
| **D10** | **Existing data is preserved:** all current play history (`sets`), emulator configuration (`emu`, `emu_conn`) and further-media rows survive untouched — the migration only adds tables. |

---

## 2. GUI `lastgames.txt` — file contract and call sites

### 2.1 Path and format

- Path: `CoreDataPaths.lastgames_file` = `<core profile dir>/lastgames.txt`
  (`data_paths.py:53-54`), resolved in Kodi via `get_core_data_paths()`
  (`lib/umsa_core_kodi.py:37-42`).
- Writer (`save_software_list`, `persistence.py:96-107`): **one line, no trailing
  newline**, comma-separated decimal **software ids** (`"12,34,56"`). Pinned byte-for-byte
  by `tests/test_persistence.py:107-115`.
- Reader (`load_software_list`, `persistence.py:79-93`): reads **only the first line**,
  splits on `,`, `int()` per token. Missing/unreadable → `OSError` → `[]`; non-integer
  token → `ValueError` **propagates** (pinned by `tests/test_persistence.py:118-123`).
- Identity: **software ids** (`software.id`), the same value `get_random_id()`
  (`database.py:852-865`) hands out for padding.
- Real-world sample (verified): the profile on this machine holds exactly one line of
  **10 valid ids** (60 bytes, last written 2026-10-18) — the migration will import real
  data here, not just a hypothetical file.

### 2.2 Internal state, ordering and pointer

- `UMSA.__init__` (`gui.py:246-248`): `self.last = []`, `self.lastptr = 9`.
- `UMSA.onInit` (`gui.py:364-375`): load file → pad with `get_random_id()` until
  `len >= 10` → if no script argument, `select_software(self.last[self.lastptr])`
  (newest entry); if launched with `select_software,<id>` (`addon.py:18-23`,
  `main()` `gui.py:2604-2606`), insert the id at `++lastptr` first, then select.
- **Order: index 0 = oldest, last element = newest.** The file stores the newest ten in
  that order; the resumed pointer is always the newest entry.
- **Backward navigation** (`software_move`, `gui.py:1868-1879`, left/right on
  `SOFTWARE_BUTTON`): left decrements the pointer (no-op at 0) and re-selects; right
  increments and, past the end, **appends a random id** then selects. Pointer moves never
  insert or remove anything else.

### 2.3 Where entries are added (all insert-before-display)

| Site | Trigger |
|---|---|
| `gui.py:370-375` | `onInit` with a `select_software` script argument |
| `gui.py:1243-1248` | `gamelist_click` — Enter on a game-list entry |
| `gui.py:516-521` | `GAME_LIST_OPTIONS` click — search with exactly one hit |
| `gui.py:1803-1808` | `update_gamelist` — any strategy returning exactly one result |
| `gui.py:1430-1436` | `open_software` — screensaver handoff (`VgmCommandMonitor.onNotification`, `gui.py:216-222`) |

All five run `lastptr += 1; last.insert(lastptr, id)` **before** `select_software(...)`.
Consequences, still open (Q1):

- **Duplicates** are allowed (clicking an id already in history inserts it again).
- **Failed displays leave phantom entries**, because `select_software` fails
  (`get_all_for_software` empty → notification + `return`, `gui.py:2037-2043`) *after*
  the insert, and it returns `None` on both the failure and the success path
  (`gui.py:2186`), so callers cannot tell them apart.
- The in-memory list is **unbounded**; only the writer trims to `self.last[-10:]`.

Not affected: hover/selection movement, filter changes, and gameplay (play history is
written by `write_status_after_play`, `gui.py:2539-2542` — a separate concept, D7/D8).

### 2.4 Current write point — the confirmed defect

The **only** write is `UMSA.exit()` (`gui.py:2560-2566`), reached only via the
clean-exit paths (`gui.py:642, 672, 1199, 1233`). Kodi destroying the window (shutdown,
window killed, crash) bypasses it and the session's history is lost.

**Persistence point (D7, decided):** the successful end of `UMSA.select_software`
(`gui.py:2186`) — the single funnel of all five insertion paths, and the only place that
knows the display succeeded (the early return at `gui.py:2037-2043` simply does not
persist). One ordered full-replace write of the trimmed tail per successful display
replaces the exit-time file write. Whether the pre-inserted id is also **removed again**
when the display fails is open (Q1), because that decides what "successfully displayed"
leaves behind in the list.

### 2.5 Robustness today

| Condition | Behaviour |
|---|---|
| missing / empty / unreadable file | `OSError` → `[]` → padded with up to 10 random ids |
| malformed line (`"12,nope"`) | `ValueError` propagates out of `onInit` — GUI startup breaks, no recovery (pinned, `tests/test_persistence.py:118-123`) |
| > 10 ids on disk | loaded fully; trimmed only at the next save |

The import (section 8) must therefore not reuse the crash-prone path blindly: a malformed
file becomes a **discarded input with a warning**, never a startup failure.

---

## 3. Filter selections — file contract (legacy source #2)

### 3.1 Path and format

- `CoreDataPaths.filter_file(name)` = `<core profile dir>/filter_<name>.txt`
  (`data_paths.py:60-65`); `filters_dir` is the same directory (`data_paths.py:48-50`),
  and `SETTINGS_FOLDER = CORE_DATA_PATHS.filters_dir` (`gui.py:80`).
- Format (`save_filter`, `persistence.py:42-61`): **exactly five lines**, always in this
  order — `Softwarelists`, `Game Categories`, `Machine Categories`, `Years`, `Players` —
  each line a comma-separated value list terminated by `\n` (empty line = empty list).
  Pinned byte-for-byte by `tests/test_persistence.py:77`
  (`"a,b\n1\n\n1980\n2,4\n"`) and by the reader's key tuple
  (`persistence.py:29-35`).
- Reader (`load_filter`, `persistence.py:10-39`): missing file (`OSError`) → five empty
  lists; **fewer than five lines → `IndexError` propagates** (pinned as intended
  behaviour by `tests/test_persistence.py:99-104`); more than five lines → extras
  silently ignored; non-UTF-8 → `UnicodeDecodeError` propagates.
- **Write failures are swallowed** (`save_filter` returns silently on `OSError`,
  `persistence.py:47-50`) — same "silently not persisted" family of defect as lastgames.
- **Values are opaque database-id strings**, not display names: `build_filter_lists`
  (`database.py:84-98`) builds active/inactive from `str(entry[0])` (row ids), and
  `define_filter` (`database.py:1176-1240`) interpolates them into
  `swl.id IN (...)`, `category.id IN (...)`, `nplayers.id IN (...)`, `year.id IN (...)`.
  Values are therefore effectively decimal integers, but **nothing validates them** —
  which is exactly why the import's validation strictness is a data-loss decision (Q2).

### 3.2 Discovery, load and save call sites

- **Startup:** `onInit` loads `filter_default.txt` into `self.filter_lists` and sets
  `self.act_filter = 'default'` (`gui.py:344-346`) — *before* `DBMod` is constructed
  (`gui.py:356-361`), which is a sequencing constraint for the post-migration load
  (section 14).
- **Load/Save Filter dialog** (`filter_category`, `gui.py:1304-1356`): names come from
  `os.listdir(SETTINGS_FOLDER)` filtered by the loose prefix test `i[:7] == 'filter_'`,
  name = `i[7:-4]`; Load → `load_filter(filter_file(name))` + `ggdb.define_filter(...)`;
  Save → `save_filter(filter_file(name), self.filter_lists)` + `self.act_filter = name`.
- **Consumption:** `DBMod.__init__(..., filter_lists, ...)` → `define_filter` on open
  (`database.py:309, 1176`), and again after every Load Filter.
- **Not persisted today:** the active filter *name* only lives for the session (fresh
  start always reads `default`), and the runtime query state `use_filter` / `order`
  (`database.py:270-271`) is never written anywhere. Whether any of this should start
  being persisted is Q3 — it would change visible filter behaviour, so it is not decided
  here.
- Real-world profile check: **zero `filter_*.txt` files exist** on this machine (the user
  never saved a named filter), so the import's filter branch currently has no sources
  here; other installations may have many.

---

## 4. `load_lastsaver()` and `lastsaver.txt` — status

Kept from the original audit, aligned with the decision (D2: it is **not** an import
source):

- The brief's premise — *unused legacy code* — is **directionally right but imprecise**:
  `load_lastsaver()` (`persistence.py:64-76`) has one live consumer,
  `gamelist_strategies.last_saver()` (`gamelist_strategies.py:149-166`, menu 84 /
  `M_LSSAVER`, reachable via `gui.py:971` and the shortcut at `gui.py:769-771`,
  context built at `gui.py:1781`).
- **No writer of `lastsaver.txt` exists in any revision** (verified with `git log -S` /
  `git grep` back to the 2017 initial commit), so that menu is permanently empty and the
  helper has never had data to read.
- Historical format (clue only): lines of `setname,swlname`, yielded newest-first
  (`reversed(...)`, `persistence.py:74-76`; pinned by `tests/test_persistence.py:126-131`).
- Consequences for this plan: **no import, no table, no consumption** (D2). The helper
  and the `lastsaver_file` path property stay untouched; removal or rewiring against a
  future history table would be a separate maintainer-triggered step.
- **`lastsaver.txt` is not a recognized migration input**, so the cleanup rule (D5/D6)
  does not cover it: if such a file ever exists in the profile, it is an *unknown* file →
  preserved, listed, and asked about (Q5).

---

## 5. Screensaver — display lifecycle and open semantics

(Unchanged findings; the bound is now decided.)

- Modes: `videos`, `cross`, `slide`, `wall` (`arguments.py:9`); `ScreensaverRuntime`
  holds the screensaver's own `DBMod` (`runtime.py:99-108`).
- **Art selection** (cross/slide/wall): one `get_random_art(self.art_types)` per loop
  iteration (`ui.py:432-446`; `database.py:867-974`) — the dict carries **both** the set
  id (`art['id']` = `sets.id`) and the software id (`art['s_id']` =
  `sets.softwarelink_id`).
- `remember_art(art)` (`ui.py:192-195`, called at `ui.py:435`) stores only one
  `current_software_id`, overwritten each iteration, and fires **before** the bad-image
  rejection (`ui.py:444-446 continue`) — therefore **not** a valid "successfully
  displayed" boundary.
- **Render** happens at `ui.py:454-571`, then the wait loop runs (`ui.py:585-595`,
  abortable by keypress). Videos mode returns early (`ui.py:409-414`); playlist
  insertion stores the software id in the ListItem `'Votes'` tag (`ui.py:390`) and
  actual playback is confirmed asynchronously in `Player.onPlayBackStarted`
  (`ui.py:712+`).
- **No history exists anywhere** (no memory list, no file, no DB write) and random
  selection is history-blind, so nothing depends on this feature yet — it starts empty
  (D2).
- **Still open (Q4), recorded as required:** duplicate display events vs unique sets;
  history ordering key; the exact successful-display boundary per mode; and the stored
  identifier (set id / software id / both) — the brief says "sets", so the recommendation
  is `set_id` with a nullable `software_id`.

---

## 6. Storage model — four new tables, one schema

All four live in `status.db` alongside the existing tables (D1, D10). All are proposals.

### 6.1 `gui_lastgames` — backward-navigation state

```sql
CREATE TABLE IF NOT EXISTS gui_lastgames (
    position    INTEGER PRIMARY KEY,   -- 0..n-1, oldest -> newest
    software_id INTEGER NOT NULL
)
```

- Order is data (position as primary key); read with `ORDER BY position`.
- **No timestamps, no UNIQUE constraint** — it is navigation state, not play history and
  not screensaver history; duplicates remain representable until Q1 says otherwise.
- **Write semantics: full replace** of the newest ten ids in one savepoint (mirrors
  `save_software_list`'s whole-file rewrite; the in-memory list stays authoritative).
- Written immediately after a successful display (D7), *not* at shutdown.
- The pointer (`lastptr`) is not persisted — restart resumes at the newest entry, exactly
  like today.

### 6.2 `filter_selections` — saved filter files

```sql
CREATE TABLE IF NOT EXISTS filter_selections (
    filter_name TEXT    NOT NULL,   -- filename part: 'default', 'arcade', ...
    category    TEXT    NOT NULL,   -- 'Softwarelists' | 'Game Categories' |
                                   -- 'Machine Categories' | 'Years' | 'Players'
    position    INTEGER NOT NULL,   -- value order within the category (file order)
    value       TEXT    NOT NULL,   -- opaque id string, preserved verbatim
    PRIMARY KEY (filter_name, category, position)
)
```

- One row per selected value; an empty category or an empty file has **no rows** (the
  faithful equivalent of an empty line); a filter that does not exist has no rows (the
  faithful equivalent of a missing file).
- **Verbatim preservation:** the five category labels are exactly the `load_filter` /
  `save_filter` key names (`persistence.py:13-19, 29-35`); values keep their file order
  via `position` (order is not load-bearing for queries — `define_filter` uses `IN (...)`
  and `build_filter_lists` uses set membership — but the brief requires preserving
  ordering semantics); `filter_name` is the filename part of `filter_<name>.txt`.
- **Write semantics: full replace per `filter_name`** in one savepoint, mirroring
  `save_filter`'s whole-file rewrite.
- The active-filter name, `use_filter` and `order` are **not** part of this table (they
  are not persisted today) — Q3.
- Exact row mapping is Q3's confirmation item; nothing is reinterpreted (no re-labelling,
  no id→name conversion, no cross-checking against `umsa.db` — the two databases are
  separate connections and no referential check is planned).

### 6.3 `screensaver_history` — last 100 displayed sets (empty at creation)

```sql
CREATE TABLE IF NOT EXISTS screensaver_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic display-event identity
    set_id       INTEGER NOT NULL,                   -- pending Q4 (brief says "sets")
    software_id  INTEGER,                            -- pending Q4
    displayed_at DATETIME                            -- 'YYYY-MM-DD HH:MM' (proposed)
)
```

- Retrieval: `ORDER BY id DESC LIMIT 100`; prune beyond the newest 100 inside the same
  savepoint as the insert.
- Duplicate events, ordering key and identifier are Q4 (schema may simplify if the
  answer is "unique sets only").
- No import, ever — starts empty (D2).

### 6.4 `status_meta` — durable import marker

```sql
CREATE TABLE IF NOT EXISTS status_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
```

Marker design: **one row**, key `legacy_import`, JSON value — deliberately not a
per-file state machine (section 9).

---

## 7. The single schema migration (D1)

### 7.1 Mechanism

- New Core module **`umsa_core/status_migrations.py`** (Kodi-free; the maintainer's
  previously stated preference for "migration in eigenem migrations modul").
  - `CURRENT_VERSION = 1`; `MIGRATIONS = {1: <fn>}` — **exactly one entry**.
  - `apply_migrations(connection) -> int`: read `PRAGMA user_version`; if `0`, run the
    single migration in **one transaction**, then set `PRAGMA user_version = 1` in that
    same transaction; on failure the transaction rolls back and the exception
    **propagates** (never swallowed), leaving version 0 stored.
  - `PRAGMA user_version` cannot be parameterised — literal ints only.
- **Authoritative DDL stays with the owners:** the single migration body calls the
  existing `create_status_tables()` (`status_repository.py:40-69`),
  `create_emulator_tables()` (`emulator_repository.py:48-83`) and the new
  `create_history_tables()` — one definition per table, `CREATE TABLE IF NOT EXISTS`
  throughout, so the body is idempotent for both fresh and legacy databases.
- **Call site:** `DBMod._open_persistent_databases` (`database.py:289-316`) replaces the
  two direct helper calls (`database.py:314-315`) with `apply_migrations(self.sdb)` on
  the real `status.db` connection. Never `umsa.db`, never any other connection.

### 7.2 Why one increment 0 → 1 covers everything

- Every existing `status.db` in the field is at version **0** (verified on the real
  profile: `user_version = 0`, tables `emu`, `emu_conn`, `sets`) and already contains the
  three legacy tables via `IF NOT EXISTS`.
- Version **1** therefore declares the *finalised* schema in full: baseline (the three
  existing tables, re-declared idempotently — a no-op on legacy databases) **plus** the
  four new tables. Fresh database and legacy database both converge to the same state
  with a single version advance, exactly as D1 requires.
- The previously proposed split (v1 baseline, v2 lastgames+meta, v3 screensaver) is
  **dropped** — it would be three increments for what must be one.
- Existing play history, emulator configuration and further-media data are untouched
  (D10): the migration only ever *adds* tables.
- Test churn this causes when implemented (listed for the later task, not done now):
  `tests/test_status_repository.py:136-137,175`,
  `tests/test_emulator_repository.py:225-226,269`, `tests/test_database.py:360-361` all
  pin `user_version == 0` and must be updated.
- **Migration failure** (exception at open) aborts `DBMod.__init__` → GUI startup fails
  with the source files **untouched** (nothing imported, nothing deleted). That is the
  safe failure mode; no marker is involved because no import was attempted.

---

## 8. One-time legacy import and cleanup

Core function, Kodi-free, e.g. `history_repository.import_legacy_files(connection, paths)
-> ImportResult` in a later task; orchestrated by the GUI at startup (section 10).

### 8.1 Sequence (fixed order — the brief's steps 1–8)

1. **Discover configured legacy paths.** Only `CoreDataPaths`-derived locations:
   `lastgames_file`, and every `data_dir/filter_*.txt` whose name part passes the
   `filter_file()` validation (`non-empty`, `Path(name).name == name`, not `.`/`..`,
   `data_paths.py:60-65`). No wildcard search outside the profile, no recursion.
2. **Read and validate every discovered source** (per-file all-or-nothing, 8.2).
3. **Preserve semantics:** lastgames keep their file order (index 0 → `position` 0,
   newest last); filter files keep category labels, value order and value strings (6.2).
4. **Malformed file = discarded as a whole**, recorded as a warning (its *contents* are
   never partially imported) — and valid files are still imported in the same run.
5. **Record a terminal outcome** (section 9), including whether any inputs were
   discarded, plus the full list of recognized input paths to delete.
6. **Commit** data rows + marker + pending-delete list in **one transaction**.
7. **Only after that commit**, delete the recognized input files — valid *and* invalid
   ones (D5). Missing files count as already deleted.
8. **Notify the user** (section 13) that migration completed, naming any discarded
   files and any paths that could not be deleted.

Special outcomes:

- **No sources at all** (both configured sets empty after checking every path) → record
  `completed_no_source` and stop. No searching, no retrying on later startups (D4).
- **Import failure** (see 9.3) → record `failed` where possible, do not delete anything,
  do not auto-retry.

### 8.2 Per-file validation rules (what "malformed" means — Q2 decides strictness)

The reader helpers are intentionally *not* reused blindly here, because they crash on
exactly the inputs the import must survive (`ValueError`, `IndexError`,
`UnicodeDecodeError`). Proposed rules, each file validated as a unit:

| Source | Proposed valid shape | On failure |
|---|---|---|
| `lastgames.txt` | decodable text; **exactly one** non-empty line (optional trailing newline) of non-empty decimal-integer tokens, no spaces | whole file discarded, warning recorded, still counted as a recognized input for deletion (D5) |
| `filter_<name>.txt` | decodable text; **exactly five** lines; each line empty or comma-separated non-empty tokens; name part passes `filter_file()` validation | same: whole file discarded + warning + still deleted afterwards |

Open (Q2): whether "exactly one line / exactly five lines / integer tokens only" should
be this strict, or looser (first-line-only like today's loader, extras ignored). This is
the one validation decision that can turn a *partially readable* file into a *discarded*
file, so it is deliberately not guessed (section 8 / mandatory clarification rule).

Deliberately **not** validated: whether an id still exists in `umsa.db`
(`umsa.db` may be absent or being re-downloaded at first startup; ids are opaque
strings).

---

## 9. Durable import marker and failure state

### 9.1 One marker, four terminal values

Single `status_meta` row, key `legacy_import`, JSON value:

```json
{"status": "completed | completed_discards | completed_no_source | failed",
 "discarded":  ["filter_arcade.txt", ...],
 "pending_cleanup": ["/abs/path/lastgames.txt", ...],
 "error": "free-text, only for status=failed"}
```

| Status | Meaning | Startup behaviour |
|---|---|---|
| `completed` | imported and recorded, nothing discarded | never import again (D4); run `pending_cleanup` if non-empty |
| `completed_discards` | imported, ≥1 invalid file discarded | same, and the notification names the discarded files |
| `completed_no_source` | no legacy sources found at all — intentional completion | never import again, never search again |
| `failed` | import attempted and failed; **awaiting explicit retry** | report the stored failure, attempt nothing (9.3) |

- A terminal value is terminal **forever** — there is no path from any `completed*`
  back to an import attempt (D4).
- `discarded` is stored (not just printed) so the discard warning can be reported again
  on a later startup, not only in the very first notification.
- `pending_cleanup` is written **in the same commit as the data and the status**, and
  shrinks as files are removed; it is empty/absent once cleanup is done.
- This is deliberately *not* a per-file state machine: one status plus two small
  path/name lists (a three-key variant would be equivalent; single-row JSON is the
  recommendation).

### 9.2 Commit-before-delete invariant

Data rows + marker + `pending_cleanup` are one transaction (brief step 6). File deletion
(7) happens strictly afterwards, in the same startup, and the per-file deletion progress
is written back with small follow-up transactions. Therefore:

- **Never** claim completion or delete a valid source before the data and marker have
  committed.
- A crash between commit and deletion leaves a terminal marker **plus** a non-empty
  `pending_cleanup` → next startup performs **cleanup only**, never a re-import (D4).
- A crash during the write-back of `pending_cleanup` can only leave already-deleted
  paths listed; re-running deletion treats "file does not exist" as success. Bounded and
  safe.

### 9.3 Failure and explicit retry

- Any exception inside step 2–6 → **no data commit** (single transaction rolls back), no
  file deletions, and a best-effort second small transaction writing `status = "failed"`
  (+ error text).
- Next startup: **report the stored `failed` state** (notification), attempt nothing —
  no silent re-attempt (D4).
- Retry is **explicit**: after the underlying problem is reviewed/corrected, the user
  triggers a retry (proposed vehicle: a dedicated frontend script command, e.g.
  `RunScript(plugin.program.umsa.mame.surfer,retry_import)`, alongside the existing
  `del_db` / `del_status` commands in `addon.py:18-37`), which clears the marker and
  re-runs 8.1. Exact trigger is Q6.
- **Documented limitation (must be confirmed — Q6):** if `status.db` itself cannot be
  written (disk full, corrupt file, read-only profile), even the `failed` marker cannot
  be recorded. The plan then has *no* durable state at all, and the next startup would
  simply see "no marker" and re-attempt — i.e. exactly the silent automatic retry the
  brief forbids, or alternatively the valid sources would be left in place forever with
  no visible signal. **No fallback is adopted here**: neither silent retry nor any
  discard of valid data will be chosen without the maintainer's explicit approval.
- Related, already-defined destructive action to keep in mind: `del_status`
  (`addon.py:31-35`) deletes `status.db`, which also erases the marker. Because the
  legacy inputs were deleted after the successful import, a post-`del_status` startup
  finds no sources and records `completed_no_source` — self-consistent, no re-import
  risk (D4).

---

## 10. Startup and recovery behaviour

All checks happen during GUI startup (brief §4), after `DBMod` is open:

| Condition observed | Action |
|---|---|
| `PRAGMA user_version == 0` | apply the single migration (7.1); failure aborts startup with files untouched |
| no `legacy_import` marker | run the one-time import (8.1) |
| marker `completed*`, `pending_cleanup` empty | nothing; never import again |
| marker `completed*`, `pending_cleanup` non-empty (deletion was interrupted) | **cleanup only** — delete the listed paths, update the list, report leftovers; **no re-import** (D4) |
| marker `completed_discards` (any time) | report the discarded files in the notification |
| marker `failed` | report the stored failure state, start **no** attempt (9.3) |

- Ordering constraint found in the audit: `onInit` currently loads the default filter
  **before** `DBMod` is created (`gui.py:344` vs `gui.py:356-361`), while the migration
  runs at `DBMod` open. The post-migration load of `filter_selections` therefore requires
  reordering those statements (DB first, then read selections) — a mechanical
  implementation detail with no intended visible behaviour change, recorded so it is not
  "discovered" later.
- Notification vehicle: section 13. Migration/import logic itself stays Kodi-free (D9).
- On a brand-new profile (no legacy files, `umsa.db` not yet downloaded) the first
  startup still reaches `status.db` and records `completed_no_source` immediately.

---

## 11. Legacy file deletion policy

- **Recognized inputs** (the only files this feature may delete):
  `CoreDataPaths.lastgames_file` and every validated `data_dir/filter_*.txt` —
  **including malformed/invalid ones** (D5). Deletion happens only after the outcome is
  durably committed (9.2).
- **Original files are not kept as backups** (D5); a separate backup already exists.
  This reverses the earlier revision of this document, which kept them.
- **Cleanup failure** (permission, lock): leave the file, keep its path in
  `pending_cleanup`, record and report the remaining path; subsequent startups **retry
  deletion only** — never the database import (D4).
- **Never deleted:** anything else — `settings.xml`, the four database files, and every
  unrecognized/unknown file (D6). No wildcard/glob deletion outside the exact recognized
  patterns, no directory-wide cleanup.
- **Unknown files** (e.g. a `lastsaver.txt`, or anything else found in the profile at
  implementation time): preserved, listed for the maintainer, and asked about before
  being added to any cleanup scope (Q5).

---

## 12. Core userdata inventory — verified layout

"Expected final contents: `settings.xml` and the intended database files." Verified three
ways (this machine, 2026-10-18):

1. **Real profile:** `/home/opencode/.kodi/userdata/addon_data/script.module.umsa.core/`
   contains exactly: `settings.xml` (729 B), `umsa.db` (147 MB), `dat.db` (207 MB),
   `status.db` (24 KB; `user_version = 0`; tables `emu`, `emu_conn`, `sets` plus
   `sqlite_sequence`), and `lastgames.txt` (60 B, 10 ids). **No** `filter_*.txt`, **no** `lastsaver.txt`, **no**
   `artwork.db` (not yet created — it appears only after the artwork/eXoDOS/GB64 scans
   first run, `artwork_scanner.py:431`, `exodos_scanner.py:247`).
2. **Downloaded archive:** `http://umsa.info/umsa_db.zip` (11,455,966 B) contains
   **exactly one member, `umsa.db`** (verified via ranged read of the zip central
   directory) — so `download_and_update_umsa_db` (`database.py:101-119`) cannot introduce
   any other file into the profile.
3. **Code producers:** the only writers into `data_dir` are `sqlite3.connect` (the four
   DBs), `persistence.save_filter` / `save_software_list` (the legacy inputs),
   `download_and_update_umsa_db` (`umsa.db`), and Kodi itself (`settings.xml`).
   Transient `status.db-journal` files may exist during a transaction (default journal
   mode; `sqlite.py:24` configures no WAL) and are not persistent content.

**Therefore, after a successful migration + cleanup the directory should contain:**
`settings.xml`, `umsa.db`, `status.db`, `dat.db`, and `artwork.db` once scans have run —
nothing else (the only removals being `lastgames.txt` + `filter_*.txt`).

Notes: the frontend's own profile
(`/home/opencode/.kodi/userdata/addon_data/plugin.program.umsa.mame.surfer/`, only
`settings.xml`) is a **different directory and out of scope**. The verified absence of
unexpected files applies to *this* machine; on other installations section 11's
"preserve and ask" rule governs whatever else is found.

---

## 13. Core/Kodi boundary, minimal API and notification

- **No new Kodi imports in `umsa_core`** (D9); the step-4.0 AST guard applies unchanged.
- New Core module `umsa_core/history_repository.py` (4.5/4.6 conventions: caller-owned
  connection, `require_row_connection`, savepoint write ownership, per-call
  construction):
  - `create_history_tables(cursor)` — authoritative DDL for the four new tables (called
    from the migration).
  - `read_lastgames() -> list[int]` / `replace_lastgames(ids) -> None` (trim to newest 10).
  - `read_filter_selections(name) -> dict[str, list[str]]` /
    `replace_filter_selections(name, lists) -> None` / `list_filter_names() -> list[str]`.
  - `import_legacy_files(paths) -> ImportResult` (section 8) and
    `record_import_result(...)` / `get_import_marker()`.
  - later, for the screensaver: `record_screensaver_display(...)`,
    `get_screensaver_history(limit=100)`.
- **DBMod facades** (the connection-attribute guard forbids add-ons touching `.sdb`, so
  both the GUI and the screensaver go through `DBMod`): `load_lastgames` /
  `save_lastgames`, `load_filter_selections` / `save_filter_selections` /
  `list_filter_names`, `get_import_marker` / `run_legacy_import` (later
  `record_screensaver_display`), each a one-line delegate to a per-call
  `_get_history_repository()` mirroring `_get_status_repository` (`database.py:747-755`).
- **Notification:** issued from the Kodi side after the Core function returns its
  result. Per the instruction to use the existing adapter: add a small notification
  helper to **`lib/umsa_core_kodi.py`** (the single permitted Kodi adapter in the core
  add-on) and call it from the frontend's startup path; alternatively the frontend's
  established `xbmcgui.Dialog().notification(...)` pattern (`gui.py:513, 1793, 2040`)
  can be used directly. Either way, `umsa_core` stays Kodi-free and no *second* adapter
  is created.
- `umsa_core_python.py` is not assumed to exist (still a roadmap item).

---

## 14. Relationship to Phase 4.7 and ordering (revised)

The five responsibilities stay separate:

| Responsibility | Home | Step |
|---|---|---|
| GUI lastgames persistence (immediate) + its one-time import/cleanup | `history_repository.py` + `status_migrations.py` + GUI call sites | **4.6.1** (this plan) |
| Filter-selection persistence + its one-time import/cleanup | same repository/migration, `filter_selections` table, GUI Load/Save call sites | **4.6.1** (same migration, D1) |
| Screensaver history (writes only, starts empty) | same repository, `screensaver_history` table, screensaver call sites | **4.6.2** (gated on Q4) |
| Filter *query* composition, filter-state accessors, parameterisation | `gamelist_filter.py` (4.7) | **4.7** — acceptance criteria unchanged |
| Play history (`sets.last_played`/`time_played`/`play_count`) | untouched; separate concept (D7/D8) | — |

**Dependency on Phase 4.7 (documented as required):** the migration itself is additive
and code-wise disjoint from 4.7 (it touches `_open_persistent_databases` plus new
modules; 4.7 touches `define_filter`/`execute_statement`/`get_by_*` and adds
`use_filter`/`order` accessors). The dependency is on the **consumption side**: the
persisted filter selections are handed to `define_filter`, i.e. into the exact filter
state that 4.7 turns into explicit input. Building the new filter-selection load path
*before* 4.7 means writing it against the implicit-state API and re-touching it during
4.7.

**Consequence: this revision reverses the previous recommendation.** The earlier "land
4.6.1 before 4.7" advice (front-load the `user_version == 0` test churn) was written
when the scope was lastgames-only. With filter selections now in the same migration, the
recommended order is **4.7 first (at minimum its pre-work: filter-state accessors + the
unbound-`order` fix), then 4.6.1 implementation**, then 4.6.2. The earlier argument still
holds for the schema-only pieces, which *could* land before 4.7 without conflict — hence
the sequence itself is a confirmation item (Q7). Either way, **4.7's scope and
acceptance criteria are not changed by this plan.**

---

## 15. Implementation and regression-test plan (later task — not executed)

Ordered, characterisation-first, none of it done now:

1. **Migration module** — `status_migrations.py`, single `MIGRATIONS = {1: ...}`
   calling the three `create_*` helpers; swap the call site; tests: fresh DB (all seven
   tables, `user_version == 1`), legacy DB seeded with representative `sets`/`emu`/
   `emu_conn` rows at version 0 (rows byte-preserved, version → 1), injected failure
   (version stays 0, rollback), and update the three `user_version == 0` assertions.
2. **History repository** — four tables via `create_history_tables`; round-trips for
   lastgames (order, trim-to-10, duplicates), filter selections (five categories, value
   order, empty categories, replace-per-name), marker read/write; Row-contract
   rejection; savepoint ownership.
3. **Import + validation** — valid lastgames (order preserved), valid filters, malformed
   file A alongside valid file B (B imported, A discarded + recorded), all-empty (→
   `completed_no_source`), marker-present re-run (no-op, DB state kept), failure →
   `failed` + no deletion + no auto-retry on the next simulated startup.
4. **Cleanup** — deletion after commit; interrupted deletion → cleanup-only path;
   un-deletable file → path recorded and reported; **unknown files untouched**
   (assert a `lastsaver.txt` and a stray `.txt` survive every path).
5. **GUI wiring** — immediate lastgames persist at `select_software` success, DB-backed
   filter load/save replacing `load_filter`/`save_filter` calls (reordered around `DBMod`
   creation), DB-backed Load/Save Filter name list replacing the `os.listdir` scan
   (`gui.py:1311-1313`), notification at startup. `tests/test_persistence.py`'s pinned
   file behaviours stay green — the helpers remain for the import path.
6. **Screensaver history (4.6.2, after Q4)** — repository methods + boundary hooks.
7. Full suite + per-file ruff/mypy comparisons. No Kodi-runtime automation exists
   (`AGENTS.md`) — GUI/screensaver behaviour is verified manually.

No test is added or modified by this document.

---

## 16. Open questions requiring a decision

Unanswered items are exactly the ones the brief requires asking about (data-loss,
deletion, order/duplicates, filter semantics, screensaver semantics, display boundary,
DB-failure recovery). None of them has been guessed in the sections above.

- **Q1 — GUI lastgames duplicates and failed displays (order/duplicate handling).**
  (a) Preserve today's duplicate-insert behaviour, or dedup? (b) On a *failed* display
  (`gui.py:2037-2043`), leave the pre-inserted id in the list (status quo) or
  rewind/remove it so history only contains displayed games? (c) Confirm order stays
  file order (oldest→newest, newest = resume point) with duplicates allowed by schema.
  *Recommendation:* preserve duplicates (no behaviour change), **remove** the entry on a
  failed display (it is what "successfully displayed" means), keep order as is.
- **Q2 — Validation strictness (data-loss decision, must not be guessed).** Proposed:
  exactly one line for `lastgames.txt`; exactly five lines + decimal-integer tokens for
  `filter_*.txt`; anything else = whole file discarded + warning + still deleted after
  commit. Alternatives: first-line-only/extra-lines-ignored (what today's loaders do)
  or non-integer values accepted verbatim. This decides which files lose their contents.
  *Recommendation:* strict (matches the writers we ship), with the discard reported by
  name in the notification and recorded in the marker.
- **Q3 — Filter semantics beyond the files.** Confirm: verbatim id strings per the five
  fixed category labels; value order preserved via `position`; empty category = no rows;
  `filter_name` = filename part; empty/missing file ≡ no rows. Also decide whether the
  **active filter name**, `use_filter` and `order` start being persisted (they are not
  today — persisting them would change what the GUI shows on the next start) and whether
  the Load/Save dialog should keep offering exactly the imported names.
  *Recommendation:* verbatim import as stated; persist none of the runtime state in this
  step (no behaviour change).
- **Q4 — Screensaver history semantics.** (a) Duplicate display events allowed (event
  log) or unique sets with recency move-up? (b) Ordering key (monotonic `id` vs
  `displayed_at`)? (c) The successful-display boundary: post-render in the
  cross/slide/wall loop (`ui.py:571`) and `Player.onPlayBackStarted` for videos
  (`ui.py:712`) — confirm, noting `remember_art` fires before image rejection and is not
  a boundary. (d) Identifier: the brief says "sets" — `set_id NOT NULL` with nullable
  `software_id`? *Recommendation:* event log (duplicates allowed), order by `id`, the two
  boundaries above, both ids stored.
- **Q5 — Unexpected userdata files.** Confirm the rule: only `lastgames.txt` and
  validated `filter_*.txt` are deleted; anything else found (e.g. `lastsaver.txt`, which
  nothing in the repository has ever written) is preserved and listed for you.
  *Recommendation:* preserve `lastsaver.txt`; list it at implementation time.
- **Q6 — Recovery after a database-level failure (must not be guessed).** (a) How is the
  explicit retry triggered (proposed: a frontend script command alongside
  `del_db`/`del_status`)? (b) The limitation in 9.3: when even the `failed` marker cannot
  be written, what is the approved fallback — silent re-attempt on next startup (forbidden
  by the brief), leaving valid sources in place with no durable signal, or a non-database
  fallback marker? **No fallback is adopted until you decide.**
- **Q7 — Ordering vs Phase 4.7.** This revision recommends **4.7 first, then 4.6.1**,
  superseding the earlier lastgames-only recommendation (section 14); the alternative
  (schema/import first, filter consumption after 4.7) remains technically valid.
  *Recommendation:* confirm 4.7 first.

Resolved by the brief and no longer open: history bound = **100** (old Q1a), screensaver
starts empty with no import (old Q6 partly), one migration instead of v1/v2/v3 (old Q7),
deletion of legacy files instead of keeping them as backups (old "keep the text file"
rule), and immediate lastgames persistence (old "proposed point" wording).

---

## 17. Document status

Audited and updated at HEAD `b84341e`. **Nothing implemented:** no production code, no
schema, no migration, no tests, no user file was deleted, renamed or rewritten — the
real profile listed in section 12 was opened **read-only**. Companion updates in this
directory: the step 4.6.1a entry and execution-order note in `roadmap.md`, the checklist
/ documents / next-step entries in `README.md`. Decisions from section 16 must be
recorded here before any implementation task is written.
