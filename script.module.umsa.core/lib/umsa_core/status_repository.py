"""Repository for play status and further media in status.db (``sets``).

Owns the table schema. Writes use :func:`umsa_core.sqlite.write_savepoint`;
reads return ``sqlite3.Row``. Formatting lives in
:mod:`umsa_core.software_details`.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable

from .sqlite import require_row_connection, write_savepoint

# Sort columns of the play status list.
PLAY_STATUS_ORDERS = ('time_played', 'last_played', 'play_count')
PLAY_STATUS_DEFAULT = 'time_played'

# Ids per ``IN (...)`` statement, below the 999-variable limit of older SQLite.
_IN_BLOCK = 500


def create_status_tables(cursor: sqlite3.Cursor) -> None:
    """Create the ``sets`` table if it does not exist.

    Schema changes go through :mod:`umsa_core.status_migrations`.
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

    Never opens or closes the connection.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Wrap a ``status.db`` connection.

        Raises:
            ValueError: If the connection does not use ``sqlite3.Row``
                (:func:`umsa_core.sqlite.require_row_connection`).
        """

        require_row_connection(connection, "StatusRepository")
        self._conn = connection

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the wrapped connection."""
        return self._conn

    def get_status_for_set(self, set_id) -> sqlite3.Row | None:
        """Return the raw status row (``SELECT *``) for ``set_id``, or ``None``.

        ``software_details.status_dict`` reads it by position.
        """

        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT * FROM sets WHERE ID = ?", (set_id,))
            return cursor.fetchone()
        finally:
            cursor.close()

    def get_status_for_sets(self, set_ids: Iterable) -> dict:
        """Return ``{set id: status row}`` for the ids that have a status row.

        The batch form of :meth:`get_status_for_set`. The ids are queried in
        blocks so a large software never exceeds SQLite's variable limit.
        """

        ids = list(set_ids)
        result = {}
        cursor = self._conn.cursor()
        try:
            for start in range(0, len(ids), _IN_BLOCK):
                block = ids[start:start + _IN_BLOCK]
                placeholders = ",".join(["?"] * len(block))
                cursor.execute(
                    f"SELECT * FROM sets WHERE id IN ({placeholders})", block
                )
                for row in cursor.fetchall():
                    result[row["id"]] = row
            return result
        finally:
            cursor.close()

    def get_played_sets(self, order, limit=250) -> list:
        """Return the status rows of the played sets, highest ``order`` first.

        Rows carry ``id``, ``last_played``, ``play_count`` and ``time_played``.

        Raises:
            ValueError: If ``order`` is not in :data:`PLAY_STATUS_ORDERS`; the
                column name is interpolated into the statement.
        """

        if order not in PLAY_STATUS_ORDERS:
            raise ValueError(f"unknown play status order: {order!r}")

        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT id, last_played, play_count, time_played FROM sets "
                f"WHERE time_played > 0 ORDER BY {order} DESC LIMIT ?",
                (limit,),
            )
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_further_media(self, set_id) -> dict | None:
        """Return ``{'marp': …, 'youtube': …}`` for ``set_id``, or ``None``."""

        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT marp, youtube FROM sets WHERE sets.id = ?", (set_id,)
            )
            row = cursor.fetchone()
            return None if row is None else dict(row)
        finally:
            cursor.close()

    def get_latest_by_set_ids(self, set_ids: Iterable) -> int | None:
        """Return the latest played set id among ``set_ids``, or ``None``.

        Uses ``ORDER BY last_played DESC LIMIT 1``, so a status row with a
        ``NULL`` ``last_played`` is still a candidate. Empty ``set_ids``
        return ``None`` without a query.
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

    def write_status_after_play(self, set_id, played_seconds) -> None:
        """Record one play session of ``played_seconds`` for ``set_id``.

        Sets ``last_played`` (``%Y-%m-%d %H:%M``), adds to ``time_played``
        and increments ``play_count``, inserting the row if needed. The read
        and the write run in one savepoint.
        """

        date = time.strftime("%Y-%m-%d %H:%M")

        with write_savepoint(self._conn, "umsa_status_write") as cursor:
            cursor.execute(
                "SELECT time_played, play_count FROM sets WHERE id = ?",
                (set_id,),
            )
            set_fetch = cursor.fetchone()
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
            else:
                set_data = (set_id, date, played_seconds, 1)
                cursor.execute(
                    "INSERT INTO sets (id, last_played, time_played, play_count) "
                    "VALUES (?,?,?,?)",
                    (set_data),
                )

    def save_further_media(
        self, set_id, marp: str | None = None, youtube: str | None = None
    ) -> None:
        """Save MARP or Youtube entries for ``set_id``.

        Only truthy values are written; an existing value is never cleared.
        A missing row gets one INSERT holding both columns.
        """

        with write_savepoint(self._conn, "umsa_status_write") as cursor:
            cursor.execute("SELECT sets.id FROM sets WHERE id = ?", (set_id,))
            if cursor.fetchone():
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
                # A second INSERT would reuse the same primary key.
                cursor.execute(
                    "INSERT INTO sets (id, marp, youtube) VALUES(?,?,?)",
                    (set_id, marp or None, youtube or None),
                )
