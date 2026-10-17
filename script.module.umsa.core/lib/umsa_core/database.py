"""Module for umsa.info sqlite3 database.

Artwork table access is centralised in :mod:`umsa_core.artwork_repository` and
DAT table access in :mod:`umsa_core.dat_repository`; DAT parsing lives in
:mod:`umsa_core.dat_parser` and the DAT scan workflow in
:mod:`umsa_core.dat_scanner`. ``DBMod`` remains the public facade.

A few direct statements intentionally remain here:

- ``open_db()``, ``add_dat_to_db()`` and ``add_art_to_db()`` copy rows between
  the per-source databases (``dat.db``/``artwork.db``) and ``umsa.db`` through
  ``ATTACH DATABASE``. That cross-database synchronisation owns multiple
  connections and attached databases, so it stays in ``DBMod`` (see the
  repository contracts).
- ``get_random_art()`` and ``get_artwork_by_software_id()`` join ``art_set``
  with the general UMSA game tables (``sets``/``swl``/``software``) and, for
  ``get_random_art()``, depend on the active ``DBMod`` filter state. These are
  mixed application queries rather than artwork-table CRUD and are left here
  on purpose.

TODO
 - remove usage of detail, use split_gamename
"""

import os
import sqlite3  # connect, Row, OperationalError
import threading
import time
import zipfile
from contextlib import contextmanager
from io import BytesIO
from re import findall, search
from urllib.request import urlopen

from .artwork import resolve_artwork_path
from .artwork_repository import ArtworkRepository, create_artwork_tables
from .artwork_scanner import ArtworkScanner
from .data_paths import CoreDataPaths
from .dat_repository import DatRepository, create_dat_tables
from .dat_scanner import DatScanner
from .game_repository import GameRepository
from .gb64_scanner import GB64Scanner
from .logging import log
from .scan_coordinator import ScanBusyError, ScanLockContext, scan_coordinator
from .sqlite import connect_sqlite

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
        item = {'id': str(entry[0]), 'name': entry[1], 'count': entry[2]}
        (active if item['id'] in active_ids else inactive).append(item)
    return {'active': active, 'inactive': inactive}


def download_and_update_umsa_db(data_dir, progress, title='Updating UMSA database'):
    """Download and extract the UMSA database archive into ``data_dir``.

    ``progress`` is called as ``progress(percent, title, message)``; ``message``
    is ``None`` for the plain percentage updates during download.
    """

    data_dir.mkdir(parents=True, exist_ok=True)

    db_zip = bytearray()
    url = urlopen("http://umsa.info/umsa_db.zip", timeout=20)
    # float with *1.0 for percentage
    db_zip_size = int(url.info()['Content-Length']) * 1.0
    while len(db_zip) < db_zip_size:
        db_zip.extend(url.read(102400))
        progress(int((len(db_zip) / db_zip_size) * 80), title, None)

    progress(80, title, 'unzip file...')
    zipfile.ZipFile(BytesIO(db_zip)).extractall(data_dir)


@contextmanager
def _scan_state_ownership(db, start_what):
    """Own ``db``'s shared scan status/progress fields for one scan.

    ``scan_perc``/``scan_what``/``scan_status`` describe the single active scan,
    so the process-wide scan lock is taken *before* any of them is touched. The
    context yields ``True`` once the lock is owned; only then does it initialise
    the fields and clear ``scan_status`` again on exit. When another scan already
    owns the lock the context yields ``False`` and never touches the fields, so a
    competing invocation can neither overwrite the active scan's progress nor
    clear (and thereby cancel) its status.

    The lock is re-entrant per thread, so the lock-aware scan methods called
    from inside the block re-acquire it harmlessly.
    """

    lock_ctx = ScanLockContext(scan_coordinator)
    try:
        lock_ctx.__enter__()
    except ScanBusyError:
        yield False
        return

    try:
        db.scan_perc = 0
        db.scan_what = start_what
        db.scan_status = True
        try:
            yield True
        finally:
            db.scan_status = False
    finally:
        lock_ctx.__exit__(None, None, None)


def run_scan_with_progress(db, scan_method, scan_args, progress, title, sleep):
    """Run a DBMod scan method in a thread while reporting progress.

    ``sleep`` is invoked as ``sleep(1000)`` for each poll (the GUI passes
    ``xbmc.sleep``). ``progress`` is called as ``progress(percent, title,
    message)``.

    The worker takes the shared scan lock *before* it initialises
    ``scan_perc``/``scan_what``/``scan_status``, so only the invocation that
    genuinely owns the scan may set them. A competing invocation that cannot
    take the lock calls the scan method anyway - the lock-aware methods return
    their ``busy`` summary without touching the shared fields - and returns that
    result without resetting the active scan's progress or cancellation signal.

    Returns the scan method's return value (for example the scanner summary
    dictionary), or ``None`` when the worker failed. Existing callers that
    ignore the result are unaffected.
    """

    scan_func = getattr(db, scan_method)

    result = {}
    finished = threading.Event()

    def worker():
        try:
            # Only the owner of the shared scan lock initialises/clears the
            # progress and status fields; a rejected invocation leaves them
            # exactly as the active scan left them.
            with _scan_state_ownership(db, ''):
                result['value'] = scan_func(*scan_args)
        except Exception as exc:  # noqa: BLE001 - a scan must never stay stuck
            log(f"UMSA scan: '{scan_method}' worker failed: {exc}",
                level='error')
        finally:
            finished.set()

    scan_thread = threading.Thread(target=worker)
    scan_thread.start()
    try:
        # The completion event (not ``db.scan_status``) stops the loop, so a
        # rejected scan returns immediately even while the active scan keeps
        # its own ``scan_status`` set.
        while not finished.is_set():
            sleep(1000)
            if finished.is_set():
                break
            progress(db.scan_perc, title, f'scanning {db.scan_what}')
    finally:
        scan_thread.join()
    progress(100, title, 'saving')
    return result.get('value')

# new db for pics
# listdir recursive for progettosnaps
# get set and swl from path
# write into db: path, swl_id and set_id
# select all -> for each set id check pics and attach

# new db for dats
# scan dats, put text into db with p_id
# second table with p_id and swl_id, set_id
# as one dat entry can have more than one set
# select all > for each set check dat, when finished, split dat entries

# dict for best machine
COUNTRIES = {
    '1NTSC' : ('ntsc',),
    '2PAL'  : ('pal',),
    '3US'   : ('usa', 'america', 'nintendo entertainment system /', 'world'),
    '4JP'   : ('jpn', 'japan', 'famicom'),
    '5EU'   : ('euro',),
    '6EU'   : ('euro', 'pal'),
    '7KR'   : ('kor',),
    '8BR'   : ('bra',),
    #'uk', 'ger', 'fra', 'spa', 'ita', 'ned', 'aus'],
}

