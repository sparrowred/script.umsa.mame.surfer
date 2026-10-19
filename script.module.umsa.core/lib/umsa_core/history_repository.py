"""status.db repository for history, filter selections, and metadata."""

from __future__ import annotations

import json
import sqlite3
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
