"""eXoDOS metadata and artwork scanner.

This module owns the eXoDOS import workflow: it loads the eXoDOS set mapping
from ``umsa.db`` once, reads and parses ``MS-DOS.xml`` from
``Content/XODOSMetadata.zip`` once, writes the resulting DAT metadata atomically
through :mod:`umsa_core.dat_repository`, and then indexes the image tree and the
GameData MP4s. Artwork is persisted per scan unit through
:mod:`umsa_core.artwork_repository`, so each unit is replaced atomically.

The scanner never imports or touches :class:`DBMod` and owns its own short-lived
worker connections. All DAT metadata mutations live in the repository; artwork
mutations live in the artwork repository. A missing/unreadable root, a missing
mapping or an unreadable/malformed XML aborts before any destructive change, so
previously published records are preserved. DAT and artwork databases are
replaced independently: the scan does not claim atomicity across them.
"""

from __future__ import annotations

import os
import sqlite3
from zipfile import ZipFile

from .artwork_repository import ArtworkRepository, create_artwork_tables
from .dat_repository import ORIGIN_EXODOS, DatRepository, create_dat_tables
from .exodos_artwork import scan_exodos_artwork
from .exodos_parser import parse_exodos_metadata
from .logging import log
from .scan_coordinator import ScanBusyError, ScanLockContext, scan_coordinator
from .sqlite import connect_sqlite, connect_sqlite_readonly

SOURCE = "exodos"
DAT_FILE = "eXoDOS"


