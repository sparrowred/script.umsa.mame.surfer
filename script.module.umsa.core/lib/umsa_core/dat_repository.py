"""Repository for the DAT tables of dat.db (``dat``, ``dat_set``, ``dat_source``).

Owns the schema. ``dat.file`` is the visible display category; ``origin``
records which import produced a row. Writes use
:func:`umsa_core.sqlite.write_savepoint`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from .dat_parser import DRIVER_WIP
from .scan_coordinator import scan_coordinator
from .sqlite import require_row_connection, write_savepoint

ORIGIN_MAME_SUPPORT = "mame_support"
ORIGIN_EXODOS = "exodos"
ORIGIN_GB64 = "gb64"

def _guard_staging_coordinated():
    """Raise ``RuntimeError`` when another thread holds the scan lock.

    Staging from outside the locked scan would corrupt the active scan's
    staging tables.
    """

    if scan_coordinator.is_locked() and not scan_coordinator.owned_by_current_thread():
        raise RuntimeError(
            "DAT staging used without the shared scan lock while another scan "
            "is running"
        )


def create_dat_tables(db_cursor: sqlite3.Cursor) -> None:
    """Create the DAT tables and upgrade old databases in place.

    Idempotent; data is never discarded. Missing ``origin``/``driver`` columns
    are added and rows without an origin get one inferred from ``file``.
    """

    db_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dat(
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            file    VARCHAR(50),
            entry   TEXT,
            origin  TEXT,
            driver  TEXT
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
    # Lookups by set id, the dat row join and the per-origin cleanup of the
    # GB64/eXoDOS scans would otherwise scan the whole tables.
    db_cursor.execute(
        "CREATE INDEX IF NOT EXISTS dat_set_id_idx ON dat_set(id)")
    db_cursor.execute(
        "CREATE INDEX IF NOT EXISTS dat_set_dat_id_idx ON dat_set(dat_id)")
    db_cursor.execute(
        "CREATE INDEX IF NOT EXISTS dat_origin_idx ON dat(origin)")
    # Driver WIP lookup by driver name (rows with a NULL driver are the rest).
    db_cursor.execute(
        "CREATE INDEX IF NOT EXISTS dat_driver_idx ON dat(driver)")
    # One row per scanned input file: header version and counters.
    db_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dat_source(
            origin            TEXT NOT NULL,
            file              TEXT NOT NULL,
            version           TEXT,
            date              TEXT,
            entries           INTEGER NOT NULL DEFAULT 0,
            unmatched_entries INTEGER NOT NULL DEFAULT 0,
            unmatched_sets    INTEGER NOT NULL DEFAULT 0,
            unmatched_drivers INTEGER NOT NULL DEFAULT 0,
            scanned_at        TEXT,
            PRIMARY KEY(origin, file)
        )
        """
    )
    _backfill_origin(db_cursor)


def _ensure_origin_column(db_cursor: sqlite3.Cursor) -> None:
    """Add the ``origin`` and ``driver`` columns to an old ``dat`` table."""

    _ensure_columns(db_cursor, "dat", ("origin", "driver"))


def _ensure_columns(db_cursor: sqlite3.Cursor, table: str, names) -> None:
    """Add every missing nullable ``TEXT`` column of ``names`` to ``table``."""

    db_cursor.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in db_cursor.fetchall()}
    for name in names:
        if name not in columns:
            db_cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} TEXT")


