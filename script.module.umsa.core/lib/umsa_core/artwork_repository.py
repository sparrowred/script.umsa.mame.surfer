"""Artwork database repository.

This module centralises all SQL access to artwork-related tables
(``art_set``, ``art_scan_unit``) and is the authoritative artwork schema
definition. The repository operates on an existing SQLite connection supplied
by the caller; it never opens or closes that connection.

Query methods do not manage transactions. The atomic operations
(``replace_scan_unit`` and the ``running``/``error``/``done`` scan-status
updates) manage their own short transactions and only commit a transaction
they started themselves, so they can never flush unrelated caller work.

Connections must use ``sqlite3.Row`` (step 4.2b contract, decision Q7), which
is what the read helpers convert rows with and what callers consume; a
connection with any other row factory is rejected at construction.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from .sqlite import require_row_connection


def create_artwork_tables(db_cursor: sqlite3.Cursor) -> None:
    """Create artwork tables and indexes if they do not exist.

    This is the authoritative schema definition for artwork tables. The
    schema is preserved exactly as-is and must not be modified in this phase.
    """

    # Ensure tables exist (new schema only)
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

    # Create art_scan_unit table
    db_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS art_scan_unit(
            source       TEXT NOT NULL,
            root_key     TEXT NOT NULL,
            scan_unit    TEXT NOT NULL,
            status       TEXT NOT NULL,
            last_error   TEXT,
            updated_at   TEXT,
            PRIMARY KEY (source, root_key, scan_unit)
        )
        """
    )


