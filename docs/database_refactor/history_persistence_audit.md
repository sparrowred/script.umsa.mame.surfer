# Phase 4.6.1a — `status.db` history & legacy-file migration: audit and plan

**Status: IMPLEMENTED (2026-10-18); corrected 2026-10-19 (D20/D21).** The design questions
Q1–Q6 are **resolved** — the maintainer's phase brief answered Q1, Q3, Q4 and Q5, the
follow-up decisions answered Q2 and Q6, and both are recorded as **D12–D21** (sections 1.1
and 1.2) plus the per-section updates — and the production work described here has since
landed:
`status_migrations.py` (versioned `status.db` migration, `user_version` 0→1),
`history_repository.py` (four tables + lastgames/filter/marker persistence),
`history_import.py` (discovery, strict validation, one-time import, cleanup, `retry_import`),
the `DBMod` facades, the GUI startup wiring and the `retry_import` script command. While
implementing, the `filter_<name>.txt` line-count rule became **strict** (D14, corrected
below) and the file-level recovery semantics follow D18. The 2026-10-19 corrective
follow-up (§1.2) fixed the empty-filter-name loss (D20) and the misclassification of
unreadable files as malformed (D21) without changing the version-1 schema or
`user_version`. What remains open is limited to the manually verified **Kodi-runtime
items** (section 16.2), which are not design decisions and cannot be settled by code
inspection.

**Scope of this update:** the finalized direction for moving three related but distinct
concepts into `status.db`, all under **one** versioned schema migration, followed by
**one** durable one-time import of the legacy `lastgames.txt` / `filter_*.txt` files and
their cleanup:

1. GUI backward-navigation history (`lastgames.txt` → `gui_lastgames`).
2. Filter selections (all `filter_*.txt` files → `filter_selections`).
3. Screensaver display history (new, last 100 successfully displayed sets →
   `screensaver_history`; starts empty, **no import**).

Basis: read-only inspection of the code as of `b84341e` — the **last code commit** at the
time of the original audit; steps 4.5 (`fcdefe5`) and 4.6 (`b84341e`) are committed and the
tracked tree was clean — plus `git log -S` history searches, verification against the
**real Kodi profile on this machine** (`/home/opencode/.kodi/userdata/addon_data/script.module.umsa.core/`)
and the contents of the distributed `umsa_db.zip` (section 12). Line references are to that
code. This document itself lives in the tracked `docs/database_refactor/` directory
(first committed in `ec400f4`, refreshed in `5514efd`); the audit snapshot is of code
`b84341e` — since then Phase 4.7 landed (`479e202` + `10f9fbd` + `da65a62` + `bc631eb`),
which satisfies this document's 4.7 dependency without changing its scope (front-end
text-file persistence is untouched), and the bounded retry-without-filters fix landed as
`bd83a4d`. **Re-verified 2026-10-18 at HEAD `bd83a4d` (tracked tree clean, full suite
661 passed / 5 skipped / 18 subtests):** every line reference in sections 2–5 and 7–10 was
re-checked against that tree, the runtime facts in sections 5 and 16.2 were re-checked
against the installed Kodi **21.3 (Omega)** and Kodistubs 21.0.0, and the profile inventory
in section 12 was re-read (unchanged).

Scope restrictions that bound this document as an **audit/plan**: documentation-only
changes; no production-code changes attributed to the audit itself; no migrations or
schema changes from the audit; no tests added or modified by the audit; no deletion or
rewriting of actual user files; no implementation of the screensaver history (4.6.2); no
Phase 4.7 work. The subsequent implementation in this phase changed production code as
described above; this document records the decided rules it followed.

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
| **D11** | **Ordering (former Q7, confirmed by the maintainer):** Phase **4.7 → 4.6.1 → 4.6.2**. 4.7's existing scope and acceptance criteria are unchanged; **text-file persistence (`lastgames.txt`, `filter_*.txt`) stays in place during 4.7** and moves only in the later one-time `status.db` migration. Rationale accepted: database-backed filter loading built before the explicit-state filter/query refactor would bind persistence to the old implicit-state API. **Q1–Q6 (the gate named here) are now resolved — see 1.1 and section 16.** |

### 1.1 Confirmed by the maintainer's phase brief and follow-up decisions (2026-10-18)

The maintainer's phase brief (which answered Q1, Q3, Q4 and Q5) plus the follow-up
decisions (Q2 token/line semantics, Q6 recovery) close **Q1–Q6**. D1–D11 above are
untouched; these rows are the
new binding rules. Every row is a *decision*, not a proposal.

