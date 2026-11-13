"""Connections and lifecycle of the UMSA databases.

``DBMod`` owns the persistent connections and nothing else of the data
access:

- ``umsa.db``, the downloaded game metadata (read-only), with ``artwork.db``
  and ``dat.db`` attached as the read-only schemas ``art`` and ``dat``. Both
  are the authoritative sources of scanned artwork and DAT texts; no data is
  copied into ``umsa.db``. ``open_db()`` reopens this connection after a
  database update.
- ``status.db`` with play status, emulator configuration, history and saved
  filters; its schema is migrated when ``DBMod`` opens it.

Everything else is reached through the accessors of ``DBMod``:

==================  ====================================================
``games``           :class:`~umsa_core.game_repository.GameRepository`
``artwork``         :class:`~umsa_core.artwork_repository.ArtworkRepository`
``dats``            :class:`~umsa_core.dat_repository.DatRepository`
``status``          :class:`~umsa_core.status_repository.StatusRepository`
``emulators``       :class:`~umsa_core.emulator_repository.EmulatorRepository`
``history``         :class:`~umsa_core.history_repository.HistoryRepository`
``software``        :class:`~umsa_core.software_details.SoftwareDetails`
``gamelist``        :class:`~umsa_core.gamelist_filter.Gamelist` (filter state)
``art_queries``     :class:`~umsa_core.artwork_queries.ArtworkQueries`
==================  ====================================================

Repositories and ``software`` are built on every access, so they can never
hold a connection that ``open_db()`` has replaced; ``gamelist`` and
``art_queries`` keep state and ask for the connection on every call. New
queries belong into those modules, not into ``DBMod``
(``tests/arch/test_dbmod_surface.py``).

Scans are not part of ``DBMod``: :class:`umsa_core.scans.Scans` runs them
with their own connections and holds the progress of the active scan.
"""

import os
import sqlite3  # connect, Row, OperationalError
from urllib.request import pathname2url

from .artwork_queries import ArtworkQueries
from .artwork_repository import ArtworkRepository, create_artwork_tables
from .dat_repository import DatRepository, create_dat_tables
from .data_paths import CoreDataPaths
from .default_filter import ensure_default_filter
from .emulator_repository import EmulatorRepository
from .game_repository import GameRepository
from .gamelist_filter import Gamelist
from .history_import import run_legacy_import as _run_legacy_import
from .history_repository import HistoryRepository
from .logging import log
from .software_details import SoftwareDetails
from .sqlite import connect_sqlite, connect_sqlite_readonly
from .status_migrations import apply_migrations
from .status_repository import StatusRepository


def _core_data_paths(db_path):
    """Adapt legacy database-directory arguments to explicit Core paths."""

    return CoreDataPaths(os.path.abspath(db_path))


