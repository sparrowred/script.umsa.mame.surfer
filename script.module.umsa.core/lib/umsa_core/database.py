"""Module for umsa.info sqlite3 database.

Artwork table access is centralised in :mod:`umsa_core.artwork_repository` and
DAT table access in :mod:`umsa_core.dat_repository`; DAT parsing lives in
:mod:`umsa_core.dat_parser` and the DAT scan workflow in
:mod:`umsa_core.dat_scanner`. ``status.db`` play history and per-set media
access is centralised in :mod:`umsa_core.status_repository`, emulator
configuration (``emu``/``emu_conn``) in :mod:`umsa_core.emulator_repository`.
``DBMod`` remains the public facade.

``umsa.db`` is the downloaded game metadata database (read-only during normal
operation). ``artwork.db`` and ``dat.db`` are the authoritative sources for
scanned artwork and DAT data respectively. They are attached as read-only
schemas ``art`` and ``dat`` on the persistent ``umsa.db`` connection. Scanner
workflows write to their respective source databases through their own
writable connections.

A few direct statements intentionally remain here:

- ``open_db()`` reopens the downloaded ``umsa.db`` read-only and reattaches
  the current ``artwork.db`` and ``dat.db`` as read-only schemas. No data is
  copied into ``umsa.db``.
- ``get_random_art()`` and ``get_artwork_by_software_id()`` join the attached
  ``art.art_set`` with the general UMSA game tables (``sets``/``swl``/
  ``software``) and, for ``get_random_art()``, depend on the active ``DBMod``
  filter state. These are mixed application queries rather than artwork-table
  CRUD and are left here on purpose.

TODO
 - remove usage of detail, use split_gamename
"""

import os
import sqlite3  # connect, Row, OperationalError
import time
from contextlib import contextmanager
from urllib.request import pathname2url

from .artwork import resolve_artwork_path
from .artwork_repository import ArtworkRepository, create_artwork_tables
from .artwork_scanner import ArtworkScanner
from .dat_repository import DatRepository, create_dat_tables
from .dat_scanner import DatScanner
from .data_paths import CoreDataPaths
from .emulator_repository import EmulatorRepository
from .game_repository import GameRepository
from .gamelist_filter import GamelistFilter
from .gamelist_filter import category_query as _category_query
from .gamelist_filter import define_filter as _define_filter
from .gamelist_filter import execute_statement as _execute_statement
from .gamelist_filter import maker_query as _maker_query
from .gamelist_filter import players_query as _players_query
from .gamelist_filter import software_query as _software_query
from .gamelist_filter import source_query as _source_query
from .gamelist_filter import swl_query as _swl_query
from .gamelist_filter import year_query as _year_query
from .gb64_scanner import GB64Scanner
from .history_import import discover_legacy_paths as _discover_legacy_paths
from .history_import import retry_import as _retry_import
from .history_import import run_legacy_import as _run_legacy_import
from .history_repository import HistoryRepository
from .logging import log
from .umsa_db_download import download_and_update_umsa_db
from .scan_coordinator import ScanBusyError, ScanLockContext, scan_coordinator
from .sqlite import connect_sqlite, connect_sqlite_readonly
from .status_migrations import apply_migrations
from .status_repository import StatusRepository

from .scan_progress import _scan_state_ownership, run_scan_with_progress  # noqa: F401
from .game_labels import make_time_nice, split_gamename  # noqa: F401


def _core_data_paths(db_path):
    """Adapt legacy database-directory arguments to explicit Core paths."""

    return CoreDataPaths(os.path.abspath(db_path))


def parse_recommended_games(rec_text, db):
    """Parse the 'Rec' dat field into popup entries.

    Returns ``(rec_list, pos)``. Separator entries (names starting with ``-``)
    are ``{'name', 'id': 0, 'year', 'maker'}`` and each increments ``pos``;
    found games are ``{'id', 'name', 'year', 'maker'}``. Names not found in the
    database are kept as ``None`` (popup_gamelist skips them).
    """

    rec_list = []
    pos = 0
    for rec_gamename in rec_text.split('[CR]'):
        if rec_gamename == '':
            continue
        if rec_gamename[0] == '-':
            rec_list.append({'name': rec_gamename, 'id': 0, 'year': '', 'maker': ''})
            pos += 1
        else:
            found = db.search_single(rec_gamename)
            rec_list.append(
                None if found is None else
                {'id': found['id'], 'name': found['name'],
                 'year': found['year'], 'maker': found['maker']})
    return rec_list, pos


def build_filter_lists(filter_lists, category, db):
    """Partition a filter category's database entries into active/inactive.

    ``active`` holds entries whose id is in ``filter_lists[category]``,
    ``inactive`` holds the rest (database order preserved). Each entry is a
    dict ``{'id': str, 'name', 'count'}``. Unknown categories yield empty lists.
    """

    active_ids = set(filter_lists.get(category, []))
    active = []
    inactive = []
    for entry in (db.get_all_dbentries(category) or []):
        item = {'id': str(entry['id']), 'name': entry['name'], 'count': entry['count']}
        (active if item['id'] in active_ids else inactive).append(item)
    return {'active': active, 'inactive': inactive}



COUNTRIES = {
    '1NTSC' : ('ntsc',),
    '2PAL'  : ('pal',),
    '3US'   : ('usa', 'america', 'nintendo entertainment system /', 'world'),
    '4JP'   : ('jpn', 'japan', 'famicom'),
    '5EU'   : ('euro',),
    '6EU'   : ('euro', 'pal'),
    '7KR'   : ('kor',),
    '8BR'   : ('bra',),
}

