"""Scan of the MAME support DAT files into dat.db.

Files are parsed and staged; only when every file was read is the
``mame_support`` result published in one transaction, with one ``dat_source``
row per file, and ``datscan.log`` written. Uses its own connections.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from .dat_parser import (
    DatFileReport,
    driver_lookup_keys,
    parse_dat,
    parse_history,
)
from .dat_repository import (
    ORIGIN_MAME_SUPPORT,
    DatRepository,
    create_dat_tables,
)
from .logging import log
from .scan_coordinator import ScanBusyError, ScanLockContext, scan_coordinator
from .scan_log import ScanLog
from .sqlite import connect_sqlite, connect_sqlite_readonly


class _DatCancellationCheckError(Exception):
    """Raised when the host cancellation predicate itself fails."""


def _source_row(report: DatFileReport, scanned_at: str) -> dict:
    """Return the ``dat_source`` values of one parsed file."""

    return {
        'file': report.file,
        'version': report.version,
        'date': report.date,
        'entries': report.entries,
        'unmatched_entries': len(report.unmatched_entries),
        'unmatched_sets': len(report.unmatched_sets),
        'unmatched_drivers': len(report.unmatched_drivers),
        'scanned_at': scanned_at,
    }


class DatScanner:
    """Scan support files into the DAT database.

    Args:
        db_paths: Resolved Core data paths (needs ``dat_db`` and ``umsa_db``).
        initialize_tables: Optional callable taking the DAT DB cursor; must
            ensure the schema exists. Default
            :func:`umsa_core.dat_repository.create_dat_tables`.
        progress: Optional ``progress(percent, what)`` callback; ``None`` for
            either value keeps it.
        is_cancelled: Optional predicate returning ``True`` when the host wants
            the scan to stop.
        listdir: Directory listing callable (default ``os.listdir``).
    """

    def __init__(self, db_paths, initialize_tables=None, progress=None,
                 is_cancelled=None, listdir=None):
        self._db_paths = db_paths
        self._initialize_tables = initialize_tables
        self._progress = progress
        self._is_cancelled = is_cancelled or (lambda: False)
        self._listdir = listdir or os.listdir

    def _report(self, percent=None, what=None):
        """Forward a progress update to the host, if a callback was given."""

        if self._progress is not None:
            self._progress(percent, what)

    def _cancelled(self, cancel_event):
        """Return ``True`` when the host or the cancel event requested a stop."""

        if cancel_event is not None and cancel_event.is_set():
            return True
        try:
            return bool(self._is_cancelled())
        except Exception as exc:
            log(f"UMSA dat scan: cancellation predicate failed ({exc}); "
                "aborting without publishing", level='error')
            raise _DatCancellationCheckError(str(exc)) from exc

    def _load_set_mapping(self):
        """Load the set mapping and the known driver names from ``umsa.db``.

        Returns ``(all_sets, drivers)``: ``all_sets`` maps ``"<swl>:<set>"``
        to the set id, ``drivers`` holds every ``sets.source`` value and its
        base name (:func:`driver_lookup_keys`).
        """

        umsa_db = self._db_paths.umsa_db
        if not os.path.isfile(umsa_db):
            raise FileNotFoundError(f"UMSA database not found: {umsa_db}")

        gdb = connect_sqlite_readonly(umsa_db, row_factory=sqlite3.Row)
        try:
            gdbc = gdb.cursor()
            try:
                gdbc.execute(
                    "SELECT sets.id, sets.name, swl.name AS swl "
                    "FROM sets JOIN swl ON sets.swllink_id = swl.id"
                )
                all_sets = {}
                for row in gdbc.fetchall():
                    all_sets[f"{row['swl']}:{row['name']}"] = row['id']
                gdbc.execute(
                    "SELECT DISTINCT source FROM sets WHERE source IS NOT NULL")
                drivers = set()
                for row in gdbc.fetchall():
                    drivers.update(driver_lookup_keys(row[0]))
                return all_sets, drivers
            finally:
                gdbc.close()
        finally:
            gdb.close()

    def _finish_report(self, datdir, set_count, reports, summary):
        """Add the sums to ``summary``, write ``datscan.log`` and log a line."""

        summary['unmatched_entries'] = sum(
            len(report.unmatched_entries) for report in reports)
        summary['unmatched_sets'] = sum(
            len(report.unmatched_sets) for report in reports)
        summary['unmatched_drivers'] = sum(
            len(report.unmatched_drivers) for report in reports)

        scan_log = ScanLog(self._db_paths.scan_log('dat'), 'UMSA dat scan')
        scan_log.line(f"Folder: {datdir}")
        scan_log.line(f"Sets in umsa.db: {set_count}")
        for report in reports:
            scan_log.section(report.file, (
                f"Version: {report.version or '-'}, date: {report.date or '-'}",
                (f"Entries: {report.entries}, "
                 f"entries without a set (not stored): "
                 f"{len(report.unmatched_entries)}, "
                 f"sets not found: {len(report.unmatched_sets)}, "
                 f"drivers not found: {len(report.unmatched_drivers)}, "
                 f"malformed lines: {len(report.malformed)}"),
            ))
            for heading, lines in (
                    ('entries without a set (not stored)',
                     report.unmatched_entries),
                    ('sets not found', report.unmatched_sets),
                    ('drivers not found', report.unmatched_drivers),
                    ('malformed lines', report.malformed)):
                if lines:
                    scan_log.section(f"{report.file}: {heading}", lines)
        if scan_log.write():
            summary['log'] = scan_log.path

        log(f"UMSA dat scan: {summary['entries']} entries from "
            f"{summary['files']} files; not stored: "
            f"{summary['unmatched_entries']} entries without a set; "
            f"{summary['unmatched_sets']} sets and "
            f"{summary['unmatched_drivers']} drivers not found; "
            f"log: {summary['log']}", level='info')

    def scan(self, datdir, cancel_event=None):
        """Scan ``datdir`` and atomically publish the ``mame_support`` result.

        Entries without a matching set are not stored; they and the sets and
        drivers not found are counted in ``dat_source`` and listed in
        ``datscan.log``, which is written only after a publish (a write failure
        is only logged). A missing ``umsa.db`` or input directory, an
        unreadable input file, a cancellation or a raising cancellation
        predicate publish nothing and keep the stored rows. Holds the scan
        lock throughout; when another scan owns it, returns at once with
        ``busy`` set.

        Returns:
            Summary with ``files``, ``entries``, ``published``, ``cancelled``,
            ``aborted``, ``errors``, ``busy``, the sums ``unmatched_entries``,
            ``unmatched_sets``, ``unmatched_drivers`` and ``log`` (path of
            ``datscan.log`` or ``None``).
        """

        summary = {
            'files': 0,
            'entries': 0,
            'published': False,
            'cancelled': False,
            'aborted': False,
            'errors': 0,
            'busy': False,
            'unmatched_entries': 0,
            'unmatched_sets': 0,
            'unmatched_drivers': 0,
            'log': None,
        }

        try:
            lock_ctx = ScanLockContext(scan_coordinator)
            lock_ctx.__enter__()
        except ScanBusyError:
            log("UMSA dat scan: rejected, another scan is already running",
                level='warning')
            summary['busy'] = True
            return summary

        try:
            return self._scan_locked(datdir, cancel_event, summary)
        finally:
            lock_ctx.__exit__(None, None, None)

    def _scan_locked(self, datdir, cancel_event, summary):
        """Run the DAT scan while the shared lock is held by the caller."""

        db_paths = self._db_paths

        # Abort before any DAT data is touched, so a failed scan can never look
        # like a valid empty result.
        try:
            all_sets, drivers = self._load_set_mapping()
        except Exception as exc:
            log(f"UMSA dat scan: cannot load UMSA set mapping: {exc}",
                level='error')
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        # A missing or inaccessible directory is never an empty scan.
        try:
            entries = list(self._listdir(datdir))
        except OSError as exc:
            log(f"UMSA dat scan: cannot list '{datdir}': {exc}", level='error')
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        db_conn = None
        repo = None
        staged_cur = None
        try:
            db_conn = connect_sqlite(
                db_paths.dat_db, row_factory=sqlite3.Row)
            cursor = db_conn.cursor()
            try:
                if self._initialize_tables is not None:
                    self._initialize_tables(cursor)
                else:
                    create_dat_tables(cursor)
            finally:
                try:
                    cursor.close()
                except Exception as exc:
                    log(f"UMSA dat scan: could not close table-init cursor: "
                        f"{exc}", level='error')

            repo = DatRepository(db_conn)
            repo.create_staging_tables()
            repo.clear_staging()
            db_conn.commit()

            staged_cur = db_conn.cursor()
            total = len(entries)

            reports = []
            processed = 0
            for datfile in entries:
                try:
                    if self._cancelled(cancel_event):
                        summary['cancelled'] = True
                        log("UMSA dat scan: cancelled before file")
                        break
                except _DatCancellationCheckError:
                    summary['aborted'] = True
                    summary['errors'] += 1
                    break

                full_path = os.path.join(datdir, datfile)

                if os.path.isdir(full_path):
                    processed += 1
                    self._report(
                        int(processed / total * 100) if total else 100, datfile
                    )
                    continue

                report = DatFileReport(datfile)
                history = datfile == 'history.xml'
                # Binary for the XML parser, which reads the encoding itself.
                open_args = ({'mode': 'rb'} if history else
                             {'mode': 'r', 'encoding': 'utf-8-sig',
                              'errors': 'ignore'})
                try:
                    with open(full_path, **open_args) as fobj:
                        if history:
                            parsed = parse_history(fobj, all_sets, report)
                        else:
                            parsed = parse_dat(fobj, all_sets, datfile,
                                               report, drivers)

                        for entry in parsed:
                            if self._cancelled(cancel_event):
                                summary['cancelled'] = True
                                break
                            repo.stage_entry(
                                entry.file,
                                entry.entry,
                                entry.set_ids,
                                db_cursor=staged_cur,
                                driver=entry.driver,
                            )
                            summary['entries'] += 1
                    db_conn.commit()
                    reports.append(report)
                    processed += 1
                    self._report(
                        int(processed / total * 100) if total else 100, datfile
                    )
                except _DatCancellationCheckError:
                    summary['aborted'] = True
                    summary['errors'] += 1
                    try:
                        db_conn.rollback()
                    except Exception as rollback_exc:
                        log(f"UMSA dat scan: rollback after cancellation "
                            f"predicate failure on '{full_path}' also failed: "
                            f"{rollback_exc}", level='error')
                    break
                except Exception as exc:
                    log(f"UMSA dat scan: failed to read or parse '{full_path}': "
                        f"{exc}", level='error')
                    summary['aborted'] = True
                    summary['errors'] += 1
                    try:
                        db_conn.rollback()
                    except Exception as rollback_exc:
                        log(f"UMSA dat scan: rollback after failure on "
                            f"'{full_path}' also failed: {rollback_exc}",
                            level='error')
                    break

                summary['files'] += 1
                if summary['cancelled']:
                    break

            if not summary['cancelled'] and not summary['aborted']:
                try:
                    self._report(what='publishing')
                    scanned_at = datetime.now().isoformat(timespec='seconds')
                    repo.publish_staged(
                        ORIGIN_MAME_SUPPORT,
                        sources=[_source_row(report, scanned_at)
                                 for report in reports],
                    )
                    summary['published'] = True
                    self._report(what='publishing complete', percent=100)
                except Exception as exc:
                    log(f"UMSA dat scan: publish failed: {exc}", level='error')
                    summary['aborted'] = True
                    summary['errors'] += 1

            if summary['published']:
                self._finish_report(datdir, len(all_sets), reports, summary)
            return summary
        finally:
            if db_conn is not None:
                if staged_cur is not None:
                    try:
                        staged_cur.close()
                    except Exception as exc:
                        log(f"UMSA dat scan: could not close staging cursor: "
                            f"{exc}", level='error')
                if repo is not None:
                    try:
                        repo.clear_staging()
                        db_conn.commit()
                    except Exception as exc:
                        log(f"UMSA dat scan: staging cleanup failed: {exc}",
                            level='error')
                        try:
                            db_conn.rollback()
                        except Exception as rollback_exc:
                            log(f"UMSA dat scan: rollback during staging "
                                f"cleanup also failed: {rollback_exc}",
                                level='error')
                try:
                    db_conn.close()
                except Exception as exc:
                    log(f"UMSA dat scan: could not close DAT database "
                        f"connection: {exc}", level='error')
