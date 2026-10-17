"""DAT database repository.

This module centralises SQL access to the DAT tables (``dat``, ``dat_set``)
and is the authoritative DAT schema definition, following the conventions of
:mod:`umsa_core.artwork_repository`.

The repository operates on an existing SQLite connection supplied by the
caller; it never opens or closes that connection. Query methods leave
transaction management to the caller. The staging and publication methods
manage their own short transaction and only commit a transaction they started
themselves, so they can never flush unrelated caller work.

``dat.file`` keeps its historical meaning: the visible display category. The
nullable ``origin`` column is internal bookkeeping that records which import
produced a row (see :data:`ORIGIN_MAME_SUPPORT`, :data:`ORIGIN_EXODOS` and
:data:`ORIGIN_GB64`).
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Optional

from .scan_coordinator import scan_coordinator

ORIGIN_MAME_SUPPORT = "mame_support"
ORIGIN_EXODOS = "exodos"
ORIGIN_GB64 = "gb64"

def _guard_staging_coordinated():
    """Refuse uncoordinated staging use while another scan holds the lock.

    The scan orchestration layer owns the global scan lock; repository staging
    operations are internal helpers expected to run inside that locked scope.
    Using them while a *different* thread owns the lock would corrupt an active
    scan's staging tables, so it is rejected early with a clear error.
    """

    if scan_coordinator.is_locked() and not scan_coordinator.owned_by_current_thread():
        raise RuntimeError(
            "DAT staging used without the shared scan lock while another scan "
            "is running"
        )


def create_dat_tables(db_cursor: sqlite3.Cursor) -> None:
    """Create the DAT tables and upgrade old databases in place.

    This is the authoritative schema definition. It is idempotent: existing
    tables are never dropped and their contents are never discarded. When the
    ``origin`` column is missing it is added, and legacy rows are assigned an
    origin inferred from their ``file`` value.
    """

    db_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dat(
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            file    VARCHAR(50),
            entry   TEXT,
            origin  TEXT
        )
        """
    )
    db_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dat_set(
            id      INTEGER,
            dat_id  INTEGER
        )
        """
    )
    _ensure_origin_column(db_cursor)
    _backfill_origin(db_cursor)


def _ensure_origin_column(db_cursor: sqlite3.Cursor) -> None:
    """Add the ``origin`` column to an old ``dat`` table when absent."""

    db_cursor.execute("PRAGMA table_info(dat)")
    columns = {row[1] for row in db_cursor.fetchall()}
    if "origin" not in columns:
        db_cursor.execute("ALTER TABLE dat ADD COLUMN origin TEXT")


def _backfill_origin(db_cursor: sqlite3.Cursor) -> None:
    """Assign an origin to legacy rows that do not have one yet.

    Only rows whose ``origin`` is still missing are touched, so an origin that
    was already assigned is never overwritten.
    """

    db_cursor.execute(
        "UPDATE dat SET origin = ? "
        "WHERE origin IS NULL AND file = 'eXoDOS'",
        (ORIGIN_EXODOS,),
    )
    db_cursor.execute(
        "UPDATE dat SET origin = ? "
        "WHERE origin IS NULL AND file = 'GameBase64'",
        (ORIGIN_GB64,),
    )
    db_cursor.execute(
        "UPDATE dat SET origin = ? WHERE origin IS NULL",
        (ORIGIN_MAME_SUPPORT,),
    )


class DatRepository:
    """DAT database operations on an externally owned connection.

    The repository never opens or closes the supplied connection. Query
    methods leave transaction management to the caller; :meth:`publish_staged`
    manages its own short transaction and only commits one it started.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the underlying connection (read-only access)."""
        return self._conn

    def create_tables(self, db_cursor: Optional[sqlite3.Cursor] = None) -> None:
        """Create/upgrade the DAT tables, optionally using a supplied cursor."""

        if db_cursor is not None:
            create_dat_tables(db_cursor)
            return
        cursor = self._conn.cursor()
        try:
            create_dat_tables(cursor)
        finally:
            cursor.close()

    def get_dat_for_set(self, set_id: int) -> dict:
        """Return a ``{display category: entry text}`` mapping for one set."""

        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT dat.file, dat.entry FROM dat "
                "JOIN dat_set ON dat.id = dat_set.dat_id "
                "WHERE dat_set.id = ?",
                (set_id,),
            )
            set_dats = {}
            for row in cursor.fetchall():
                set_dats[row[0]] = row[1]
            return set_dats
        finally:
            cursor.close()

    def get_dat_for_sets(self, set_ids: Iterable[int]) -> dict:
        """Return ``{set id: {display category: entry text}}`` for many sets.

        Parameterised and safe for an empty list (which returns an empty
        mapping rather than invalid SQL).
        """

        ids = list(set_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT dat_set.id, dat.file, dat.entry FROM dat "
                "JOIN dat_set ON dat.id = dat_set.dat_id "
                f"WHERE dat_set.id in ({placeholders})",
                ids,
            )
            set_file = {}
            for row in cursor.fetchall():
                set_id = row[0]
                if set_id not in set_file:
                    set_file[set_id] = {}
                set_file[set_id][row[1]] = row[2]
            return set_file
        finally:
            cursor.close()

    # -- staging ---------------------------------------------------------

    def create_staging_tables(
        self, db_cursor: Optional[sqlite3.Cursor] = None
    ) -> None:
        """Create the staging tables used by a DAT scan, if not present."""

        _guard_staging_coordinated()
        close = False
        if db_cursor is None:
            db_cursor = self._conn.cursor()
            close = True
        try:
            db_cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS dat_staging(
                    stage_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                    file      VARCHAR(50),
                    entry     TEXT
                )
                """
            )
            db_cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS dat_staging_set(
                    stage_id  INTEGER,
                    id        INTEGER
                )
                """
            )
        finally:
            if close:
                db_cursor.close()

    def clear_staging(self, db_cursor: Optional[sqlite3.Cursor] = None) -> None:
        """Discard every staged DAT entry without touching published data."""

        _guard_staging_coordinated()
        close = False
        if db_cursor is None:
            db_cursor = self._conn.cursor()
            close = True
        try:
            db_cursor.execute("DELETE FROM dat_staging")
            db_cursor.execute("DELETE FROM dat_staging_set")
        finally:
            if close:
                db_cursor.close()

    def stage_entry(
        self,
        file: str,
        entry: Optional[str],
        set_ids: Iterable[int],
        db_cursor: Optional[sqlite3.Cursor] = None,
    ) -> int:
        """Stage one parsed entry and its set relationships.

        Returns the staging id. The caller owns the transaction; staging is
        written to separate tables so it can never collide with the ids of
        already published ``dat`` rows.
        """

        close = False
        if db_cursor is None:
            db_cursor = self._conn.cursor()
            close = True
        try:
            db_cursor.execute(
                "INSERT INTO dat_staging(file, entry) VALUES (?, ?)",
                (file, entry),
            )
            stage_id = db_cursor.lastrowid
            if stage_id is None:
                raise RuntimeError("staging insert did not return a row id")
            for set_id in set_ids:
                db_cursor.execute(
                    "INSERT INTO dat_staging_set(stage_id, id) VALUES (?, ?)",
                    (stage_id, set_id),
                )
            return stage_id
        finally:
            if close:
                db_cursor.close()

    def replace_origin_for_set(
        self, origin: str, set_id: int, file: str, entry: Optional[str]
    ) -> int:
        """Replace the ``origin`` metadata attached to one set.

        Used by per-set importers (for example GameBase64) that own exactly one
        metadata row per set and must stay idempotent across repeated scans.
        In a single short transaction it removes only the ``origin`` rows
        currently linked to ``set_id`` and then inserts a fresh ``file``/
        ``entry`` row linked to ``set_id``.

        Rows of other origins are never touched, and a removed row is deleted
        only when no remaining ``dat_set`` relationship still needs it, so a row
        shared with another set survives. On any error the transaction is rolled
        back and the previous valid rows are kept. The caller's connection is
        never closed. Returns the id of the inserted row.
        """

        conn = self._conn
        had_transaction = conn.in_transaction
        cursor = conn.cursor()
        try:
            cursor.execute("SAVEPOINT umsa_dat_replace_set")
            try:
                cursor.execute(
                    "SELECT dat.id FROM dat_set JOIN dat ON dat.id = dat_set.dat_id "
                    "WHERE dat.origin = ? AND dat_set.id = ?",
                    (origin, set_id),
                )
                old_ids = [row[0] for row in cursor.fetchall()]
                for dat_id in old_ids:
                    cursor.execute(
                        "DELETE FROM dat_set WHERE dat_id = ? AND id = ?",
                        (dat_id, set_id),
                    )
                    cursor.execute(
                        "DELETE FROM dat WHERE id = ? AND NOT EXISTS "
                        "(SELECT 1 FROM dat_set WHERE dat_id = ?)",
                        (dat_id, dat_id),
                    )
                cursor.execute(
                    "INSERT INTO dat(file, entry, origin) VALUES (?, ?, ?)",
                    (file, entry, origin),
                )
                new_id = cursor.lastrowid
                if new_id is None:
                    raise RuntimeError("dat insert did not return a row id")
                cursor.execute(
                    "INSERT INTO dat_set(id, dat_id) VALUES (?, ?)",
                    (set_id, new_id),
                )
            except Exception:
                cursor.execute("ROLLBACK TO umsa_dat_replace_set")
                cursor.execute("RELEASE umsa_dat_replace_set")
                raise
            else:
                cursor.execute("RELEASE umsa_dat_replace_set")
                if not had_transaction:
                    conn.commit()
            return new_id
        finally:
            cursor.close()

    def publish_staged(self, origin: str) -> int:
        """Atomically replace one origin's published rows with the staged data.

        In a single short transaction it deletes the ``dat_set`` relationships
        belonging to records of ``origin``, deletes those ``dat`` records,
        inserts the staged entries (assigning fresh ids) and their
        relationships, and clears the staging tables. On any error the
        transaction is rolled back and the previous valid rows are kept.

        Returns the number of published entries.
        """

        _guard_staging_coordinated()
        conn = self._conn
        had_transaction = conn.in_transaction
        cursor = conn.cursor()
        reader = conn.cursor()
        published = 0
        try:
            cursor.execute("SAVEPOINT umsa_dat_publish")
            try:
                cursor.execute(
                    "DELETE FROM dat_set WHERE dat_id IN "
                    "(SELECT id FROM dat WHERE origin = ?)",
                    (origin,),
                )
                cursor.execute("DELETE FROM dat WHERE origin = ?", (origin,))

                reader.execute(
                    "SELECT stage_id, file, entry FROM dat_staging "
                    "ORDER BY stage_id"
                )
                while True:
                    batch = reader.fetchmany(500)
                    if not batch:
                        break
                    for stage_id, file, entry in batch:
                        cursor.execute(
                            "INSERT INTO dat(file, entry, origin) "
                            "VALUES (?, ?, ?)",
                            (file, entry, origin),
                        )
                        new_id = cursor.lastrowid
                        cursor.execute(
                            "INSERT INTO dat_set(id, dat_id) "
                            "SELECT id, ? FROM dat_staging_set "
                            "WHERE stage_id = ?",
                            (new_id, stage_id),
                        )
                        published += 1

                cursor.execute("DELETE FROM dat_staging")
                cursor.execute("DELETE FROM dat_staging_set")
            except Exception:
                cursor.execute("ROLLBACK TO umsa_dat_publish")
                cursor.execute("RELEASE umsa_dat_publish")
                raise
            else:
                cursor.execute("RELEASE umsa_dat_publish")
                if not had_transaction:
                    conn.commit()
            return published
        finally:
            reader.close()
            cursor.close()