class DBMod:
    """Database class for umsa.info sqlite3 database"""

    def __init__(self, db_path, nonmame=None, filter_lists=None, pref_country='US'):

        self.nonmame = nonmame
        self.pref_country = pref_country
        # filter, order and selector state of the game lists; asks for the
        # connection on every call because open_db() replaces it
        self.gamelist = Gamelist(lambda: self.gdb)
        # artwork joined with the game tables; nonmame can change later
        self.art_queries = ArtworkQueries(
            lambda: self.gdb, self.gamelist, lambda: self.nonmame)
        if not filter_lists:
            filter_lists = {}

        # Clean up whatever was opened if setup fails partway through. The
        # connection attributes may not all exist yet at that point, so the
        # cleanup helpers look them up defensively.
        try:
            self._open_persistent_databases(db_path, filter_lists)
        except Exception:
            self.close()
            raise

    def _open_persistent_databases(self, db_path, filter_lists):
        """Open the persistent umsa.db/status.db connections and prepare them."""

        self.db_paths = _core_data_paths(db_path)

        self._ensure_source_databases()

        self.gdb = connect_sqlite_readonly(self.db_paths.umsa_db, row_factory=sqlite3.Row)
        self.gdbc = self.gdb.cursor()

        self._attach_source_databases()

        self.sdb = connect_sqlite(self.db_paths.status_db)
        self.sdb.row_factory = sqlite3.Row
        self.sdbc = self.sdb.cursor()

        self.gamelist.define_filter(filter_lists)

        # Migrate status.db via repositories in one transaction; failure propagates.
        apply_migrations(self.sdb)

    def open_db(self, db_path):
        """Reopen umsa database, needed after update of umsa.db

        Reconnect to the downloaded umsa.db read-only and reattach the
        current artwork.db and dat.db as read-only schemas. The persistent
        status.db connection is left untouched. Any previous umsa.db
        connection is closed first so it can never be silently overwritten.
        No artwork/DAT data is copied into umsa.db.

        If opening or attaching fails, every cleanup step is attempted
        independently and logged; the original exception is re-raised.
        """

        self.close_umsa_db()

        self.db_paths = _core_data_paths(db_path)

        self._ensure_source_databases()

        gdb = None
        gdbc = None
        attached = set()
        try:
            gdb = connect_sqlite_readonly(self.db_paths.umsa_db, row_factory=sqlite3.Row)
            gdbc = gdb.cursor()

            for alias, statement, params in self._source_attach_statements():
                gdbc.execute(statement, params)
                attached.add(alias)

            self.gdb = gdb
            self.gdbc = gdbc
        except Exception:
            if gdbc is not None:
                for alias in ('art', 'dat'):
                    if alias not in attached:
                        continue
                    try:
                        gdbc.execute(f"DETACH DATABASE '{alias}'")
                    except Exception as exc:
                        log(f"UMSA database open_db: could not detach "
                            f"'{alias}' schema during cleanup: {exc}",
                            level='error')
                try:
                    gdbc.close()
                except Exception as exc:
                    log(f"UMSA database open_db: could not close umsa cursor "
                        f"during cleanup: {exc}", level='error')
            if gdb is not None:
                try:
                    gdb.close()
                except Exception as exc:
                    log(f"UMSA database open_db: could not close umsa "
                        f"connection during cleanup: {exc}", level='error')
            raise

    def close_umsa_db(self):
        """Close the persistent umsa.db connection, keeping status.db open.

        Safe to call more than once and even if __init__ failed before the
        connection was opened. The connection objects are left in a closed
        state rather than cleared so callers holding a reference see the
        connection they closed. Cursor and connection cleanup are independent;
        failures are logged without preventing the other close attempt.
        Successfully closed handle pairs are not retried.
        """

        gdbc = getattr(self, 'gdbc', None)
        gdb = getattr(self, 'gdb', None)
        closed_handles = getattr(self, '_umsa_closed_handles', None)
        if (closed_handles is not None
                and closed_handles[0] is gdbc
                and closed_handles[1] is gdb):
            return

        cleanup_failed = False
        if gdbc is not None:
            try:
                gdbc.close()
            except Exception as exc:
                cleanup_failed = True
                log(f"UMSA database close_umsa_db: could not close umsa "
                    f"cursor: {exc}", level='error')
        if gdb is not None:
            try:
                gdb.close()
            except Exception as exc:
                cleanup_failed = True
                log(f"UMSA database close_umsa_db: could not close umsa "
                    f"connection: {exc}", level='error')
        if not cleanup_failed:
            self._umsa_closed_handles = (gdbc, gdb)

    def close(self):
        """Close every persistent database connection owned by DBMod.

        Safe to call more than once and even if __init__ failed before both
        connections were opened. Cleanup is best-effort: failures are logged
        without preventing the remaining resources from being closed.
        """

        try:
            self.close_umsa_db()
        except Exception as exc:
            log(f"UMSA database close: umsa cleanup failed: {exc}",
                level='error')

        sdbc = getattr(self, 'sdbc', None)
        sdb = getattr(self, 'sdb', None)
        closed_handles = getattr(self, '_status_closed_handles', None)
        if (closed_handles is not None
                and closed_handles[0] is sdbc
                and closed_handles[1] is sdb):
            return

        cleanup_failed = False
        if sdbc is not None:
            try:
                sdbc.close()
            except Exception as exc:
                cleanup_failed = True
                log(f"UMSA database close: could not close status cursor: "
                    f"{exc}", level='error')
        if sdb is not None:
            try:
                sdb.close()
            except Exception as exc:
                cleanup_failed = True
                log(f"UMSA database close: could not close status connection: "
                    f"{exc}", level='error')
        if not cleanup_failed:
            self._status_closed_handles = (sdbc, sdb)

    def _ensure_source_databases(self):
        """Ensure artwork.db and dat.db exist with authoritative schemas.

        Creates missing schemas and upgrades existing artwork.db and dat.db
        schemas without truncating or repopulating existing data.
        """

        for path, create_tables in (
                (self.db_paths.artwork_db, create_artwork_tables),
                (self.db_paths.dat_db, create_dat_tables)):
            conn = connect_sqlite(path, row_factory=sqlite3.Row)
            try:
                create_tables(conn.cursor())
                conn.commit()
            finally:
                conn.close()

    def _source_attach_statements(self):
        """Return (alias, statement, params) attaching artwork.db/dat.db read-only.

        The URI is a bound parameter (the umsa.db connection is opened with
        ``uri=True``, so ``mode=ro`` applies); only the constant alias is part
        of the statement text, because identifiers cannot be bound.
        """

        statements = []
        for alias, path in (('art', self.db_paths.artwork_db),
                            ('dat', self.db_paths.dat_db)):
            uri = f'file:{pathname2url(os.fspath(path))}?mode=ro'
            statements.append((alias, f"ATTACH DATABASE ? AS {alias}", (uri,)))
        return statements

    def _attach_source_databases(self):
        """Attach artwork.db as 'art' and dat.db as 'dat' (read-only)."""

        for _alias, statement, params in self._source_attach_statements():
            self.gdbc.execute(statement, params)

    # Repositories are built per access, never cached: they can never hold a
    # connection that open_db() has replaced, and they never own or close it.

    @property
    def games(self):
        """Game metadata of ``umsa.db`` (:class:`GameRepository`)."""

        return GameRepository(self.gdb)

    @property
    def artwork(self):
        """Scanned artwork of the attached ``art`` schema (:class:`ArtworkRepository`)."""

        return ArtworkRepository(self.gdb, schema="art")

    @property
    def dats(self):
        """DAT texts of the attached ``dat`` schema (:class:`DatRepository`)."""

        return DatRepository(self.gdb, schema="dat")

    @property
    def status(self):
        """Play status and further media of ``status.db`` (:class:`StatusRepository`)."""

        return StatusRepository(self.sdb)

    @property
    def emulators(self):
        """Emulator configuration of ``status.db`` (:class:`EmulatorRepository`)."""

        return EmulatorRepository(self.sdb)

    @property
    def history(self):
        """History, saved filters and metadata of ``status.db`` (:class:`HistoryRepository`)."""

        return HistoryRepository(self.sdb)

    @property
    def software(self):
        """Software details composed from the repositories (:class:`SoftwareDetails`)."""

        return SoftwareDetails(self.games, self.status, self.dats, self.artwork)

    def ensure_default_filter(self):
        """Create the default filter once (first start); never raises.

        Returns ``True`` when the filter was written now, see
        :func:`umsa_core.default_filter.ensure_default_filter`.
        """

        return ensure_default_filter(self.history, self.gdb, self.nonmame)

    def run_legacy_import(self):
        """Run the one-time legacy import via the configured Core paths."""

        return _run_legacy_import(self.sdb, self.db_paths)