| # | Decision |
|---|---|
| **D12** | **History entries exist only after a successful display (Q1 resolved).** A lastgames entry is appended **only once `select_software` has succeeded** — the early return (`gui.py:2038-2043`) must leave neither an in-memory nor a persisted entry, so the insert-and-advance currently done by the five call sites (and by `software_move`'s append) moves into `select_software`'s success funnel (or `select_software` must report success to its callers; it returns `None` on both paths today, `gui.py:2186`). **Repeated display events stay separate entries** — duplicates are preserved, no dedup. Order stays file order (index 0 = oldest, newest = resume point) and the pointer behaviour of `software_move` is unchanged: the established navigation semantics must not change. |
| **D13** | **Token validation: strip, then decimal digits (Q2, token half).** Every candidate id token is whitespace-stripped and must then be a non-empty decimal-integer string (`^[0-9]+$`). Whitespace around ids is accepted (matching today's `int()` semantics in `load_software_list`, `persistence.py:91`), so a hand-edited `"12, 34"` is **not** a data loss. A token that is not a decimal integer after stripping, or undecodable bytes, makes the **whole file** malformed → discarded whole, recorded as a warning, still deleted after the commit (D3/D5). |
| **D14** | **Filter line count is a validity criterion — strict five-line rule (Q2, line half; supersedes the earlier "tolerance kept" wording).** `lastgames.txt`: line 1 is the data, any further lines are **ignored, unreported** (today's reader only calls `readline()`); a zero-byte file *or* an empty first line means **no entries**. `filter_<name>.txt`: the file must contain **exactly five logical lines**, mapping positionally onto the five categories in the order `Softwarelists`, `Game Categories`, `Machine Categories`, `Years`, `Players`; lines may be empty (an empty line is an empty category). A single trailing newline does not add a sixth logical line. **A file with any other line count (fewer or more than five) is malformed and discarded whole** — the import never pads missing categories and never ignores extras (so the legacy `IndexError` on shorter files is neither inherited nor silently reinterpreted). Every non-empty line is a comma-separated list of decimal-integer id tokens, each whitespace-stripped; a non-decimal or undecodable token discards the whole file (D13). Files we ship always contain exactly five lines (`save_filter`), so strictness only ever affects hand-edited input, and it never partially imports one. |
| **D15** | **No new runtime-state persistence (Q3 resolved).** `act_filter` (the active filter *name*), `use_filter` and `order` are **not** persisted — verified they are not persisted today either (`database.py:280-281`, `gui.py:345-346`), so adding them would visibly change what the GUI shows on the next start. Only the five selections per named filter move into `filter_selections`. The **public Core API dictionary keys stay exactly as they are** (`"Softwarelists"`, `"Game Categories"`, `"Machine Categories"`, `"Players"`, `"Years"` — `persistence.py:13-19`); the database may store the **internal** keys `softwarelists`, `game_categories`, `machine_categories`, `years`, `players` **with an explicit, documented mapping table** used on read and write (verified: the dict-literal order at `persistence.py:13-19` differs from the file-line order at `persistence.py:29-35` — `Players`/`Years` are swapped — so the mapping is by *name*, never by position). The Load/Save Filter dialog keeps offering exactly the imported names (replacing the `os.listdir` scan with `list_filter_names()` changes nothing visible). |
| **D16** | **Screensaver history semantics (Q4 resolved).** Records are keyed by **`set_id`** (the `sets.id` that `get_random_art` returns as `art['id']`, `database.py:908`); the **software id is stored alongside** (`art['s_id']` = `sets.softwarelink_id`) and stays the value the context-menu handoff uses today (`ui.py:192-195`, `ui.py:143`). Bound: **at most 100 distinct sets, ordered by most recent successful display**; re-displaying a set moves its single row to the newest position (only the newest copy is retained) — i.e. one row per set, not an event log; rows are pruned past the newest 100 inside the same savepoint as the write. **Images** are recorded only after the iteration's controls have been populated — immediately after the render block (`ui.py:454-571`), **before** the wait loop — because `remember_art` fires before the bad-image rejection (`ui.py:435` vs `ui.py:444-446`) and is therefore not a boundary. **Videos** are recorded only once the stream is available, in `Player.onAVStarted()` (verified present in Kodistubs 21.0.0, annotated `@python_v18`, so available on every Kodi the add-ons support) — not in `onPlayBackStarted`, and never at enqueue time. **Orphan `set_id` rows are never silently substituted:** if the set no longer resolves in `umsa.db` (`get_info_by_set_and_swl` raises `TypeError` on no match, `game_repository.py:482-484`), the row is kept, the handoff is refused with a logged + notified "set no longer available", and no other set is shown instead. |
| **D17** | **Deletion scope (Q5 resolved).** Only `lastgames.txt` and validated `filter_*.txt` are ever deleted (D6). `lastsaver.txt` — for which **no writer exists in any revision**, only `load_lastsaver` + its single consumer (`gamelist_strategies.py:153`) — and every other unknown file are **preserved and reported to the maintainer**, never added to the cleanup scope by name-guessing. |
| **D18** | **Database-failure recovery (Q6 resolved).** (a) If `status.db` cannot be read or written such that the required outcome **cannot be committed**, the failure is **reported and the import retries at the next GUI startup** — no marker exists in that case, so "no marker" *is* the retry signal — and **no separate fallback status file may be introduced** (this reverses the "no fallback is adopted until you decide" holding position in 9.3). (b) A durably recorded **`failed` state stays terminal** (D4 unchanged): it is reported on every startup and retried only through a new explicit frontend script command `retry_import`, registered beside `del_db`/`del_status` in `addon.py:18-37`. (c) A **deletion** failure never re-triggers the import — cleanup-only on the next startup (D4). |
| **D19** | **`gui_lastgames` retention is the newest 100, not 10** (maintainer change). Storage keeps the newest **100** ids (`position` 0..99) instead of today's `self.last[-10:]` trim (`gui.py:2566`); the in-memory session list, the pointer and the navigation behaviour are unchanged. This is the one deliberate *visible* behaviour change of the phase: after a restart the GUI resumes with up to 100 entries of backward history instead of 10. The legacy import reads whatever the file holds and writes at most the newest 100. |
| **D20** | **A saved filter keeps its name even with five empty categories (corrective follow-up)**. The published version-1 schema is unchanged: `save_filter_selections` also writes one **definition marker** row into the existing `filter_selections` table under the reserved internal category `__filter_definition__` (position 0, value `"1"`). The marker is written for imported *and* GUI-saved filters, replaced atomically with the selections on every save, is never a selectable category, and never appears in any public filter dictionary (it is absent from all four category maps/orders). `list_filter_names()` keeps reading names with `SELECT DISTINCT filter_name`, so version-1 databases whose non-empty filters predate the marker keep working with no reset and no re-import. |
| **D21** | **Filesystem read/discovery failures are not malformed content (corrective follow-up)**. `_read_decodable` maps only `UnicodeDecodeError` to `ValueError` (whole-file discard, filename recorded, deleted only after the outcome commits). `OSError` (permissions, I/O, missing file) and directory-enumeration errors propagate to `run_legacy_import`, which aborts *before* the import transaction: no recognized source is deleted and no other file is partially imported. A best-effort durable `failed` marker carrying the diagnostic is recorded (D18); if that write also fails, no marker exists and the next ordinary startup retries; if it succeeds, ordinary startups wait for the explicit `retry_import` command. |

### 1.2 Corrective follow-up (2026-10-19)

Two defects found after the initial 4.6.1 landing are corrected **without** changing the
version-1 schema, `PRAGMA user_version`, or the migration strategy:

1. **Completely empty filters lost their name** (D20). Because a filter with no
   selections wrote no rows, `list_filter_names()` could not see it; a successful import
   would then delete the legacy file and lose the name permanently. Fixed with the
   reserved `__filter_definition__` marker row (D20). The fix is schema-compatible: no
   `ALTER TABLE`, no new column, no new migration - the existing
   `(filter_name, category, position, value)` primary key already distinguishes the marker
   from the five selectable categories. Version-1 databases with pre-marker, non-empty
   filters continue to load and list unchanged (regression-tested).
2. **Unreadable files were misclassified as malformed** (D21). `_read_decodable()`
   previously folded `OSError` and `UnicodeDecodeError` into `ValueError`, so a
   permission/I/O error on a recognized file caused that file to be scheduled for
   deletion. Now only `UnicodeDecodeError` is malformed content; `OSError` (and discovery
   enumeration errors) abort the attempt before the import transaction, after a
   best-effort durable `failed` marker, leaving every source in place for the explicit
   `retry_import`.

Notification detail was tightened at the same time: the startup and explicit-retry paths
now include the pending-cleanup **filenames** (not just a count) and preserve the
discarded filenames for diagnosis. These fixes are a **prerequisite for 4.6.2**; 4.6.2's
own status is otherwise unchanged.

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
  (`database.py:864`) hands out for padding.
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
Consequences — **decided in D12**:

- **Duplicates** are allowed (clicking an id already in history inserts it again) and
  **stay allowed**: repeated display events are preserved as separate entries.
- **Failed displays must not leave phantom entries.** Today they do: `select_software`
  fails (`get_all_for_software` empty → notification + `return`, `gui.py:2038-2043`)
  *after* the insert, and it returns `None` on both the failure and the success path
  (`gui.py:2186`), so callers cannot tell them apart. **Required change:** the
  insert-and-advance moves into `select_software`'s success path (or callers must receive
  an explicit success signal), so a failed display leaves the list exactly as it was.
- The in-memory list is **unbounded** (unchanged); persistence keeps the newest **100**
  (D19), replacing the writer's `self.last[-10:]` trim.

Not affected: hover/selection movement, filter changes, and gameplay (play history is
written by `write_status_after_play`, `gui.py:2539-2542` — a separate concept, D7/D8).

### 2.4 Current write point — the confirmed defect

The **only** write is `UMSA.exit()` (`gui.py:2560-2566`), reached only via the
clean-exit paths (`gui.py:642, 672, 1199, 1233`). Kodi destroying the window (shutdown,
window killed, crash) bypasses it and the session's history is lost.

**Persistence point (D7 + D12, decided):** the successful end of `UMSA.select_software`
(`gui.py:2186`) — the single funnel of all five insertion paths, and the only place that
knows the display succeeded (the early return at `gui.py:2038-2043` neither appends nor
persists). One ordered full-replace write of the newest 100 ids per successful display
(D19) replaces the exit-time file write. Because the entry now appears only on success,
"successfully displayed" is by construction what the stored history contains; the
`None`-on-both-paths return has to be resolved as part of the wiring (success signal or
in-funnel insert), which is an implementation detail of the decided behaviour, not an open
question.

### 2.5 Robustness today

| Condition | Behaviour |
|---|---|
| missing / empty / unreadable file | `OSError` → `[]` → padded with up to 10 random ids |
| malformed line (`"12,nope"`) | `ValueError` propagates out of `onInit` — GUI startup breaks, no recovery (pinned, `tests/test_persistence.py:118-123`) |
| > 10 ids on disk | loaded fully; trimmed only at the next save |

The import (section 8) must therefore not reuse the crash-prone path blindly: a file with
a non-integer token becomes a **discarded input with a warning** (D13), never a startup
failure. For `lastgames.txt` the first line is the data and later lines are ignored (D14);
for `filter_<name>.txt` a wrong line count is a **discard**, not a tolerated repair (D14).

---

## 3. Filter selections — file contract (legacy source #2)

### 3.1 Path and format

- `CoreDataPaths.filter_file(name)` = `<core profile dir>/filter_<name>.txt`
  (`data_paths.py:60-65`); `filters_dir` is the same directory (`data_paths.py:49-50`),
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
  (`database.py:94`) builds active/inactive from `str(entry[0])` (row ids), and
  `define_filter` (`database.py:1212`, a one-line facade over `gamelist_filter.py` since step 4.7) feeds them into
  `swl.id IN (...)`, `category.id IN (...)`, `nplayers.id IN (...)`, `year.id IN (...)`.
  Values are therefore effectively decimal integers, and the import validates exactly
  that: strip, then `^[0-9]+$`, whole file discarded otherwise (**D13**); the file must
  also hold **exactly five logical lines**, otherwise it is discarded whole (**D14**).

### 3.2 Discovery, load and save call sites

- **Startup:** `onInit` loads `filter_default.txt` into `self.filter_lists` and sets
  `self.act_filter = 'default'` (`gui.py:344-346`) — *before* `DBMod` is constructed
  (`gui.py:357`), which is a sequencing constraint for the post-migration load
  (section 14).
- **Load/Save Filter dialog** (`filter_category`, `gui.py:1304-1356`): names come from
  `os.listdir(SETTINGS_FOLDER)` filtered by the loose prefix test `i[:7] == 'filter_'`,
  name = `i[7:-4]`; Load → `load_filter(filter_file(name))` + `ggdb.define_filter(...)`;
  Save → `save_filter(filter_file(name), self.filter_lists)` + `self.act_filter = name`.
- **Consumption:** `DBMod.__init__(..., filter_lists, ...)` → `define_filter` on open
  (`database.py:309, 1176`), and again after every Load Filter.
- **Not persisted today, and still not persisted (D15):** the active filter *name* only
  lives for the session (fresh start always reads `default`, `gui.py:345-346`), and the
  runtime query state `use_filter` / `order` (`database.py:280-281`) is never written
  anywhere — so none of it starts being persisted in this step, and the visible filter
  behaviour on the next start is unchanged.
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
  preserved and reported, never deleted (**D17**, resolving Q5).

---

## 5. Screensaver — display lifecycle and decided semantics

(Unchanged findings; the bound is now decided.)

- Modes: `videos`, `cross`, `slide`, `wall` (`arguments.py:9`); `ScreensaverRuntime`
  holds the screensaver's own `DBMod` (`runtime.py:99-108`).
- **Art selection** (cross/slide/wall): one `get_random_art(self.art_types)` per loop
  iteration (`ui.py:433-446`; `database.py:881`) — the dict carries **both** the set
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
  (`ui.py:712+`) — **the decision records on `onAVStarted` instead** (see the D16 bullet
  below). **`set_id` does not travel with the video at all today** — only the
  software id does, read back via `getVotes()` for the context handoff (`ui.py:143`).
- `get_random_art` returns **`None`** when the query finds no artwork
  (`database.py:938-940`), not an empty dict — `remember_art(None)` handles that
  (`ui.py:195`), but any recording hook must too.
- **No history exists anywhere** (no memory list, no file, no DB write) and random
  selection is history-blind, so nothing depends on this feature yet — it starts empty
  (D2).
- **Decided (D16, resolving Q4):** records are keyed by `set_id` with the software id
  stored alongside for the context menu; **at most 100 distinct sets** ordered by most
  recent successful display, re-display moving the single row to the newest position;
  images recorded immediately after the render block (`ui.py:454-571`) and **before** the
  wait loop; videos recorded in **`Player.onAVStarted()`**, which exists in the installed
  runtime (`onAVStarted` is annotated `@python_v18`, i.e. Kodi ≥ 18 — verified against
  Kodistubs 21.0.0 and the Kodi **21.3 (Omega)** on this machine); orphan `set_id`s kept
  and reported, never substituted. The **mechanism for carrying `set_id` on a video** is
  the video unique-ID API — `InfoTagVideo.setUniqueID(str(set_id), 'umsa_set_id')`
  (value first, type second) written on the playlist ListItem and read back with
  `getUniqueID('umsa_set_id')` — which is `@python_v20`
  and therefore guarded with a capability check: on a Kodi older than 20 the set id cannot
  be carried, video displays are then not recorded (logged), while the existing
  `Votes`-based software-id handoff keeps working unchanged. See 16.2 for what that
  leaves to verify in Kodi.

---

## 6. Storage model — four new tables, one schema

All four live in `status.db` alongside the existing tables (D1, D10). The schemas below
are the decided design (D12–D19, section 1.1); nothing has been implemented yet.

### 6.1 `gui_lastgames` — backward-navigation state

```sql
CREATE TABLE IF NOT EXISTS gui_lastgames (
    position    INTEGER PRIMARY KEY,   -- 0..n-1, oldest -> newest
    software_id INTEGER NOT NULL
)
```

- Order is data (position as primary key); read with `ORDER BY position`.
- **No timestamps, no UNIQUE constraint** — it is navigation state, not play history and
  not screensaver history; **duplicates are representable and deliberately preserved**
  (D12).
- **Write semantics: full replace of the newest 100 ids** (D19) in one savepoint —
  positions 0..99, oldest → newest, mirroring `save_software_list`'s whole-file rewrite
  (which today trims to `self.last[-10:]`, `gui.py:2566`); the in-memory list stays
  authoritative for the session and is not trimmed.
- Written immediately after a successful display (D7 + D12), *not* at shutdown; a failed
  display writes nothing and leaves no entry.
- The pointer (`lastptr`) is not persisted — restart resumes at the newest entry, exactly
  like today.

### 6.2 `filter_selections` — saved filter files

```sql
CREATE TABLE IF NOT EXISTS filter_selections (
    filter_name TEXT    NOT NULL,   -- filename part: 'default', 'arcade', ...
    category    TEXT    NOT NULL,   -- 'softwarelists' | 'game_categories' |
                                   -- 'machine_categories' | 'years' | 'players'
                                   -- | '__filter_definition__' (definition marker, D20)
    position    INTEGER NOT NULL,   -- value order within the category (file order)
    value       TEXT    NOT NULL,   -- opaque id string, preserved verbatim
    PRIMARY KEY (filter_name, category, position)
)
```

- One row per selected value; an empty category has **no value rows** (the faithful
  equivalent of an empty line). Since the corrective follow-up (D20) every saved or
  imported filter **also** carries exactly one **definition marker** row under the
  reserved internal category `__filter_definition__`, so an all-empty filter is still
  discoverable by name; a filter that does not exist has no rows at all.
  faithful equivalent of a missing file).
- **Category keys:** the table stores the **internal** keys `softwarelists`,
  `game_categories`, `machine_categories`, `years`, `players` (D15); the public Core API
  keeps returning the exact legacy labels `load_filter` / `save_filter` use
  (`persistence.py:13-19, 29-35`) through an explicit name mapping. **Mapping is by name,
  never by position** — the dict literal and the file-line order differ (`Players` before
  `Years` vs after).
- **Verbatim preservation:** values keep their file order via `position` (order is not
  load-bearing for queries — `define_filter` uses `IN (...)` and `build_filter_lists` uses
  set membership — but ordering semantics are preserved as stored data); values are
  whitespace-stripped on import (D13) and `filter_name` is the filename part of
  `filter_<name>.txt`.
- **Write semantics: full replace per `filter_name`** in one savepoint, mirroring
  `save_filter`'s whole-file rewrite. The definition marker (D20) is written in the same
  savepoint, so replacing a populated filter with an empty one leaves no stale selection
  rows behind.
- The active-filter name, `use_filter` and `order` are **not** part of this table —
  nothing runtime-persisted is added (D15).
- No id→name conversion, no cross-checking against `umsa.db` — the two databases are
  separate connections and no referential check is planned (ids stay opaque strings).

### 6.3 `screensaver_history` — last 100 displayed sets (empty at creation)

```sql
CREATE TABLE IF NOT EXISTS screensaver_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic recency identity
    set_id       INTEGER NOT NULL UNIQUE,            -- one row per set (D16)
    software_id  INTEGER,                            -- kept for the context menu (D16)
    displayed_at DATETIME                            -- 'YYYY-MM-DD HH:MM'
)
```

- **Write (D16):** on each successful display, the existing row for that `set_id` (if any)
  is deleted and re-inserted, which moves it to the newest position and keeps only the
  newest copy; then rows beyond the newest 100 (`ORDER BY id DESC LIMIT 100`) are pruned
  — all inside one savepoint. Retrieval: `ORDER BY id DESC LIMIT 100`.
- **No foreign key to `umsa.db`:** `sets` lives in a different database on a different
  connection, so referential integrity cannot be expressed in SQLite here. An orphaned
  `set_id` is therefore *kept* and handled at read time (D16: report, never substitute).
- `displayed_at` is advisory only — ordering is the monotonic `id`, so no clock
  dependency.
- No import, ever — starts empty (D2).
- **Status (4.6.2 implemented):** the write/retention contract above lives in
  `HistoryRepository.record_screensaver_display` (`SCREENSAVER_HISTORY_LIMIT = 100`, the
  delete + re-insert + prune triple inside one `SAVEPOINT`), read back by
  `list_screensaver_history` `ORDER BY id DESC`; `DBMod` exposes both through
  `record_screensaver_display`/`get_screensaver_history`.

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
- **Call site:** `DBMod._open_persistent_databases` (`database.py:301-328`) replaces the
  two direct helper calls (`database.py:326-327`) with `apply_migrations(self.sdb)` on
  the real `status.db` connection. Never `umsa.db`, never any other connection.
- **Trigger: GUI startup only, when required** (brief §4) — `version 0` ⇒ migrate, then
  the import check of section 10 runs; the screensaver, the scanners and any background
  thread never trigger a migration or an import.

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
   newest last), duplicates included (D12), capped at the newest 100 (D19); filter files
   keep category membership, value order and value strings (6.2), stored under the
   internal category keys through the explicit mapping (D15).
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
- **Import failure** (see 9.3) → record `failed` where possible and do not delete
  anything; the recorded state is terminal and retries only via `retry_import` (D18b).
  If not even the failure can be recorded, nothing was committed → **report and retry at
  the next GUI startup** (D18a), with no fallback file.