class ArtworkRepository:
    """Artwork database operations on an externally owned connection.

    The repository never opens or closes the supplied connection. Query
    methods leave transaction management to the caller; the atomic
    operations (``replace_scan_unit`` and the ``running``/``error``/``done``
    scan-status updates) manage their own short transactions and only
    commit a transaction they started themselves, so they can never flush
    unrelated caller work.

    Connections must use ``sqlite3.Row`` (step 4.2b contract, decision Q7),
    which is what the read helpers convert rows with and what callers
    consume; a connection with any other row factory is rejected at
    construction.

    The repository accepts an optional ``schema`` parameter to qualify table
    names. For scanner-owned connections where artwork.db is the ``main``
    database, use ``schema="main"`` (the default). For the DBMod connection
    where artwork.db is attached as ``art``, use ``schema="art"``. The
    schema identifier must be from the allowlist ``{"main", "art"}``.
    """

    _ALLOWED_SCHEMAS = frozenset({"main", "art"})

    def __init__(self, connection: sqlite3.Connection, schema: str = "main") -> None:
        """Initialise the repository.

        Args:
            connection: An existing SQLite connection to operate on. The
                repository does not own this connection.
            schema: The database schema qualifier (``"main"`` or ``"art"``).
                Defaults to ``"main"`` for scanner-owned connections.

        Raises:
            ValueError: If the connection does not use ``sqlite3.Row`` or if
                ``schema`` is not in the allowlist.
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
        """Return the underlying connection (read-only access)."""
        return self._conn

    @property
    def schema(self) -> str:
        """Return the schema qualifier in use (``"main"`` or ``"art"``)."""
        return self._schema

    def _qt(self, table: str) -> str:
        """Return a schema-qualified table name."""
        return f"{self._schema}.{table}"

    def get_artwork_for_set(self, set_id: int) -> list:
        """Return artwork records for a single set ID.

        Returns a list of dicts built from the ``sqlite3.Row`` rows, matching
        the historical caller expectation (dict-like rows with named access).

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
        """Return one artwork record for a set and type, or ``None``.

        Used to fetch the additional artwork record (for example the
        screensaver's left-side image) without changing the surrounding
        selection workflow.
        """
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
        """Return artwork records grouped by set ID."""
        set_ids_list = list(set_ids)
        if not set_ids_list:
            return {}
        # Build parameter placeholders
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
        """Get distinct artwork types, excluding specified types."""
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

    def get_scan_unit_status(
        self, source: str, root_key: str, scan_unit: str
    ) -> str | None:
        """Get the current status for a scan unit, or None if not found."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                f"SELECT status FROM {self._qt('art_scan_unit')} "
                f"WHERE source=? AND root_key=? AND scan_unit=?",
                (source, root_key, scan_unit),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return row["status"]
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
        """Persist one scan-unit status in a short, explicit transaction.

        The ``running``/``error`` markers intentionally live outside the
        atomic artwork replacement so an interrupted scan can be identified on
        resume, so they are committed immediately. The commit is only issued
        when this call opened the transaction; if the caller already had one
        open, committing would flush unrelated work, so the write is left for
        the caller to commit.
        """
        if status == "error":
            statement = (
                "INSERT OR REPLACE INTO art_scan_unit "
                "(source,root_key,scan_unit,status,last_error,updated_at) "
                "VALUES (?,?,?,?,?,datetime('now'))"
            )
            args = (source, root_key, scan_unit, status, last_error)
        else:
            statement = (
                "INSERT OR REPLACE INTO art_scan_unit "
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

    def set_scan_unit_done(
        self,
        source: str,
        root_key: str,
        scan_unit: str,
        db_cursor: sqlite3.Cursor | None = None,
    ) -> None:
        """Mark a scan unit as done."""
        self._write_status(source, root_key, scan_unit, "done", db_cursor=db_cursor)

    def delete_scan_unit(self, source: str, root_key: str, scan_unit: str) -> int:
        """Delete every record of one scan unit and forget its status.

        Intended for retiring a legacy scan unit once its replacement has been
        written successfully. It is scoped strictly to the given
        ``(source, root_key, scan_unit)``; other units and sources are never
        touched. It manages its own short transaction, only commits one it
        started, and never closes the caller's connection. Returns the number of
        removed artwork rows.
        """

        conn = self._conn
        had_transaction = conn.in_transaction
        cursor = conn.cursor()
        try:
            cursor.execute("SAVEPOINT umsa_art_delete_unit")
            try:
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
            except Exception:
                cursor.execute("ROLLBACK TO umsa_art_delete_unit")
                cursor.execute("RELEASE umsa_art_delete_unit")
                raise
            else:
                cursor.execute("RELEASE umsa_art_delete_unit")
                if not had_transaction:
                    conn.commit()
            return removed if removed is not None else 0
        finally:
            cursor.close()

    def list_scan_units(self, source: str, root_key: str) -> list:
        """List every persisted scan unit for an exact ``(source, root_key)``.

        The result is the union of the registered units in ``art_scan_unit`` and
        the distinct scan units present in ``art_set``. Legacy artwork rows that
        never received a status record, and registered empty units that never
        received artwork rows, are therefore both included. Order is stable
        (sorted) but should not be relied upon for correctness.
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

    def delete_scan_units(
        self, source: str, root_key: str, scan_units: Iterable[str]
    ) -> int:
        """Delete several scan units of one source/root in a single transaction.

        Every listed unit has its ``art_set`` rows and its ``art_scan_unit``
        status removed inside one savepoint, so the cleanup is all-or-nothing.
        It is scoped strictly to the given ``(source, root_key)`` and to the
        listed units; other units, sources and roots are never touched. It
        manages its own short transaction, only commits one it started, and
        never closes the caller's connection. Returns the number of removed
        artwork rows.
        """

        units = [unit for unit in scan_units if unit is not None]
        if not units:
            return 0

        conn = self._conn
        had_transaction = conn.in_transaction
        cursor = conn.cursor()
        removed = 0
        try:
            cursor.execute("SAVEPOINT umsa_art_delete_units")
            try:
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
            except Exception:
                cursor.execute("ROLLBACK TO umsa_art_delete_units")
                cursor.execute("RELEASE umsa_art_delete_units")
                raise
            else:
                cursor.execute("RELEASE umsa_art_delete_units")
                if not had_transaction:
                    conn.commit()
            return removed
        finally:
            cursor.close()

    def replace_scan_unit(
        self, source: str, root_key: str, scan_unit: str, artwork_rows: Iterable[tuple]
    ) -> None:
        """Replace artwork records for a scan unit and mark it done atomically.

        All changes are one logical unit of work executed inside a SQLite
        savepoint:

        1. Deletes only records for the specified (source, root_key, scan_unit).
        2. Inserts all artwork rows.
        3. Marks the unit as done (clearing any previous error).

        The savepoint makes the replacement atomic without hijacking the
        caller's transaction. When no transaction is active, releasing the
        savepoint commits the operation durably. When the caller already owns a
        transaction, the savepoint nests inside it: releasing commits only the
        replacement, and the caller's transaction and unrelated pending work are
        left untouched for the caller to commit or roll back.

        On any error the savepoint is rolled back, so the previous artwork rows
        and scan-unit state are preserved and the caller's transaction stays
        active and usable. The caller's connection is never closed.
        """
        conn = self._conn
        had_transaction = conn.in_transaction
        cursor = conn.cursor()
        try:
            # Materialise the replacement inside the try so the cursor is closed
            # even when consuming ``artwork_rows`` raises. Nothing is written
            # before the savepoint, so a failure here leaves the database
            # untouched.
            rows = list(artwork_rows)
            cursor.execute("SAVEPOINT umsa_art_replace_unit")
            try:
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
                    "(source,root_key,scan_unit,status,updated_at) "
                    "VALUES (?,?,?,?,datetime('now'))",
                    (source, root_key, scan_unit, "done"),
                )
            except Exception:
                cursor.execute("ROLLBACK TO umsa_art_replace_unit")
                cursor.execute("RELEASE umsa_art_replace_unit")
                raise
            else:
                cursor.execute("RELEASE umsa_art_replace_unit")
                if not had_transaction:
                    conn.commit()
        finally:
            cursor.close()