class ExodosScanner:
    """Import eXoDOS metadata and artwork into the UMSA databases.

    Args:
        db_paths: Resolved Core data paths (needs ``umsa_db``, ``dat_db`` and
            ``artwork_db``).
        initialize_dat: Optional callable taking the DAT DB cursor; must ensure
            the ``dat``/``dat_set`` schema exists. Defaults to the repository's
            authoritative schema helper.
        initialize_art: Optional callable taking the artwork DB cursor; must
            ensure the ``art_set``/``art_scan_unit`` schema exists. Defaults to
            the repository's authoritative schema helper.
        progress: Optional ``progress(percent, what)`` callback. Either value
            may be ``None`` to leave it unchanged.
        is_cancelled: Optional predicate returning ``True`` when the host wants
            the scan to stop.
    """

    def __init__(self, db_paths, initialize_dat=None, initialize_art=None,
                 progress=None, is_cancelled=None):
        self._db_paths = db_paths
        self._initialize_dat = initialize_dat
        self._initialize_art = initialize_art
        self._progress = progress
        self._is_cancelled = is_cancelled or (lambda: False)

    # -- callbacks -------------------------------------------------------

    def _report(self, percent=None, what=None):
        """Forward a progress update to the host, if a callback was given."""

        if self._progress is not None:
            self._progress(percent, what)

    def _cancelled(self):
        """Return ``True`` when the host requested a stop."""

        try:
            return bool(self._is_cancelled())
        except Exception:
            return False

    def _init_dat_schema(self, conn):
        """Ensure the DAT schema exists on ``conn`` (committed separately)."""

        cursor = conn.cursor()
        try:
            if self._initialize_dat is not None:
                self._initialize_dat(cursor)
            else:
                create_dat_tables(cursor)
        finally:
            cursor.close()
        conn.commit()

    def _init_art_schema(self, conn):
        """Ensure the artwork schema exists on ``conn`` (committed separately)."""

        cursor = conn.cursor()
        try:
            if self._initialize_art is not None:
                self._initialize_art(cursor)
            else:
                create_artwork_tables(cursor)
        finally:
            cursor.close()
        conn.commit()

    # -- set mapping -----------------------------------------------------

    def _load_sets(self):
        """Load the eXoDOS set mappings from ``umsa.db``.

        Returns ``(exodos_sets, exodos_sets_names)`` where ``exodos_sets`` maps
        the normalized gamename to the set id and ``exodos_sets_names`` maps the
        set name to the set id.
        """

        uconn = connect_sqlite_readonly(self._db_paths.umsa_db)
        try:
            uc = uconn.cursor()
            uc.execute(
                "SELECT sets.id, sets.gamename, sets.name "
                "FROM sets JOIN swl ON sets.swllink_id=swl.id "
                "WHERE swl.name = 'exodos'"
            )
            rows = uc.fetchall()
        finally:
            uconn.close()

        exodos_sets = {}
        exodos_sets_names = {}
        for set_id, gamename, name in rows:
            if name:
                exodos_sets_names[name] = set_id
            key = (gamename or '').replace(':', '_').replace(
                "'", '_').replace('?', '_').lower()
            if key:
                exodos_sets[key] = set_id
        return exodos_sets, exodos_sets_names

    # -- scan ------------------------------------------------------------

    def scan(self, exodos_path, cancel_event=None):
        """Scan an eXoDOS installation under the shared scan lock.

        This public entry point owns the process-wide scan lock for the whole
        combined metadata/artwork workflow. When another covered scan is already
        running it returns immediately with ``busy`` set and leaves all data
        untouched.

        Returns a summary whose keys are ``busy``, ``aborted``, ``errors``,
        ``matched``, ``unmatched``, ``artwork_units``, ``artwork_rows``,
        ``artwork_errors``, ``artwork_aborted``, ``artwork_unmatched``,
        ``artwork_image_state`` and ``artwork_videosnap_state``. ``aborted``
        describes the metadata phase (or a pre-scan failure);
        ``artwork_aborted`` describes the artwork phase, ``artwork_errors``
        counts artwork failures and ``artwork_unmatched`` counts GameData
        archives that could not be mapped to a set. The two ``*_state`` fields
        distinguish a complete (possibly empty) inventory from a ``missing``,
        ``inaccessible``, ``not_a_directory``, ``incomplete`` or ``cancelled``
        one, and are ``skipped`` for a phase that was never attempted. Metadata
        and artwork are separate databases and are not atomic across each other.
        """

        busy_summary = {
            'busy': True,
            'aborted': False,
            'errors': 0,
            'matched': 0,
            'unmatched': 0,
            'artwork_units': 0,
            'artwork_rows': 0,
            'artwork_errors': 0,
            'artwork_aborted': False,
            'artwork_unmatched': 0,
            'artwork_image_state': 'skipped',
            'artwork_videosnap_state': 'skipped',
        }

        try:
            lock_ctx = ScanLockContext(scan_coordinator)
            lock_ctx.__enter__()
        except ScanBusyError:
            log("UMSA exodos scan: rejected, another scan is already running",
                level='warning')
            return busy_summary

        try:
            return self._scan_locked(exodos_path, cancel_event)
        finally:
            lock_ctx.__exit__(None, None, None)

    def _scan_locked(self, exodos_path, cancel_event=None):
        """Run the eXoDOS scan while the shared lock is held by the caller.

        A missing/unreadable root, a missing mapping or an unreadable/malformed
        XML aborts before any destructive change. The complete parsed result is
        written through the repository, which atomically replaces only the
        eXoDOS origin rows, so previously published records survive a failed
        scan.
        """

        summary = {
            'busy': False,
            'aborted': False,
            'errors': 0,
            'matched': 0,
            'unmatched': 0,
            'artwork_units': 0,
            'artwork_rows': 0,
            'artwork_errors': 0,
            'artwork_aborted': False,
            'artwork_unmatched': 0,
            'artwork_image_state': 'skipped',
            'artwork_videosnap_state': 'skipped',
        }

        if cancel_event is not None and cancel_event.is_set():
            summary['aborted'] = True
            summary['errors'] += 1
            return summary
        if self._cancelled():
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        if not exodos_path:
            log("UMSA exodos scan: no eXoDOS root configured", level='error')
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        # A missing/unreadable umsa.db must abort before anything is touched, so
        # a failed scan can never look like a valid empty result.
        try:
            exodos_sets, exodos_sets_names = self._load_sets()
        except Exception as exc:
            log(f"UMSA exodos scan: cannot load exodos set mapping: {exc}",
                level='error')
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        dat_conn = None
        art_conn = None
        try:
            dat_conn = connect_sqlite(
                self._db_paths.dat_db, row_factory=sqlite3.Row)
            self._init_dat_schema(dat_conn)
            art_conn = connect_sqlite(
                self._db_paths.artwork_db, row_factory=sqlite3.Row)
            self._init_art_schema(art_conn)

            dat_repo = DatRepository(dat_conn)
            art_repo = ArtworkRepository(art_conn)

            # Read and parse the XML once, before any destructive change.
            self._report(what='reading MS-DOS.xml from zip')
            try:
                xml_file = os.path.join(
                    exodos_path, 'Content', 'XODOSMetadata.zip')
                with ZipFile(xml_file, 'r') as archive:
                    exodos_xml = archive.read(
                        'xml/all/MS-DOS.xml').decode('utf-8', 'ignore')
                parsed = parse_exodos_metadata(exodos_xml, exodos_sets_names)
            except Exception as exc:
                log(f"UMSA support: exodos: cannot read or parse MS-DOS.xml: "
                    f"{exc}", level='error')
                self._report(what='exodos metadata failed', percent=0)
                summary['aborted'] = True
                summary['errors'] += 1
                return summary

            self._report(what='scanning xml...', percent=0)
            for set_name in parsed.unmatched:
                log(f"UMSA support: exodos: cant find entry for dat {set_name}",
                    level='warning')
            summary['unmatched'] = len(parsed.unmatched)

            # The complete result has been parsed and validated before anything
            # is deleted. An entirely unmatched/empty result must not wipe the
            # previously published eXoDOS metadata, so it is skipped.
            if parsed.records:
                dat_repo.replace_origin(ORIGIN_EXODOS, parsed.records)
            else:
                log("UMSA support: exodos: no matched metadata, keeping "
                    "existing records", level='warning')
            summary['matched'] = len(parsed.records)

            self._report(percent=100)

            # Index the image tree and GameData MP4s. The helper owns the
            # one-pass filesystem inventories and neither parses the XML nor
            # writes the DAT metadata. It persists every unit through the
            # repository, so its report is folded into the scan summary.
            try:
                artwork = scan_exodos_artwork(
                    exodos_path, exodos_sets, art_repo, self._report,
                    is_cancelled=self._cancelled)
            except Exception as exc:
                # The metadata phase already succeeded and stays committed; an
                # unexpected artwork failure is reported as a failed artwork
                # phase so the scan is never mistaken for a complete success.
                log(f"UMSA exodos scan: artwork phase failed: {exc}",
                    level='error')
                summary['artwork_aborted'] = True
                summary['artwork_errors'] += 1
                summary['errors'] += 1
            else:
                summary['artwork_units'] = artwork['units']
                summary['artwork_rows'] = artwork['rows']
                summary['artwork_errors'] = artwork['errors']
                summary['artwork_unmatched'] = artwork.get('unmatched', 0)
                summary['artwork_image_state'] = artwork.get(
                    'image_state', 'skipped')
                summary['artwork_videosnap_state'] = artwork.get(
                    'videosnap_state', 'skipped')
                summary['errors'] += artwork['errors']
                if artwork.get('aborted'):
                    summary['artwork_aborted'] = True

            # Persist the metadata phase regardless of the artwork outcome.
            dat_conn.commit()
        finally:
            if art_conn is not None:
                art_conn.close()
            if dat_conn is not None:
                dat_conn.close()

        return summary