### 8.2 Per-file validation rules (decided — D13/D14/D21)

The reader helpers are intentionally *not* reused blindly here, because they crash on
exactly the inputs the import must survive (`ValueError` on a non-integer token,
`IndexError` on a short filter file, `UnicodeDecodeError` on bad bytes). A **filesystem**
failure while reading (``OSError``: permission, I/O, missing) is *not* a content verdict —
it aborts the whole attempt before step 6 above, leaving every source for `retry_import`
(D21). Decided rules, each file validated as a unit:

| Source | Valid shape (decided) | On failure |
|---|---|---|
| `lastgames.txt` | decodable text; **line 1 is the data** (further lines ignored, unreported); every token whitespace-stripped and then a non-empty decimal integer; empty file or empty first line = **no entries** (not malformed) | a non-integer token or undecodable bytes → **whole file discarded**, warning recorded, still counted as a recognized input for deletion (D5) |
| `filter_<name>.txt` | decodable text; **exactly five logical lines** mapping positionally onto the five categories (an empty line = empty category; one trailing newline is not a sixth line; wrong line count → malformed); each non-empty line: tokens whitespace-stripped and then non-empty decimal integers; name part passes `filter_file()` validation (`data_paths.py:60-65`) | a wrong line count, a non-integer token or undecodable bytes → same: **whole file discarded** + warning + still deleted afterwards |

