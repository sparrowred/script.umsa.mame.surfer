"""eXoDOS scan: XML metadata into dat.db, then images and videos into artwork.db.

The metadata is replaced atomically; a missing root, mapping or XML aborts
before any change. Artwork is replaced per scan unit. The two databases are
not atomic across each other. Uses its own connections.
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


class _ExodosCancellationCheckError(Exception):
    """Raised when the host cancellation predicate itself fails."""

SOURCE = "exodos"
DAT_FILE = "eXoDOS"


class ExodosScanner:
    """Import eXoDOS metadata and artwork into the UMSA databases.

    Args:
        db_paths: Resolved Core data paths (needs ``umsa_db``, ``dat_db`` and
            ``artwork_db``).
        initialize_dat: Optional callable taking the DAT DB cursor; default
            :func:`umsa_core.dat_repository.create_dat_tables`.
        initialize_art: Optional callable taking the artwork DB cursor;
            default :func:`umsa_core.artwork_repository.create_artwork_tables`.
        progress: Optional ``progress(percent, what)`` callback; ``None`` for
            either value keeps it.
        is_cancelled: Optional predicate returning ``True`` when the host wants
            the scan to stop; a predicate that raises aborts the scan.
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

    def _cancelled(self, cancel_event=None):
        """Return ``True`` when the host or the cancel event requested a stop."""

        if cancel_event is not None and cancel_event.is_set():
            return True
        try:
            return bool(self._is_cancelled())
        except Exception as exc:
            log(f"UMSA exodos scan: cancellation predicate failed ({exc}); "
                "aborting", level='error')
            raise _ExodosCancellationCheckError(str(exc)) from exc

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
        """Return ``({normalized gamename: id}, {set name: id})`` of the eXoDOS sets."""

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
        """Scan an eXoDOS installation under the shared scan lock; return the summary.

        When another scan holds the lock, return at once with ``busy`` set.

        Returns:
            Summary with ``busy``, ``aborted`` (metadata phase or pre-scan
            failure), ``errors``, ``matched``, ``unmatched``,
            ``artwork_units``, ``artwork_rows``, ``artwork_errors``,
            ``artwork_aborted``, ``artwork_unmatched`` (GameData archives
            without a set) and ``artwork_image_state`` /
            ``artwork_videosnap_state``: ``complete``, ``missing``,
            ``inaccessible``, ``not_a_directory``, ``incomplete``,
            ``cancelled`` or ``skipped`` (phase not attempted).
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
        """Run the eXoDOS scan while the caller holds the scan lock."""

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

        try:
            cancelled = self._cancelled(cancel_event)
        except _ExodosCancellationCheckError:
            cancelled = True
        if cancelled:
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        if not exodos_path:
            log("UMSA exodos scan: no eXoDOS root configured", level='error')
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        # Abort before anything is touched, so a failed scan can never look
        # like a valid empty result.
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

            # Last stop before the eXoDOS metadata is replaced.
            try:
                cancelled = self._cancelled(cancel_event)
            except _ExodosCancellationCheckError:
                cancelled = True
            if cancelled:
                log("UMSA exodos scan: stopped before writing metadata, "
                    "existing records kept", level='warning')
                summary['aborted'] = True
                summary['errors'] += 1
                return summary

            # An empty result must not wipe the stored eXoDOS metadata.
            if parsed.records:
                dat_repo.replace_origin(ORIGIN_EXODOS, parsed.records)
            else:
                log("UMSA support: exodos: no matched metadata, keeping "
                    "existing records", level='warning')
            summary['matched'] = len(parsed.records)

            self._report(percent=100)

            # A failing predicate stops the artwork phase like a cancel (its
            # checks partly sit under broad except blocks, a raise there could
            # be taken for a unit error) and is counted as an error afterwards.
            predicate_failed = []

            def artwork_cancelled():
                """Return whether to stop; a failing predicate counts as a stop."""
                try:
                    return self._cancelled(cancel_event)
                except _ExodosCancellationCheckError:
                    predicate_failed.append(True)
                    return True

            try:
                artwork = scan_exodos_artwork(
                    exodos_path, exodos_sets, art_repo, self._report,
                    is_cancelled=artwork_cancelled)
            except Exception as exc:
                # The metadata stays; the scan must not look complete.
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
            if predicate_failed:
                summary['artwork_aborted'] = True
                summary['artwork_errors'] += 1
                summary['errors'] += 1

            # The metadata is kept whatever the artwork outcome.
            dat_conn.commit()
        finally:
            if art_conn is not None:
                art_conn.close()
            if dat_conn is not None:
                dat_conn.close()

        return summary
