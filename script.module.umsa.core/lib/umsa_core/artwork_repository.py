"""Repository for the artwork tables of artwork.db (``art_set``, ``art_scan_unit``).

Owns the schema. Writes use :func:`umsa_core.sqlite.write_savepoint`; the
``running``/``error`` scan-unit markers commit at once so an interrupted scan
can be found on resume.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from .sqlite import require_row_connection, write_savepoint


def create_artwork_tables(db_cursor: sqlite3.Cursor) -> None:
    """Create artwork tables and indexes if they do not exist.

    ``art_scan_unit.dir_mtime`` (mtime of the unit directory at its last
    successful scan) is added to older databases by ``ALTER TABLE``.
    """

    db_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS art_set(
            art_id          INTEGER PRIMARY KEY,
            id              INTEGER NOT NULL,
            source          TEXT NOT NULL,
            root_key        TEXT NOT NULL,
            scan_unit       TEXT NOT NULL,
            type            TEXT NOT NULL,
            extension       TEXT NOT NULL,
            relative_path   TEXT,
            archive_member  TEXT
        )
        """
    )
    db_cursor.execute("CREATE INDEX IF NOT EXISTS idx_art_set_id ON art_set(id)")
    db_cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_art_set_source ON art_set(source)"
    )
    db_cursor.execute("CREATE INDEX IF NOT EXISTS idx_art_set_type ON art_set(type)")
    db_cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_art_set_scan_unit ON art_set(scan_unit)"
    )
    db_cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_art_set_source_root_scan "
        "ON art_set(source, root_key, scan_unit)"
    )

    db_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS art_scan_unit(
            source       TEXT NOT NULL,
            root_key     TEXT NOT NULL,
            scan_unit    TEXT NOT NULL,
            status       TEXT NOT NULL,
            last_error   TEXT,
            updated_at   TEXT,
            dir_mtime    REAL,
            PRIMARY KEY (source, root_key, scan_unit)
        )
        """
    )
    db_cursor.execute("PRAGMA table_info(art_scan_unit)")
    if "dir_mtime" not in {row[1] for row in db_cursor.fetchall()}:
        db_cursor.execute("ALTER TABLE art_scan_unit ADD COLUMN dir_mtime REAL")


class ArtworkRepository:
    """Artwork operations on a caller-owned connection.

    Never opens or closes the connection. Query methods leave transactions to
    the caller. ``schema`` qualifies the table names: ``"main"`` for a
    scanner's own artwork.db connection, ``"art"`` for the attached schema of
    ``DBMod``.
    """

    _ALLOWED_SCHEMAS = frozenset({"main", "art"})

    def __init__(self, connection: sqlite3.Connection, schema: str = "main") -> None:
        """Wrap a connection for the schema ``"main"`` or ``"art"``.

        Raises:
            ValueError: If the connection does not use ``sqlite3.Row``
                (:func:`umsa_core.sqlite.require_row_connection`) or
                ``schema`` is not allowed.
        """
        require_row_connection(connection, "ArtworkRepository")
        if schema not in self._ALLOWED_SCHEMAS:
            raise ValueError(
                f"ArtworkRepository schema must be one of {sorted(self._ALLOWED_SCHEMAS)}, got {schema!r}"
            )
        self._conn = connection
        self._schema = schema

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the wrapped connection."""
        return self._conn

    @property
    def schema(self) -> str:
        """Return the schema qualifier in use (``"main"`` or ``"art"``)."""
        return self._schema

    def _qt(self, table: str) -> str:
        """Return a schema-qualified table name."""
        return f"{self._schema}.{table}"

    def get_artwork_for_set(self, set_id: int) -> list:
        """Return the artwork records of one set as a list of dicts.

        TODO think about if dict with key = type is better?
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                f"SELECT art_id,id,source,root_key,scan_unit,type,extension,"
                f"relative_path,archive_member "
                f"FROM {self._qt('art_set')} WHERE id = ?",
                (set_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def get_artwork_record_for_set_type(
        self, set_id: int, art_type: str
    ) -> dict | None:
        """Return one artwork record for a set and type, or ``None``."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                f"SELECT source, root_key, scan_unit, type, extension, "
                f"relative_path, archive_member "
                f"FROM {self._qt('art_set')} WHERE {self._qt('art_set')}.id = ? AND type = ?",
                (set_id, art_type),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)
        finally:
            cursor.close()

    def get_artwork_for_sets(self, set_ids: Iterable[int]) -> dict:
        """Return ``{set id: [record, …]}``; each record also carries ``filename``."""
        set_ids_list = list(set_ids)
        if not set_ids_list:
            return {}
        placeholders = ",".join("?" for _ in set_ids_list)
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                f"SELECT art_id,id,source,root_key,scan_unit,type,extension,"
                f"relative_path,archive_member "
                f"FROM {self._qt('art_set')} WHERE id in ({placeholders})",
                set_ids_list,
            )
            art_set = {}
            for i in cursor.fetchall():
                row = dict(i)
                row["filename"] = row.get("relative_path")
                row_id = row.get("id")
                if row_id not in art_set:
                    art_set[row_id] = []
                art_set[row_id].append(row)
            return art_set
        finally:
            cursor.close()

    def get_art_types(self, excluded: Iterable[str] | None = None) -> list:
        """Return the distinct artwork types without ``excluded`` (default: media)."""
        if excluded is None:
            excluded = ("videosnaps", "manuals", "soundtrack", "ips")
        excluded_set = set(excluded)
        cursor = self._conn.cursor()
        try:
            cursor.execute(f"SELECT DISTINCT type FROM {self._qt('art_set')} ORDER BY type")
            art_types = []
            for i in cursor.fetchall():
                t = i["type"]
                if t is None:
                    continue
                if t not in excluded_set:
                    art_types.append(t)
            return art_types
        finally:
            cursor.close()

    def get_scan_unit_state(
        self, source: str, root_key: str, scan_unit: str
    ) -> tuple[str | None, float | None]:
        """Return ``(status, dir_mtime)`` of a scan unit, ``(None, None)`` if unknown."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                f"SELECT status, dir_mtime FROM {self._qt('art_scan_unit')} "
                f"WHERE source=? AND root_key=? AND scan_unit=?",
                (source, root_key, scan_unit),
            )
            row = cursor.fetchone()
            if row is None:
                return None, None
            return row["status"], row["dir_mtime"]
        finally:
            cursor.close()

    def _write_status(
        self,
        source: str,
        root_key: str,
        scan_unit: str,
        status: str,
        last_error: str | None = None,
        db_cursor: sqlite3.Cursor | None = None,
    ) -> None:
        """Write one scan-unit status and commit it at once.

        The ``running``/``error`` markers live outside the atomic artwork
        replacement so an interrupted scan can be found on resume. The commit
        is issued only when this call opened the transaction; inside a caller
        transaction the caller commits.
        """
        if status == "error":
            statement = (
                f"INSERT OR REPLACE INTO {self._qt('art_scan_unit')} "
                "(source,root_key,scan_unit,status,last_error,updated_at) "
                "VALUES (?,?,?,?,?,datetime('now'))"
            )
            args = (source, root_key, scan_unit, status, last_error)
        else:
            statement = (
                f"INSERT OR REPLACE INTO {self._qt('art_scan_unit')} "
                "(source,root_key,scan_unit,status,updated_at) "
                "VALUES (?,?,?,?,datetime('now'))"
            )
            args = (source, root_key, scan_unit, status)

        conn = db_cursor.connection if db_cursor is not None else self._conn
        had_transaction = conn.in_transaction
        if db_cursor is not None:
            db_cursor.execute(statement, args)
        else:
            cursor = self._conn.cursor()
            try:
                cursor.execute(statement, args)
            finally:
                cursor.close()
        if not had_transaction:
            conn.commit()

    def set_scan_unit_running(
        self,
        source: str,
        root_key: str,
        scan_unit: str,
        db_cursor: sqlite3.Cursor | None = None,
    ) -> None:
        """Mark a scan unit as running."""
        self._write_status(source, root_key, scan_unit, "running", db_cursor=db_cursor)

    def set_scan_unit_error(
        self,
        source: str,
        root_key: str,
        scan_unit: str,
        last_error: str | None = None,
        db_cursor: sqlite3.Cursor | None = None,
    ) -> None:
        """Mark a scan unit as error, storing the last error message."""
        self._write_status(
            source,
            root_key,
            scan_unit,
            "error",
            last_error=last_error,
            db_cursor=db_cursor,
        )

    def delete_scan_unit(self, source: str, root_key: str, scan_unit: str) -> int:
        """Delete the records and the status of one scan unit; return the rows removed.

        For retiring an old scan unit once its replacement has been written.
        """

        with write_savepoint(self._conn, "umsa_art_delete_unit") as cursor:
            cursor.execute(
                f"DELETE FROM {self._qt('art_set')} "
                "WHERE source=? AND root_key=? AND scan_unit=?",
                (source, root_key, scan_unit),
            )
            removed = cursor.rowcount
            cursor.execute(
                f"DELETE FROM {self._qt('art_scan_unit')} "
                "WHERE source=? AND root_key=? AND scan_unit=?",
                (source, root_key, scan_unit),
            )
        return removed if removed is not None else 0

    def list_scan_units(self, source: str, root_key: str) -> list:
        """Return the sorted scan units of ``(source, root_key)``.

        The union of ``art_scan_unit`` and ``art_set``, so units without a
        status row and registered units without artwork are both included.
        """

        cursor = self._conn.cursor()
        try:
            cursor.execute(
                f"SELECT scan_unit FROM {self._qt('art_scan_unit')} "
                f"WHERE source=? AND root_key=? "
                f"UNION "
                f"SELECT scan_unit FROM {self._qt('art_set')} WHERE source=? AND root_key=?",
                (source, root_key, source, root_key),
            )
            units = [row["scan_unit"] for row in cursor.fetchall()]
            return sorted(u for u in units if u is not None)
        finally:
            cursor.close()

    def delete_other_roots(
        self, source: str, keep_root_keys: Iterable[str]
    ) -> int:
        """Delete the records of every root of ``source`` not in ``keep_root_keys``.

        A moved artwork folder gets a new ``root_key``; the rows of the old
        root can no longer be resolved and are removed here (``art_set`` and
        ``art_scan_unit``) in one savepoint. An empty ``keep_root_keys``
        deletes nothing, so a source is never emptied completely. Returns the
        number of removed artwork rows.
        """

        keep = sorted({key for key in keep_root_keys if key})
        if not keep:
            return 0

        placeholders = ",".join("?" * len(keep))
        args = (source, *keep)
        with write_savepoint(self._conn, "umsa_art_delete_roots") as cursor:
            cursor.execute(
                f"DELETE FROM {self._qt('art_set')} "
                f"WHERE source=? AND root_key NOT IN ({placeholders})",
                args,
            )
            removed = cursor.rowcount or 0
            cursor.execute(
                f"DELETE FROM {self._qt('art_scan_unit')} "
                f"WHERE source=? AND root_key NOT IN ({placeholders})",
                args,
            )
        return removed

    def delete_scan_units(
        self, source: str, root_key: str, scan_units: Iterable[str]
    ) -> int:
        """Delete several scan units of one source/root in one savepoint.

        All-or-nothing. Returns the number of removed artwork rows.
        """

        units = [unit for unit in scan_units if unit is not None]
        if not units:
            return 0

        removed = 0
        with write_savepoint(self._conn, "umsa_art_delete_units") as cursor:
            for unit in units:
                cursor.execute(
                    f"DELETE FROM {self._qt('art_set')} "
                    "WHERE source=? AND root_key=? AND scan_unit=?",
                    (source, root_key, unit),
                )
                removed += cursor.rowcount or 0
                cursor.execute(
                    f"DELETE FROM {self._qt('art_scan_unit')} "
                    "WHERE source=? AND root_key=? AND scan_unit=?",
                    (source, root_key, unit),
                )
        return removed

    def replace_scan_unit(
        self,
        source: str,
        root_key: str,
        scan_unit: str,
        artwork_rows: Iterable[tuple],
        dir_mtime: float | None = None,
    ) -> None:
        """Replace the artwork rows of a scan unit and mark it done, in one savepoint.

        ``dir_mtime`` is the mtime of the unit directory taken before it was
        listed; the scanner skips the unit later only while it still matches.
        On error the previous rows and unit state are kept.
        """
        # Materialise the replacement before the savepoint: nothing is written
        # yet, so a failure while consuming ``artwork_rows`` leaves the
        # database untouched.
        rows = list(artwork_rows)
        with write_savepoint(self._conn, "umsa_art_replace_unit") as cursor:
            cursor.execute(
                f"DELETE FROM {self._qt('art_set')} "
                "WHERE source=? AND root_key=? AND scan_unit=?",
                (source, root_key, scan_unit),
            )
            if rows:
                cursor.executemany(
                    f"INSERT INTO {self._qt('art_set')} "
                    "(id,source,root_key,scan_unit,type,extension,"
                    "relative_path,archive_member) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    rows,
                )
            cursor.execute(
                f"INSERT OR REPLACE INTO {self._qt('art_scan_unit')} "
                "(source,root_key,scan_unit,status,updated_at,dir_mtime) "
                "VALUES (?,?,?,?,datetime('now'),?)",
                (source, root_key, scan_unit, "done", dir_mtime),
            )
