# Phase 4.6.1a — GUI Lastgames & Screensaver History Persistence: Audit and Plan

**Status: AUDITED / PLANNED — nothing in this document is implemented.** No production
code, schema, migration, test or user file was changed by this audit. Every schema,
API, migration and import below is a *proposal* pending maintainer answers to the
open questions in section 10.

Basis: read-only inspection of the working tree at git HEAD `b84341e` ("refactor(database):
move emulator configuration to emulator_repository"), plus `git log -S` / `git grep`
across the full history for the file-based helpers. Line references are to that tree.

Two distinct requirements are audited separately, as mandated:

1. **GUI lastgames** — the recently-displayed-games list used for backward navigation
   (`lastgames.txt` today); must eventually be persisted in `status.db` *immediately
   after a successful display*, not only at GUI exit.
2. **Screensaver history** — a *planned, not implemented* feature: store the last 100
   sets actually displayed by the screensaver in `status.db`.

They are different features with different identifiers, semantics and event boundaries
and must **not** share a table.

---

## 1. GUI `lastgames.txt` — file contract and call sites

### 1.1 Path and format

- Path: `CoreDataPaths.lastgames_file` = `<core profile dir>/lastgames.txt`
  (`script.module.umsa.core/lib/umsa_core/data_paths.py:53-54`), resolved in Kodi via
  `umsa_core_kodi.get_core_data_paths()` (`lib/umsa_core_kodi.py:37-42`) — the shared
  Core profile (`xbmcaddon.Addon(id="script.module.umsa.core").getAddonInfo("profile")`).
- Format (writer: `save_software_list`, `persistence.py:96-107`): **one line, no trailing
  newline**, comma-separated decimal **software ids** (`"12,34,56"`). Round-trip pinned by
  `tests/test_persistence.py:107-115`.
- Format (reader: `load_software_list`, `persistence.py:79-93`): reads **only the first
  line** (`readline()`), splits on `,`, converts each token with `int()`. Missing/unreadable
  file → `OSError` caught → empty list. Non-integer token → `ValueError` **propagates**
  (pinned by `tests/test_persistence.py:118-123`).
- Identifier semantics: **software ids** (`software.id` in `umsa.db`), *not* set ids and
  not play-history rows. `DBMod.get_random_id()` (`database.py:852-865`) also returns
  software ids, which is what the random padding inserts.

### 1.2 Internal state, ordering and pointer

- `UMSA.__init__` (`gui.py:246-248`): `self.last = []`, `self.lastptr = 9`.
- `UMSA.onInit` (`gui.py:364-375`):
  - `self.last = load_software_list(CORE_DATA_PATHS.lastgames_file)`;
  - padded with `get_random_id()` until `len(self.last) >= 10` (entries appended);
  - if no `initial_software_id`: `select_software(self.last[self.lastptr])` — index 9,
    i.e. the **last element = most recently displayed**;
  - else (script launch `RunScript(plugin…,select_software,<id>)`, `main()`
    `gui.py:2604-2606`, `addon.py:18-23`): `lastptr += 1`, `last.insert(lastptr, id)`,
    then `select_software`.
- **Ordering: index 0 = oldest, last element = newest.** File order equals in-memory tail
  order (`self.last[-10:]` written verbatim).
- **Backward navigation** (`software_move`, `gui.py:1868-1879`, bound to left/right on
  `SOFTWARE_BUTTON` via `gui.py:645-650`):
  - left: `lastptr -= 1` (no-op at 0), `select_software(last[lastptr])` — moves toward
    older entries, **without removing** anything;
  - right: `lastptr += 1`; if past the end, **appends a random id**, then selects.
- `lastptr` is **not** persisted; on restart the pointer always resumes at the newest
  entry (index 9 after padding).

### 1.3 Where entries are added

All additions are `lastptr += 1; last.insert(lastptr, software_id); select_software(...)`
— **insert-before-display**, so a failed display still leaves the id in the list:

| Site | Trigger |
|---|---|
| `gui.py:370-375` | `onInit` with a `select_software` script argument |
| `gui.py:1243-1248` | `gamelist_click` — Enter on a game-list entry |
| `gui.py:516-521` | `onClick` `GAME_LIST_OPTIONS` — search with exactly one hit |
| `gui.py:1803-1808` | `update_gamelist` — any strategy returning exactly one result |
| `gui.py:1430-1436` | `open_software` — screensaver context-menu handoff, dispatched from `VgmCommandMonitor.onNotification` (`gui.py:216-222`) via `umsa_core_kodi.send_software_open` |

Not affected by: selection/hover movement in the game list (`gamelist_move` only refreshes
artwork), left/right pointer moves (no insert), filter changes, or playing a game
(`run_emulator` writes play history to `status.db` via `write_status_after_play`,
`gui.py:2539-2542` — a **separate** concept).

**Duplicates exist today:** clicking a game that is already in history inserts it again
(no dedup anywhere). Pointer moves never create duplicates. Whether to preserve this
exactly is open question **Q5**.

**Type quirk (pre-existing, documented not fixed):** the single-result paths insert
`results[0]['id']` which is an int for all current strategies, but `popup_gamelist`
stringifies ids for the UI (`gui.py:1837`) and a future strategy returning a non-int id
would be persisted as-is and then crash `load_software_list`'s `int()` on the next start.

### 1.4 List-size limit

- In-memory: **unbounded** — every insert grows the list; sessions can accumulate more
  than 10 entries.
- On disk: **last 10 only** — `save_software_list(..., self.last[-10:])` trims to the
  newest ten (tail).
- On load: padded up to **at least 10** with random ids, so index 9 always exists.
- Consequence: on a fresh profile the persisted list can contain up to 9 entries that
  were **never displayed** (pure random padding), and after a short session the tail can
  be mostly padding. The product requirement is "recently *displayed* games"; the current
  implementation approximates it.

### 1.5 Successful vs failed display

`select_software` (`gui.py:2015-2186`) is the single funnel every display path goes
through. On failure (`get_all_for_software` returns no machines, `gui.py:2037-2043`) it
logs, shows a notification and **returns `None` early**; on success it also returns
`None` (end of method, `gui.py:2186`). **Callers cannot currently distinguish success
from failure**, and because the list insert happens *before* the call, a failed display
leaves a phantom history entry and a moved pointer. This is the exact gap the "persist
immediately after successful display" requirement must close (open question **Q4**).

### 1.6 Current write point — the shutdown-only defect

The **only** write to `lastgames.txt` is `UMSA.exit()` (`gui.py:2560-2566`:
`save_software_list(CORE_DATA_PATHS.lastgames_file, self.last[-10:])`). `exit()` runs only
on the clean-exit paths:

- `ACTION_CANCEL_DIALOG` (back/escape etc., `gui.py:621-642`) on the main screen;
- the `M_EXIT` main-menu item (`gui.py:671-672`);
- two media hand-offs that close the GUI first (`gui.py:1199`, `gui.py:1233`).

There is **no** `onNotification`-independent close hook, no `onClosed`, and `main()`
(`gui.py:2609-2610`) just ends `doModal()` and deletes the object — so if Kodi destroys
the window (system shutdown, window killed, crash, unhandled exception in `onAction`),
`exit()` never runs and **the whole session's navigation history is lost**. That is the
confirmed defect: persistence currently depends on the GUI being closed cleanly through
one of three code paths.

**Proposed smallest reliable persistence point (not implemented):** the successful end of
`UMSA.select_software` (`gui.py:2186`, after the artwork/indicators are shown). It is the
single funnel of all five insertion paths *and* the only place that knows the display
actually succeeded (its early-return failure branch at `gui.py:2037-2043` would simply not
persist). One ordered write of the trimmed tail (`self.last[-10:]`) per successful
display trivially replaces the exit-time write; `exit()` can keep writing during a
transition period or be reduced to a no-op — implementation decision, see section 8.
Alternative considered and rejected as primary: `onFocus`/action handlers — they fire for
navigation and would persist non-display events.

### 1.7 Robustness of the current file handling

| Condition | Behaviour today |
|---|---|
| File missing | `OSError` → `[]` → padded with 10 random ids; old state = nothing to lose |
| File empty | `readline()` → `''` → `[]` → same padding |
| File unreadable (permissions) | same as missing (`OSError`); the file is **not** overwritten until a clean `exit()` |
| File truncated/garbage (`"12,nope"`) | `ValueError` from `int()` **propagates out of `onInit`** — GUI startup breaks; no recovery, no fallback to random padding (pinned behaviour, `tests/test_persistence.py:118-123`) |
| More than 10 ids | loaded fully in memory; trimmed to 10 only at next save |

The migration/import (section 6) must handle the malformed case **without losing the
original file** and without reporting a successful import.

---

## 2. `load_lastsaver()` — precise status (correction to the brief's premise)

The brief calls `load_lastsaver()` "currently unused legacy code". The audit confirms a
**more precise** status:

- `load_lastsaver()` (`persistence.py:64-76`) **has exactly one caller**:
  `gamelist_strategies.last_saver()` (`gamelist_strategies.py:149-166`), registered as
  strategy **84 / `M_LSSAVER`** (`gamelist_strategies.py:229`; constant at `gui.py:163`).
- That strategy is **reachable from the GUI**: the listmode submenu always contains the
  item `'Screensaver session'` (`gui.py:971`), and a context action on the
  `M_ASETTINGS` menu entry is a "shortcut to last screensaver list"
  (`gui.py:769-771`). `update_gamelist` passes `lastsaver_path=CORE_DATA_PATHS.lastsaver_file`
  in the strategy context (`gui.py:1773-1782`).
- **However, nothing ever writes `lastsaver.txt`.** Verified by `git log -S` and
  `git grep` across *every* commit back to the 2017 initial commit: the only references
  that ever existed are the loader, the `CoreDataPaths.lastsaver_file` path property
  (`data_paths.py:57-58`), the strategy consumer and tests. There is no
  `save_lastsaver`, no write of that path, in any revision.
- Net effect: the `M_LSSAVER` list is **always empty**, and `update_gamelist` shows the
  generic `'found nothing...'` notification (`gui.py:1790-1795`). The feature is
  *referenced but permanently dead*, because its data source is never populated.

**Historical data format (clue to previous behaviour only, not a contract):** the loader
reads lines of `setname,swlname` (comma-separated pair per line) and yields them in
**reverse file order** (`reversed(last_list)`, `persistence.py:74-76` — i.e. last line
first, implying a hypothetical writer appended newest-last). Each pair is resolved via
`DBMod.get_info_by_set_and_swl(i[0], i[1])` → `{name, software_id, year, maker}`
(`game_repository.py:477-508`), so the historical identity was **(set name, softwarelist
name)**, mapped to a software for display. `tests/test_persistence.py:126-131` pins the
reverse-order read.

**Conclusions:**

- There is **no live data source** and **no preservation requirement** for
  `lastsaver.txt` (nothing writes it; a user file could only come from an external tool,
  for which there is no evidence). Open question **Q6** asks for explicit confirmation.
- The planned screensaver history (section 3) must **not** reintroduce file persistence
  and must **not** be shaped by this helper. Reviving the `M_LSSAVER` menu on top of the
  new `status.db` history table is a *possible later step*, out of scope here.
- `load_lastsaver()` itself stays untouched in this phase (removal or rewiring is a
  separate, maintainer-triggered decision).

---

## 3. Screensaver — display lifecycle and the event boundary for history

### 3.1 Current lifecycle (no history anywhere)

`screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py`, driven by
`runtime.ScreensaverRuntime._run` (`runtime.py:77-134`; the runtime holds the screensaver's
own `DBMod` instance, `runtime.py:108`, opened with `use_filter = False`).

- Modes: `videos`, `cross`, `slide`, `wall` (`arguments.py:9`).
- **Art selection** (cross/slide/wall): `get_art_and_call_saver`'s loop
  (`ui.py:432-595`) calls `self.parent.umsa.ggdb.get_random_art(self.art_types)`
  (`ui.py:433`; `database.py:867-974`). The result dict carries **both** the **set id**
  (`art['id']` = `sets.id`) and the **software id** (`art['s_id']` =
  `sets.softwarelink_id`), plus `gamename`, `swl_name`, `type`, resolved paths.
- `remember_art(art)` (`ui.py:192-195`, called at `ui.py:435`) stores only the *current*
  `current_software_id` for the context-menu handoff — a **single value, overwritten every
  iteration**, and it is set **before** the bad-image rejection (`ui.py:444-446`
  `continue`), so it can name a set that was never rendered.
- **Render**: the artwork is applied to the window controls at `ui.py:454-571`
  (cross: `addControl`; slide: `setImage` + slide properties; wall: position mesh +
  `setImage`), then the wait loop runs one second at a time for `ssaver_time` seconds
  (`ui.py:585-595`), checking `self.running` so a keypress aborts mid-wait.
- **Videos mode**: `get_art_and_call_saver` returns early (`ui.py:409-414`) after two
  `add_video_to_playlist()` calls; each call picks a random `videosnaps` art and puts the
  software id into the ListItem `'Votes'` tag (`ui.py:354-393`, `s_id` at 390).
  Playback is confirmed asynchronously by `Player.onPlayBackStarted`
  (`ui.py:712-771`); `Player.onPlayBackEnded` appends the next video (`ui.py:773-784`).
  `remember_art` is **not** used in this mode.
- The saver tracks **no history**: no in-memory list, no file, no DB write. The only
  cross-run state is the window property `UMSA.Screensaver.Mode`.
- **Random selection is history-blind**: `get_random_art` has no "recently shown"
  exclusion, so the same set can repeat back-to-back. No existing behaviour depends on
  `load_lastsaver()` (section 2) or on any other history.

### 3.2 Candidate event boundaries (to be confirmed — Q3)

| Mode | Candidate "successfully displayed" boundary | Notes |
|---|---|---|
| cross / slide / wall | after the render block completes for the fetched art (`ui.py:571`, immediately before the wait loop) | the bad-image `continue` (`ui.py:444-446`) already excludes rejected candidates; `remember_art` at 435 is **too early** (pre-rejection) |
| videos | `Player.onPlayBackStarted` (`ui.py:712`), reading the current playlist item's `'Votes'` tag | the only point that proves the video is actually playing; playlist insertion alone (`ui.py:391`) is candidate selection |

Wall-mode nuance: one loop iteration renders **one** artwork image of **one** set into a
grid cell; a "display" is therefore one iteration, not the whole wall. Cross-mode
accumulates up to 60 images; likewise each iteration is one displayed set.

### 3.3 What is unresolved and must not be guessed

- **Repeated events vs unique sets** (Q1b): nothing in the current code decides this.
  An event log (duplicates allowed) and a unique-set recency list (re-display moves the
  entry) need different schemas (unique index vs monotonic event id).
- **Identifier** (Q2): the screensaver's display identity is the **set id** (`art['id']`),
  while every existing consumer pattern (GUI lastgames, the screensaver→GUI handoff,
  the historical `lastsaver.txt` pairs) speaks **software ids** or (set, swl) pairs.
- **History bound**: this plan follows the stated requirement of **100** entries; the
  maintainer's private idea list mentions "last 12 screensaver entries" (`TODO.txt:72`).
  Q1a asks for confirmation.
- **Survival across restarts**: `status.db` is persistent shared Core data, so a table
  there survives Kodi restarts by construction (and can be wiped by the existing
  `RunScript(...,del_status)` maintenance action, `addon.py:31-35` — acceptable: it is
  the user's explicit reset).

---

## 4. Proposed storage models in `status.db` (separate, purpose-specific)

Neither table is created by this audit. Both proposals keep `status.db`'s existing
tables (`sets`, `emu`, `emu_conn` — `status_repository.py:40-69`,
`emulator_repository.py:48-83`) untouched.

### 4.1 GUI lastgames — `gui_lastgames`

```sql
CREATE TABLE IF NOT EXISTS gui_lastgames (
    position    INTEGER PRIMARY KEY,   -- 0..n-1, oldest -> newest
    software_id INTEGER NOT NULL
)
```

- A rowid table with an explicit **position column as the primary key**: order is data,
  exactly as in the file (index 0 = oldest). Retrieval:
  `SELECT software_id FROM gui_lastgames ORDER BY position`.
- **No timestamps, no play counts, no UNIQUE constraint.** This is navigation state, not
  play history (`sets.last_played`/`time_played`/`play_count`) and not screensaver
  history. Duplicates are *allowed by schema* so current behaviour (Q5) can be preserved
  verbatim without a schema change later.
- **Write semantics: full replace** of the ≤10 newest ids in one savepoint
  (`DELETE FROM gui_lastgames` + ordered `INSERT`s) — mirrors `save_software_list`'s
  whole-file rewrite and the fact that the in-memory list is authoritative. The writer
  trims to the newest 10 before inserting (current `self.last[-10:]` contract).
- Position alone is sufficient: the pointer (`lastptr`) is intentionally **not**
  persisted — today it always resumes at the newest entry, and preserving that keeps the
  import/restore semantics identical to the file.

### 4.2 Screensaver history — `screensaver_history`

```sql
CREATE TABLE IF NOT EXISTS screensaver_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic display-event identity
    set_id       INTEGER NOT NULL,                   -- pending Q2
    software_id  INTEGER,                            -- pending Q2
    displayed_at DATETIME                            -- 'YYYY-MM-DD HH:MM', same format as sets.last_played
)
```

- **Ordered event identity** via `AUTOINCREMENT` (monotonic, never reused) — supports
  "last N in display order" without relying on timestamp granularity (multiple displays
  can share a minute; `sets.last_played` already uses minute resolution).
- Retrieval of the most recent 100 in intended (newest-first) order:
  `SELECT … FROM screensaver_history ORDER BY id DESC LIMIT 100` — the same iteration
  direction `load_lastsaver()` used (newest first).
- Pruning beyond 100, inside the same savepoint as the insert:
  `DELETE FROM screensaver_history WHERE id NOT IN (SELECT id FROM screensaver_history ORDER BY id DESC LIMIT 100)`.
  (At ≤100 rows this is trivially cheap; `id <= (SELECT MAX(id) … - 100)` is an
  equivalent alternative to evaluate at implementation time.)
- `displayed_at` is proposed as useful for future display ("shown 3 days ago") but is
  not load-bearing for ordering; drop it only if the maintainer objects (part of Q2's
  scope).
- The `set_id`/`software_id` split is deliberate hedging for Q2: if the answer is
  "software id only" or "set id only", the other column is simply not created. This is
  the single schema-level unknown and is why the table is **not** part of the first
  migration batch.

### 4.3 Import marker table — `status_meta`

```sql
CREATE TABLE IF NOT EXISTS status_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
```

Tiny key/value store owned by the migration module; first use: key
`lastgames_imported` (value: import timestamp). Keeping the marker in `status.db`
(durable, survives deletion of the text file) rather than renaming `lastgames.txt`
satisfies "keep the text file as backup" and "never re-import an old file over newer DB
state" simultaneously. Do not overload this table for unrelated metadata later without a
decision.

---

## 5. Proposed `status.db` migration mechanism (PRAGMA user_version)

Follows the confirmed policy in `README.md` ("`status.db` schema and migration policy
(confirmed — Q6)") — the mechanism itself is the missing piece that policy requires.

### 5.1 Module and shape

- New Core module **`umsa_core/status_migrations.py`** (Kodi-free; matches the
  maintainer's own idea of "migration in eigenem migrations modul", `TODO.txt:70`).
  - `CURRENT_VERSION = <int>`; `MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]]`
    (or an ordered list of `(version, fn)`), keys = target versions, strictly increasing
    from 1.
  - `apply_migrations(connection) -> int`: reads `PRAGMA user_version`; applies each
    pending migration in ascending order; each in **its own transaction**; sets
    `PRAGMA user_version = <n>` **inside** that transaction, after the migration's
    statements succeed (SQLite `user_version` writes are transactional); on failure the
    transaction rolls back and the exception **propagates** (never swallowed), leaving
    the old version stored.
  - `PRAGMA user_version` cannot be parameterised — literal ints only, derived from the
    migration keys, never from data.
- **Authoritative DDL stays with the repositories**: migration 1 calls the existing
  `create_status_tables()` (`status_repository.py:40`) and `create_emulator_tables()`
  (`emulator_repository.py:48`) helpers, so the baseline schema has exactly one
  definition. Migration 2+ call the new `create_history_tables()` helper of the history
  repository (section 7).
- **Call site**: `DBMod._open_persistent_databases` (`database.py:289-316`), on the real
  `status.db` connection (`self.sdb`), replacing the two direct schema-helper calls at
  `database.py:314-315` with `apply_migrations(self.sdb)` (which internally invokes the
  same helpers via migration 1). The `status.db` connection is the only connection
  migrations ever touch — never `umsa.db` (policy rule 2).

### 5.2 Version plan

| Version | Contents | Rationale |
|---|---|---|
| 0 | implicit legacy/unversioned state — **all existing user databases** | every current `status.db` has `user_version = 0` and already contains `sets`/`emu`/`emu_conn` via `CREATE TABLE IF NOT EXISTS` |
| 1 | baseline: `sets` + `emu` + `emu_conn` via the two repository helpers (idempotent `IF NOT EXISTS`), then store version 1 | converges fresh *and* legacy databases with **zero** destructive work: on a legacy DB every statement is a no-op; a fresh DB gets the full baseline. No reset, no rebuild, no recreate |
| 2 | `gui_lastgames` + `status_meta` (history repository's `create_history_tables`) + the one-time `lastgames.txt` import hook (section 6) | GUI lastgames feature |
| 3 | `screensaver_history` (final shape per Q1b/Q2) | screensaver history feature — **separate step**, only after the open questions are answered |

Existing databases: preserved completely — migrations only ever *add* tables
(`IF NOT EXISTS`); nothing in versions 1–3 alters or drops `sets`, `emu` or `emu_conn`.
Play history, emulator configuration and MARP/Youtube links are untouched.

Existing tests that **pin `user_version == 0`** must be updated when the mechanism lands
(implementation step, listed in section 8): `tests/test_status_repository.py:136-137,175`,
`tests/test_emulator_repository.py:225-226,269`, `tests/test_database.py:360-361`.

### 5.3 Migration vs legacy-file import are separate operations

- **Migration** = schema only, runs on every `DBMod` open, idempotent, ordered by
  `user_version`.
- **Import** = one-time *data* operation (section 6), runs only when its marker is
  absent, and is a distinct function with its own tests. A failed import must never
  advance a version or write a marker.

---

## 6. One-time legacy import of `lastgames.txt`

Proposed Core function (Kodi-free, e.g. in the history repository module):
`import_lastgames_file(connection, paths) -> bool`.

Ordered behaviour:

1. If `status_meta` has key `lastgames_imported` → return immediately (never re-import;
   protects newer DB state from an old file that outlives its migration).
2. If `lastgames.txt` does not exist → write the marker (nothing to import) and return.
3. Parse with the **existing** `load_software_list()` (`persistence.py:79-93`) so the
   accepted format is byte-identical to today's loader. `OSError` → treat as missing
   (step 2). `ValueError` (malformed content) → **abort**: no rows, no marker, original
   file untouched, error logged and surfaced — the next startup retries (open question
   **Q8** covers the retry policy).
4. On success: one savepoint — insert rows `position = 0..n-1` in file order (preserving
   the current navigation order exactly, newest = last position) and insert the marker
   row, then commit. Order preservation is the hard requirement: after import,
   `read_lastgames()[−1]` must equal the newest id the old file would have resumed at.
5. **The text file is never deleted, renamed or truncated** — it stays as backup until
   the maintainer verifies the migration (explicit requirement).

GUI integration (implementation-time): `UMSA.onInit` (`gui.py:364-375`) calls the import
once (it already owns the resolved `CORE_DATA_PATHS` and the `DBMod` instance), then
loads the list from the DB via the new facade; the random-padding fallback
(`gui.py:366-368`) stays for the empty case, which now also covers "malformed legacy file
→ logged, not imported".

**No import for screensaver history** — there is no real data source (section 2).
`load_lastsaver()` is documented as legacy read-only code and stays out of the new
feature's contract.

---

## 7. Core/Kodi boundary and minimal public API

All new Core code is Kodi-free (step-4.0 AST guard applies unchanged; no `xbmc*` imports
may appear in `umsa_core/`). The GUI and the screensaver remain the only places that know
*when* a display happened.

New module `umsa_core/history_repository.py`, following the 4.5/4.6 repository
conventions exactly (caller-owned connection, `require_row_connection`, savepoint write
ownership, per-call construction):

- `create_history_tables(cursor)` — authoritative DDL for `gui_lastgames` +
  `status_meta` (+ `screensaver_history` when it lands), called from the migrations.
- `HistoryRepository`:
  - `read_lastgames() -> list[int]` — ordered oldest→newest.
  - `replace_lastgames(software_ids) -> None` — full replace, trimmed to newest 10, one
    savepoint.
  - `import_lastgames_file(paths) -> bool` — section 6.
  - later (step 3 of the feature): `record_screensaver_display(...)`,
    `get_screensaver_history(limit=100)`.

**Facade surface on `DBMod`** (the connection-attribute guard forbids add-ons touching
`.sdb` — `docs/database_refactor/README.md` boundary guard 2 — so the GUI/screensaver must
go through `DBMod`):

- `load_lastgames()` / `save_lastgames(software_ids)` — one-line facades over a
  per-call `_get_history_repository()`, matching `_get_status_repository`
  (`database.py:747-755`).
- later: `record_screensaver_display(...)` facade for the screensaver runtime.

**Callers and their responsibilities:**

- GUI (`plugin.program.umsa.mame.surfer/resources/lib/gui.py`): calls
  `self.ggdb.save_lastgames(self.last[-10:])` at the successful end of `select_software`
  (section 1.6) and `self.ggdb.load_lastgames()` in `onInit`; runs the one-time import.
  All Kodi-side concerns (what counts as a display, the history list itself) stay in the
  GUI.
- Screensaver (`screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py` / `runtime.py`):
  calls `self.ggdb.record_screensaver_display(...)` at the confirmed render/playback
  boundaries (section 3.2). It already holds a `DBMod` (`runtime.py:108`).
- Nothing new is added to `umsa_core_kodi.py`: no host abstraction is required — paths
  and settings resolution already exist (`get_core_data_paths`, `get_core_settings`), and
  `umsa_core_python.py` remains a future roadmap item (not assumed to exist).

---

## 8. Implementation and regression-test plan (for a later task; not executed)

Ordered steps, each independently reviewable, characterisation-first per house style:

1. **Migration mechanism** — `umsa_core/status_migrations.py`, migration 1 (baseline),
   call-site swap in `_open_persistent_databases`. Tests: fresh DB (tables appear,
   `user_version == 1`); legacy DB seeded with representative `sets`/`emu`/`emu_conn`
   rows at `user_version == 0` (rows preserved byte-for-byte, version → 1); failure
   injection (migration raises → version stays 0, transaction rolled back); the three
   existing `user_version == 0` assertions updated (files listed in section 5.2).
2. **History repository + migration 2** — `history_repository.py`,
   `gui_lastgames` + `status_meta`, `read_lastgames`/`replace_lastgames`. Tests:
   replace/read round-trip incl. order and trim-to-10, duplicate ids, empty replace,
   savepoint ownership (caller transaction never committed), Row-contract rejection.
3. **Legacy import** — `import_lastgames_file`. Tests: valid file (order preserved,
   marker written), missing file (marker written, empty), malformed file (ValueError →
   no rows, no marker, file unchanged), re-run after marker (no-op, DB state kept even
   if the file still exists), unreadable file.
4. **GUI immediate persistence** — `select_software` success-path save + `onInit` load
   via facade; exit-path write reduced or kept (decision at implementation). Regression:
   the pinned loader behaviours in `tests/test_persistence.py` stay green (the file
   helpers remain for the import path); Kodi-runtime behaviour verified manually (no
   Kodi-runtime test harness exists — `AGENTS.md`).
5. **Screensaver history (separate step, after Q1b/Q2)** — migration 3, repository
   methods, render/playback-boundary hooks in `ui.py`, facade. Tests: repository-level
   (record/order/prune-at-100/duplicates per decided semantics); boundary hooks remain
   manual/Kodi-runtime.
6. Full suite + per-file ruff/mypy comparisons, per house conventions.

Nothing in this list may start before the open questions (section 10) are answered and
this document is updated with the decisions.

---

## 9. Relationship to Phase 4.7 (`gamelist_filter.py`) and recommended order

The five responsibilities, kept separate as required:

| Responsibility | Home | Phase |
|---|---|---|
| Persistence of GUI navigation history (lastgames) | new `history_repository.py` + `status.db` migration + GUI call sites | **4.6.1** (this plan) |
| Future persistence of screensaver display history | same repository, separate table, separate migration, screensaver call sites | **4.6.2** (after Q1b/Q2) |
| Filter *state* persistence (`filter_<name>.txt` via `load_filter`/`save_filter`, `persistence.py:10-61`) | unchanged; stays file-based (out of scope for both 4.6.1 and 4.7) | — |
| Explicit-state filter/query composition (`define_filter`, `execute_statement`, `get_by_*`, state accessors) | `gamelist_filter.py` | **4.7** (unchanged acceptance criteria) |
| SQL parameterisation after characterisation tests | `gamelist_filter.py`, separate commit (Q2) | **4.7** (unchanged) |

**Code-overlap analysis:** 4.7 restructures `database.py`'s filter/query section and
adds DBMod state accessors (`set_filter_enabled`, `set_order`) plus GUI call-site swaps
for `use_filter`/`order` mutations (`gui.py:755-761`, `gui.py:541`). 4.6.1 touches
`database.py` only at `_open_persistent_databases` (migration call) and adds new facade
methods; its GUI edits are in `select_software`/`onInit`/`exit` — **disjoint regions**.
No shared table, no shared state, no shared tests. The `get_random_id`/`get_random_art`
mixed queries that both the GUI padding and the screensaver use stay in `DBMod`
(roadmap non-goals) and are untouched by either step.

**Recommendation: land 4.6.1 (migration mechanism + GUI lastgames) before 4.7.**

- It is small, status.db-scoped, and unblocks the correctness defect (history lost on
  unclean exit) earlier.
- It puts the `user_version` test churn (three files) and the new repository into the
  tree *before* 4.7's large characterisation batch is baselined, so 4.7's goldens are
  written against a finalised status.db layout and never re-baselined.
- Doing it after 4.7 would work too (zero file overlap), but then 4.7's suite would run
  against a tree whose `select_software` is about to change, inviting avoidable golden
  churn in GUI-adjacent tests.
- **4.7's acceptance criteria are not changed by this audit** — only this ordering
  recommendation is added, and it is recorded here as required by the brief.

---

## 10. Open questions requiring maintainer decisions

Each question states why it matters and the safest recommendation. No schema that
depends on an unanswered question has been created.

- **Q1a — Screensaver history bound: 100 or 12?** The stated requirement says the last
  **100** sets; the maintainer's private idea list says "last 12 screensaver entries"
  (`TODO.txt:72`). Matters only for the pruning constant (schema is identical).
  *Recommendation:* 100, per the stated requirement; treat `TODO.txt` as superseded.
- **Q1b — Screensaver history: every display event, or unique sets?** An event log
  (same set may appear many times; monotonic `id`; simplest, lossless, matches "sets
  actually displayed") vs a unique-set recency list (re-display moves the set to the
  front; needs a UNIQUE constraint and upsert logic; better if the future consumer is
  "browse what I've seen" without repeats). **Materially changes the schema** — this is
  why `screensaver_history` is deferred to migration 3. *Recommendation:* event log with
  duplicates; if a deduped view is wanted later, derive it at read time.
- **Q2 — Screensaver history identifier: set id, software id, or both?** The render
  identity is the **set id** (`art['id']`), but the handoff and every GUI consumer speak
  **software ids** (`art['s_id']`). *Recommendation:* store **both** columns (nullable
  `software_id`, `NOT NULL set_id` as proposed in 4.2) — both are always present in the
  `get_random_art` result, and this avoids a schema migration if a future `M_LSSAVER`
  revival wants software ids. Drop `displayed_at` if unwanted.
- **Q3 — Confirm the successful-display boundaries** from section 3.2: post-render point
  in the cross/slide/wall loop; `Player.onPlayBackStarted` for videos. *Recommendation:*
  adopt as proposed; `remember_art` is explicitly *not* the boundary (pre-rejection).
- **Q4 — GUI lastgames: persistence point and failed-display cleanup.** Proposed point:
  successful end of `select_software`. Sub-question: today a *failed* display still
  leaves the id in `self.last` with a moved pointer (section 1.5). Should the
  implementation (a) keep that quirk (minimal change) or (b) rewind `lastptr` and remove
  the just-inserted id on the failure branch, so history only ever contains displayed
  games (matches the product requirement, slightly larger change)? *Recommendation:* (b)
  — it is the stated product semantics — but only with explicit approval, since it is a
  behaviour change.
- **Q5 — GUI lastgames duplicates: preserve or dedup?** Current behaviour allows the
  same software id to appear repeatedly (click-insert, section 1.3). The proposed schema
  permits duplicates. *Recommendation:* preserve current behaviour exactly (no dedup) in
  4.6.1; dedup would be a separate, explicit behaviour change.
- **Q6 — `lastsaver.txt` preservation: confirm "none".** The audit found no writer in
  any revision (section 2), so there is nothing to import and no supported legacy
  format. *Recommendation:* no import; document the helper as legacy; optionally schedule
  a later step reviving `M_LSSAVER` on the new history table.
- **Q7 — Migration module location and baseline version.** Proposed:
  `umsa_core/status_migrations.py`, baseline = version 1 (idempotent re-declaration of
  the existing three tables), new tables from version 2. Alternative: start numbering at
  a higher value or fold baseline creation back into the repository helpers with the
  migration layer only for *changes*. *Recommendation:* as proposed — it makes "legacy
  = 0, fresh = 0" uniform and keeps exactly one DDL source.
- **Q8 — Import-failure retry policy.** A malformed `lastgames.txt` is skipped without a
  marker, so the import retries on every startup (logged each time) until the user fixes
  or removes the file. Alternative: write a distinct `lastgames_import_failed` marker
  after the first failure to try once only. *Recommendation:* retry (self-healing, no
  risk of silently skipping a repaired file); the log line makes it visible.

---

## 11. Document status

Audited and planned at HEAD `b84341e`. **Nothing implemented:** no production code, no
schema, no migration, no tests, no user-file changes. Companion updates: step 4.6.1a
entries in `roadmap.md` and `README.md` (this file is referenced from both). Decisions
from section 10 must be recorded here before any implementation task is written.