Why this shape (both halves were open as Q2):

- **Tokens (D13):** the writers we ship emit bare `str(id)` values (`save_filter`,
  `save_software_list`), and today's lastgames loader already accepts spaces via `int()`
  (`persistence.py:91`) — so strip-then-validate imports every hand-edited file that
  today's loaders would accept, and rejects only what cannot be an id.
- **Line count (D14):** `lastgames.txt` keeps the legacy first-line-only tolerance
  (further lines ignored, unreported). `filter_<name>.txt` is **strict**: exactly five
  logical lines are required, because a positional category mapping with missing or extra
  lines cannot be interpreted unambiguously — padding or ignoring lines would silently
  invent or drop categories. A wrong line count therefore discards the whole file (no
  partial import); token and decode errors discard a file in the same way.

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
| `failed` | import attempted and failed; **awaiting explicit retry** | report the stored failure, attempt nothing; retry only via `retry_import` (9.3, D18b) |

- A terminal value is terminal **forever** — there is no path from any `completed*`
  back to an import attempt (D4); `failed` leaves only via the explicit command (D18b).
- `discarded` is stored (not just printed) so the discard warning can be reported again
  on a later startup, not only in the very first notification.
- `pending_cleanup` is written **in the same commit as the data and the status**, and
  shrinks as files are removed; it is empty/absent once cleanup is done.