class DBMod:
    """Database class for umsa.info sqlite3 database"""

    def __init__(self, db_path, nonmame=None, filter_lists=None, pref_country='US'):

        self.nonmame = nonmame
        self.pref_country = pref_country
        self.use_filter = True
        self.order = 'name'
        self.scan_perc = 0
        self.scan_what = 'nothing'
        self.scan_status = True
        self.join = ''
        self.where = ''
        self._where_params = []
        self._filter_where_params = []
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

        self.define_filter(filter_lists)

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

            art_uri = f'file:{pathname2url(os.fspath(self.db_paths.artwork_db))}?mode=ro'
            dat_uri = f'file:{pathname2url(os.fspath(self.db_paths.dat_db))}?mode=ro'
            gdbc.execute(f"ATTACH DATABASE '{art_uri}' AS art")
            attached.add('art')
            gdbc.execute(f"ATTACH DATABASE '{dat_uri}' AS dat")
            attached.add('dat')

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

    def create_dat_tables(self, db_cursor):
        """create dat tables

        Delegates to the authoritative DAT schema definition in the DAT
        repository. The signature is preserved for compatibility with existing
        callers; the helper also handles the origin column upgrade/backfill.
        """

        create_dat_tables(db_cursor)

    def create_art_tables(self, db_cursor):
        """create art tables

        Delegates to the authoritative artwork schema definition in the
        artwork repository. The signature is preserved for compatibility
        with existing callers.
        """

        create_artwork_tables(db_cursor)

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

    def close_db(self):
        """Compatibility wrapper: close only the umsa.db connection.

        Historically ``close_db`` closed only ``umsa.db`` and left
        ``status.db`` open (the database-update sequence relies on that, then
        calls :meth:`open_db` again). Use :meth:`close` for a full shutdown.
        """

        self.close_umsa_db()

    def _ensure_source_databases(self):
        """Ensure artwork.db and dat.db exist with authoritative schemas.

        Creates missing schemas and upgrades existing artwork.db and dat.db
        schemas without truncating or repopulating existing data.
        """

        if not self.db_paths.artwork_db.exists():
            conn = connect_sqlite(self.db_paths.artwork_db, row_factory=sqlite3.Row)
            try:
                create_artwork_tables(conn.cursor())
                conn.commit()
            finally:
                conn.close()
        else:
            conn = connect_sqlite(self.db_paths.artwork_db, row_factory=sqlite3.Row)
            try:
                create_artwork_tables(conn.cursor())
                conn.commit()
            finally:
                conn.close()

        if not self.db_paths.dat_db.exists():
            conn = connect_sqlite(self.db_paths.dat_db, row_factory=sqlite3.Row)
            try:
                create_dat_tables(conn.cursor())
                conn.commit()
            finally:
                conn.close()
        else:
            conn = connect_sqlite(self.db_paths.dat_db, row_factory=sqlite3.Row)
            try:
                create_dat_tables(conn.cursor())
                conn.commit()
            finally:
                conn.close()

    def _attach_source_databases(self):
        """Attach artwork.db as 'art' and dat.db as 'dat' (read-only)."""
        art_uri = f'file:{pathname2url(os.fspath(self.db_paths.artwork_db))}?mode=ro'
        dat_uri = f'file:{pathname2url(os.fspath(self.db_paths.dat_db))}?mode=ro'
        self.gdbc.execute(f"ATTACH DATABASE '{art_uri}' AS art")
        self.gdbc.execute(f"ATTACH DATABASE '{dat_uri}' AS dat")

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
                initialize_dat=self.create_dat_tables,
                initialize_art=self.create_art_tables,
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
                initialize_dat=self.create_dat_tables,
                initialize_art=self.create_art_tables,
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
                initialize_tables=self.create_dat_tables,
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
                self.create_art_tables,
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

    def _get_artwork_repository(self):
        """Return a repository bound to the current umsa.db connection.

        The repository is created per call rather than cached, so it can
        never hold a reference to a connection that ``open_db()`` has since
        replaced. It never owns or closes ``self.gdb``. Uses the ``art``
        schema where artwork.db is attached.
        """

        return ArtworkRepository(self.gdb, schema="art")

    def _get_dat_repository(self):
        """Return a DAT repository bound to the current umsa.db connection.

        Created per call (never cached) so it can never hold a reference to a
        connection that ``open_db()`` has since replaced. It never owns or
        closes ``self.gdb``. Uses the ``dat`` schema where dat.db is attached.
        """

        return DatRepository(self.gdb, schema="dat")

    def _get_game_repository(self):
        """Return a game repository bound to the current umsa.db connection.

        Created per call (never cached) so it can never hold a reference to a
        connection that ``open_db()`` has since replaced. It never owns or
        closes ``self.gdb``.
        """

        return GameRepository(self.gdb)

    def _get_status_repository(self):
        """Return a status repository bound to the current status.db connection.

        Created per call (never cached) so it can never hold a reference to a
        connection that has since been replaced. It never owns or closes
        ``self.sdb``.
        """

        return StatusRepository(self.sdb)

    def _get_emulator_repository(self):
        """Return an emulator repository bound to the current status.db connection.

        Created per call (never cached) so it can never hold a reference to a
        connection that has since been replaced. It never owns or closes
        ``self.sdb``.
        """

        return EmulatorRepository(self.sdb)

    def _get_history_repository(self):
        """Return a history repository bound to the current status.db connection.

        Created per call (never cached) so it can never hold a reference to a
        connection that has since been replaced. It never owns or closes
        ``self.sdb``.
        """

        return HistoryRepository(self.sdb)

    def get_art_types(self):
        """get all types of artwork which contain images

        except videosnaps, manuals, soundtracks and patches
        """

        return self._get_artwork_repository().get_art_types()

    def get_artwork_for_set(self, set_id):
        """get artwork for one set"""

        repo = self._get_artwork_repository()
        return repo.get_artwork_for_set(set_id)

    def get_artwork_for_sets(self, set_ids):
        """get artwork for a list of sets"""

        repo = self._get_artwork_repository()
        return repo.get_artwork_for_sets(set_ids)

    def get_dat_for_set(self, set_id):
        """get dat file entries for one set

        Returns a ``{display category: entry text}`` mapping. Delegates to
        :class:`umsa_core.dat_repository.DatRepository`; the result structure
        is unchanged.
        """

        return self._get_dat_repository().get_dat_for_set(set_id)

    def get_dat_for_sets(self, set_ids):
        """get dat file entries for a list of sets

        Returns a ``{set id: {display category: entry text}}`` mapping.
        Delegates to :class:`umsa_core.dat_repository.DatRepository`; an empty
        list returns an empty mapping.
        """

        return self._get_dat_repository().get_dat_for_sets(set_ids)

    def get_random_id(self):
        """get a random id"""

        where = ''
        where_params = []
        if self.filter_join and self.filter_where:
            where = "WHERE sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                " ".join(self.filter_join), " AND ".join(self.filter_where)
            )
            where_params = list(self._filter_where_params)

        select_statement = f"SELECT DISTINCT software.id \
                            FROM sets JOIN software ON software.id = sets.softwarelink_id \
                            {where} ORDER BY RANDOM() LIMIT 1"
        self.gdbc.execute(select_statement, where_params)
        return self.gdbc.fetchone()[0]

    def has_artwork(self, art_types):
        """Return whether any artwork of the given types can be selected.

        The check uses the same joined tables, the same artwork database
        (``art.art_set``) and the same active filter as
        :meth:`get_random_art`, so a positive answer means the random
        selection can really return a row. It stops at the first hit and
        never loads a whole artwork collection.

        ``art_types`` may be empty (the answer is then ``False``) and may
        contain duplicates.
        """

        types = list(dict.fromkeys(art_types or []))
        if not types:
            return False
        types_in = ",".join("?" * len(types))

        # with the active filter first, like the random selection
        # (an empty filter would produce an invalid "AND" clause)
        if self.use_filter and self.filter_where:
            statement = "SELECT 1 FROM art.art_set art JOIN sets ON sets.id = art.id {} \
                         WHERE art.type IN ({}) AND {} LIMIT 1".format(
                             " ".join(self.filter_join),
                             types_in,
                             " AND ".join(self.filter_where))
            self.gdbc.execute(statement,
                              list(types) + list(self._filter_where_params))
            if self.gdbc.fetchone():
                return True

        # and without filter if the filter found nothing
        statement = f"SELECT 1 FROM art.art_set art JOIN sets ON sets.id = art.id \
                    WHERE art.type IN ({types_in}) LIMIT 1"
        self.gdbc.execute(statement, list(types))
        return bool(self.gdbc.fetchone())

    def get_random_art(self, art_types):
        """Get 1 random artwork

        TODO
        - check where get_random_art is used and if machine, left is always needed
           if not make optional
        - get machine pic, see screensaver/get_machine_pic
        - get bottom left, type video/snap/title = cover/flyer
                           type cover/flyer = snap
          needs fetch info for snap from db for aspect ratio

        Takes a list of artwork types
        Returns a dictonary with informations or None if nothing is found

        Artwork locations live in the ``art.art_set`` schema (attached artwork.db):
        every row carries ``source``, ``root_key``, ``relative_path`` and
        ``archive_member``. Callers resolve them with
        :func:`umsa_core.artwork.resolve_artwork_path`; the additional left
        image is resolved here for the screensaver.

        The random artwork selection intentionally stays in ``DBMod``: it
        joins the attached ``art.art_set`` with ``sets`` and applies the active
        ``filter_join``/``filter_where`` state, so it is a mixed application
        query rather than artwork-table CRUD. The isolated left-image lookup
        is delegated to :class:`ArtworkRepository`.
        """

        art_columns = (
            "sets.id, art.source, art.root_key, art.scan_unit, "
            "art.type, art.extension, art.relative_path, "
            "art.archive_member"
        )
        types_in = ",".join("?" * len(art_types))

        rand_art = None
        end_result = {}

        # get with filter if on
        if self.use_filter:
            # TODO doesnt work when filter = everything but filter = on
            statement = "SELECT {} FROM art.art_set art JOIN sets ON sets.id = art.id {} \
                         WHERE art.type IN ({}) AND {} \
                         ORDER BY RANDOM() LIMIT 1".format(
                             art_columns,
                             " ".join(self.filter_join),
                             types_in,
                             " AND ".join(self.filter_where))
            self.gdbc.execute(statement,
                              list(art_types) + list(self._filter_where_params))
            rand_art = self.gdbc.fetchone()
        # and without filter if we haven't found anything
        if not rand_art:
            statement = f"SELECT {art_columns} FROM art.art_set art JOIN sets ON sets.id = art.id \
                        WHERE art.type IN ({types_in}) \
                        ORDER BY RANDOM() LIMIT 1"
            self.gdbc.execute(statement, list(art_types))
            rand_art = self.gdbc.fetchone()
            if not rand_art:
                log(f"UMSA database get_random art: no artwork for {art_types}", level='warning')
                return None
        end_result.update(rand_art)

        # get needed infos
        self.gdbc.execute(
            "SELECT sets.name, swl.name as swl_name, gamename, \
                    year.name as year, maker.name as maker, softwarelink_id as s_id, \
                    swl.system_id as swl_system_id, cat.name as category, cat.flag as is_machine \
             FROM sets, swl, year, maker, category cat \
             WHERE sets.id = ? \
             AND sets.year_id = year.id AND sets.publisher_id = maker.id \
             AND sets.swllink_id = swl.id AND sets.classification_id = cat.id",
            (rand_art['id'],)
        )
        art_info = self.gdbc.fetchone()
        end_result.update(art_info)
        end_result.update(
            {'machine_name': self.get_machine_name(end_result['swl_system_id'])[0]})

        # snap/title: get display
        if 'snap' in art_types or 'titles' in art_types:
            if end_result['swl_name'] == 'mame':
                machine = rand_art['id']
            else:
                machine = end_result['swl_system_id']
            self.gdbc.execute(
                "SELECT display_rotation, display_type \
                FROM sets WHERE id = ?", (machine,)
            )
            art_displayinfo = self.gdbc.fetchone()
            end_result.update(art_displayinfo)
        else:
            end_result.update({'display_rotation': 0, 'display_type': ''})

        # get left pic if swl is nonmame
        if (end_result['swl_name'] == 'exodos') or (end_result['swl_name'].startswith('gb64_')):
            if end_result['type'] in ('snap', 'titles', 'videosnaps'):
                lefttype = 'covers'
            else:
                lefttype = 'snap'
            leftpic = self._get_artwork_repository().get_artwork_record_for_set_type(
                rand_art['id'], lefttype
            )
            if leftpic:
                left_path = resolve_artwork_path(
                    leftpic, end_result, self._art_source_roots())
                if left_path:
                    end_result.update({'left_pic': left_path})

        return end_result

    def _art_source_roots(self):
        """Return configured roots for the non-MAME artwork sources.

        ``get_random_art`` only resolves the additional left image, which is
        picked from the eXoDOS/GB64 sources whose roots are held here.
        """

        nonmame = self.nonmame or {}
        return {
            'exodos': nonmame.get('exodos', ''),
            'gb64': nonmame.get('gb64', ''),
        }

    def get_random_vgm_batch(self, db_path, limit=100):
        """Return up to ``limit`` random vgmplay entries from a short-lived read-only connection.

        The connection is opened only for this query and closed on every exit
        path. No filesystem inspection is performed here; callers decide
        which candidates are actually playable.
        """

        db_paths = _core_data_paths(db_path)
        try:
            db_conn = connect_sqlite_readonly(db_paths.umsa_db)
        except sqlite3.Error as error:
            log(f"UMSA database get_random_vgm_batch: open failed: {error}", level='warning')
            return []

        dbc = None
        try:
            dbc = db_conn.cursor()
            vgmplay_row = dbc.execute(
                "SELECT id FROM swl WHERE name = 'vgmplay'").fetchone()
            if vgmplay_row is None:
                log("UMSA database get_random_vgm_batch: no vgmplay software list",
                    level='warning')
                return []
            rows = dbc.execute(
                "SELECT name, gamename FROM sets \
                 WHERE swllink_id = ? ORDER BY RANDOM() LIMIT ?",
                (vgmplay_row[0], limit)).fetchall()
        except sqlite3.Error as error:
            log(f"UMSA database get_random_vgm_batch: read failed: {error}",
                level='warning')
            return []
        finally:
            if dbc is not None:
                dbc.close()
            db_conn.close()

        return [{'name': row[0], 'gamename': row[1]} for row in rows]

    def get_set_ids_for_software(self, software_id):
        """Return all set ids for given software id"""

        return self._get_game_repository().get_set_ids_for_software(software_id)

    def get_series(self, software_id):
        """Return all software from a series based on a software id

        TODO software can belong to more than one series
        """

        return self._get_game_repository().get_series(software_id)

    def check_series(self, software_id):
        """Return count of series entries based on software id"""

        return self._get_game_repository().check_series(software_id)

    def check_compilation(self, software_id):
        """Return if software is connected to a compilation

        2 = Software is on a compilation
        1 = Software is a compilation
        0 = No connection found
        """

        return self._get_game_repository().check_compilation(software_id)

    def make_time_nice(self, timestamp, now=None):
        """Return hours and minutes as 1 string.

        Parameters: timestamp
        Optional: now = now-(Y-m-d H:M)
        """
        from .game_labels import make_time_nice as _make_time_nice

        return _make_time_nice(timestamp, now=now)

    def get_status_for_set(self, set_id):
        """Return play status for a set id"""

        i = self._get_status_repository().get_status_for_set(set_id)
        if not i:
            return None

        time_played = self.make_time_nice(i[2])

        status = {
            'last_played': i[1],
            'time_played': time_played,
            'time_played2': i[2],
            'play_count': i[3],
            'options': i[4],
            'last_nice': self.make_time_nice(i[1], now=True),
        }
        return status

    def get_further_media(self, set_id):
        """Return MARP and Youtube entries for a set"""

        return self._get_status_repository().get_further_media(set_id)

    def save_further_media(self, set_id, marp=None, youtube=None):
        """Save MARP or Youtube entries for a set"""

        self._get_status_repository().save_further_media(
            set_id, marp=marp, youtube=youtube
        )

    def get_emulators(self, source=None, swl_name=None):
        """Returns emulators based on source or swl_name"""

        return self._get_emulator_repository().get_emulators(
            source=source, swl_name=swl_name
        )

    def get_emulator(self, emu_id=None, emu_conn_id=None):
        """Return information about saved emulator"""

        return self._get_emulator_repository().get_emulator(
            emu_id=emu_id, emu_conn_id=emu_conn_id
        )

    def save_emulator(self, emu_info, reconfigure, source=None, swl_name=None):
        """Save emulator to database and connect if needed."""

        return self._get_emulator_repository().save_emulator(
            emu_info, reconfigure, source=source, swl_name=swl_name
        )

    def connect_emulator(self, emu_id, source=None, swl_name=None):
        """Connect emulator to source or softwarelist"""

        return self._get_emulator_repository().connect_emulator(
            emu_id, source=source, swl_name=swl_name
        )

    def delete_emulator_connection(self, emu_conn_id):
        """Delete emulator connection to softwarelist or source

        Return emulator id it not used anymore
        """

        return self._get_emulator_repository().delete_emulator_connection(
            emu_conn_id
        )

    def delete_emulator(self, emu_id):
        """Delete emulator and all connections"""

        return self._get_emulator_repository().delete_emulator(emu_id)

    def load_lastgames(self):
        """Return the persisted GUI backward-navigation history (oldest first)."""

        return self._get_history_repository().load_lastgames()

    def save_lastgames(self, software_list):
        """Persist the newest 100 GUI history ids (oldest to newest)."""

        self._get_history_repository().save_lastgames(software_list)

    def list_filter_names(self):
        """Return the names of all saved (database-backed) filters."""

        return self._get_history_repository().list_filter_names()

    def load_filter_selections(self, filter_name):
        """Return a saved filter's selections keyed by public category label."""

        return self._get_history_repository().load_filter_selections(filter_name)

    def save_filter_selections(self, filter_name, filter_lists):
        """Atomically replace all persisted selections for ``filter_name``."""

        self._get_history_repository().save_filter_selections(
            filter_name, filter_lists
        )

    def record_screensaver_display(self, set_id, software_id=None):
        """Record one successfully displayed set in ``screensaver_history``.

        One row per distinct set (``set_id``), moved to the newest position on
        every display and pruned past the newest 100 (decision D16);
        ``software_id`` is the context-menu handoff id stored alongside. The
        write only touches the ``status.db`` history table inside one
        savepoint: it never runs the legacy import, never deletes legacy
        files and never commits an unrelated caller transaction.
        """

        self._get_history_repository().record_screensaver_display(
            set_id, software_id
        )

    def get_screensaver_history(self, limit=None):
        """Return the screensaver display history, newest first.

        Each entry carries the persisted ``set_id`` with its ``software_id``
        and ``displayed_at``; a ``set_id`` no longer present in ``umsa.db`` is
        returned as stored, never substituted (decision D16).
        """

        return self._get_history_repository().list_screensaver_history(limit)

    def get_import_marker(self):
        """Return the durable legacy-import marker dict, or ``None``."""

        return self._get_history_repository().get_import_marker()

    def run_legacy_import(self):
        """Run the one-time legacy import via the configured Core paths."""

        return _run_legacy_import(self.sdb, self.db_paths)

    def retry_legacy_import(self):
        """Clear a recorded failure and re-run the legacy import once."""

        return _retry_import(self.sdb, self.db_paths)

    def discover_legacy_paths(self):
        """Return the recognized legacy import paths ``(lastgames, filters)``."""

        return _discover_legacy_paths(self.db_paths)

    def write_status_after_play(self, set_id, played_seconds):
        """Update play status for set id

        Writes played seconds and play count
        """

        self._get_status_repository().write_status_after_play(
            set_id, played_seconds
        )

    def get_latest_by_software(self, software_id):
        """Return id of latest played set for a software id"""

        sets = self.get_set_ids_for_software(software_id)
        return self._get_status_repository().get_latest_by_set_ids(sets)

    def set_filter_enabled(self, flag):
        """Enable or disable the active filter for subsequent queries

        Named mutation API for the public ``use_filter`` state, so callers do
        not have to touch the attribute directly. The state itself stays on
        ``DBMod``.
        """

        self.use_filter = flag

    def set_order(self, order):
        """Set the list ordering for subsequent queries

        Accepts the valid order names ``name``, ``year`` and ``publisher``;
        ``execute_statement`` validates the value against its whitelist and
        falls back to the safe name ordering otherwise. Named mutation API for
        the public ``order`` state, which stays on ``DBMod``.
        """

        self.order = order

    def define_filter(self, filter_lists):
        """define filter

        TODO
        - when list smaller then 50% of all do NOT IN = faster?
        - do we need a special field for all as the lists can grow with updates?
          or show new entries after update!
        - make this count always visible in filter list and keep actual, is in gui:
          simply call this more often (:
        """

        state, display = _define_filter(self.gdb, filter_lists)
        self.filter_join = list(state.filter_join)
        self.filter_where = list(state.filter_where)
        self._filter_where_params = list(state.filter_where_params)
        return display

    def execute_statement(self, set_id=None, software_id=None, prevnext=None):
        """Execute prepared statement with filter settings

        TODO
        - rework var names
        - keep inital count when used with set_id in gui
          so no overwrite with prevnext
        - make number of listmenu entries settings.xml
        - more logic: when swl.name = "gameboy" then no need for swl filter! = faster
        """

        state = GamelistFilter(
            join=self.join,
            where=self.where,
            order=self.order,
            use_filter=self.use_filter,
            filter_join=tuple(self.filter_join),
            filter_where=tuple(self.filter_where),
            where_params=tuple(self._where_params),
            filter_where_params=tuple(self._filter_where_params),
        )
        slist, pos, result_count = _execute_statement(
            self.gdb, state, set_id, software_id, prevnext)
        self.order = state.order
        return slist, pos, result_count

    def get_by_software(self, set_id):
        """Return list of software"""

        self.join, self.where, self._where_params = _software_query()
        return self.execute_statement(set_id)

    def get_software_for_source(self, set_id, source):
        """Return list of software based on MAME source file"""

        self.join, self.where, self._where_params = _source_query(source)
        return self.execute_statement(set_id)

    def get_by_cat(self, cat, set_id):
        """Return list of software based on category"""

        self.join, self.where, self._where_params = _category_query(cat)
        return self.execute_statement(set_id)

    def get_by_year(self, year, set_id):
        """Return list of software based on year"""

        self.join, self.where, self._where_params = _year_query(year)
        return self.execute_statement(set_id)

    def get_by_players(self, players, set_id):
        """Return list of software based on number of players"""

        self.join, self.where, self._where_params = _players_query(players)
        return self.execute_statement(set_id)

    def get_by_maker(self, maker, set_id):
        """Return list of software based on maker"""

        self.join, self.where, self._where_params = _maker_query(self.gdb, maker)
        return self.execute_statement(set_id)

    def get_by_swl(self, swl_name, set_id):
        """Return list of software based on softwarelist"""

        self.join, self.where, self._where_params = _swl_query(swl_name)
        return self.execute_statement(set_id)

    def get_maker(self):
        """Return list of makers"""

        return self._get_game_repository().get_maker()

    def get_swl(self):
        """Return list of softwarelists"""

        return self._get_game_repository().get_swl()

    def get_source(self):
        """Return list of softwarelists"""

        return self._get_game_repository().get_source()

    def get_year(self):
        """Return list of years"""

        return self._get_game_repository().get_year()

    def get_players(self):
        """Return list of players"""

        return self._get_game_repository().get_players()

    def get_categories(self):
        """Return list of categories"""

        return self._get_game_repository().get_categories()

    def get_last_played(self, order):
        """get_last_played"""

        results = []
        software_dict = {}

        # get status for sets
        self.sdbc.execute(
            f"SELECT id, last_played, play_count, time_played FROM sets \
             WHERE time_played > 0 ORDER BY {order} DESC LIMIT 250")
        # get software info for sets from status.db
        for i in self.sdbc.fetchall():
            self.gdbc.execute(
                "SELECT software.id, software.name, year.name as year, maker.name as maker \
                 FROM software \
                    JOIN year ON software.year_id = year.id \
                    JOIN maker ON software.developer_id = maker.id \
                    JOIN sets ON software.id = sets.softwarelink_id \
                 WHERE sets.id = ?", (i['id'],))
            software = self.gdbc.fetchone()
            # put in dict to summarize sets
            if software and software['id'] in software_dict:
                software_dict[software['id']]["play_count"] += i['play_count']
                software_dict[software['id']]["time_played"] += i['time_played']
                software_dict[software['id']]["last_played"] = max(software_dict[software['id']]["last_played"], i['last_played'])
            elif software:
                software_dict[software['id']] = {
                    "time_played": i['time_played'],
                    "last_played": i['last_played'],
                    "play_count": i['play_count'],
                    "name": software['name'],
                    "year": software['year'],
                    "maker": software['maker'],
                }
        # sort dict after value in var order and create list for return
        for software_id, status in sorted(software_dict.items(), key=lambda t: t[1][order], reverse=True):

            time_played = self.make_time_nice(status["time_played"])

            last_nice = self.make_time_nice(status['last_played'], now=True)

            if order == "time_played":
                last = '{}x, {}'.format(
                    status["play_count"],
                    last_nice,
                )
                first = time_played
            elif order == "play_count":
                last = f'{time_played}, {last_nice}'
                first = '{}x'.format(status['play_count'])
            else:
                last = '{}, {}x'.format(
                    time_played,
                    status["play_count"],
                )
                first = last_nice

            name = "{} ({}, {})".format(status['name'], status['year'], status['maker'],)
            results.append({'id': software_id, 'name': name, 'year': first, 'maker': last,})

        return results, 0

    def get_parts_for_set_id(self, set_id):
        """Get parts for a set id

        sets can have more than one media
        like 2 floppies or 1 floppy and 1 hdd or cd-rom
        """

        return self._get_game_repository().get_parts_for_set_id(set_id)

    def get_disks(self, swl_name, set_name):
        """Return disks from a given set and softwarelist"""

        return self._get_game_repository().get_disks(swl_name, set_name)

    def create_cmdline(self, parts, devices, setname):
        """create command line to start a software list item in mame"""
        from .cmdline import create_cmdline as _create_cmdline

        return _create_cmdline(parts, devices, setname)

    # create commandline options for mame
    def get_cmd_line_options(self, set_id, set_name, machine_name, swl_name):
        """Create command line options for MAME emulator run

        Based on id, name of set, and the names of machine and swl.
        """

        # get options for softwarelist
        ## this is manually set coz some swls need special options
        ## like a device in a slot so the machine supports hdds
        repo = self._get_game_repository()
        swlopt = repo.get_swl_options(swl_name)
        # make swl_options a list
        if swlopt[0]:
            swl_options = swlopt[0].strip().split(' ')
        else:
            swl_options = None

        # get id for machine
        machine_id = repo.get_machine_id(machine_name)

        # get devices supported by the machine
        _devices = repo.get_devices_for_machine(machine_id[0])

        # get all parts for the choosen set
        _part = repo.get_parts_for_set_id(set_id)

        # check if we have a requirement in sharedfeat
        _sharedfeat = repo.get_sharedfeat_requirement(set_id)

        # create cmd line
        _cmd_options, first_device = self.create_cmdline(
            list(_part), _devices, set_name
        )

        more_options = []
        if _cmd_options:
            # add additional manual swl options
            if swl_options:
                more_options += swl_options

            # add sharedfeat
            if _sharedfeat:
                # security if definition for sharedfeat_requirement
                # is not swl:set
                if ':' in _sharedfeat[0]:
                    _swl, _set = _sharedfeat[0].split(':')
                else:
                    _set = _sharedfeat[0]
                    _swl = None
                # when definition is ok
                if _swl:
                    # create new cmdline option for requirement
                    log(f"UMSA database: get_cmd_line_options: set {_set}, swl {_swl}", level='debug')
                    _setinfo = self.get_info_by_set_and_swl(_set, _swl)
                    log(f"UMSA database: get_cmd_line_options: setid {_setinfo}", level='debug')
                    _parts2 = repo.get_parts_for_set_id(_setinfo['set_id'])
                    log(f"UMSA database: get_cmd_line_options: parts {_parts2}", level='debug')
                    _cmdopt = self.create_cmdline(list(_parts2), _devices, _set)[0]
                    more_options += _cmdopt
                # else add the requirement set as option
                # directly after machine name
                # hopefully most of the time mame will then
                # find the correct swl entry
                else:
                    more_options += [_set]

            # when we know the devices also set -statename
            cmd_options = [machine_name]+more_options+_cmd_options+[
                '-statename', f'%g/%d_{first_device}', ]

        elif swl_options:
            cmd_options = [machine_name] + swl_options + [set_name]
        else:
            cmd_options = [machine_name, set_name]
        cmd_options.extend(['-snapname', f'{swl_name}/{set_name}/%i'])

        return cmd_options

    def get_all_dbentries(self, cat):
        """Return select parameters based on filter categories.

        Gets a filter category.
        Returns a list of database tables and rows.
        """

        return self._get_game_repository().get_all_dbentries(cat)

    def search_single(self, my_search):
        """search single"""

        return self._get_game_repository().search_single(my_search)

    def get_artwork_by_software_id(self, software_id, artwork, source_roots=None):
        """get artwork by software id

        fetch given artwork type and all machines for a software id.

        Returns a two element list ``[art_path, machines]`` where ``art_path``
        is the fully resolved location of a random matching artwork (empty
        string when none is found) and ``machines`` is a comma separated list
        of machine abbreviations.

        This remains in ``DBMod``: it joins the attached ``art.art_set`` with the
        game tables (``sets``/``swl``) and resolves the resulting path, so it is
        a mixed application query rather than artwork-table CRUD.
        """

        all_machines = []
        self.gdbc.execute(
            "SELECT DISTINCT system_abbr FROM swl, sets \
               WHERE sets.softwarelink_id = ? AND sets.swllink_id = swl.id",
            (software_id,)
        )
        for j in self.gdbc.fetchall():
            all_machines.append(j[0])

        self.gdbc.execute(
            "SELECT sets.name, swl.name as swl_name, \
                   art.source, art.root_key, art.scan_unit, \
                   art.type, art.extension, art.relative_path, \
                   art.archive_member \
             FROM sets, swl, art.art_set art \
             WHERE sets.softwarelink_id = ? \
             AND swl.id = sets.swllink_id \
             AND art.id = sets.id \
             AND art.type = ? \
             ORDER BY RANDOM() LIMIT 1",
            (software_id, artwork)
        )
        snap_info = self.gdbc.fetchone()

        art_path = ''
        if snap_info:
            art = dict(snap_info)
            art_path = resolve_artwork_path(art, art, source_roots or {})

        return [art_path, ', '.join(all_machines)]

    def get_searchresults(self, my_search):
        """get search results

        TODO:
        - single word search: split by " ": v.gamename IN ('test', 'wrum')

             - remove s.name, problem with showing gamename when s.name is selected
             - use filters or present option to use filters

        LATER - show button for next/prev page
              - save last 10 search terms and make as a popup for search button incl new search
        """

        return self._get_game_repository().get_searchresults(my_search)

    def get_machine_name(self, machine_id):
        """Get name of machine from id"""

        return self._get_game_repository().get_machine_name(machine_id)

    def count_source(self, source):
        """Count all source files in MAME"""

        return self._get_game_repository().count_source(source)

    def count_machines_for_swl(self, swl_name):
        """Count all machines for 1 software list"""

        return self._get_game_repository().count_machines_for_swl(swl_name)

    def get_machines(self, swl_name, machine=None):
        "Get original and compatible machines for 1 software list"

        return self._get_game_repository().get_machines(swl_name, machine)

    def get_set_name(self, set_id):
        """Returns set name from set id

        TODO: Only used by run_emulator, diff_emu: search for rom file in filesystem
        """

        return self._get_game_repository().get_set_name(set_id)

    def get_best_machine_for_set(self, swl_name, detail, swl_machine_id):
        """Determine which machine to take for MAME emulation

        TODO
        - rework: no more list, use dict from get_machines !!!
        - but machine_id into return
        """

        # get originals, compatible machines
        machines = self.get_machines(swl_name)[0]

        # no machine found
        if len(machines) == 0:
            return None
        # only 1 machine
        if len(machines) == 1:
            return machines[0]
        # only 1 original
        if (machines[0]['status'] == "original" and
                machines[1]['status'] == "compatible"
           ):
            return machines[0]

        best_machine = None
        # check if swl_machine is in machines
        for machine in machines:
            if machine['id'] == swl_machine_id:
                best_machine = machine

        # no hit until now, set first machine
        if not best_machine:
            best_machine = machines[0]
        # exception for famicom_flop
        # TODO famicom should be disconnected in mame source
        if swl_name == "famicom_flop":
            best_machine = machines[1]

        # get country from detail
        for country_sorted in sorted(COUNTRIES.keys()):
            for country in COUNTRIES[country_sorted]:
                if country in detail.lower():
                    # check gamename of machines for country from detail
                    # first try actual best
                    for country2 in COUNTRIES[country_sorted]:
                        if country2 in best_machine['fullname'].lower():
                            return best_machine
                    # now check all machines
                    for machine in machines:
                        for country2 in COUNTRIES[country_sorted]:
                            if country2 in machine['fullname'].lower():
                                best_machine = machine
                                return best_machine
        return best_machine

    def get_all_for_software(self, software_id):
        """get all infos for software

        get all sets nicely sorted (last played, prefered history, year)
        includes a best machine to use for swl set

        all_sets.append is used instead of .extend
        so we have all_sets[software_with_same_name][sets] = {infos}
        and not all_sets[[software1],[software2]]

        TODO:
        - better document this function
        - have lists for each software with same name order by year
          connect at the end and add flag so gui can mark the other software with the same name
          also make search for software with same name a setting
        - include preferred country (select it or make it first in list?)
        - maybe dont order select by year, done later,
          order by name so usa, jap... are sorted correct
        """

        time1 = time.time()

        pos_machine = 0
        pos_set = 0
        all_sets = []

        # every umsa.db read below goes through the game repository; this
        # method only composes their results with the status/dat/artwork data
        repo = self._get_game_repository()

        # get all sets for software id
        all_sets.append(repo.get_sets_for_software(software_id))

        # check if we have other software by this name
        # get software name
        software_name = repo.get_software_name(software_id)
        # get all software ids for software name
        for other_id in repo.get_software_ids_for_name(software_name):
            if software_id == other_id:  # is the original
                continue
            all_sets.append(repo.get_sets_for_software(other_id))

        diff_machines = {}
        set_ids = []
        count = 1
        for diff_software in all_sets:
            for machine in diff_software:

                set_ids.append(str(machine['id']))
                resulting_machine = ''
                # TODO get status in one select like art and dat
                # get last_played
                last_played = self.get_status_for_set(machine['id'])

                if machine['system_id'] == 270257: # mame
                    # resulting_machine is the parent
                    if machine['cloneof_id']:
                        resulting_machine = machine['cloneof_id']
                    else:
                        resulting_machine = machine['id']
                    # resulting_machine = machine['category'] use category
                    best_machine = None
                    machine_name = 'mame'
                    if machine['category_flag']: # ismachine
                        machine_label = machine['category']
                    else:
                        # TODO handhelds are not arcade, but a game not a machine
                        machine_label = 'Arcade'
                else: # swl
                    # diff machine is swl machine
                    # TODO: to test used machine name from swl
                    resulting_machine = str(machine['system_id'])
                    # get best machine
                    best_machine = self.get_best_machine_for_set(
                        machine['swl'], machine['detail'], machine['system_id'])
                    if best_machine:
                        machine_name = best_machine['setname']
                        machine_label = best_machine['label2']
                    else:
                        machine_name, machine_label = repo.get_machine_name(
                            machine['system_id'])

                # create key in diff_machines
                if resulting_machine not in diff_machines:
                    diff_machines[resulting_machine] = {
                        'id'      : count,
                        'year'    : machine['year'],
                        'setlist' : []
                    }
                    count += 1
                # remember earliest year for later sort
                else:
                    diff_machines[resulting_machine]['year'] = min(diff_machines[resulting_machine]['year'], machine['year'])

                # TODO: what is really needed?
                #  swl machine is not needed?
                #  make last_played 3 entries here?
                diff_machines[resulting_machine]['setlist'].append({
                    'id': machine['id'],
                    'name': machine['name'],
                    'gamename': machine['gamename'],
                    'detail': machine['detail'],
                    'source': machine['source'],
                    'year': machine['year'],
                    'publisher': machine['maker'],
                    'swl_name': machine['swl'],
                    'swl_machine_id': machine['system_id'],
                    'machine_name': machine_name,
                    'machine_label': machine_label,
                    'display_type': machine['display_type'],
                    'display_rotation': machine['display_rotation'],
                    'category': machine['category'],
                    'nplayers': machine['nplayers'],
                    'clone': machine['cloneof_id'],
                    'is_machine': machine['category_flag'],
                    'last_played': last_played,
                })

        # create list to return
        return_list = []
        # sort by year
        for i in sorted(diff_machines.items(), key=lambda t: t[1]['year']):
            return_list.append(i[1]['setlist'])
        # get absolut latest played
        # TODO search for pref. country when not last played
        latest_set_id = self.get_latest_by_software(software_id)
        # find latest in return_list
        if latest_set_id:
            count1 = 0
            for i in return_list:
                count2 = 0
                for j in i:
                    if j['id'] == latest_set_id:
                        pos_machine = count1
                        pos_set = count2
                        break
                    count2 += 1
                count1 += 1
        all_dat = self.get_dat_for_sets(set_ids)
        all_art = self.get_artwork_for_sets(set_ids)
        time2 = time.time()
        log(f"UMSA database: get_all_for_software: time = {(time2-time1)*1000.0:.0f}ms", level='debug')

        return return_list, pos_machine, pos_set, all_dat, all_art

    def get_info_by_set_and_swl(self, setname, swlname):
        """get info by set and swl"""

        return self._get_game_repository().get_info_by_set_and_swl(setname, swlname)

    def get_set_info_by_id(self, set_id):
        """get info by set id"""

        return self._get_game_repository().get_set_info_by_id(set_id)
