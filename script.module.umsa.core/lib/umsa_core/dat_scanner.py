"""Coordinate scanning of MAME support DAT files into the DAT database.

The scanner owns the filesystem workflow: it resolves the Core data paths,
opens its own worker connections through :func:`connect_sqlite`, loads the
UMSA set mapping once, discovers the input files, parses them with
:mod:`umsa_core.dat_parser` and stages the results through
:class:`umsa_core.dat_repository.DatRepository`. Only when every file has been
read and parsed successfully does it publish the staged ``mame_support``
result in one short transaction.

The scanner never touches ``DBMod`` and never receives its connection. It
contains no per-entry SQL; all statement ownership lives in the repository.
"""

from __future__ import annotations

import os
import sqlite3
import time

from .dat_parser import parse_dat, parse_history
from .dat_repository import (
    ORIGIN_MAME_SUPPORT,
    DatRepository,
    create_dat_tables,
)
from .logging import log
from .scan_coordinator import ScanBusyError, ScanLockContext, scan_coordinator
from .sqlite import connect_sqlite, connect_sqlite_readonly


class _DatCancellationCheckError(Exception):
    """Raised when the host cancellation predicate itself fails."""


class DatScanner:
    """Scan support files into the DAT database.

    Args:
        db_paths: Resolved Core data paths (needs ``dat_db`` and ``umsa_db``).
        initialize_tables: Optional callable taking the DAT DB cursor; must
            ensure the ``dat``/``dat_set`` schema exists. Defaults to the
            repository's authoritative schema helper.
        progress: Optional ``progress(percent, what)`` callback. Either value
            may be ``None`` to leave it unchanged.
        is_cancelled: Optional predicate returning ``True`` when the host wants
            the scan to stop.
        listdir: Optional directory listing callable (defaults to
            ``os.listdir``).
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
        """Load the ``"<swl>:<set>" -> set id`` mapping from ``umsa.db``."""

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
                return all_sets
            finally:
                gdbc.close()
        finally:
            gdb.close()

    def scan(self, datdir, cancel_event=None):
        """Scan ``datdir`` and atomically publish the ``mame_support`` result.

        Returns a summary whose keys are ``files``, ``entries``, ``published``,
        ``cancelled``, ``aborted`` and ``errors``.

        A missing/unreadable ``umsa.db``, a missing input directory or any
        unreadable/unparseable input file aborts the scan without publishing,
        leaving the previously stored DAT rows untouched. Cancellation discards
        the staged result and likewise keeps the previous rows. A cancellation
        predicate that raises is treated as an abort, never as "keep going".

        The shared scan lock is acquired before any scan-specific preparation
        or destructive change and held until the final status updates have
        completed. When another scan already owns the lock the call returns
        immediately with ``busy`` set and leaves all data untouched.
        """

        summary = {
            'files': 0,
            'entries': 0,
            'published': False,
            'cancelled': False,
            'aborted': False,
            'errors': 0,
            'busy': False,
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
        _t0 = time.time()
        _phase = {}

        db_paths = self._db_paths

        # A missing/unreadable UMSA database must abort before any DAT data is
        # touched, so a failed scan can never look like a valid empty result.
        try:
            t = time.time(); all_sets = self._load_set_mapping(); _phase["load_mapping"] = time.time()-t
        except Exception as exc:
            log(f"UMSA dat scan: cannot load UMSA set mapping: {exc}",
                level='error')
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        # Discover the input files before opening the DAT database. A missing
        # or inaccessible directory must never be treated as an empty scan.
        try:
            t = time.time(); entries = list(self._listdir(datdir)); _phase["discover"] = time.time()-t
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

            t_parse_start = time.time(); processed = 0
            for index, datfile in enumerate(entries):
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

                # Ignore directory entries instead of trying to open them.
                if os.path.isdir(full_path):
                    processed += 1
                    self._report(
                        int(processed / total * 100) if total else 100, datfile
                    )
                    continue

                try:
                    with open(full_path, 'r', encoding='utf-8',
                              errors='ignore') as fobj:
                        if datfile == 'history.xml':
                            parsed = parse_history(fobj.read(), all_sets)
                        else:
                            parsed = parse_dat(fobj, all_sets, datfile)

                        for entry in parsed:
                            if self._cancelled(cancel_event):
                                summary['cancelled'] = True
                                break
                            repo.stage_entry(
                                entry.file,
                                entry.entry,
                                entry.set_ids,
                                db_cursor=staged_cur,
                            )
                            summary['entries'] += 1
                    db_conn.commit()
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
                    # An unreadable or unparseable input must not be treated as
                    # successfully processed; discard this file's staged rows
                    # and abort without publishing.
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

            # Publish only when every file was read and no cancellation or
            # abort happened.
            if not summary['cancelled'] and not summary['aborted']:
                try:
                    _phase["parse"] = time.time() - t_parse_start
                    t_pub = time.time()
                    self._report(what='publishing', percent=processed if 'processed' in locals() else total if total else 100)
                    repo.publish_staged(ORIGIN_MAME_SUPPORT)
                    summary['published'] = True
                    _phase["publish"] = time.time() - t_pub
                    self._report(what='publishing complete', percent=100)
                except Exception as exc:
                    log(f"UMSA dat scan: publish failed: {exc}", level='error')
                    summary['aborted'] = True
                    summary['errors'] += 1

            _phase["total_locked"] = time.time() - _t0
            log(f"UMSA dat scan timing: { {k: round(v,3) for k,v in _phase.items()} }", level="debug")
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
