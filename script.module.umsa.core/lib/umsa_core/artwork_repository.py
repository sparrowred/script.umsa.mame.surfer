"""Artwork database repository.

This module centralises all SQL access to artwork-related tables
(``art_set``, ``art_scan_unit``) and is the authoritative artwork schema
definition. The repository operates on an existing SQLite connection supplied
by the caller; it never opens or closes that connection.

Query methods do not manage transactions. The atomic operations
(``replace_scan_unit`` and the ``running``/``error``/``done`` scan-status
updates) manage their own short transactions and only commit a transaction
they started themselves, so they can never flush unrelated caller work.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Optional


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
    replacement and scan-status methods manage their own short transaction
    and only commit one they started, so the caller's connection and any
    unrelated pending work are left untouched.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialise the repository.

        Args:
            connection: An existing SQLite connection to operate on. The
                repository does not own this connection.
        """
        self._conn = connection

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the underlying connection (read-only access)."""
        return self._conn

    def get_artwork_for_set(self, set_id: int) -> list:
        """Return artwork records for a single set ID.

        Returns a list of dict-like rows (matching sqlite3.Row behaviour via
        the connection's row factory) as fetched from the database. The
        caller's connection row factory is respected.

        TODO think about if dict with key = type is better?
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT art_id,id,source,root_key,scan_unit,type,extension,"
                "relative_path,archive_member "
                "FROM art_set WHERE id = ?",
                (set_id,),
            )
            rows = cursor.fetchall()
            # Return list of dicts to match existing caller expectations
            result = []
            for r in rows:
                try:
                    result.append(dict(r))
                except Exception:
                    result.append(
                        {
                            "art_id": r[0] if len(r) > 0 else None,
                            "id": r[1] if len(r) > 1 else None,
                            "source": r[2] if len(r) > 2 else None,
                            "root_key": r[3] if len(r) > 3 else None,
                            "scan_unit": r[4] if len(r) > 4 else None,
                            "type": r[5] if len(r) > 5 else None,
                            "extension": r[6] if len(r) > 6 else None,
                            "relative_path": r[7] if len(r) > 7 else None,
                            "archive_member": r[8] if len(r) > 8 else None,
                        }
                    )
            return result
        finally:
            cursor.close()

    def get_artwork_record_for_set_type(
        self, set_id: int, art_type: str
    ) -> Optional[dict]:
        """Return one artwork record for a set and type, or ``None``.

        Used to fetch the additional artwork record (for example the
        screensaver's left-side image) without changing the surrounding
        selection workflow.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT source, root_key, scan_unit, type, extension, "
                "relative_path, archive_member "
                "FROM art_set WHERE art_set.id = ? AND type = ?",
                (set_id, art_type),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            try:
                return dict(row)
            except Exception:
                return {
                    "source": row[0] if len(row) > 0 else None,
                    "root_key": row[1] if len(row) > 1 else None,
                    "scan_unit": row[2] if len(row) > 2 else None,
                    "type": row[3] if len(row) > 3 else None,
                    "extension": row[4] if len(row) > 4 else None,
                    "relative_path": row[5] if len(row) > 5 else None,
                    "archive_member": row[6] if len(row) > 6 else None,
                }
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
                "SELECT art_id,id,source,root_key,scan_unit,type,extension,"
                "relative_path,archive_member "
                "FROM art_set WHERE id in ({})".format(placeholders),
                set_ids_list,
            )
            art_set = {}
            for i in cursor.fetchall():
                try:
                    row = dict(i)
                except Exception:
                    row = {
                        "art_id": i[0] if len(i) > 0 else None,
                        "id": i[1] if len(i) > 1 else None,
                        "source": i[2] if len(i) > 2 else None,
                        "root_key": i[3] if len(i) > 3 else None,
                        "scan_unit": i[4] if len(i) > 4 else None,
                        "type": i[5] if len(i) > 5 else None,
                        "extension": i[6] if len(i) > 6 else None,
                        "relative_path": i[7] if len(i) > 7 else None,
                        "archive_member": i[8] if len(i) > 8 else None,
                    }
                row["filename"] = row.get("relative_path")
                row_id = row.get("id")
                if row_id not in art_set:
                    art_set[row_id] = []
                art_set[row_id].append(row)
            return art_set
        finally:
            cursor.close()

    def get_art_types(self, excluded: Optional[Iterable[str]] = None) -> list:
        """Get distinct artwork types, excluding specified types."""
        if excluded is None:
            excluded = ("videosnaps", "manuals", "soundtrack", "ips")
        excluded_set = set(excluded)
        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT type FROM art_set ORDER BY type")
            art_types = []
            for i in cursor.fetchall():
                try:
                    t = i["type"]
                except Exception:
                    t = i[0] if i else None
                if t is None:
                    continue
                if t not in excluded_set:
                    art_types.append(t)
            return art_types
        finally:
            cursor.close()

    def get_scan_unit_status(
        self, source: str, root_key: str, scan_unit: str
    ) -> Optional[str]:
        """Get the current status for a scan unit, or None if not found."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT status FROM art_scan_unit "
                "WHERE source=? AND root_key=? AND scan_unit=?",
                (source, root_key, scan_unit),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            try:
                return row["status"]
            except Exception:
                return row[0] if row else None
        finally:
            cursor.close()

    def _write_status(
        self,
        source: str,
        root_key: str,
        scan_unit: str,
        status: str,
        last_error: Optional[str] = None,
        db_cursor: Optional[sqlite3.Cursor] = None,
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
        db_cursor: Optional[sqlite3.Cursor] = None,
    ) -> None:
        """Mark a scan unit as running."""
        self._write_status(source, root_key, scan_unit, "running", db_cursor=db_cursor)

    def set_scan_unit_error(
        self,
        source: str,
        root_key: str,
        scan_unit: str,
        last_error: Optional[str] = None,
        db_cursor: Optional[sqlite3.Cursor] = None,
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
        db_cursor: Optional[sqlite3.Cursor] = None,
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
                    "DELETE FROM art_set "
                    "WHERE source=? AND root_key=? AND scan_unit=?",
                    (source, root_key, scan_unit),
                )
                removed = cursor.rowcount
                cursor.execute(
                    "DELETE FROM art_scan_unit "
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
                "SELECT scan_unit FROM art_scan_unit "
                "WHERE source=? AND root_key=? "
                "UNION "
                "SELECT scan_unit FROM art_set WHERE source=? AND root_key=?",
                (source, root_key, source, root_key),
            )
            # Index the single selected column positionally so the method works
            # with both the default tuple rows and ``sqlite3.Row`` rows, without
            # depending on the caller's row factory.
            units = [row[0] for row in cursor.fetchall()]
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
                        "DELETE FROM art_set "
                        "WHERE source=? AND root_key=? AND scan_unit=?",
                        (source, root_key, unit),
                    )
                    removed += cursor.rowcount or 0
                    cursor.execute(
                        "DELETE FROM art_scan_unit "
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
                    "DELETE FROM art_set "
                    "WHERE source=? AND root_key=? AND scan_unit=?",
                    (source, root_key, scan_unit),
                )
                if rows:
                    cursor.executemany(
                        "INSERT INTO art_set "
                        "(id,source,root_key,scan_unit,type,extension,"
                        "relative_path,archive_member) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        rows,
                    )
                cursor.execute(
                    "INSERT OR REPLACE INTO art_scan_unit "
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