- This is deliberately *not* a per-file state machine: one status plus two small
  path/name lists (a three-key variant would be equivalent; single-row JSON is the
  decided shape).

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

### 9.3 Failure and retry — decided (D18)

- Any exception inside step 2–6 → **no data commit** (single transaction rolls back), no
  file deletions, and a best-effort second small transaction writing `status = "failed"`
  (+ error text).
- **If that second transaction also cannot commit** (disk full, corrupt file, read-only
  profile — `status.db` unreadable/unwritable): **no durable state exists at all**, so the
  failure is **reported** through the Kodi-side notification and the import **retries at
  the next GUI startup**, because "no marker" is the retry signal. **No fallback status
  file and no non-database marker of any kind** (D18a) — this is the brief's explicit
  instruction and it replaces the earlier holding position of "no fallback is adopted
  until you decide". Valid sources are never discarded without a committed outcome.
- **If `failed` *was* recorded**: the next startup **reports the stored state and attempts
  nothing** — no silent re-attempt (D4).
- Retry is **explicit** (D18b): after the underlying problem is reviewed/corrected, the
  user triggers a retry through a dedicated frontend script command —
  `RunScript(plugin.program.umsa.mame.surfer,retry_import)` — registered alongside the
  existing `del_db` / `del_status` commands in `addon.py:18-37`, which clears the marker
  and re-runs 8.1.
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
| marker `failed` | report the stored failure state, start **no** attempt; retry only via `retry_import` (9.3, D18b) |
| import attempted, **nothing committed** (incl. `status.db` not writable) | **report + retry at the next GUI startup** — no marker exists, so the next startup re-enters the import; no fallback file (9.3, D18a) |
| `status.db` unusable so early that `DBMod.__init__` itself raises | startup aborts with all sources untouched (7.2); nothing was attempted, so the next startup naturally retries (D18a) |

