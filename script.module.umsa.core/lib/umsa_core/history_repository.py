"""status.db repository for history, filter selections, and metadata."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any

from .sqlite import require_row_connection

FILTER_CATEGORY_INTERNAL = {
    "Softwarelists": "softwarelists",
    "Game Categories": "game_categories",
    "Machine Categories": "machine_categories",
    "Years": "years",
    "Players": "players",
}

FILTER_CATEGORY_PUBLIC = {
    "softwarelists": "Softwarelists",
    "game_categories": "Game Categories",
    "machine_categories": "Machine Categories",
    "years": "Years",
    "players": "Players",
}

FILTER_CATEGORY_ORDER = [
    "Softwarelists",
    "Game Categories",
    "Machine Categories",
    "Years",
    "Players",
]

FILTER_CATEGORY_INTERNAL_ORDER = [
    "softwarelists",
    "game_categories",
    "machine_categories",
    "years",
    "players",
]

# Reserved internal category holding the "this filter exists" marker row.
# It is deliberately absent from every mapping above: it is never selectable,
# never returned to a caller, and never written by anything but
# ``save_filter_selections``. Its single row is what lets a filter with five
# empty categories keep its name - ``list_filter_names`` reads names from
# ``filter_selections``, and an all-empty selection set would otherwise leave
# that table with no rows for the filter at all.
FILTER_DEFINITION_CATEGORY = "__filter_definition__"

# Retention bound for the screensaver display history (decision D16/D2): at
# most this many *distinct* sets are kept, pruned past the newest ones.
SCREENSAVER_HISTORY_LIMIT = 100

# ``sets.id`` is a positive SQLite rowid; only plain decimal integers count
# (same token rule as the legacy import, decision D13).
_SET_ID_RE = re.compile(r"^[0-9]+$")


def normalize_set_id(value: Any) -> int:
    """Return ``value`` as a positive ``sets.id`` integer.

    The screensaver video path carries the set id as string metadata
    (``umsa_set_id``), so every value entering the history is normalised here
    first: an ``int`` must already be positive, a ``str`` must be a
    whitespace-stripped non-empty decimal integer. Anything else (``None``,
    ``0``, negatives, ``"abc"``, ``"12.0"``, non-string/non-int types)
    raises ``ValueError`` and no history row is written.
    """

    if isinstance(value, bool):
        raise ValueError(f"invalid set id {value!r}")  # noqa: TRY004 - callers catch ValueError, not TypeError
    if isinstance(value, int):
        set_id = value
    elif isinstance(value, str):
        stripped = value.strip()
        if _SET_ID_RE.match(stripped) is None:
            raise ValueError(f"invalid set id {value!r}")
        set_id = int(stripped)
    else:
        raise ValueError(f"invalid set id {value!r}")  # noqa: TRY004 - callers catch ValueError, not TypeError
    if set_id <= 0:
        raise ValueError(f"invalid set id {value!r}")
    return set_id


def _write_within_savepoint(
    connection: sqlite3.Connection, operation
) -> None:
    had_transaction = connection.in_transaction
    cursor = connection.cursor()
    try:
        cursor.execute("SAVEPOINT umsa_history_write")
        try:
            operation(cursor)
        except Exception:
            cursor.execute("ROLLBACK TO umsa_history_write")
            cursor.execute("RELEASE umsa_history_write")
            raise
        else:
            cursor.execute("RELEASE umsa_history_write")
            if not had_transaction:
                connection.commit()
    finally:
        cursor.close()


def create_history_tables(cursor: sqlite3.Cursor) -> None:
    """Create the history and metadata tables for status.db."""

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS gui_lastgames (
            position    INTEGER PRIMARY KEY,
            software_id INTEGER NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS filter_selections (
            filter_name TEXT    NOT NULL,
            category    TEXT    NOT NULL,
            position    INTEGER NOT NULL,
            value       TEXT    NOT NULL,
            PRIMARY KEY (filter_name, category, position)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS screensaver_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id       INTEGER NOT NULL UNIQUE,
            software_id  INTEGER,
            displayed_at DATETIME
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS status_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


class HistoryRepository:
    """History and filter persistence operations on status.db."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        require_row_connection(connection, "HistoryRepository")
        self._conn = connection

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def load_lastgames(self) -> list[int]:
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT software_id FROM gui_lastgames ORDER BY position ASC"
            )
            return [int(row["software_id"]) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def save_lastgames(self, software_list: list[int]) -> None:
        ids = list(software_list)[-100:] if software_list else []
        ids_list = list(ids)

        def operation(cursor: sqlite3.Cursor) -> None:
            cursor.execute("DELETE FROM gui_lastgames")
            for pos, software_id in enumerate(ids_list):
                cursor.execute(
                    "INSERT INTO gui_lastgames (position, software_id) VALUES (?, ?)",
                    (pos, int(software_id)),
                )

        _write_within_savepoint(self._conn, operation)

    def list_filter_names(self) -> list[str]:
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT DISTINCT filter_name FROM filter_selections ORDER BY filter_name"
            )
            return [row["filter_name"] for row in cursor.fetchall()]
        finally:
            cursor.close()

    def load_filter_selections(self, filter_name: str) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {
            "Softwarelists": [],
            "Game Categories": [],
            "Machine Categories": [],
            "Years": [],
            "Players": [],
        }
        cursor = self._conn.cursor()
        try:
            for internal in FILTER_CATEGORY_INTERNAL_ORDER:
                public = FILTER_CATEGORY_PUBLIC[internal]
                cursor.execute(
                    "SELECT value FROM filter_selections "
                    "WHERE filter_name = ? AND category = ? "
                    "ORDER BY position ASC",
                    (filter_name, internal),
                )
                result[public] = [row["value"] for row in cursor.fetchall()]
        finally:
            cursor.close()
        return result

    def save_filter_selections(
        self, filter_name: str, filter_lists: dict[str, list[str]]
    ) -> None:
        def operation(cursor: sqlite3.Cursor) -> None:
            cursor.execute(
                "DELETE FROM filter_selections WHERE filter_name = ?",
                (filter_name,),
            )
            # Definition marker: keeps the name discoverable even when every
            # category is empty. Replaced atomically with the selections below.
            cursor.execute(
                "INSERT INTO filter_selections "
                "(filter_name, category, position, value) "
                "VALUES (?, ?, 0, '1')",
                (filter_name, FILTER_DEFINITION_CATEGORY),
            )
            for public_key in FILTER_CATEGORY_ORDER:
                internal_key = FILTER_CATEGORY_INTERNAL[public_key]
                values = filter_lists.get(public_key, [])
                for pos, value in enumerate(values):
                    cursor.execute(
                        "INSERT INTO filter_selections "
                        "(filter_name, category, position, value) "
                        "VALUES (?, ?, ?, ?)",
                        (filter_name, internal_key, pos, str(value)),
                    )

        _write_within_savepoint(self._conn, operation)

    def record_screensaver_display(
        self, set_id: Any, software_id: Any = None
    ) -> None:
        """Record one *successfully displayed* set (decision D16).

        ``set_id`` (the ``sets.id`` returned as ``art['id']``) is the identity
        of the row; ``software_id`` (``art['s_id']``, the context-menu handoff
        value) is stored alongside and refreshed on every display. Both are
        normalised first - ``set_id`` through :func:`normalize_set_id`
        (positive decimal id), ``software_id`` to ``int`` or ``None``.

        Semantics: **one row per distinct set, recency ordered by the
        monotonic ``id``**, never by ``displayed_at``. An existing row for the
        set is deleted and re-inserted so the set moves to the newest position
        with a fresh ``id`` (no duplicate, no growth on re-display); rows past
        the newest :data:`SCREENSAVER_HISTORY_LIMIT` distinct sets are then
        pruned. The delete + insert + prune run inside one savepoint, so a
        failure leaves the history exactly as it was (the caller's transaction,
        if any, is neither committed nor closed). ``displayed_at`` is written
        as advisory local time in ``YYYY-MM-DD HH:MM`` form.

        Raises:
            ValueError: ``set_id`` (or ``software_id``) is not a valid id.
            sqlite3.Error: the write failed; the savepoint is rolled back
                first, so no partial update survives.
        """

        normalized_set_id = normalize_set_id(set_id)
        normalized_software_id = (
            None if software_id is None else int(software_id)
        )
        # Local (advisory) wall-clock time, not UTC: the column is declared as a
        # timezone-naive DATETIME and displayed_at is never used for ordering.
        displayed_at = datetime.now().strftime("%Y-%m-%d %H:%M")  # noqa: DTZ005

        def operation(cursor: sqlite3.Cursor) -> None:
            # Move the set to the newest position: the old row keeps its
            # UNIQUE set_id, so it must go before the re-insert.
            cursor.execute(
                "DELETE FROM screensaver_history WHERE set_id = ?",
                (normalized_set_id,),
            )
            cursor.execute(
                "INSERT INTO screensaver_history "
                "(set_id, software_id, displayed_at) VALUES (?, ?, ?)",
                (normalized_set_id, normalized_software_id, displayed_at),
            )
            # Retention: drop everything beyond the newest 100 ids.
            cursor.execute(
                "DELETE FROM screensaver_history "
                "WHERE id NOT IN (SELECT id FROM screensaver_history "
                "ORDER BY id DESC LIMIT ?)",
                (SCREENSAVER_HISTORY_LIMIT,),
            )

        _write_within_savepoint(self._conn, operation)

    def list_screensaver_history(
        self, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return the screensaver display history, **newest first**.

        One dict per distinct set (``set_id``, ``software_id``,
        ``displayed_at``) ordered by the monotonic ``id`` descending -
        i.e. most recently displayed first - limited to ``limit`` rows
        (:data:`SCREENSAVER_HISTORY_LIMIT` by default).

        Rows are returned exactly as stored: a ``set_id`` that no longer
        exists in ``umsa.db`` (the two databases are updated independently)
        is kept and reported as-is, never substituted with another set's id
        and never dropped by this reader (decision D16).
        """

        effective_limit = (
            SCREENSAVER_HISTORY_LIMIT if limit is None else int(limit)
        )
        if effective_limit <= 0:
            return []
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT set_id, software_id, displayed_at "
                "FROM screensaver_history ORDER BY id DESC LIMIT ?",
                (effective_limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def get_import_marker(self) -> dict[str, Any] | None:
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT value FROM status_meta WHERE key = 'legacy_import'"
            )
            row = cursor.fetchone()
            if not row:
                return None
            try:
                return json.loads(row["value"])
            except (ValueError, TypeError):
                return None
        finally:
            cursor.close()

    def record_import_marker(self, marker: dict[str, Any]) -> None:
        value = json.dumps(marker, ensure_ascii=False)

        def operation(cursor: sqlite3.Cursor) -> None:
            cursor.execute(
                "INSERT OR REPLACE INTO status_meta (key, value) VALUES (?, ?)",
                ("legacy_import", value),
            )

        _write_within_savepoint(self._conn, operation)

    def clear_import_marker(self) -> None:
        def operation(cursor: sqlite3.Cursor) -> None:
            cursor.execute(
                "DELETE FROM status_meta WHERE key = 'legacy_import'"
            )

        _write_within_savepoint(self._conn, operation)
