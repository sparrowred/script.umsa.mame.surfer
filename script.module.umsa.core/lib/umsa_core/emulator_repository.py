"""status.db repository for emulator configuration (``emu``/``emu_conn``).

This module centralises SQL access to the ``status.db`` ``emu`` and
``emu_conn`` tables (emulator configuration and its source/software-list
connections) and is the authoritative definition of their schema, following
the conventions of :mod:`umsa_core.status_repository` and
:mod:`umsa_core.dat_repository`. Emulator configuration is a distinct domain
from play history, so it lives in its own repository class rather than in
``StatusRepository`` (roadmap step 4.6).

The repository operates on an existing SQLite connection supplied by the
caller; it never opens or closes it, never caches a different connection and
never manages the lifetime of the caller's connection. Connections must use
``sqlite3.Row`` (step 4.2b contract, decision Q7) and are rejected otherwise.

Write methods run their statements inside a savepoint (the ownership-aware
transaction convention of :class:`umsa_core.status_repository.StatusRepository`):

- a standalone successful write commits the transaction the savepoint
  started, so ``connection.in_transaction`` is ``False`` afterwards;
- a failure rolls back exactly the repository operation's statements;
- a caller-owned outer transaction is never committed (and unrelated pending
  caller changes survive a repository failure);
- no savepoint or transaction is left open on either path.

``save_emulator`` keeps the historical two-phase sequence: the ``emu`` row is
written and committed first, and only then (when ``reconfigure`` is false) is
the connection created — a failing connection insert therefore leaves the
saved emulator in the database. ``delete_emulator`` likewise keeps the
historical order and commit boundaries: the ``emu_conn`` rows are deleted and
committed before the ``emu`` row delete is attempted, so a failed emulator
delete leaves the connections removed (intentionally unchanged failure
atomicity, documented in ``docs/database_refactor``).

Reads never commit and own only short-lived cursors that are closed in a
``finally`` block. Rows are normalised to plain dicts at the boundary —
``dict`` is the public shape of all six facade methods.
"""

from __future__ import annotations

import sqlite3

from .logging import log
from .sqlite import require_row_connection