- Ordering constraint found in the audit: `onInit` currently loads the default filter
  **before** `DBMod` is created (`gui.py:344` vs `gui.py:357`), while the migration
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
  implementation time): **preserved and reported** to the maintainer; never added to the
  cleanup scope without a new explicit decision (**D17**, resolving Q5).

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
  - `read_lastgames() -> list[int]` / `replace_lastgames(ids) -> None` (keep the newest
    **100**, D19).
  - `read_filter_selections(name) -> dict[str, list[str]]` /
    `replace_filter_selections(name, lists) -> None` / `list_filter_names() -> list[str]`
    (internal category keys internally, public labels at the boundary — D15).
  - `import_legacy_files(paths) -> ImportResult` (section 8) and
    `record_import_result(...)` / `get_import_marker()` / `clear_import_marker()` (the
    last one only from the explicit `retry_import` path — D18b).
  - later, for the screensaver: `record_screensaver_display(set_id, software_id)`,
    `get_screensaver_history(limit=100)` (D16).
- **DBMod facades** (the connection-attribute guard forbids add-ons touching `.sdb`, so
  both the GUI and the screensaver go through `DBMod`): `load_lastgames` /
  `save_lastgames`, `load_filter_selections` / `save_filter_selections` /
  `list_filter_names`, `get_import_marker` / `run_legacy_import` (later
  `record_screensaver_display`), each a one-line delegate to a per-call
  `_get_history_repository()` mirroring `_get_status_repository` (`database.py:759-767`).
- **Frontend retry command:** `addon.py` gains `retry_import` beside `del_db` /
  `del_status` (`addon.py:18-37`); it clears a recorded `failed` marker through the
  facade and re-runs the import — **the only path that may clear a recorded failure**
  (D18b).
- **Notification:** issued from the Kodi side after the Core function returns its
  result. Per the instruction to use the existing adapter: add a small notification
  helper to **`lib/umsa_core_kodi.py`** (the single permitted Kodi adapter in the core
  add-on) and call it from the frontend's startup path; alternatively the frontend's
  established `xbmcgui.Dialog().notification(...)` pattern (`gui.py:513, 1793, 2040`)
  can be used directly. Either way, `umsa_core` stays Kodi-free and no *second* adapter
  is created.
- **Notification detail (corrective follow-up):** the startup and explicit-`retry_import`
  notifications name the pending-cleanup files (basenames, not just a count) and keep the
  discarded filenames, so the failure/cleanup state is diagnosable from the notification
  alone.
- `umsa_core_python.py` is not assumed to exist (still a roadmap item).

---

## 14. Relationship to Phase 4.7 and ordering (confirmed — D11)

The five responsibilities stay separate:

| Responsibility | Home | Step |
|---|---|---|
| GUI lastgames persistence (immediate) + its one-time import/cleanup | `history_repository.py` + `status_migrations.py` + GUI call sites | **4.6.1** (this plan) |
| Filter-selection persistence + its one-time import/cleanup | same repository/migration, `filter_selections` table, GUI Load/Save call sites | **4.6.1** (same migration, D1) |
| Screensaver history (writes only, starts empty) | same repository, `screensaver_history` table, screensaver call sites | **4.6.2** (semantics decided in D16; implementation still follows 4.6.1) |
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

**Ordering: confirmed as 4.7 → 4.6.1 → 4.6.2 (D11).** The earlier "land 4.6.1 before
4.7" advice (front-load the `user_version == 0` test churn) was written when the scope
was lastgames-only; with filter selections in the same migration the maintainer
confirmed the dependency argument: database-backed filter loading before the
explicit-state refactor would bind persistence to the old implicit-state API and create
avoidable follow-up changes. Two accompanying rules:

- **Phase 4.7's existing scope and acceptance criteria are unchanged**, and its
  text-file persistence (`load_filter`/`save_filter`, `lastgames.txt` via
  `save_software_list`) **stays in place during 4.7** — nothing is migrated early; the
  files move only inside the later one-time `status.db` migration (sections 8–11).
- **Q1–Q6 (section 16) are resolved** (D12–D19, section 1.1), so the documented gate on
  4.6.1 is cleared: validation rules, deletion scope, filter semantics, screensaver
  semantics and DB-failure recovery are all decided. Only the Kodi-runtime verification
  items in 16.2 remain, and they are checked during implementation, not before it.

The schema/import pieces remain code-disjoint from 4.7 and *could* technically land
earlier, but that option is no longer part of the plan.

---

## 15. Implementation and regression-test plan (executed — items 1–6 landed, 7 verified)

**Preconditions (D11):** Phase 4.7 has landed with its existing scope and acceptance
criteria (text-file persistence untouched — committed through `bd83a4d`), and Q1–Q6 are
resolved and recorded as D12–D19 (section 1.1) and in section 16. The Kodi-runtime
verifications in 16.2 were performed *while* implementing. The steps below were
characterisation-first; items 1–5 are the 4.6.1 migration/import work and item 6 is 4.6.2:

1. **Migration module** — `status_migrations.py`, single `MIGRATIONS = {1: ...}`
   calling the three `create_*` helpers; swap the call site; tests: fresh DB (all seven
   tables, `user_version == 1`), legacy DB seeded with representative `sets`/`emu`/
   `emu_conn` rows at version 0 (rows byte-preserved, version → 1), injected failure
   (version stays 0, rollback), and update the three `user_version == 0` assertions.
