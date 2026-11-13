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

The scan entry points (``scan_dats``, ``scan_artwork``, ``scan_exodos_to_db``,
``scan_gb64_to_db``) still live here with the shared scan progress fields;
the scanners write through their own connections.
"""

import os
import sqlite3  # connect, Row, OperationalError
from urllib.request import pathname2url

from .artwork_queries import ArtworkQueries
from .artwork_repository import ArtworkRepository, create_artwork_tables
from .artwork_scanner import ArtworkScanner
from .dat_repository import DatRepository, create_dat_tables
from .dat_scanner import DatScanner
from .data_paths import CoreDataPaths
from .default_filter import ensure_default_filter
from .emulator_repository import EmulatorRepository
from .game_repository import GameRepository
from .gamelist_filter import Gamelist
from .gb64_scanner import GB64Scanner
from .history_import import run_legacy_import as _run_legacy_import
from .history_repository import HistoryRepository
from .logging import log
from .scan_progress import _scan_state_ownership
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
        self.scan_perc = 0
        self.scan_what = 'nothing'
        self.scan_status = True
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

    def _run_scan_with_shared_state(self, start_what, run):
        """Run ``run`` while owning the shared scan progress/status fields.

        ``scan_perc``/``scan_what``/``scan_status`` describe the single active
        scan, so only the invocation that actually acquires the process-wide
        scan lock may initialise or finalise them. A competing invocation that
        cannot take the lock delegates straight to the scanner, whose public
        ``scan()`` returns its ``busy`` summary without touching this instance's
        progress or cancellation state (in particular it does not clear
        ``scan_status`` and thereby cancel the active scan).
        """

        with _scan_state_ownership(self, start_what):
            return run()

    def scan_gb64_to_db(self, empty, db_path):
        """Read GameBase64 info from zip and artwork.

        This is a thin compatibility wrapper around
        :class:`umsa_core.gb64_scanner.GB64Scanner`. It keeps the historical
        ``scan_gb64_to_db(empty, db_path)`` interface, the
        ``scan_perc``/``scan_what``/``scan_status`` attributes used by
        ``run_scan_with_progress()`` and the GUI, and returns the scanner's
        summary dictionary unchanged.

        The ``empty`` argument is a legacy placeholder that is never read; the
        GameBase64 root is taken from the Core ``gb64`` setting instead. See
        :meth:`GB64Scanner.scan` for the import semantics.
        """

        db_paths = _core_data_paths(db_path) if db_path else self.db_paths
        gb64_root = self.nonmame.get('gb64', '') if self.nonmame else ''

        def progress(percent, what):
            if percent is not None:
                self.scan_perc = percent
            if what is not None:
                self.scan_what = what

        def is_cancelled():
            return not self.scan_status

        def run():
            return GB64Scanner(
                db_paths,
                initialize_dat=create_dat_tables,
                initialize_art=create_artwork_tables,
                progress=progress,
                is_cancelled=is_cancelled,
            ).scan(gb64_root)

        return self._run_scan_with_shared_state('reading covers...', run)

    def scan_exodos_to_db(self, empty, db_path):
        """Read eXoDOS xml and artwork.

        This is a thin compatibility wrapper around
        :class:`umsa_core.exodos_scanner.ExodosScanner`. It keeps the historical
        ``scan_exodos_to_db(empty, db_path)`` interface, the
        ``scan_perc``/``scan_what``/``scan_status`` attributes used by
        ``run_scan_with_progress()`` and the GUI, and returns the scanner's
        summary dictionary unchanged.
        """

        db_paths = _core_data_paths(db_path) if db_path else self.db_paths
        exodos_root = self.nonmame.get('exodos', '') if self.nonmame else ''

        def progress(percent, what):
            if percent is not None:
                self.scan_perc = percent
            if what is not None:
                self.scan_what = what

        def is_cancelled():
            return not self.scan_status

        def run():
            from .exodos_scanner import ExodosScanner
            return ExodosScanner(
                db_paths,
                initialize_dat=create_dat_tables,
                initialize_art=create_artwork_tables,
                progress=progress,
                is_cancelled=is_cancelled,
            ).scan(exodos_root)

        return self._run_scan_with_shared_state(
            'reading MS-DOS.xml from zip', run)

    def scan_dats(self, datdir, db_path):
        """Read all MAME dat files from a directory

        datdir -- directory with dat files
        db_path -- directory for database files

        This is a thin compatibility wrapper around
        :class:`umsa_core.dat_scanner.DatScanner`. It keeps the public
        ``scan_dats(datdir, db_path)`` interface, the
        ``scan_perc``/``scan_what``/``scan_status`` attributes used by
        ``run_scan_with_progress()`` and the GUI, and returns the scanner's
        summary dictionary unchanged.

        See :meth:`DatScanner.scan` for the staging/replacement semantics.
        """

        db_paths = _core_data_paths(db_path) if db_path else self.db_paths

        def progress(percent, what):
            if percent is not None:
                self.scan_perc = percent
            if what is not None:
                self.scan_what = what

        def is_cancelled():
            return not self.scan_status

        def run():
            return DatScanner(
                db_paths,
                initialize_tables=create_dat_tables,
                progress=progress,
                is_cancelled=is_cancelled,
            ).scan(datdir)

        return self._run_scan_with_shared_state('files', run)

    def scan_artwork(self, paths=None, db_path=None, listdir=None, source=None,
                     cancel_event=None, only_types=None, resume=True, **kwargs):
        """Scan artwork folders, unit-based and resumable.

        This is a thin compatibility wrapper around
        :class:`umsa_core.artwork_scanner.ArtworkScanner`. It preserves the
        historical ``DBMod.scan_artwork()`` interface, keeps the
        ``scan_status``/``scan_perc``/``scan_what`` attributes used by
        ``run_scan_with_progress()`` and the GUI in sync, and returns the
        scanner's summary dictionary unchanged.

        See :meth:`ArtworkScanner.scan` for the discovery/inventory semantics,
        resumability, filesystem retry policy and summary keys.
        """

        db_paths = _core_data_paths(db_path) if db_path else self.db_paths

        def progress(percent, what):
            if percent is not None:
                self.scan_perc = percent
            if what is not None:
                self.scan_what = what

        def is_cancelled():
            return not self.scan_status

        def run():
            return ArtworkScanner(
                db_paths,
                create_artwork_tables,
                progress=progress,
                is_cancelled=is_cancelled,
                listdir=listdir,
            ).scan(
                paths,
                source=source,
                only_types=only_types,
                resume=resume,
                cancel_event=cancel_event,
            )

        return self._run_scan_with_shared_state('discovering', run)

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