def _backfill_origin(db_cursor: sqlite3.Cursor) -> None:
    """Assign an origin to rows without one; an existing origin is never overwritten."""

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
    """DAT operations on a caller-owned connection.

    Never opens or closes the connection. Query methods leave transactions to
    the caller. ``schema`` qualifies the read queries: ``"main"`` for a
    scanner's own dat.db connection, ``"dat"`` for the attached schema of
    ``DBMod``.
    """

    _ALLOWED_SCHEMAS = frozenset({"main", "dat"})

    def __init__(self, connection: sqlite3.Connection, schema: str = "main") -> None:
        """Wrap a connection for the schema ``"main"`` or ``"dat"``.

        Raises:
            ValueError: If the connection does not use ``sqlite3.Row``
                (:func:`umsa_core.sqlite.require_row_connection`) or
                ``schema`` is not allowed.
        """
        require_row_connection(connection, "DatRepository")
        if schema not in self._ALLOWED_SCHEMAS:
            raise ValueError(
                f"DatRepository schema must be one of {sorted(self._ALLOWED_SCHEMAS)}, got {schema!r}"
            )
        self._conn = connection
        self._schema = schema

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def schema(self) -> str:
        return self._schema

    def _qt(self, table: str) -> str:
        """Return a schema-qualified table name."""
        return f"{self._schema}.{table}"

    def get_dat_for_set(self, set_id: int) -> dict:
        """Return a ``{display category: entry text}`` mapping for one set."""

        cursor = self._conn.cursor()
        try:
            cursor.execute(
                f"SELECT {self._qt('dat')}.file, {self._qt('dat')}.entry FROM {self._qt('dat')} "
                f"JOIN {self._qt('dat_set')} ON {self._qt('dat')}.id = {self._qt('dat_set')}.dat_id "
                f"WHERE {self._qt('dat_set')}.id = ?",
                (set_id,),
            )
            set_dats = {}
            for row in cursor.fetchall():
                set_dats[row[0]] = row[1]
            return set_dats
        finally:
            cursor.close()

    def get_dat_for_sets(self, set_ids: Iterable[int]) -> dict:
        """Return ``{set id: {display category: entry text}}`` for many sets."""

        ids = list(set_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                f"SELECT {self._qt('dat_set')}.id, {self._qt('dat')}.file, {self._qt('dat')}.entry FROM {self._qt('dat')} "
                f"JOIN {self._qt('dat_set')} ON {self._qt('dat')}.id = {self._qt('dat_set')}.dat_id "
                f"WHERE {self._qt('dat_set')}.id in ({placeholders})",
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

    def get_driver_wip(self, drivers: Iterable[str]) -> dict:
        """Return ``{driver name: WIP Driver text}`` of the drivers that have one."""

        names = list(dict.fromkeys(d for d in drivers if d))
        if not names:
            return {}
        placeholders = ",".join("?" for _ in names)
        dat = self._qt('dat')
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                f"SELECT driver, entry FROM {dat} "
                f"WHERE file = ? AND driver IN ({placeholders})",
                [DRIVER_WIP, *names],
            )
            return {row[0]: row[1] for row in cursor.fetchall()}
        finally:
            cursor.close()

    def get_sources(self, origin: str | None = None) -> list:
        """Return the ``dat_source`` rows as dicts, sorted by ``file``.

        ``origin`` limits the result to one origin; ``None`` returns all.
        """

        table = self._qt('dat_source')
        cursor = self._conn.cursor()
        try:
            if origin is None:
                cursor.execute(f"SELECT * FROM {table} ORDER BY file, origin")
            else:
                cursor.execute(
                    f"SELECT * FROM {table} WHERE origin = ? ORDER BY file",
                    (origin,),
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    # -- staging ---------------------------------------------------------

    def create_staging_tables(
        self, db_cursor: sqlite3.Cursor | None = None
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
                    entry     TEXT,
                    driver    TEXT
                )
                """
            )
            _ensure_columns(db_cursor, "dat_staging", ("driver",))
            db_cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS dat_staging_set(
                    stage_id  INTEGER,
                    id        INTEGER
                )
                """
            )
            db_cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_dat_staging_set_stage_id "
                "ON dat_staging_set(stage_id)"
            )
        finally:
            if close:
                db_cursor.close()

    def clear_staging(self, db_cursor: sqlite3.Cursor | None = None) -> None:
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
        entry: str | None,
        set_ids: Iterable[int],
        db_cursor: sqlite3.Cursor | None = None,
        driver: str | None = None,
    ) -> int:
        """Stage one parsed entry and its set relationships; return the staging id.

        ``driver`` is the MAME driver name of a ``WIP Driver`` entry. The
        caller owns the transaction. Staging tables are separate, so staged
        ids never collide with published ``dat`` rows.
        """

        close = False
        if db_cursor is None:
            db_cursor = self._conn.cursor()
            close = True
        try:
            db_cursor.execute(
                "INSERT INTO dat_staging(file, entry, driver) VALUES (?, ?, ?)",
                (file, entry, driver),
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
        self, origin: str, set_id: int, file: str, entry: str | None
    ) -> int:
        """Replace the ``origin`` row of one set; return the id of the new row.

        For per-set importers (GameBase64) that must stay idempotent. In one
        savepoint the ``origin`` rows linked to ``set_id`` are unlinked (and
        deleted when no other set uses them) and a fresh row is inserted. Rows
        of other origins are never touched; on error the old rows are kept.
        """

        with write_savepoint(self._conn, "umsa_dat_replace_set") as cursor:
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
        return new_id

    def replace_origin(self, origin: str, records,
                       allow_empty: bool = False) -> int:
        """Replace all rows of ``origin`` in one savepoint; return the number inserted.

        Each record exposes ``file``, ``entry`` and ``set_ids`` (optionally
        ``driver``), like :class:`umsa_core.dat_parser.DatEntry`. Rows of other
        origins are never touched; on failure the old rows are kept.

        Raises:
            ValueError: If ``records`` is empty and ``allow_empty`` is false,
                so a failed parse or an unmatched scan never wipes the data.
        """

        entries = list(records)
        if not entries and not allow_empty:
            raise ValueError(
                "refusing to replace an origin with an empty record collection"
            )

        published = 0
        with write_savepoint(self._conn, "umsa_dat_replace_origin") as cursor:
            cursor.execute(
                "DELETE FROM dat_set WHERE dat_id IN "
                "(SELECT id FROM dat WHERE origin = ?)",
                (origin,),
            )
            cursor.execute("DELETE FROM dat WHERE origin = ?", (origin,))

            for entry in entries:
                set_ids = getattr(entry, "set_ids", ())
                cursor.execute(
                    "INSERT INTO dat(file, entry, origin, driver) "
                    "VALUES (?, ?, ?, ?)",
                    (entry.file, entry.entry, origin,
                     getattr(entry, "driver", None)),
                )
                new_id = cursor.lastrowid
                if new_id is None:
                    raise RuntimeError("dat insert did not return a row id")
                for set_id in set_ids:
                    cursor.execute(
                        "INSERT INTO dat_set(id, dat_id) VALUES (?, ?)",
                        (set_id, new_id),
                    )
                published += 1
        return published

    def publish_staged(self, origin: str, sources=None) -> int:
        """Replace the rows of ``origin`` with the staged data; return the count.

        One savepoint: delete the old rows, insert the staged ones with fresh
        ids, clear the staging tables. On error the old rows are kept.
        ``sources`` (dicts keyed by the ``dat_source`` columns except
        ``origin``) replaces the ``dat_source`` rows of ``origin`` in the same
        savepoint; ``None`` leaves them untouched.
        """

        _guard_staging_coordinated()
        conn = self._conn
        reader = conn.cursor()
        published = 0
        try:
            with write_savepoint(conn, "umsa_dat_publish") as cursor:
                cursor.execute(
                    "DELETE FROM dat_set WHERE dat_id IN "
                    "(SELECT id FROM dat WHERE origin = ?)",
                    (origin,),
                )
                cursor.execute("DELETE FROM dat WHERE origin = ?", (origin,))

                reader.execute(
                    "SELECT stage_id, file, entry, driver FROM dat_staging "
                    "ORDER BY stage_id"
                )
                while True:
                    batch = reader.fetchmany(500)
                    if not batch:
                        break
                    for stage_id, file, entry, driver in batch:
                        cursor.execute(
                            "INSERT INTO dat(file, entry, origin, driver) "
                            "VALUES (?, ?, ?, ?)",
                            (file, entry, origin, driver),
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

                if sources is not None:
                    cursor.execute(
                        "DELETE FROM dat_source WHERE origin = ?", (origin,))
                    for source in sources:
                        cursor.execute(
                            "INSERT INTO dat_source(origin, file, version, "
                            "date, entries, unmatched_entries, "
                            "unmatched_sets, unmatched_drivers, scanned_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (origin, source['file'], source.get('version'),
                             source.get('date'), source.get('entries', 0),
                             source.get('unmatched_entries', 0),
                             source.get('unmatched_sets', 0),
                             source.get('unmatched_drivers', 0),
                             source.get('scanned_at')),
                        )
            return published
        finally:
            reader.close()