2. **History repository** — four tables via `create_history_tables`; round-trips for
   lastgames (order, cap at the newest **100** — D19, duplicates preserved — D12),
   filter selections (five categories via the internal-key mapping — D15, value order,
   empty/missing lines, replace-per-name), screensaver history (one row per set,
   move-up on re-display, prune past 100 — D16), marker read/write; Row-contract
   rejection; savepoint ownership.
3. **Import + validation** — valid lastgames (order preserved), valid filters, a token
   with surrounding whitespace (accepted and normalised — D13), extra lines in
   `lastgames.txt` (ignored, unreported — D14), a `filter_<name>.txt` with the wrong
   line count (discarded whole — D14, never padded or truncated), a non-integer token or
   undecodable bytes in file A alongside valid file B (B imported, A discarded +
   recorded), an empty five-line filter file (imported as empty categories), all-empty
   (→ `completed_no_source`), marker-present re-run (no-op, DB state kept), recorded
   failure → `failed` + no deletion + **no** auto-retry on the next simulated startup,
   uncommittable outcome → no marker + retry on the next simulated startup with **no
   fallback file** (D18).
4. **Cleanup** — deletion after commit; interrupted deletion → cleanup-only path;
   un-deletable file → path recorded and reported; **unknown files untouched**
   (assert a `lastsaver.txt` and a stray `.txt` survive every path) — D17.
5. **GUI wiring** — entry appended **only** on `select_software` success and persisted
   immediately with the newest 100 ids (D12/D19), DB-backed filter load/save replacing
   `load_filter`/`save_filter` calls (reordered around `DBMod`
   creation), DB-backed Load/Save Filter name list replacing the `os.listdir` scan
   (`gui.py:1311-1313`), `retry_import` command wired beside `del_db`/`del_status`
   (`addon.py:18-37`), notification at startup. `tests/test_persistence.py`'s pinned
   file behaviours stay green — the helpers remain for the import path.
6. **Screensaver history (4.6.2) — ✅ implemented.** `HistoryRepository.record_screensaver_display`
   / `list_screensaver_history` (Kodi-free) behind the `DBMod.record_screensaver_display` /
   `get_screensaver_history` facades, plus the boundary hooks in `ui.py`: `Saver.record_display`
   is called once after the completed cross/slide/wall render block and before the wait loop
   (`normalize_set_id` → `record_screensaver_display`; a missing/invalid id or any DB failure is
   logged and never breaks rendering), and `Player.onAVStarted()` records for videos with the
   `set_id` carried through the `attach_set_id`/`read_set_id` `umsa_set_id` unique ID (value
   first: `setUniqueID(str(set_id), 'umsa_set_id')`), capability-guarded for Kodi < 20 via
   `hasattr` (video displays then logged, not recorded, and nothing faked); `read_software_id`
   keeps the `Votes`-based handoff unchanged. Orphan rows are reported and never substituted.
   Tests: `tests/test_screensaver_history_repository.py` (51) and
   `tests/test_screensaver_history_hooks.py` (52).
7. Full suite + per-file ruff/mypy comparisons. No Kodi-runtime automation exists
   (`AGENTS.md`) — GUI/screensaver behaviour is verified manually, including the 16.2
   items. Full suite after 4.6.2: **819 passed**, 5 skipped, 18 subtests passed; new files
   add no ruff findings (per-file comparison against the HEAD baseline), and the
   pre-existing `ui.py`/`database.py` findings are unchanged.

No test is added or modified by this document.

---

## 16. Question status — Q1–Q6 resolved, verification items remaining

The six questions that gated this phase are **answered**; every resolution is recorded
with its binding decision and the evidence behind it. Nothing below is a proposal.

### 16.1 Resolutions (Q1–Q6)

