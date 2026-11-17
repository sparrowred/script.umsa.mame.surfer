"""Repository for the emulator configuration in status.db (``emu``, ``emu_conn``).

Owns the table schema. Writes use :func:`umsa_core.sqlite.write_savepoint`.
``save_emulator`` and ``delete_emulator`` commit in two steps, so a failure in
the second step leaves the first one applied.
"""

from __future__ import annotations

import sqlite3

from .logging import log
from .sqlite import require_row_connection, write_savepoint


def create_emulator_tables(cursor: sqlite3.Cursor) -> None:
    """Create the ``emu`` and ``emu_conn`` tables if they do not exist."""

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

    Never opens or closes the connection; rows are returned as plain dicts.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Wrap a ``status.db`` connection.

        Raises:
            ValueError: If the connection does not use ``sqlite3.Row``
                (:func:`umsa_core.sqlite.require_row_connection`).
        """

        require_row_connection(connection, "EmulatorRepository")
        self._conn = connection

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def get_emulators(self, source=None, swl_name=None) -> list[dict]:
        """Return the emulators of a source or software list, ordered by name.

        A truthy ``source`` wins over ``swl_name``; with neither, every
        emulator is returned. The filtered queries add the connection id as
        ``emu_conn_id``.
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
        """Return one emulator by ``emu_id`` or ``emu_conn_id``, or ``None``.

        A truthy ``emu_id`` wins; with neither, no query runs.
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
        """Insert or update an emulator and, unless ``reconfigure``, connect it.

        The ``emu`` row is committed first; the connection is created
        afterwards by :meth:`connect_emulator` in its own unit, so a failing
        connection insert leaves the saved emulator in place. An update takes
        the id from ``emu_info['id']``.
        """

        if "id" in emu_info:
            emu_id = emu_info["id"]
            with write_savepoint(self._conn, "umsa_emu_write") as cursor:
                cursor.execute(
                    "UPDATE emu SET name = ?, exe = ?, dir = ?, zip = ?, mode = ? "
                    "WHERE id = ?",
                    (emu_info["name"], emu_info["exe"], emu_info["dir"],
                     emu_info["zip"], emu_info["mode"], emu_id))
        else:
            with write_savepoint(self._conn, "umsa_emu_write") as cursor:
                cursor.execute(
                    "INSERT INTO emu (name, exe, dir, zip, mode) VALUES (?, ?, ?, ?, ?)",
                    (emu_info["name"], emu_info["exe"], emu_info["dir"],
                     emu_info["zip"], emu_info["mode"]))
                # Read it now, before a later write can change lastrowid.
                emu_id = cursor.lastrowid

        if not reconfigure:
            self.connect_emulator(emu_id, source=source, swl_name=swl_name)

    def connect_emulator(self, emu_id, source=None, swl_name=None) -> None:
        """Connect an emulator to a source or software list.

        A truthy ``source`` wins over ``swl_name``; with neither, nothing is
        inserted and a debug message is logged.
        """

        if source:
            column, value = "source", source
        elif swl_name:
            column, value = "swl", swl_name
        else:
            log("UMSA database: connect_emulator error", level='debug')
            return

        with write_savepoint(self._conn, "umsa_emu_write") as cursor:
            cursor.execute(
                f"INSERT INTO emu_conn (emu_id, {column}) VALUES (?, ?)",
                (emu_id, value))

    def delete_emulator_connection(self, emu_conn_id):
        """Delete one emulator connection to a software list or source.

        The read and the delete run in one unit. Returns the emulator id only
        when the deleted connection was its last one, otherwise ``None``.
        """

        with write_savepoint(self._conn, "umsa_emu_write") as cursor:
            cursor.execute(
                "SELECT emu_id FROM emu_conn WHERE emu_id IN "
                "(SELECT emu_id FROM emu_conn WHERE id = ?)", (emu_conn_id,))
            connected_emus = cursor.fetchall()
            cursor.execute("DELETE FROM emu_conn WHERE id = ?", (emu_conn_id,))
        return connected_emus[0][0] if len(connected_emus) == 1 else None

    def delete_emulator(self, emu_id) -> None:
        """Delete an emulator and all of its connections.

        The connection rows are deleted and committed first, the emulator row
        in a second unit, so a failed emulator delete leaves the connections
        removed.
        """

        with write_savepoint(self._conn, "umsa_emu_write") as cursor:
            cursor.execute("DELETE FROM emu_conn WHERE emu_id = ?", (emu_id,))
        with write_savepoint(self._conn, "umsa_emu_write") as cursor:
            cursor.execute("DELETE FROM emu WHERE id = ?", (emu_id,))