def create_emulator_tables(cursor: sqlite3.Cursor) -> None:
    """Create the ``status.db`` ``emu``/``emu_conn`` tables (schema, unchanged).

    Column names, order, declared types, defaults, primary keys and
    autoincrement behaviour are exactly the DDL that used to be inlined in
    ``DBMod._open_persistent_databases``. No migration runs here: schema
    changes must follow the documented ``PRAGMA user_version`` policy (Q6 in
    ``docs/database_refactor/README.md``), and this step introduces no schema
    change.

    Args:
        cursor: Any cursor on the ``status.db`` connection.
    """

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS emu(
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      VARCHAR(100) NOT NULL,
            exe       VARCHAR(100) NOT NULL,
            dir       VARCHAR(200) NOT NULL,
            zip       INT NOT NULL,
            mode      INT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS emu_conn(
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            emu_id    INT NOT NULL,
            swl       VARCHAR(50),
            source    VARCHAR(100)
        )
        """
    )


class EmulatorRepository:
    """Emulator-configuration operations on a caller-owned connection.

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

        require_row_connection(connection, "EmulatorRepository")
        self._conn = connection

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the underlying connection (read-only access)."""
        return self._conn

    def get_emulators(self, source=None, swl_name=None) -> list[dict]:
        """Return emulators based on source or software list.

        Preserves the historical filter precedence: ``source`` wins when it
        is truthy, then ``swl_name``, otherwise every emulator is returned.
        The filtered queries join ``emu_conn`` and expose the connection id as
        ``emu_conn_id``; the unfiltered query returns only the ``emu``
        columns. Rows are ordered by emulator name and returned as plain
        dicts; no match yields an empty list.
        """

        cursor = self._conn.cursor()
        try:
            if source:
                cursor.execute(
                    "SELECT emu.id, emu.name, emu.exe, emu.dir, emu.zip, emu.mode, \
                            emu_conn.id as emu_conn_id \
                     FROM emu JOIN emu_conn ON emu.id = emu_conn.emu_id \
                     WHERE emu_conn.source = ? ORDER BY emu.name", (source,))
            elif swl_name:
                cursor.execute(
                    "SELECT emu.id, emu.name, emu.exe, emu.dir, emu.zip, emu.mode, \
                            emu_conn.id as emu_conn_id \
                     FROM emu JOIN emu_conn ON emu.id = emu_conn.emu_id \
                     WHERE emu_conn.swl = ? ORDER BY emu.name", (swl_name,))
            else:
                cursor.execute(
                    "SELECT id, name, exe, dir, zip, mode FROM emu ORDER BY name")
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return [dict(row) for row in rows] if rows else []

    def get_emulator(self, emu_id=None, emu_conn_id=None) -> dict | None:
        """Return information about one saved emulator, or ``None``.

        Preserves the historical lookup precedence: a truthy ``emu_id``
        matches the ``emu`` row directly, a truthy ``emu_conn_id`` resolves
        through ``emu_conn``, otherwise (no caller reaches this state) no
        query runs and ``None`` is returned.
        """

        cursor = self._conn.cursor()
        try:
            if emu_id:
                cursor.execute(
                    "SELECT id, name, exe, dir, zip, mode FROM emu WHERE id = ?",
                    (emu_id,))
            elif emu_conn_id:
                cursor.execute(
                    "SELECT id, name, exe, dir, zip, mode FROM emu WHERE id = \
                     (SELECT emu_id FROM emu_conn WHERE id = ?)", (emu_conn_id,))
            else:
                return None
            row = cursor.fetchone()
        finally:
            cursor.close()
        return dict(row) if row is not None else None

    def save_emulator(self, emu_info, reconfigure, source=None, swl_name=None) -> None:
        """Save an emulator and connect it if needed.

        Keeps the observable sequence of the historical ``DBMod`` method:

        1. insert or update the ``emu`` row (inside its own savepoint);
        2. commit that emulator-row change;
        3. if ``reconfigure`` is false, create the requested connection via
           :meth:`connect_emulator` — a separate unit with its own commit.

        For a new emulator the generated id is read from the insert cursor
        immediately after the INSERT, before any later write can move
        ``lastrowid``. For an update the emulator id comes from
        ``emu_info['id']`` (never from a stale ``lastrowid``); the
        update-plus-``reconfigure=False`` combination is unreachable from
        every existing caller — ``gui.py`` always passes ``reconfigure=True``
        when ``emu_info`` comes from ``get_emulator`` — and is pinned by a
        test. Observable return value: ``None``.
        """

        if "id" in emu_info:
            emu_id = emu_info["id"]

            def operation(cursor: sqlite3.Cursor) -> None:
                cursor.execute(
                    "UPDATE emu SET name = ?, exe = ?, dir = ?, zip = ?, mode = ? "
                    "WHERE id = ?",
                    (emu_info["name"], emu_info["exe"], emu_info["dir"],
                     emu_info["zip"], emu_info["mode"], emu_id))

            self._write_within_savepoint(operation)
        else:
            captured: dict = {}

            def operation(cursor: sqlite3.Cursor) -> None:
                cursor.execute(
                    "INSERT INTO emu (name, exe, dir, zip, mode) VALUES (?, ?, ?, ?, ?)",
                    (emu_info["name"], emu_info["exe"], emu_info["dir"],
                     emu_info["zip"], emu_info["mode"]))
                # capture the generated id from the insert cursor immediately,
                # before any subsequent write could change lastrowid
                captured["id"] = cursor.lastrowid

            self._write_within_savepoint(operation)
            emu_id = captured["id"]

        if not reconfigure:
            self.connect_emulator(emu_id, source=source, swl_name=swl_name)

    def connect_emulator(self, emu_id, source=None, swl_name=None) -> None:
        """Connect an emulator to a source or software list.

        Preserves the historical precedence: a truthy ``source`` wins over a
        truthy ``swl_name``; when neither is supplied nothing is inserted and
        the historical debug-level message is logged. Observable return
        value: ``None``.
        """

        if source:
            def operation(cursor: sqlite3.Cursor) -> None:
                cursor.execute(
                    "INSERT INTO emu_conn (emu_id, source) VALUES (?, ?)",
                    (emu_id, source))
        elif swl_name:
            def operation(cursor: sqlite3.Cursor) -> None:
                cursor.execute(
                    "INSERT INTO emu_conn (emu_id, swl) VALUES (?, ?)",
                    (emu_id, swl_name))
        else:
            log("UMSA database: connect_emulator error", level='debug')
            return

        self._write_within_savepoint(operation)

    def delete_emulator_connection(self, emu_conn_id):
        """Delete one emulator connection to a software list or source.

        The read and the delete run in one unit so the decision about
        whether the emulator is still connected is made consistently with
        the deletion. Returns the emulator id only when the deleted
        connection was that emulator's final connection, otherwise ``None``.
        """

        result: dict = {}

        def operation(cursor: sqlite3.Cursor) -> None:
            # get emu.ids for emu_conn.id before deleting
            cursor.execute(
                "SELECT emu_id FROM emu_conn WHERE emu_id IN "
                "(SELECT emu_id FROM emu_conn WHERE id = ?)", (emu_conn_id,))
            connected_emus = cursor.fetchall()
            # delete emu_conn.id
            cursor.execute("DELETE FROM emu_conn WHERE id = ?", (emu_conn_id,))
            # return it if only 1
            result["emu_id"] = connected_emus[0][0] if len(connected_emus) == 1 else None

        self._write_within_savepoint(operation)
        return result["emu_id"]

    def delete_emulator(self, emu_id) -> None:
        """Delete an emulator and all of its connections.

        Preserves the historical order and commit boundaries: the connection
        rows are deleted and committed first, then the emulator row is
        deleted in its own unit — a failed emulator delete therefore leaves
        the connections removed (intentionally unchanged failure atomicity
        from the two-commit historical implementation). Observable return
        value: ``None``.
        """

        def delete_connections(cursor: sqlite3.Cursor) -> None:
            cursor.execute("DELETE FROM emu_conn WHERE emu_id = ?", (emu_id,))

        def delete_emulator_row(cursor: sqlite3.Cursor) -> None:
            cursor.execute("DELETE FROM emu WHERE id = ?", (emu_id,))

        self._write_within_savepoint(delete_connections)
        self._write_within_savepoint(delete_emulator_row)

    def _write_within_savepoint(self, operation) -> None:
        """Run ``operation(cursor)`` inside an ownership-aware savepoint.

        Follows the ``StatusRepository`` write convention: a savepoint is
        always opened (which also starts the transaction when none is
        active), the statements are released on success and rolled back to
        on failure, and only a transaction this call started is committed. A
        caller's outer transaction and its pending changes are never
        committed, never rolled back, and never left with a dangling
        savepoint.
        """

        conn = self._conn
        had_transaction = conn.in_transaction
        cursor = conn.cursor()
        try:
            cursor.execute("SAVEPOINT umsa_emu_write")
            try:
                operation(cursor)
            except Exception:
                cursor.execute("ROLLBACK TO umsa_emu_write")
                cursor.execute("RELEASE umsa_emu_write")
                raise
            else:
                cursor.execute("RELEASE umsa_emu_write")
                if not had_transaction:
                    conn.commit()
        finally:
            cursor.close()
