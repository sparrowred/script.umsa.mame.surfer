"""status.db repository for play history and per-set further media.

This module centralises SQL access to the ``status.db`` ``sets`` table (play
status, play history and the per-set MARP/Youtube links) and is the
authoritative definition of that table's schema, following the conventions of
:mod:`umsa_core.dat_repository` and :mod:`umsa_core.game_repository`. The
``emu``/``emu_conn`` tables of ``status.db`` are still defined in
:mod:`umsa_core.database` until roadmap step 4.6.

The repository operates on an existing SQLite connection supplied by the
caller; it never opens or closes it, never caches a different connection and
never manages the lifetime of the caller's connection. Connections must use
``sqlite3.Row`` (step 4.2b contract, decision Q7) and are rejected otherwise.

Write methods run their statements inside a savepoint (the ownership-aware
transaction convention of :class:`umsa_core.dat_repository.DatRepository`):

- a standalone successful write commits the transaction the savepoint
  started, so ``connection.in_transaction`` is ``False`` afterwards;
- a failure rolls back exactly the repository operation's statements;
- a caller-owned outer transaction is never committed (and unrelated pending
  caller changes survive a repository failure);
- no savepoint or transaction is left open on either path.

Reads never commit and own only short-lived cursors that are closed in a
``finally`` block. Rows are returned transparently as the connection's native
``sqlite3.Row``, so both ``row['col']`` and ``row[i]`` access keep working;
presentation and time formatting stay in :class:`umsa_core.database.DBMod`.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable

from .sqlite import require_row_connection


def create_status_tables(cursor: sqlite3.Cursor) -> None:
    """Create the ``status.db`` ``sets`` table (current schema, unchanged).

    Column names, order, declared types, defaults and the primary-key
    behaviour are exactly the DDL that used to be inlined in
    ``DBMod._open_persistent_databases``. No migration runs here: schema
    changes must follow the documented ``PRAGMA user_version`` policy (Q6 in
    ``docs/database_refactor/README.md``), and this step introduces no schema
    change.

    Args:
        cursor: Any cursor on the ``status.db`` connection.
    """

    cursor.execute(
        # last_played = YYYY-MM-DD HH:MM
        # time_played = seconds
        """
        CREATE TABLE IF NOT EXISTS sets(
            id             INT PRIMARY KEY NOT NULL,
            last_played    DATETIME,
            time_played    BIGINT DEFAULT 0,
            play_count     INT DEFAULT 0,
            options        TEXT,
            emu_id         INT,
            marp           TEXT,
            youtube        TEXT
        )
        """
    )


class StatusRepository:
    """Play-history and further-media operations on a caller-owned connection.

    The repository never opens or closes the supplied connection and never
    caches a different one; :class:`umsa_core.database.DBMod` builds one per
    call so it can never pin a connection that later code has replaced.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialise the repository.

        Args:
            connection: The existing ``status.db`` connection to operate on.
                The repository does not own this connection.

        Raises:
            ValueError: If the connection does not use ``sqlite3.Row``.
        """

        require_row_connection(connection, "StatusRepository")
        self._conn = connection

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the underlying connection (read-only access)."""
        return self._conn

    def get_status_for_set(self, set_id) -> sqlite3.Row | None:
        """Return the raw status row for ``set_id``, or ``None``.

        Row-transparent: both positional access (``row[1]``…``row[4]``, used
        by ``DBMod.get_status_for_set``'s dict building) and named access keep
        working. Time/elapsed formatting is presentation logic and stays in
        ``DBMod``.
        """

        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT * FROM sets WHERE ID = ?", (set_id,))
            return cursor.fetchone()
        finally:
            cursor.close()

    def get_further_media(self, set_id) -> sqlite3.Row | None:
        """Return a ``marp``/``youtube`` row for ``set_id``, or ``None``.

        Row-transparent and *not* converted to a dict or tuple: consumers use
        named-column access such as ``row['marp']``.
        """

        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT marp, youtube FROM sets WHERE sets.id = ?", (set_id,)
            )
            return cursor.fetchone()
        finally:
            cursor.close()

    def get_latest_by_set_ids(self, set_ids: Iterable) -> int | None:
        """Return the latest played set id among ``set_ids``, or ``None``.

        Keeps the historical ``ORDER BY last_played DESC LIMIT 1`` semantics
        across the given ids (a status row with a ``NULL`` ``last_played`` is
        still a candidate, exactly as before). An empty id collection returns
        ``None`` without building malformed SQL, and set ids without a status
        row simply do not match. Returns the bare id value (not a Row), which
        is the shape ``DBMod.get_latest_by_software`` has always returned.
        """

        ids = list(set_ids)
        if not ids:
            return None

        placeholders = ",".join(["?"] * len(ids))
        select_statement = (
            f"SELECT id FROM sets WHERE id IN ({placeholders}) "
            "ORDER BY last_played DESC LIMIT 1"
        )
        cursor = self._conn.cursor()
        try:
            cursor.execute(select_statement, ids)
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            return None
        return row[0]

    def _write_within_savepoint(self, operation) -> None:
        """Run ``operation(cursor)`` inside an ownership-aware savepoint.

        Follows the ``DatRepository`` write convention: a savepoint is always
        opened (which also starts the transaction when none is active), the
        statements are released on success and rolled back to on failure, and
        only a transaction this call started is committed. A caller's outer
        transaction and its pending changes are never committed, never rolled
        back, and never left with a dangling savepoint.
        """

        conn = self._conn
        had_transaction = conn.in_transaction
        cursor = conn.cursor()
        try:
            cursor.execute("SAVEPOINT umsa_status_write")
            try:
                operation(cursor)
            except Exception:
                cursor.execute("ROLLBACK TO umsa_status_write")
                cursor.execute("RELEASE umsa_status_write")
                raise
            else:
                cursor.execute("RELEASE umsa_status_write")
                if not had_transaction:
                    conn.commit()
        finally:
            cursor.close()

    def write_status_after_play(self, set_id, played_seconds) -> None:
        """Record one play session for ``set_id``.

        Preserves the existing behaviour exactly: the timestamp format
        ``%Y-%m-%d %H:%M``; a new status row is inserted when none exists;
        otherwise ``last_played`` is replaced, ``time_played`` accumulates
        ``played_seconds`` and ``play_count`` is incremented with the same
        arithmetic as before. The SELECT and the corresponding INSERT/UPDATE
        run within one savepoint, so an exception can never leave a partially
        applied update. Observable return value: ``None``.
        """

        date = time.strftime("%Y-%m-%d %H:%M")

        def operation(cursor: sqlite3.Cursor) -> None:
            # get data
            cursor.execute(
                "SELECT time_played, play_count FROM sets WHERE id = ?",
                (set_id,),
            )
            set_fetch = cursor.fetchone()
            # update data
            if set_fetch:
                set_data = (
                    date,
                    played_seconds + set_fetch[0],
                    set_fetch[1] + 1,
                    set_id,
                )
                cursor.execute(
                    "UPDATE sets "
                    "SET last_played = ?, time_played = ?, play_count = ? "
                    "WHERE id = ?",
                    (set_data),
                )
            # new data
            else:
                set_data = (set_id, date, played_seconds, 1)
                cursor.execute(
                    "INSERT INTO sets (id, last_played, time_played, play_count) "
                    "VALUES (?,?,?,?)",
                    (set_data),
                )

        self._write_within_savepoint(operation)

    def save_further_media(
        self, set_id, marp: str | None = None, youtube: str | None = None
    ) -> None:
        """Save MARP or Youtube entries for ``set_id``.

        Preserves the Q4 fix and the current update semantics: an existing
        row is only updated with the supplied truthy ``marp``/``youtube``
        values (unspecified values are never overwritten); a missing row gets
        exactly one INSERT holding both columns when at least one value is
        supplied; when neither needs writing and no row exists, nothing
        happens. Observable return value: ``None``.
        """

        def operation(cursor: sqlite3.Cursor) -> None:
            # check set_id
            cursor.execute("SELECT sets.id FROM sets WHERE id = ?", (set_id,))
            if cursor.fetchone():
                # update
                if marp:
                    cursor.execute(
                        "UPDATE sets SET marp = ? WHERE id = ?", (marp, set_id)
                    )
                if youtube:
                    cursor.execute(
                        "UPDATE sets SET youtube = ? WHERE id = ?",
                        (youtube, set_id),
                    )
            elif marp or youtube:
                # insert: both values belong to this one row, so a single
                # INSERT writes them (a second INSERT would reuse the same PK)
                cursor.execute(
                    "INSERT INTO sets (id, marp, youtube) VALUES(?,?,?)",
                    (set_id, marp or None, youtube or None),
                )

        self._write_within_savepoint(operation)