- **Q1 — GUI lastgames duplicates and failed displays → D12.** (a) Duplicates are
  preserved as separate entries (a repeated display is a real event). (b) An entry exists
  only after a successful display: the insert-and-advance moves into `select_software`'s
  success funnel, and the failure return (`gui.py:2038-2043`) appends nothing — today's
  pre-insert plus the `None`-on-both-paths return (`gui.py:2186`) is exactly the behaviour
  that changes. (c) Order and pointer behaviour stay as they are (index 0 = oldest,
  newest = resume point); storage keeps the newest **100** (D19 — the maintainer's
  retention change; today's writer trims to 10 at `gui.py:2566`).
- **Q2 — Validation strictness → D13 (tokens) + D14 (line count).** Tokens: strip, then
  `^[0-9]+$` — anything else discards the whole file, recorded and deleted after commit,
  which keeps the brief's all-or-nothing rule exactly where a value cannot be an id.
  Line count: `lastgames.txt` keeps the legacy first-line-only tolerance (further lines
  ignored, unreported), but `filter_<name>.txt` must have **exactly five logical lines** —
  a wrong count discards the whole file (never padded, never truncated) because the
  positional category mapping cannot be repaired without inventing or dropping
  categories. A non-integer token or undecodable bytes discards a file in every case.
- **Q3 — Filter semantics beyond the files → D15.** Verbatim id strings, value order via
  `position`, empty category / empty file / missing file ≡ no rows, `filter_name` =
  filename part — all as decided. The **active filter name, `use_filter` and `order` are
  not persisted** (verified absent today: `database.py:280-281`, `gui.py:345-346`), and the
  Load/Save dialog keeps offering exactly the imported names. The public Core API keys
  stay unchanged; the database stores the internal keys through an explicit by-name
  mapping (the key *orders* differ between `persistence.py:13-19` and `:29-35`, so
  position can never be used for the mapping).
- **Q4 — Screensaver history semantics → D16.** Unique sets with recency move-up (not an
  event log), ordering by the monotonic `id` (not `displayed_at`), identifier `set_id`
  with `software_id` stored alongside for the context menu. The image boundary is the
  post-render point (`ui.py:454-571`, before the wait loop; `remember_art` at
  `ui.py:435` fires before image rejection and is explicitly **not** a boundary), the
  video boundary is **`Player.onAVStarted()`** (`ui.py:712` is `onPlayBackStarted`, which
  is not used for recording). `set_id` travels with a video through the `umsa_set_id`
  unique ID, capability-guarded for Kodi < 20. Orphaned `set_id` rows are kept and
  reported, never substituted.
- **Q5 — Unexpected userdata files → D17.** Only `lastgames.txt` and validated
  `filter_*.txt` are deleted; `lastsaver.txt` (never written by any revision — only
  `load_lastsaver`, `persistence.py:64-76`, and its single consumer
  `gamelist_strategies.py:153`) and anything else unknown is preserved and reported.
- **Q6 — Recovery after a database-level failure → D18.** (a) A recorded `failed` state
  retries only through the new explicit `retry_import` script command beside
  `del_db`/`del_status` (`addon.py:18-37`). (b) When even the marker cannot be written,
  the approved behaviour is exactly the brief's: **report the failure and retry at the
  next GUI startup, with no fallback status file** — "no marker" is the retry signal, and
  valid sources are never discarded without a committed outcome. Deletion failures stay
  cleanup-only (D4).

Resolved by the maintainer earlier and unchanged: history bound = **100**, screensaver
starts empty with no import source, **one** migration instead of the earlier v1/v2/v3
split, deletion of the legacy files instead of keeping them as backups, immediate
lastgames persistence after a successful display, and the **4.7 → 4.6.1 → 4.6.2 ordering
(D11, former Q7)** — plus, from this update, `gui_lastgames` retention of **100** (D19).

### 16.2 Kodi-runtime verification items (cannot be settled by code inspection)

Not design decisions — checked while implementing, on a real Kodi (this machine runs
**Kodi 21.3 (Omega)**, add-ons declare `xbmc.python 3.0.0` = Kodi 19 floor):

1. **`onAVStarted` per playlist item** — fires once per video, including when
   `playnext()` advances the playlist, so exactly one record is written per displayed
   video (the callback exists since Kodi 18; `ui.py` currently uses only
   `onPlayBackStarted`/`onPlayBackEnded`, `ui.py:712`, `:773`).
2. **Unique-ID round-trip** — `setUniqueID(str(set_id), 'umsa_set_id')` (value first,
   type second) on the playlist ListItem
   must read back as `getUniqueID('umsa_set_id')` from `Player.getVideoInfoTag()` during
   playback; both are `@python_v20`, so the capability guard must degrade cleanly on
   Kodi 19 (video displays then not recorded; the `Votes`-based software-id handoff at
   `ui.py:143` unaffected).
3. **Image boundary reality** — Kodi exposes no image-load success callback, so
   "control populated" is the strongest available "actually displayed" signal; confirm
   that known-bad files are still rejected earlier by `check_snapshot` (`ui.py:252-293`)
   and never reach the record.
4. **Orphan row behaviour** — with a `set_id` absent from `umsa.db`, the context-menu
   handoff must produce the documented report instead of the `TypeError` that
   `get_info_by_set_and_swl` raises on no match (`game_repository.py:482-484`).
5. **Startup notification ordering** — the migration/import notification appears once,
   after `DBMod` is open, including on a brand-new profile (fresh `status.db`,
   no legacy files).

---

## 17. Document status

Original audit code basis `b84341e` (steps 4.5/4.6 committed as `fcdefe5` and `b84341e`);
documentation reconciled in the tracked `docs/database_refactor/` directory (`ec400f4`
initial, `5514efd` refresh). Since the audit, Phase 4.7 landed (`479e202` + `10f9fbd` +
`da65a62` + `bc631eb`) — satisfying the 4.7 dependency — and the bounded
retry-without-filters fix landed as **`bd83a4d`**, so the suite is **661 passed, 5
skipped, 18 subtests passed** at HEAD `bd83a4d` with a clean tracked tree (pre-existing
ruff findings unchanged).

**This update (2026-10-18, documentation only)** records the maintainer's phase brief and
the five follow-up answers: Q1–Q6 are resolved as **D12–D19** (section 1.1, section 16),
including the `gui_lastgames` retention change to **100** entries (D19); sections 2–11
were restated from proposals into decided rules, line references were re-checked against
`bd83a4d`, and the remaining open work is limited to the Kodi-runtime verifications in
**16.2** (tested while implementing, this machine runs Kodi 21.3 with Kodistubs 21.0.0).

**Implementation (2026-10-18):** the production work is now in place — the versioned
migration, the history repository, the legacy importer/cleanup/`retry_import`, the `DBMod`
facades, the GUI startup wiring and the `retry_import` script command — with the strict
filter line-count rule (D14) and the D18 recovery semantics. During the audit itself
nothing was implemented: the real profile listed in section 12 was opened **read-only**,
and no user file was deleted, renamed or rewritten. Companion updates in this directory:
the step 4.6.1a entry and execution-order note in `roadmap.md`, the checklist / documents
/ next-step / validation entries in `README.md`. The D11 ordering **4.7 → 4.6.1 → 4.6.2**
holds with 4.7 and 4.6.1 complete; 4.6.2 (screensaver history) remains, with the 16.2
checks verified during implementation on this machine.

**Step 4.6.2 (2026-10-19, in the working tree):** the screensaver display-history writes
are now implemented on top of the 4.6.1 schema with **no new migration and no schema
change** — `HistoryRepository.record_screensaver_display`/`list_screensaver_history`
(Kodi-free), the `DBMod` facades `record_screensaver_display`/`get_screensaver_history`,
and the `ui.py` boundary hooks (`Saver.record_display` for cross/slide/wall after the
render block; `Player.onAVStarted()` for videos via the `umsa_set_id` unique ID, Kodi < 20
guarded) — see section 15 item 6. New tests: `tests/test_screensaver_history_repository.py`
(51 passed) and `tests/test_screensaver_history_hooks.py` (52 passed); full suite
**819 passed**, 5 skipped, 18 subtests passed, with the new files adding no ruff findings.
The section 16.2 items were re-checked while implementing; the `setUniqueID` argument order
is documented correctly now (value first, type second) in sections 5 and 16.2.