def split_gamename(complete_name):
    """Split the complete name of a MAME description into the name and details plus version.

    Return: gamename, detail
    """

    gamename, detail, details = '', '', []
    # dont be greedy, exlucde ( from detail
    for name, detail in findall(r'(.*?) (\([^(]*?\))', complete_name):
        gamename += name.strip()
        details.append(detail[1:-1]) # remove ()
    detail = ', '.join(details)
    # check as above does not match when () is missing
    if not gamename:
        gamename = complete_name

    # TODO rework finding version in gamename
    # might need version finding without v or V
    # find versions like 1.1 at the end of gamename
    version = search(r'([vV]\d+\.\d+)', gamename)
    if version:
        if not detail:
            detail = version.group()
        else:
            detail = f'{version.group()} {detail}'

    return gamename, detail

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

        # connect to umsa db
        self.db_paths = _core_data_paths(db_path)
        self.gdb = connect_sqlite(self.db_paths.umsa_db)
        self.gdb.row_factory = sqlite3.Row
        self.gdbc = self.gdb.cursor()

        # sanity
        self.create_dat_tables(self.gdbc)
        self.create_art_tables(self.gdbc)
        self.gdb.commit()

        # connect to status db
        self.sdb = connect_sqlite(self.db_paths.status_db)
        self.sdb.row_factory = sqlite3.Row
        self.sdbc = self.sdb.cursor()

        # defines filter with self.filter_tables, self.filter_where
        self.define_filter(filter_lists)

        # create db layout (first run)
        self.sdbc.execute(
            # last_playes = YYYY-MM-DD HH:MM
            # time_played = seconds
            """
            CREATE TABLE IF NOT EXISTS sets(
                id             INT PRIMARY KEY NOT NULL,
                last_played    DATETIME,
                time_played    BIGINT DEFAULT 0,
                play_count     INT DEFAULT 0,
                options        TEXT,
                emu_id         INT,
                marp           TEXT,
                youtube        TEXT
            )
            """
        )
        self.sdbc.execute(
            """
            CREATE TABLE IF NOT EXISTS emu(
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      VARCHAR(100) NOT NULL,
                exe       VARCHAR(100) NOT NULL,
                dir       VARCHAR(200) NOT NULL,
                zip       INT NOT NULL,
                mode      INT NOT NULL
            )
            """
        )
        self.sdbc.execute(
            """
            CREATE TABLE IF NOT EXISTS emu_conn(
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                emu_id    INT NOT NULL,
                swl       VARCHAR(50),
                source    VARCHAR(100)
            )
            """
        )
        self.sdb.commit()

    def open_db(self, db_path):
        """Reopen umsa database, needed after update of umsa.db

        Reconnect and import support and artwork databases. The persistent
        status.db connection is left untouched. Any previous umsa.db
        connection is closed first so it can never be silently overwritten.
        """

        # Never replace an active umsa.db connection without closing it first.
        self.close_umsa_db()

        # connect to umsa db
        self.db_paths = _core_data_paths(db_path)
        gdb = connect_sqlite(self.db_paths.umsa_db)
        gdb.row_factory = sqlite3.Row
        gdbc = gdb.cursor()
        self.gdb = gdb
        self.gdbc = gdbc

        attached = set()
        failed = False
        try:
            # creat additonal tables
            self.create_dat_tables(gdbc)
            self.create_art_tables(gdbc)
            gdb.commit()

            # make sure the attached dat.db carries the current schema too
            self._upgrade_dat_db(self.db_paths)

            # copy dat, art over via attach
            gdbc.execute(
                "ATTACH DATABASE ? AS dat", (os.fspath(self.db_paths.dat_db),)
            )
            attached.add('dat')
            gdbc.execute(
                "ATTACH DATABASE ? AS art", (os.fspath(self.db_paths.artwork_db),)
            )
            attached.add('art')
            # Replace the DAT data atomically: the delete and the copy live in
            # one transaction, so a failed copy never leaves the target empty.
            gdbc.execute("DELETE FROM main.dat_set")
            gdbc.execute("DELETE FROM main.dat")
            gdbc.execute(
                "INSERT INTO main.dat (id, file, entry, origin) "
                "SELECT id, file, entry, origin FROM dat.dat"
            )
            gdbc.execute(
                "INSERT INTO main.dat_set (id, dat_id) "
                "SELECT id, dat_id FROM dat.dat_set"
            )
            gdbc.execute("INSERT INTO main.art_set SELECT art_id,id,source,root_key,scan_unit,type,extension,relative_path,archive_member FROM art.art_set")
            gdb.commit()
        except Exception:
            failed = True
            # Undo any pending write; the original exception is re-raised.
            try:
                gdb.rollback()
            except Exception:
                pass
            raise
        finally:
            # Drop every database that was attached, even on the error path,
            # so the connection is never left with unexpected attachments. A
            # failed DETACH must not mask the original exception.
            for alias in ('art', 'dat'):
                if alias in attached:
                    try:
                        gdbc.execute("DETACH DATABASE '{}'".format(alias))
                    except Exception:
                        pass
            if failed:
                # Do not keep a half-copied connection around; leave a known,
                # recoverable state that lets the caller retry open_db().
                self.close_umsa_db()

    def create_dat_tables(self, db_cursor):
        """create dat tables

        Delegates to the authoritative DAT schema definition in the DAT
        repository. The signature is preserved for compatibility with existing
        callers; the helper also upgrades old databases in place by adding and
        backfilling the ``origin`` column.
        """

        create_dat_tables(db_cursor)

    def _upgrade_dat_db(self, db_paths):
        """Ensure the local ``dat.db`` carries the current DAT schema.

        ``open_db()``/``add_dat_to_db()`` read ``origin`` from the attached
        ``dat.db``; older databases lack that column, so it is upgraded (and
        backfilled) before the copy.
        """

        dat_conn = connect_sqlite(db_paths.dat_db)
        try:
            cursor = dat_conn.cursor()
            try:
                create_dat_tables(cursor)
            finally:
                cursor.close()
            dat_conn.commit()
        finally:
            dat_conn.close()

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
        connection they closed.
        """

        gdbc = getattr(self, 'gdbc', None)
        if gdbc is not None:
            try:
                gdbc.close()
            except Exception:
                pass
        gdb = getattr(self, 'gdb', None)
        if gdb is not None:
            try:
                gdb.close()
            except Exception:
                pass

    def close(self):
        """Close every persistent database connection owned by DBMod.

        Safe to call more than once and even if __init__ failed before both
        connections were opened.
        """

        self.close_umsa_db()

        sdbc = getattr(self, 'sdbc', None)
        if sdbc is not None:
            try:
                sdbc.close()
            except Exception:
                pass
        sdb = getattr(self, 'sdb', None)
        if sdb is not None:
            try:
                sdb.close()
            except Exception:
                pass

    def close_db(self):
        """Compatibility wrapper: close only the umsa.db connection.

        Historically ``close_db`` closed only ``umsa.db`` and left
        ``status.db`` open (the database-update sequence relies on that, then
        calls :meth:`open_db` again). Use :meth:`close` for a full shutdown.
        """

        self.close_umsa_db()

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

    def add_dat_to_db(self, db_path):
        """add dat to database"""

        db_paths = _core_data_paths(db_path)
        # The attached dat.db must carry the current schema (including the
        # origin column) before it is read below.
        self._upgrade_dat_db(db_paths)
        gdb = connect_sqlite(db_paths.umsa_db)
        gdbc = gdb.cursor()
        attached = False
        try:
            # creat additonal tables
            self.create_dat_tables(gdbc)
            # attach dat db and copy
            gdbc.execute("ATTACH DATABASE ? AS dat", (os.fspath(db_paths.dat_db),))
            attached = True
            # Replace the DAT data atomically: the delete and the copy live in
            # one transaction, so a failed copy never leaves the target empty
            # or partially updated.
            gdbc.execute("DELETE FROM main.dat_set")
            gdbc.execute("DELETE FROM main.dat")
            gdbc.execute(
                "INSERT INTO main.dat (id, file, entry, origin) "
                "SELECT id, file, entry, origin FROM dat.dat"
            )
            gdbc.execute(
                "INSERT INTO main.dat_set (id, dat_id) "
                "SELECT id, dat_id FROM dat.dat_set"
            )
            gdb.commit()
        except Exception:
            # Undo any pending write; the original exception is re-raised.
            try:
                gdb.rollback()
            except Exception:
                pass
            raise
        finally:
            # Detaching after the copy keeps SQLite from committing an
            # attached database implicitly on close.
            if attached:
                try:
                    gdbc.execute("DETACH DATABASE 'dat'")
                except Exception:
                    pass
            gdb.close()

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
        replaced. It never owns or closes ``self.gdb``.
        """

        return ArtworkRepository(self.gdb)

    def _get_dat_repository(self):
        """Return a DAT repository bound to the current umsa.db connection.

        Created per call (never cached) so it can never hold a reference to a
        connection that ``open_db()`` has since replaced. It never owns or
        closes ``self.gdb``.
        """

        return DatRepository(self.gdb)

    def _get_game_repository(self):
        """Return a game repository bound to the current umsa.db connection.

        Created per call (never cached) so it can never hold a reference to a
        connection that ``open_db()`` has since replaced. It never owns or
        closes ``self.gdb``.
        """

        return GameRepository(self.gdb)

    def add_art_to_db(self, db_path):
        """add artwork to database

        can be threaded
        """

        # own connect to umsa.db
        db_paths = _core_data_paths(db_path)
        gdb = connect_sqlite(db_paths.umsa_db)
        gdbc = gdb.cursor()
        attached = False
        try:
            # sanity: create additonal tables
            self.create_art_tables(gdbc)
            # attach and copy over
            gdbc.execute(
                "ATTACH DATABASE ? AS art", (os.fspath(db_paths.artwork_db),)
            )
            attached = True
            # Replace the artwork data atomically: the delete and the copy live
            # in one transaction, so a failed copy never leaves umsa.db empty
            # or partially updated.
            gdbc.execute("DELETE FROM main.art_set")
            gdbc.execute("INSERT INTO main.art_set SELECT art_id,id,source,root_key,scan_unit,type,extension,relative_path,archive_member FROM art.art_set")
            gdb.commit()
            gdbc.execute("SELECT COUNT(*) FROM art_set")
            count = gdbc.fetchone()[0]
            log(f"UMSA artwork: copied {count} records into umsa.db")
        except Exception:
            # Undo any pending write; the original exception is re-raised.
            try:
                gdb.rollback()
            except Exception:
                pass
            raise
        finally:
            # Detaching after the copy keeps SQLite from committing an
            # attached database implicitly on close.
            if attached:
                try:
                    gdbc.execute("DETACH DATABASE 'art'")
                except Exception:
                    pass
            gdb.close()

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
        if self.filter_join and self.filter_where:
            where = "WHERE sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                " ".join(self.filter_join), " AND ".join(self.filter_where)
            )

        select_statement = f"SELECT DISTINCT software.id \
                            FROM sets JOIN software ON software.id = sets.softwarelink_id \
                            {where} ORDER BY RANDOM() LIMIT 1"
        self.gdbc.execute(select_statement)
        return self.gdbc.fetchone()[0]

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

        Artwork locations live in the ``art_set`` schema: every row carries
        ``source``, ``root_key``, ``relative_path`` and ``archive_member``.
        Callers resolve them with
        :func:`umsa_core.artwork.resolve_artwork_path`; the additional left
        image is resolved here for the screensaver.

        The random artwork selection intentionally stays in ``DBMod``: it
        joins ``art_set`` with ``sets`` and applies the active
        ``filter_join``/``filter_where`` state, so it is a mixed application
        query rather than artwork-table CRUD. The isolated left-image lookup
        is delegated to :class:`ArtworkRepository`.
        """

        art_columns = (
            "sets.id, art_set.source, art_set.root_key, art_set.scan_unit, "
            "art_set.type, art_set.extension, art_set.relative_path, "
            "art_set.archive_member"
        )
        types_in = "'" + "','".join(art_types) + "'"

        rand_art = None
        end_result = {}

        # get with filter if on
        if self.use_filter:
            # TODO doesnt work when filter = everything but filter = on
            statement = "SELECT {} FROM art_set JOIN sets ON sets.id = art_set.id {} \
                         WHERE art_set.type IN ({}) AND {} \
                         ORDER BY RANDOM() LIMIT 1".format(
                             art_columns,
                             " ".join(self.filter_join),
                             types_in,
                             " AND ".join(self.filter_where))
            self.gdbc.execute(statement)
            rand_art = self.gdbc.fetchone()
        # and without filter if we haven't found anything
        if not rand_art:
            statement = "SELECT {} FROM art_set JOIN sets ON sets.id = art_set.id \
                        WHERE art_set.type IN ({}) \
                        ORDER BY RANDOM() LIMIT 1".format(art_columns, types_in)
            self.gdbc.execute(statement)
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

    def get_random_vgm(self, db_path):
        """Return random vgm entry from sets."""

        # connect to db
        db_paths = _core_data_paths(db_path)
        db_conn = connect_sqlite(db_paths.umsa_db)
        try:
            dbc = db_conn.cursor()

            dbc.execute("SELECT id FROM swl WHERE name = 'vgmplay'")
            vgmplay_swl_id = dbc.fetchone()[0]

            dbc.execute("SELECT name, gamename FROM sets \
                WHERE swllink_id = ? ORDER BY RANDOM() LIMIT 1", (vgmplay_swl_id,))
            random_vgm = dbc.fetchone()
        finally:
            db_conn.close()

        return {'name': random_vgm[0], 'gamename': random_vgm[1]}

    def get_set_ids_for_software(self, software_id):
        """Return all set ids for given software id"""

        return self._get_game_repository().get_set_ids_for_software(software_id)

    def get_status_for_software(self, software_id):
        """Return play status for given software id"""

        # call umsa.db for sets
        sets = self.get_set_ids_for_software(software_id)
        # get count of play_count and time_played from status.db
        select_statement = "SELECT COUNT(play_count), COUNT(time_played) \
                            FROM sets WHERE id IN ({})".format(','.join(['?'] * len(sets)))
        self.sdbc.execute(select_statement, sets)

        status = self.sdbc.fetchone()
        log(f"UMSA database get_status_for_software: result = {status}", level='debug')
        return status

    def get_series(self, software_id):
        """Return all software from a series based on a software id

        TODO software can belong to more than one series
        """

        # check if software has a series attached
        self.gdbc.execute(
            "SELECT series_id \
             FROM series_seq WHERE software_id = ?", (software_id,)
        )
        series_ids = self.gdbc.fetchall()
        if not series_ids:
            return None

        # get all entries for the series
        all_series = []
        self.gdbc.execute(
            "SELECT software_id \
             FROM series_seq, software, year \
             WHERE series_id = ? AND software_id = software.id \
             AND software.year_id = year.id \
             ORDER BY seqno, year.name", (series_ids[0]['series_id'],) # simply use first series
        )
        for i in self.gdbc.fetchall():
            self.gdbc.execute(
                "SELECT DISTINCT s.id, s.name, y.name as year, m.name as maker \
                 FROM software s, sets v, \
                      year y, maker m \
                 WHERE s.id = v.softwarelink_id AND y.id = s.year_id \
                       AND m.id = s.developer_id AND s.id = ?", (i[0],)
            )
            all_series.append(self.gdbc.fetchone())
        return all_series

    def check_series(self, software_id):
        """Return count of series entries based on software id"""

        # first check if series exists
        self.gdbc.execute(
            "SELECT series_id \
             FROM series_seq WHERE software_id = ?", (software_id, )
        )
        series_exists = self.gdbc.fetchone()
        # now count
        if series_exists:
            self.gdbc.execute(
                "SELECT COUNT(series_id) \
                 FROM series_seq WHERE series_id = ?", (series_exists['series_id'],)
            )
            return self.gdbc.fetchone()[0]
        return None

    def check_compilation(self, software_id):
        """Return if software is connected to a compilation

        2 = Software is on a compilation
        1 = Software is a compilation
        0 = No connection found
        """

        self.gdbc.execute(
            "SELECT software.id FROM software \
                JOIN compilations ON compilations.software_id = software.id \
             WHERE software.id = ?", (software_id,))
        if self.gdbc.fetchone():
            return 1

        self.gdbc.execute(
            "SELECT software.id FROM software \
                JOIN compilations ON compilations.compilation_id = software.id \
             WHERE software.id = ?", (software_id,))
        if self.gdbc.fetchone():
            return 2

        return 0

    def make_time_nice(self, timestamp, now=None):
        """Return hours and minutes as 1 string.

        Parameters: timestamp
        Optional: now = now-(Y-m-d H:M)
        """

        if not timestamp:
            return ""
        if now:
            minute = divmod(
                int(time.time() - time.mktime(time.strptime(timestamp, "%Y-%m-%d %H:%M"))), 60
            )[0]
        else:
            minute = divmod(int(timestamp), 60)[0]
        hour, minute = divmod(minute, 60)
        day, hour = divmod(hour, 24)
        year, day = divmod(day, 365)
        if year > 0 and day > 0:
            last_nice = "%dy %dd" % (year, day)
        elif day > 0:
            last_nice = "%dd" % (day)
        elif hour == 0:
            last_nice = "%dm" % (minute)
        else:
            last_nice = "%d:%02dh" % (hour, minute)
        return last_nice

    def get_status_for_set(self, set_id):
        """Return play status for a set id"""

        self.sdbc.execute(
            "SELECT * FROM sets WHERE ID = ?", (set_id,)
        )
        i = self.sdbc.fetchone()
        if not i:
            return None

        minute = divmod(i[2], 60)[0]
        hour, minute = divmod(minute, 60)
        time_played = "%d:%02d" % (hour, minute)

        status = {
            'last_played'   : i[1],
            'time_played'   : time_played,
            'time_played2'  : i[2],
            'play_count'    : i[3],
            'options'       : i[4],
            'last_nice'     : self.make_time_nice(i[1], now=True),
        }
        return status

    def get_further_media(self, set_id):
        """Return MARP and Youtube entries for a set"""

        self.sdbc.execute("SELECT marp, youtube FROM sets WHERE sets.id = ?", (set_id,))
        return self.sdbc.fetchone()

    def save_further_media(self, set_id, marp=None, youtube=None):
        """Save MARP or Youtube entries for a set"""

        # check set_id
        self.sdbc.execute("SELECT sets.id FROM sets WHERE id = ?", (set_id,))
        if self.sdbc.fetchone():
            # update
            if marp:
                self.sdbc.execute("UPDATE sets SET marp = ? WHERE id = ?", (marp, set_id))
            if youtube:
                self.sdbc.execute("UPDATE sets SET youtube = ? WHERE id = ?", (youtube, set_id))
        else:
            # insert
            if marp:
                self.sdbc.execute("INSERT INTO sets (id, marp) VALUES(?,?)", (set_id, marp))
            if youtube:
                self.sdbc.execute("INSERT INTO sets (id, youtube) VALUES(?,?)", (set_id, youtube))
        self.sdb.commit()

    def get_emulators(self, source=None, swl_name=None):
        """Returns emulators based on source or swl_name"""

        if source:
            self.sdbc.execute(
                "SELECT emu.id, emu.name, emu.exe, emu.dir, emu.zip, emu.mode, \
                        emu_conn.id as emu_conn_id \
                 FROM emu JOIN emu_conn ON emu.id = emu_conn.emu_id \
                 WHERE emu_conn.source = ? ORDER BY emu.name", (source,))
        elif swl_name:
            self.sdbc.execute(
                "SELECT emu.id, emu.name, emu.exe, emu.dir, emu.zip, emu.mode, \
                        emu_conn.id as emu_conn_id \
                 FROM emu JOIN emu_conn ON emu.id = emu_conn.emu_id \
                 WHERE emu_conn.swl = ? ORDER BY emu.name", (swl_name,))
        else:
            self.sdbc.execute("SELECT id, name, exe, dir, zip, mode FROM emu ORDER BY name")
        rows = self.sdbc.fetchall()
        return [dict(row) for row in rows] if rows else []

    def get_emulator(self, emu_id=None, emu_conn_id=None):
        """Return information about saved emulator"""

        if emu_id:
            self.sdbc.execute(
                "SELECT id, name, exe, dir, zip, mode FROM emu WHERE id = ?", (emu_id,))
        elif emu_conn_id:
            self.sdbc.execute(
                "SELECT id, name, exe, dir, zip, mode FROM emu WHERE id = \
                 (SELECT emu_id FROM emu_conn WHERE id = ?)", (emu_conn_id,))
        row = self.sdbc.fetchone()
        return dict(row) if row is not None else None

    def save_emulator(self, emu_info, reconfigure, source=None, swl_name=None):
        """Save emulator to database and connect if needed."""

        if 'id' in emu_info:
            self.sdbc.execute(
                "UPDATE emu SET name = ?, exe = ?, dir = ?, zip = ?, mode = ? \
                    WHERE id = ?",
                (emu_info['name'], emu_info['exe'], emu_info['dir'],
                 emu_info['zip'], emu_info['mode'], emu_info['id']))
        else:
            self.sdbc.execute(
                "INSERT INTO emu (name, exe, dir, zip, mode) VALUES (?, ?, ?, ?, ?)",
                (emu_info['name'], emu_info['exe'], emu_info['dir'],
                 emu_info['zip'], emu_info['mode']))
        self.sdb.commit()
        if not reconfigure:
            emu_id = self.sdbc.lastrowid
            self.connect_emulator(emu_id, source=source, swl_name=swl_name)

    def connect_emulator(self, emu_id, source=None, swl_name=None):
        """Connect emulator to source or softwarelist"""

        if source:
            self.sdbc.execute(
                "INSERT INTO emu_conn (emu_id, source) VALUES (?, ?)", (emu_id, source)
            )
        elif swl_name:
            self.sdbc.execute(
                "INSERT INTO emu_conn (emu_id, swl) VALUES (?, ?)", (emu_id, swl_name)
            )
        else:
            log("UMSA database: connect_emulator error", level='debug')
        self.sdb.commit()

    def delete_emulator_connection(self, emu_conn_id):
        """Delete emulator connection to softwarelist or source

        Return emulator id it not used anymore
        """

        # get emu.ids for emu_conn.id before deleting
        self.sdbc.execute("SELECT emu_id FROM emu_conn WHERE emu_id IN \
                           (SELECT emu_id FROM emu_conn WHERE id = ?)", (emu_conn_id,))
        connected_emus = self.sdbc.fetchall()
        # delete emu_conn.id
        self.sdbc.execute("DELETE FROM emu_conn WHERE id = ?", (emu_conn_id,))
        self.sdb.commit()
        # return it if only 1
        if len(connected_emus) == 1:
            return connected_emus[0][0]
        return None

    def delete_emulator(self, emu_id):
        """Delete emulator and all connections"""

        self.sdbc.execute("DELETE FROM emu_conn WHERE emu_id = ?", (emu_id,))
        self.sdb.commit()
        self.sdbc.execute("DELETE FROM emu WHERE id = ?", (emu_id,))
        self.sdb.commit()

    def write_options(self, set_id, options):
        """Write options"""

        self.sdbc.execute(
            "UPDATE sets SET options = ? WHERE id = ?", (set_id, options)
        )
        self.sdb.commit()

    def write_status_after_play(self, set_id, played_seconds):
        """Update play status for set id

        Writes played seconds and play count
        """

        # get time string
        date = time.strftime("%Y-%m-%d %H:%M")
        # get data
        self.sdbc.execute("SELECT time_played, play_count FROM sets WHERE id = ?", (set_id,))
        set_fetch = self.sdbc.fetchone()
        # update data
        if set_fetch:
            set_data = (date, played_seconds+set_fetch[0], set_fetch[1]+1, set_id)
            self.sdbc.execute(
                "UPDATE sets \
                 SET last_played = ?, time_played = ?, play_count = ? \
                 WHERE id = ?", (set_data))
        # new data
        else:
            set_data = (set_id, date, played_seconds, 1)
            self.sdbc.execute(
                "INSERT INTO sets (id, last_played, time_played, play_count) \
                 VALUES (?,?,?,?)", (set_data))
        self.sdb.commit()

    def get_latest_by_software(self, software_id):
        """Return id of latest played set for a software id"""

        sets = self.get_set_ids_for_software(software_id)

        select_statement = "SELECT id FROM sets WHERE id IN ({}) \
                            ORDER BY last_played DESC LIMIT 1".format(','.join(['?'] * len(sets)))
        self.sdbc.execute(select_statement, sets)
        set_id = self.sdbc.fetchone()
        if set_id:
            set_id = set_id[0]
        return set_id

    def define_filter(self, filter_lists):
        """define filter

        TODO
        - when list smaller then 50% of all do NOT IN = faster?
        - do we need a special field for all as the lists can grow with updates?
          or show new entries after update!
        - make this count always visible in filter list and keep actual, is in gui:
          simply call this more often (:
        """

        self.filter_join = []
        self.filter_where = []
        # swl
        if filter_lists.get('Softwarelists'):
            self.gdbc.execute("SELECT COUNT(id) FROM swl")
            swl_count = self.gdbc.fetchone()[0]
            if swl_count > len(filter_lists['Softwarelists']):
                self.filter_join.append("JOIN swl ON swl.id = sets.swllink_id")
                self.filter_where.append(
                    "swl.id IN ({})".format(','.join(filter_lists['Softwarelists'])))
            else:
                log("UMSA datbase define_filter: all swls, no filter used", level='debug')
        # game categories, machines
        if ((filter_lists.get('Game Categories')) or
                (filter_lists.get('Machine Categories'))):
            self.gdbc.execute("SELECT COUNT(id) FROM category")
            cat_count = self.gdbc.fetchone()[0]
            len_filterlists = len(filter_lists['Game Categories']+filter_lists['Machine Categories'])
            log(f"UMSA database: filter categories {cat_count}, {len_filterlists}", level='debug')
            if cat_count > len_filterlists:
                self.filter_join.append("JOIN category ON category.id = sets.classification_id")
                self.filter_where.append("category.id IN ({})".format(
                    ','.join(filter_lists['Game Categories']+filter_lists['Machine Categories'])))
            else:
                log("UMSA database: define_filter: all categories, no filter used", level='debug')
        # players
        if filter_lists.get('Players'):
            self.gdbc.execute("SELECT COUNT(id) FROM nplayers")
            players_count = self.gdbc.fetchone()[0]
            log(f"UMSA database: filter players {players_count}, {len(filter_lists['Players'])}", level='debug')
            if players_count > len(filter_lists['Players']):
                self.filter_join.append("JOIN nplayers ON nplayers.id = sets.nplayers_id")
                self.filter_where.append("nplayers.id IN ({})".format(
                    ','.join(filter_lists['Players'])))
            else:
                log("UMSA database: define_filter: all players, no filter used", level='debug')
        # years
        if filter_lists.get('Years'):
            self.gdbc.execute("SELECT COUNT(id) FROM year")
            year_count = self.gdbc.fetchone()[0]
            if year_count > len(filter_lists['Years']):
                self.filter_join.append("JOIN year ON year.id = sets.year_id")
                self.filter_where.append("year.id IN ({})".format(','.join(filter_lists['Years'])))
            else:
                log("UMSA database: define_filter: all years, no filter used", level='debug')
        # count
        filter_where = ''
        if self.filter_join and self.filter_where:
            filter_where = "WHERE sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                " ".join(self.filter_join), " AND ".join(self.filter_where))
        select_statement = f"SELECT COUNT (DISTINCT software.id) \
            FROM sets JOIN software ON software.id = sets.softwarelink_id {filter_where}"
        self.gdbc.execute(select_statement)
        count = self.gdbc.fetchone()[0]
        self.gdbc.execute("SELECT COUNT (software.id) FROM software")
        all_count = self.gdbc.fetchone()[0]
        percent = int(round(count/float(all_count)*100))
        return f"{count} ({percent}%)"

    def execute_statement(self, set_id=None, software_id=None, prevnext=None):
        """Execute prepared statement with filter settings

        TODO
        - rework var names
        - keep inital count when used with set_id in gui
          so no overwrite with prevnext
        - make number of listmenu entries settings.xml
        - more logic: when swl.name = "gameboy" then no need for swl filter! = faster
        """

        time_start = time.time()
        result_count = 0
        where = ""
        filter_join = ""
        filter_where = ""
        if self.filter_join and self.filter_where:
            filter_join = " ".join(self.filter_join)
            filter_where = " AND ".join(self.filter_where)
        # prepare joins and wheres from filters
        s_join, s_where = '', ''
        if self.use_filter and self.where:
            if self.join and self.join not in self.filter_join:
                s_join = f"{self.join} {filter_join}"
            elif filter_join:
                s_join = filter_join
            if self.where and filter_where:
                s_where = f"{self.where} AND {filter_where}"
            elif self.where:
                s_where = self.where
            elif filter_where:
                s_where = filter_where
            if s_join and s_where:
                where = f"sets.id IN (SELECT sets.id FROM sets {s_join} WHERE {s_where})"
            # only for source
            elif self.where:
                where = self.where
        elif self.use_filter:
            if filter_join and filter_where:
                where = f"sets.id IN (SELECT sets.id FROM sets {filter_join} WHERE {filter_where})"
        elif self.join and self.where:
            where = f"sets.id IN (SELECT sets.id FROM sets {self.join} WHERE {self.where})"
        else:
            log("UMSA database: execute_statement: no join and where clause", level='debug')
        # get software name
        if set_id:
            name_statement = "SELECT software.name FROM software \
                    JOIN sets ON software.id = sets.softwarelink_id \
                    WHERE sets.id = ?"
            self.gdbc.execute(name_statement, (set_id,))
            sname = self.gdbc.fetchone()[0]
        elif software_id:
            self.gdbc.execute(
                "SELECT software.name FROM software WHERE software.id = ?", (software_id,)
            )
            sname = self.gdbc.fetchone()[0]
        else:
            log("UMSA database: execute_statement: no set or software id error", level='debug')
        # add ordering
        if self.order == 'name':
            order = 'software.name'
        elif self.order == 'year':
            order = 'year.name, software.name'
        elif self.order == 'publisher':
            order = 'maker.name, software.name'
        else:
            self.order = 'software.name'
        time_rampup = time.time()

        # fetch
        slist = []
        while not slist:
            # normal, previous or next
            if not prevnext:
                if where:
                    i_where = "WHERE "+where
                else:
                    i_where = ""
                limit = ""
            elif prevnext == 'prev':
                if where:
                    i_where = f'WHERE software.name <= "{sname}" AND {where}'
                else:
                    i_where = f'WHERE software.name <= "{sname}"'
                limit = "DESC LIMIT 100"
            elif prevnext == 'next':
                if where:
                    i_where = f'WHERE software.name >= "{sname}" AND {where}'
                else:
                    i_where = f'WHERE software.name >= "{sname}"'
                limit = "ASC LIMIT 100"
            else:
                log("UMSA database execute_statement: prevnext error {prevnext}", level='debug')
            # fetch software list
            select_statement = f"SELECT DISTINCT \
                    software.id, software.name, year.name as year, maker.name as maker \
                FROM sets \
                    JOIN software ON software.id = sets.softwarelink_id \
                    JOIN year ON year.id = software.year_id \
                    JOIN maker ON maker.id = software.developer_id \
                {i_where} ORDER BY {order} {limit}"
            self.gdbc.execute(select_statement)
            slist = self.gdbc.fetchall()
            # no results: try without filter
            if len(slist) == 0:
                log("UMSA database: fetch list: no result, retry without filters", level='debug')
                if self.where:
                    where = f"sets.id IN (SELECT sets.id FROM sets {self.join} WHERE {self.where})"
                else:
                    where = ""
        time_fetch = time.time()

        # get position and set prevnext
        if not prevnext:
            result_count = len(slist)
            # search for name
            # TODO rework
            count, pos = 0, 0
            for i in slist:
                count += 1
                if sname == i['name']:
                    pos = count
                    break
            # TODO do we need new_slist?
            if count < 50: # begin of list
                pos -= 1
                # TODO get rid of flag, try without new_slist
                flag = None
                if len(slist) > 100:
                    flag = True
                new_slist = slist[:count+50+(50-count)]
                if flag:
                    new_slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
            elif count > len(slist)-100: # end of list
                pos = pos-(len(slist)-100)
                new_slist = slist[count-(count-(len(slist)-100)):]
                new_slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
            else: # middle of list
                pos = 50
                new_slist = slist[count-50:count+50]
                new_slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
                new_slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
            slist = new_slist
        elif prevnext == 'next':
            pos = 1
            slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
            if len(slist) == 100:
                slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
        else: # prev
            pos = len(slist)
            slist.reverse()
            slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
            if len(slist) == 100:
                slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
        time_rest = time.time()
        log(f'UMSA database: execute_statement: begin {(time_rampup - time_start) * 1000:.0f}ms', level='debug')
        log(f'UMSA database:                   fetch {(time_fetch - time_rampup) * 1000:.0f}ms', level='debug')
        log(f'UMSA database:                   pos   {(time_rest - time_fetch) * 1000:.0f}ms', level='debug')
        log(f'UMSA database:                   all   {(time_rest - time_start) * 1000:.0f}ms', level='debug')
        return slist, pos, result_count

    def get_by_software(self, set_id):
        """Return list of software"""

        self.join = ''
        self.where = ''
        return self.execute_statement(set_id)

    def get_software_for_source(self, set_id, source):
        """Return list of software based on MAME source file"""

        self.join = ''
        self.where = f'sets.source = "{source}"'
        return self.execute_statement(set_id)

    def get_by_cat(self, cat, set_id):
        """Return list of software based on category"""

        self.join = "JOIN category ON category.id = sets.classification_id"
        self.where = f'category.name = "{cat}"'
        return self.execute_statement(set_id)

    def get_by_year(self, year, set_id):
        """Return list of software based on year"""

        self.join = 'JOIN year ON year.id = sets.year_id'
        self.where = f'year.name = "{year}"'
        return self.execute_statement(set_id)

    def get_by_players(self, players, set_id):
        """Return list of software based on number of players"""

        self.join = 'JOIN nplayers ON nplayers.id = sets.nplayers_id'
        self.where = f'nplayers.name = "{players}"'
        return self.execute_statement(set_id)

    def get_by_maker(self, maker, set_id):
        """Return list of software based on maker"""

        # get parent if maker is clone
        self.gdbc.execute("SELECT cloneof_id FROM maker WHERE maker.name = ?", (maker,))
        cloneof_id = self.gdbc.fetchone()[0]
        if not cloneof_id:
            self.gdbc.execute("SELECT id FROM maker WHERE maker.name = ?", (maker,))
            cloneof_id = self.gdbc.fetchone()[0]
        # get all maker ids
        all_maker_ids = []
        if cloneof_id:
            self.gdbc.execute("SELECT id FROM maker \
                WHERE cloneof_id = ? OR id = ?", (cloneof_id, cloneof_id))
            for i in self.gdbc.fetchall():
                all_maker_ids.append(str(i['id']))
        # set join and where
        self.join = 'JOIN maker ON maker.id = sets.publisher_id'
        if all_maker_ids:
            self.where = 'maker.id IN ({})'.format(','.join(all_maker_ids))
        else:
            self.where = f'maker.name = "{maker}"'
        return self.execute_statement(set_id)

    def get_by_swl(self, swl_name, set_id):
        """Return list of software based on softwarelist"""

        self.join = 'JOIN swl ON swl.id = sets.swllink_id'
        self.where = f'swl.name = "{swl_name}"'
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
        for software_id, status in reversed(
                sorted(software_dict.items(), key=lambda t: t[1][order])):

            minute = divmod(status["time_played"], 60)[0]
            hour, minute = divmod(minute, 60)
            time_played = "%d:%02d" % (hour, minute)

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

        self.gdbc.execute(
            "SELECT   p.name, pv.name, pv.disk \
             FROM     part_set pv, part p \
             WHERE    p.id = pv.part_id AND pv.variant_id = ? \
             ORDER BY p.name", (set_id,))
        return self.gdbc.fetchall()

    def get_disks(self, swl_name, set_name):
        """Return disks from a given set and softwarelist"""

        self.gdbc.execute(
            "SELECT sets.id FROM sets \
                JOIN swl ON swl.id = sets.swllink_id \
             WHERE sets.name = ? AND swl.name = ?",
            (set_name, swl_name))
        set_id = self.gdbc.fetchone()
        if set_id:
            self.gdbc.execute("SELECT disk FROM part_set WHERE variant_id = ?", (set_id[0],))
            disks = self.gdbc.fetchall()
            if disks:
                return disks
        return None

    def create_cmdline(self, parts, devices, setname):
        """create command line to start a software list item in mame"""

        cmd_options = []
        first_device = None

        hit = False
        for device in devices:
            # split the interface
            # because interface="c64_cart,vic10_cart" for c128_cart and c64_cart
            for interface in device[1].split(','):
                for part in parts:
                    if interface == part[1]:
                        hit = True
                        cmd_options.extend(
                            [
                                f'-{device[0]}',
                                f'{setname}:{part[0]}'
                            ]
                        )
                        # use device from first hit for snaps and states
                        if not first_device:
                            first_device = device[0]
                        parts.remove(part)
                        break
            # only pack one part into a device
            # TODO: make exception for x68000: -flop1 x -flop2 y
            if hit:
                break

        return cmd_options, first_device

    # create commandline options for mame
    def get_cmd_line_options(self, set_id, set_name, machine_name, swl_name):
        """Create command line options for MAME emulator run

        Based on id, name of set, and the names of machine and swl.
        """

        # get options for softwarelist
        ## this is manually set coz some swls need special options
        ## like a device in a slot so the machine supports hdds
        self.gdbc.execute(
            "SELECT options FROM swl WHERE name = ?", (swl_name,)
        )
        swlopt = self.gdbc.fetchone()
        # make swl_options a list
        if swlopt[0]:
            swl_options = swlopt[0].strip().split(' ')
        else:
            swl_options = None

        # get id for machine
        self.gdbc.execute(
            "SELECT v.id \
             FROM sets v, swl \
             WHERE v.swllink_id = swl.id AND swl.name = ? AND v.name = ?",
            ('mame', machine_name)
        )
        machine_id = self.gdbc.fetchone()

        # get devices supported by the machine
        self.gdbc.execute(
            "SELECT d.name, dv.name \
             FROM device_set dv, device d \
             WHERE d.id = dv.device_id AND dv.variant_id = ? \
             ORDER BY d.name", (machine_id[0],))
        _devices = self.gdbc.fetchall()

        # get all parts for the choosen set
        _part = self.get_parts_for_set_id(set_id)

        # check if we have a requirement in sharedfeat
        self.gdbc.execute(
            "SELECT sfv.name FROM sharedfeature sf, sharedfeature_set sfv \
             WHERE sf.name = 'requirement' AND sf.id = sfv.sharedfeat_id AND sfv.variant_id = ? \
             ORDER BY sf.name", (set_id,)
        )
        _sharedfeat = self.gdbc.fetchone()

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
                    _parts2 = self.get_parts_for_set_id(_setinfo['set_id'])
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

        # when we have no cmd_options then the machine needs a device
        # in a slot so it can support the media, thus we have no hit within
        # the devices and parts and therefore no cmd_options
        # little hack: normally we would need to get devices from mame
        # with the correct device in a slot: mame -slot xyz -lm
        elif swl_options:
            cmd_options = [machine_name] + swl_options + [set_name]
        # last exit is to just start mame with the machine and set as options
        else:
            cmd_options = [machine_name, set_name]
        # set snap dir to swl name
        cmd_options.extend(['-snapname', f'{swl_name}/{set_name}/%i'])

        return cmd_options

    def get_all_dbentries(self, cat):
        """Return select parameters based on filter categories.

        Gets a filter category.
        Returns a list of database tables and rows.
        """

        if cat == "Softwarelists":
            select_placeholders = (
                'description', 'swl', 'swllink', '', 'description'
            )
        elif cat == "Game Categories":
            select_placeholders = (
                'name', 'category', 'classification',
                'AND t.flag = 0', 'name'
            )
        elif cat == "Machine Categories":
            select_placeholders = (
                'name', 'category', 'classification',
                'AND t.flag = 1', 'name'
            )
        elif cat == "Years":
            select_placeholders = (
                'name', 'year', 'year', '', 'name'
            )
        elif cat == "Players":
            select_placeholders = (
                'name', 'nplayers', 'nplayers', '', 'name'
            )
        else:
            return None

        select_statement = "SELECT t.id, t.%s, count(distinct s.id) \
                            FROM %s t, software s, sets v \
                            WHERE t.id = v.%s_id and s.id = v.softwarelink_id %s \
                            GROUP BY t.id ORDER BY t.%s" % select_placeholders
        self.gdbc.execute(select_statement)

        return self.gdbc.fetchall()

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

        This remains in ``DBMod``: it joins ``art_set`` with the game tables
        (``sets``/``swl``) and resolves the resulting path, so it is a mixed
        application query rather than artwork-table CRUD.

        TODO
        - an abbreviation for machine name would make text shorter
        - should check first for a snap of machine in software
        - first needs export of machine in software from umsa
        """

        # get all machines
        all_machines = []
        # get abbreviation
        # TODO change sql to join and order by year.name
        self.gdbc.execute(
            "SELECT DISTINCT system_abbr FROM swl, sets \
               WHERE sets.softwarelink_id = ? AND sets.swllink_id = swl.id",
            (software_id,)
        )
        for j in self.gdbc.fetchall():
            all_machines.append(j[0])

        # get set ids with artwork
        self.gdbc.execute(
            "SELECT sets.name, swl.name as swl_name, \
                   art_set.source, art_set.root_key, art_set.scan_unit, \
                   art_set.type, art_set.extension, art_set.relative_path, \
                   art_set.archive_member \
             FROM sets, swl, art_set \
             WHERE sets.softwarelink_id = ? \
             AND swl.id = sets.swllink_id \
             AND art_set.id = sets.id \
             AND art_set.type = ? \
             ORDER BY RANDOM() LIMIT 1",
            (software_id, artwork)
        )
        # TODO ^ check machine from software table first
        # TODO ^ get all and random one artwork?
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

        # count
        self.gdbc.execute(
            "SELECT COUNT(DISTINCT software.id) \
                FROM sets \
                    JOIN software ON software.id = sets.softwarelink_id \
             WHERE sets.gamename LIKE ?", ("%"+my_search+"%",))
        results_count = self.gdbc.fetchone()[0]
        # fetch
        self.gdbc.execute(
            "SELECT DISTINCT software.id, software.name, year.name as year, maker.name as maker \
                FROM software \
                    JOIN year ON year.id = software.year_id \
                    JOIN maker ON maker.id = software.developer_id \
                    JOIN sets ON sets.softwarelink_id = software.id \
                WHERE sets.gamename LIKE ? \
             ORDER BY software.name LIMIT 100", ("%"+my_search+"%",))
        results = self.gdbc.fetchall()
        count, pos = 0, 0
        for i in results:
            # check if search is in beginning of s.name and set pos
            if my_search.lower() == i[1][:len(my_search)].lower():
                pos = count
                break
            count += 1

        return results, pos, results_count

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

        # TODO join
        self.gdbc.execute(
            "SELECT DISTINCT \
                s.id, s.name, s.gamename, s.detail, \
                y.name as year, m.name as maker, ss.status, ss.filtr \
             FROM \
                sets s, swl sw, \
                swl_status ss, year y, \
                maker m \
            WHERE \
                sw.name = ? \
                AND sw.id = ss.swl_id \
                AND s.id = ss.system_id \
                AND y.id = s.year_id \
                AND m.id = s.publisher_id \
            ORDER BY \
                ss.status DESC, y.name, s.name",
            (swl_name,)
        )

        machines = []
        pos, count = 0, 0
        for db_result in self.gdbc.fetchall():
            machines.append(
                {
                    'id'       : db_result['id'],
                    'name'     : "{}, {}".format(db_result['gamename'], db_result['maker']),
                    'label2'   : db_result['gamename'],
                    'setname'  : db_result['name'],
                    'detail'   : db_result['detail'],
                    'fullname' : db_result['gamename'],
                    'status'   : db_result['status'],
                    'filter'   : db_result['filtr'],
                    'year'     : db_result['year'],
                    'maker'    : "{},{}".format(db_result['status'], db_result['filtr'])
                }
            )
            if machine == db_result['name']:
                pos = count
            count += 1

        return machines, pos

    def get_swl_id(self, swl_name):
        """get swl id

        TODO: unused
        """

        self.gdbc.execute(
            "SELECT id FROM swl WHERE name = ?", (swl_name,)
        )
        return self.gdbc.fetchone()[0]

    def get_set_name(self, set_id):
        """Returns set name from set id

        TODO: Only used by run_emulator, diff_emu: search for rom file in filesystem
        """

        return self._get_game_repository().get_set_name(set_id)

    def get_info_for_id(self, _id):
        """get info for id

        TODO: unused
        """

        self.gdbc.execute(
            "SELECT DISTINCT v.id, v.name, v.gamename, c.name, c.flag \
             FROM sets v, swl, \
                  year y, category c \
             WHERE v.id = swl.system_id AND y.id = v.year_id \
                   AND c.id = v.classification_id AND swl.id IN \
                   ( SELECT DISTINCT swl.id \
                     FROM sets v, software s, \
                          swl, year y \
                     WHERE v.softwarelink_id = s.id AND y.id = s.year_id \
                           AND v.swllink_id = swl.id AND s.id = ? ) \
             ORDER BY y.name DESC", (_id,)
        )
        machines = self.gdbc.fetchall()
        return machines

    def get_sets_for_machine(self, software_id, machine_id):
        """Get sets for a machine

        TODO: unused

        Gets software and machine id
        Returns list of all sets and set is saved in database dictonary
        """

        # get_sets: get all sets for s.id and machine (can mean more than 1 swl)
        self.gdbc.execute(
            "SELECT \
                v.id, v.name, v.gamename, v.detail, v.source, \
                y.name as year, m.name as publisher, swl.name as swl_name, \
                v.display_type , v.display_rotation, c.name as category, \
                c.flag as category_is_machine \
             FROM \
                sets v, swl, \
                year y, maker m, \
                category c \
             WHERE \
                v.softwarelink_id = ? \
                AND v.year_id = y.id \
                AND v.publisher_id = m.id \
                AND c.id = v.classification_id \
                AND v.swllink_id = swl.id \
                AND swl.id IN \
                    ( SELECT DISTINCT swl.id \
                      FROM swl, sets v \
                      WHERE swl.system_id = v.id AND v.id = ? ) \
             ORDER BY v.cloneof_id, v.detail, v.gamename",
            (software_id, machine_id)
        )

        return self.gdbc.fetchall()

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

        # get all sets for software id
        self.gdbc.execute(
            "SELECT \
                sets.id, sets.name, sets.gamename, sets.detail, sets.source, \
                year.name as year, maker.name as maker, swl.name as swl, swl.system_id, \
                sets.display_type, sets.display_rotation, \
                category.name as category, category.flag as category_flag, \
                nplayers.name as nplayers, sets.cloneof_id \
             FROM sets \
             JOIN year ON sets.year_id = year.id \
             JOIN maker ON sets.publisher_id = maker.id \
             JOIN swl ON sets.swllink_id = swl.id \
             JOIN category ON sets.classification_id = category.id \
             JOIN nplayers ON sets.nplayers_id = nplayers.id \
             WHERE \
                sets.softwarelink_id = ? \
             ORDER BY \
                year.name, sets.cloneof_id, sets.gamename",
            (software_id,)
        )
        all_sets.append(self.gdbc.fetchall())

        # check if we have other software by this name
        # get software name
        self.gdbc.execute(
            "SELECT name FROM software WHERE id = ?", (software_id,)
        )
        software_name = self.gdbc.fetchone()[0]
        # get all software ids for software name
        self.gdbc.execute(
            "SELECT id FROM software WHERE name = ?", (software_name,)
        )
        for i in self.gdbc.fetchall():
            if software_id == i['id']: # is the original
                continue
            self.gdbc.execute(
                "SELECT \
                    sets.id, sets.name, sets.gamename, sets.detail, sets.source, \
                    year.name as year, maker.name as maker, swl.name as swl, swl.system_id, \
                    sets.display_type, sets.display_rotation, \
                    category.name as category, category.flag as category_flag, \
                    nplayers.name as nplayers, sets.cloneof_id \
                FROM sets \
                JOIN year ON sets.year_id = year.id \
                JOIN maker ON sets.publisher_id = maker.id \
                JOIN swl ON sets.swllink_id = swl.id \
                JOIN category ON sets.classification_id = category.id \
                JOIN nplayers ON sets.nplayers_id = nplayers.id \
                WHERE \
                    sets.softwarelink_id = ? \
                ORDER BY \
                    year.name, sets.cloneof_id, sets.gamename",
                (i['id'],)
            )
            all_sets.append(self.gdbc.fetchall())

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
                        self.gdbc.execute(
                            "SELECT name, gamename FROM sets WHERE id = ?",
                            (machine['system_id'],))
                        machine_name, machine_label = self.gdbc.fetchone()

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

        self.gdbc.execute(
            "SELECT v.id, v.gamename, y.name, m.name, s.id \
             FROM software s, sets v, \
                  swl, year y, maker m \
             WHERE s.id = v.softwarelink_id AND v.swllink_id = swl.id \
                   AND y.id = v.year_id AND m.id = v.publisher_id \
                   AND v.name = ? AND swl.name = ?",
            (setname, swlname)
        )
        db_fetch = self.gdbc.fetchone()

        result = {
            'software_id'   : db_fetch[4],
            'set_id'        : db_fetch[0],
            'name'          : db_fetch[1],
            'year'          : db_fetch[2],
            'maker'         : db_fetch[3],
            'label'         : f"{db_fetch[2]} - {db_fetch[1]}, {db_fetch[3]}",
        }
        return result
