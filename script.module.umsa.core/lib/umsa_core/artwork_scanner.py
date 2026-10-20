"""Artwork folder scanning for the UMSA artwork database.

This module owns the artwork scan algorithm: discovering ``<type>/
<software_list>`` scan units under each configured root, inventorying each
unit's files, updating the artwork database atomically, reporting progress,
honouring cancellation and applying the filesystem retry policy.

It is deliberately Kodi- and ``DBMod``-free. The host supplies the resolved
database paths, a callback that ensures the artwork tables exist, progress
and cancellation callbacks and the directory listing callable. Importing
``database.py`` here would create a circular import, so the scanner takes
its dependencies explicitly instead.
"""

import errno
import os
import sqlite3
import stat
import threading

from .artwork import root_key_for_path
from .artwork_repository import ArtworkRepository
from .logging import log
from .scan_coordinator import ScanBusyError, ScanLockContext, scan_coordinator
from .sqlite import connect_sqlite, connect_sqlite_readonly

# --- Artwork scan filesystem retry policy -------------------------------------
# Bounded retry for transient filesystem/network errors while listing artwork
# directories (for example an SMB share briefly dropping out). Kept small so
# the UI stays responsive, and centralised so the values are easy to tune.
# ``_ART_LIST_ATTEMPTS`` counts the first try; each entry in
# ``_ART_LIST_RETRY_DELAYS`` is the wait before the corresponding retry.
_ART_LIST_ATTEMPTS = 3
_ART_LIST_RETRY_DELAYS = (0.5, 1.0)

# File-handle exhaustion (EMFILE/ENFILE) is *not* a network timeout. Retrying
# it like one just keeps the process pinned at its descriptor limit, so it gets
# a single short recovery attempt and then aborts the scan.
_ART_LIST_RESOURCE_RECOVERY_DELAY = 0.5


def _art_errno_values(*names):
    """Collect errno values by name, skipping names missing on this platform."""

    return frozenset(
        code for code in (getattr(errno, name, None) for name in names)
        if code is not None
    )


# Transient network/filesystem conditions: retried a few times.
_ART_LIST_TRANSIENT_ERRNOS = _art_errno_values(
    "EAGAIN", "EWOULDBLOCK", "EINTR", "ETIMEDOUT",
    "ECONNRESET", "ECONNABORTED",
    "ENETRESET", "ENETDOWN", "ENETUNREACH",
    "EHOSTDOWN", "EHOSTUNREACH",
    "ESTALE", "EIO", "EREMOTEIO",
)

# Resource exhaustion: the process or the system is out of file handles. A
# single short recovery retry is allowed, then the scan aborts cleanly.
_ART_LIST_RESOURCE_ERRNOS = _art_errno_values("EMFILE", "ENFILE")

# Raw Win32 error codes (``OSError.winerror``). There is no portable module
# exposing these, so they are named here and only consulted when ``winerror``
# is present (Windows); ``errno`` is still checked as a fallback. They are kept
# separate from the POSIX errno sets because the numbering is unrelated.
_WINERROR_RESOURCE = frozenset({
    4,     # ERROR_TOO_MANY_OPEN_FILES
    8,     # ERROR_NOT_ENOUGH_MEMORY
    14,    # ERROR_OUTOFMEMORY
    1450,  # ERROR_NO_SYSTEM_RESOURCES
    1816,  # ERROR_NOT_ENOUGH_QUOTA
})
_WINERROR_TRANSIENT = frozenset({
    51,    # ERROR_REM_NOT_LIST
    53,    # ERROR_BAD_NETPATH
    54,    # ERROR_NETWORK_BUSY
    55,    # ERROR_DEV_NOT_EXIST
    59,    # ERROR_UNEXP_NET_ERR
    64,    # ERROR_NETNAME_DELETED
    67,    # ERROR_BAD_NET_NAME
    121,   # ERROR_SEM_TIMEOUT
    1117,  # ERROR_IO_DEVICE
    1231,  # ERROR_NETWORK_UNREACHABLE
    1232,  # ERROR_HOST_UNREACHABLE
})


class _ArtworkScanResourceError(Exception):
    """Raised when listing keeps failing because file handles are exhausted."""

    def __init__(self, what, path, exc):
        super().__init__(f"{what} '{path}': {exc}")
        self.what = what
        self.path = path
        self.exc = exc


def _classify_listing_error(exc):
    """Classify an exception as ``'resource'``, ``'transient'`` or ``None``.

    Windows ``winerror`` takes precedence over ``errno`` when both are present,
    because the errno mapping can be lossy. Everything else (missing paths,
    wrong structure, permissions, programming errors) is ``None`` and must not
    be retried.
    """

    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        if winerror in _WINERROR_RESOURCE:
            return "resource"
        if winerror in _WINERROR_TRANSIENT:
            return "transient"

    err = getattr(exc, "errno", None)
    if err is not None:
        if err in _ART_LIST_RESOURCE_ERRNOS:
            return "resource"
        if err in _ART_LIST_TRANSIENT_ERRNOS:
            return "transient"

    return None


def _format_os_error(exc):
    """Return a concise diagnostic string for an exception, incl. winerror."""

    if not isinstance(exc, OSError):
        return str(exc)

    parts = []
    err = getattr(exc, "errno", None)
    if err is not None:
        try:
            message = os.strerror(err)
        except (ValueError, OverflowError):
            message = str(exc)
        parts.append(f"errno {err} ({message})")
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        parts.append(f"winerror {winerror}")
    if not parts:
        parts.append(str(exc))
    return ", ".join(parts)


def _art_list_retry_delay(attempt):
    """Delay in seconds before retry ``attempt`` (0-based), clamped to last."""

    delays = _ART_LIST_RETRY_DELAYS
    if attempt < len(delays):
        return delays[attempt]
    return delays[-1]


def _is_dir(path):
    """Return ``(is_directory, error)`` for a filesystem entry.

    A successful check of a non-directory is ``(False, None)``. When the
    check itself fails (for example file-handle exhaustion), the error is
    returned so callers can report it instead of silently treating the entry
    as "not a directory".

    ``os.stat``/``stat.S_ISDIR`` is used instead of ``os.path.isdir`` because
    the latter swallows access failures and returns ``False``, which would let
    an unreadable directory masquerade as a plain file.
    """

    try:
        return stat.S_ISDIR(os.stat(path).st_mode), None
    except OSError as exc:
        return False, exc


class ArtworkScanner:
    """Discover and inventory artwork roots into the artwork database.

    The scanner owns the scanning algorithm and its filesystem helpers. It has
    no knowledge of ``DBMod``; the host passes in the resolved Core data paths,
    a callback that creates the artwork tables, optional progress/cancellation
    callbacks and the directory listing callable.

    Args:
        db_paths: Resolved Core data paths (needs ``artwork_db`` and
            ``umsa_db``).
        initialize_tables: Callable taking the artwork DB cursor; must ensure
            the ``art_set``/``art_scan_unit`` tables exist.
        progress: Optional ``progress(percent, what)`` callback. Either value
            may be ``None`` to leave it unchanged.
        is_cancelled: Optional predicate that returns ``True`` when the host
            wants the scan to stop.
        listdir: Optional directory listing callable (defaults to
            ``os.listdir``).
    """

    def __init__(self, db_paths, initialize_tables, progress=None,
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
        return self._is_cancelled()

    def scan(self, paths=None, source=None, only_types=None, resume=True,
             cancel_event=None):
        """Scan artwork folders under the shared scan lock.

        This is the public entry point. It acquires the process-wide scan lock
        for the whole workflow (discovery, per-unit inventory, database writes
        and status updates). When another covered scan is already running it
        returns immediately with ``busy`` set and leaves all data untouched.
        """

        summary = {
            'discovered': 0,
            'processed': 0,
            'skipped': 0,
            'inserted': 0,
            'errors': 0,
            'cancelled': False,
            'aborted': False,
            'discovery_incomplete': False,
            'busy': False,
        }

        try:
            lock_ctx = ScanLockContext(scan_coordinator)
            lock_ctx.__enter__()
        except ScanBusyError:
            log("UMSA artwork scan: rejected, another scan is already running",
                level='warning')
            summary['busy'] = True
            return summary

        try:
            result = self._scan_locked(
                paths, source, only_types, resume, cancel_event)
            # Attach the busy flag to the scanner's own summary dict.
            result['busy'] = False
            return result
        finally:
            lock_ctx.__exit__(None, None, None)

    def _scan_locked(self, paths=None, source=None, only_types=None, resume=True,
                     cancel_event=None):
        """Scan artwork folders, unit-based and resumable.

        Directory layout is ``<root>/<type>/<software_list>/<set>.<ext>``.
        The only exception is the MAME software list, which nests the type
        again: ``<root>/<type>/<type>/<set>.<ext>``.

        Every ``<type>/<software_list>`` pair forms one scan unit. Discovered
        units are stored in ``art_scan_unit`` (so an interrupted run resumes
        and skips finished units) and matching files are recorded in
        ``art_set``.

        paths -- a single path or a sequence of paths.
        source -- artwork source name; defaults to ``progettosnaps`` for the
            first path and ``own_artwork`` for the rest.
        only_types -- optional restriction to a set of artwork types.
        resume -- skip units already marked ``done``.
        cancel_event -- optional ``threading.Event`` used to stop the scan and
            to interrupt retry waits.

        A ``None`` or empty path is skipped without shifting the source
        identity onto the following root: identity follows the original path
        position, so the second root stays ``own_artwork`` even when the first
        is unconfigured.

        Each successfully inventoried unit is updated atomically: its prior
        ``art_set`` rows are replaced and its ``art_scan_unit`` status becomes
        ``done`` in a single transaction. A unit whose software list cannot be
        resolved, or whose directory cannot be listed, keeps its existing
        records and is marked ``error`` (never ``done``). Discovery and unit
        failures are counted in the returned summary, whose keys are
        ``discovered``, ``processed``, ``skipped``, ``inserted``, ``errors``,
        ``cancelled``, ``aborted`` and ``discovery_incomplete``.

        Transient filesystem/network errors are retried a few times. File-handle
        exhaustion (``EMFILE``/``ENFILE``, or the Windows equivalents) gets a
        single short recovery retry and then aborts the whole scan cleanly
        (``aborted`` is set): records already committed are kept, and the
        unfinished unit is left not-``done`` so a later scan retries it.
        """

        if isinstance(paths, str):
            path_list = [paths]
        elif paths is None:
            path_list = []
        else:
            path_list = list(paths)
        if cancel_event is None:
            cancel_event = threading.Event()

        db_paths = self._db_paths
        # The connections are opened inside the try block below so the cleanup
        # in its finally also covers a failure while opening or initialising
        # them (for example an unreadable umsa.db).
        db_conn = None
        gdb = None

        listdir = self._listdir

        def listing(path, what):
            """List a directory, retrying transient errors.

            Returns the entries on success, or ``None`` when the listing
            genuinely failed (a failure is never reported as an empty
            directory). Raises ``_ArtworkScanResourceError`` when file handles
            stay exhausted, so the caller can abort the scan instead of opening
            yet more paths.
            """

            last_exc = None
            attempts = 0
            resource_retried = False
            max_attempts = _ART_LIST_ATTEMPTS + 1  # room for one recovery retry
            while attempts < max_attempts:
                attempts += 1
                try:
                    return list(listdir(path))
                except OSError as exc:
                    last_exc = exc
                    kind = _classify_listing_error(exc)

                    if kind == "resource":
                        # The process/system is out of file handles. One short
                        # recovery retry, then stop: retrying again would only
                        # hold the scan at the descriptor limit.
                        if resource_retried or attempts >= max_attempts:
                            log(f"UMSA artwork scan: aborting scan, file handles "
                                f"still exhausted listing {what} '{path}' "
                                f"({_format_os_error(exc)})", level='error')
                            raise _ArtworkScanResourceError(what, path, exc)
                        resource_retried = True
                        log(f"UMSA artwork scan: file handles exhausted listing "
                            f"{what} '{path}' ({_format_os_error(exc)}); single "
                            f"recovery retry in "
                            f"{_ART_LIST_RESOURCE_RECOVERY_DELAY:.1f}s",
                            level='warning')
                        if cancel_event.wait(_ART_LIST_RESOURCE_RECOVERY_DELAY):
                            log(f"UMSA artwork scan: cancelled while waiting to "
                                f"retry listing {what} '{path}'", level='warning')
                            return None
                        continue

                    if kind != "transient":
                        # Missing path, wrong structure or permissions: a retry
                        # would only delay the inevitable.
                        break

                    if attempts >= _ART_LIST_ATTEMPTS:
                        break
                    delay = _art_list_retry_delay(attempts - 1)
                    log(f"UMSA artwork scan: transient error listing {what} "
                        f"'{path}' ({_format_os_error(exc)}); retry "
                        f"{attempts + 1}/{_ART_LIST_ATTEMPTS} in {delay:.1f}s",
                        level='warning')
                    if cancel_event.wait(delay):
                        log(f"UMSA artwork scan: cancelled while waiting to "
                            f"retry listing {what} '{path}'", level='warning')
                        return None
                except Exception as exc:
                    last_exc = exc
                    break

            log(f"UMSA artwork scan: cannot list {what} '{path}' "
                f"({_format_os_error(last_exc)}); skipping", level='warning')
            return None

        log(f"UMSA artwork scan: start paths={path_list} source={source} resume={resume}")

        # Discovery error tracking starts before the first filesystem access so
        # an unreadable path can never be mistaken for an empty one. The
        # counters are initialised up front so the summary can still be
        # produced if the scan aborts early.
        errors = 0
        discovery_incomplete = False
        aborted = False
        total = 0
        processed = skipped = inserted = 0
        cancelled = False

        def finish():
            """Log the scan result and build the summary returned to callers."""

            self._report(100, None)
            log(f"UMSA artwork scan: finished units={total} processed={processed} "
                f"skipped={skipped} inserted={inserted} errors={errors} "
                f"cancelled={cancelled} aborted={aborted} "
                f"discovery_incomplete={discovery_incomplete}")
            if aborted:
                log("UMSA artwork scan: scan aborted early because the filesystem "
                    "ran out of file handles; artwork already recorded is kept "
                    "and the unfinished unit stays eligible for a later retry",
                    level='error')
            elif discovery_incomplete:
                log("UMSA artwork scan: discovery was incomplete, some "
                    "configured paths could not be listed; the scan result is "
                    "not complete", level='error')
            elif errors and not cancelled:
                log(f"UMSA artwork scan: completed with {errors} error(s)",
                    level='error')
            return {
                'discovered': total,
                'processed': processed,
                'skipped': skipped,
                'inserted': inserted,
                'errors': errors,
                'cancelled': cancelled,
                'aborted': aborted,
                'discovery_incomplete': discovery_incomplete,
            }

        try:
            db_conn = connect_sqlite(
                db_paths.artwork_db, row_factory=sqlite3.Row)
            dbc = db_conn.cursor()
            gdb = connect_sqlite_readonly(db_paths.umsa_db)
            gdbc = gdb.cursor()

            self._initialize_tables(dbc)
            db_conn.commit()

            repo = ArtworkRepository(db_conn)

            self._report(0, 'discovering')

            # Discover scan units (type/software_list) without reading files yet.
            units = []
            for idx, path in enumerate(path_list):
                # Source identity is positional: the first root is always
                # 'progettosnaps' and later roots 'own_artwork'. An empty or
                # unconfigured path must be skipped without shifting the
                # identity onto the next root, and must never fall back to
                # listing the current working directory.
                source_name = source or ('progettosnaps' if idx == 0 else 'own_artwork')
                if not path:
                    log(f"UMSA artwork scan: empty path for source "
                        f"'{source_name}', skipping", level='warning')
                    continue
                root_key = root_key_for_path(path)
                entries = listing(path, 'root')
                if entries is None:
                    # An unreadable root is not an empty root: count it and
                    # keep the existing records of this source untouched.
                    errors += 1
                    discovery_incomplete = True
                    log(f"UMSA artwork scan: root '{path}' for source "
                        f"'{source_name}' could not be listed, skipping "
                        "(existing artwork preserved)", level='error')
                    continue
                art_types = []
                for d in entries:
                    dpath = os.path.join(path, d)
                    ok, err = _is_dir(dpath)
                    if ok:
                        art_types.append(d)
                    elif err is not None:
                        # A directory check that failed is not a plain
                        # non-directory: report it so discovery is not assumed
                        # complete.
                        errors += 1
                        discovery_incomplete = True
                        log(f"UMSA artwork scan: could not determine whether "
                            f"'{dpath}' is a directory for source "
                            f"'{source_name}' ({_format_os_error(err)}); "
                            "skipping entry", level='warning')
                art_types.sort()
                log(f"UMSA artwork scan: root '{path}' source '{source_name}' "
                    f"key {root_key[:12]} types={art_types}")
                for art_type in art_types:
                    if only_types and art_type not in only_types:
                        continue
                    if art_type == 'icons':
                        continue
                    art_type_path = os.path.join(path, art_type)
                    entries = listing(art_type_path, art_type)
                    if entries is None:
                        # A type directory that cannot be read hides an unknown
                        # number of units: report it and never treat it as an
                        # empty directory.
                        errors += 1
                        discovery_incomplete = True
                        log(f"UMSA artwork scan: type directory "
                            f"'{art_type_path}' for source '{source_name}' "
                            "could not be listed, skipping", level='error')
                        continue
                    subdirs = []
                    for d in sorted(entries):
                        dpath = os.path.join(art_type_path, d)
                        ok, err = _is_dir(dpath)
                        if ok:
                            subdirs.append(d)
                        elif err is not None:
                            errors += 1
                            discovery_incomplete = True
                            log(f"UMSA artwork scan: could not determine "
                                f"whether '{dpath}' is a directory "
                                f"({_format_os_error(err)}); skipping entry",
                                level='warning')
                    if art_type in subdirs:
                        units.append((source_name, root_key, path,
                                      f"{art_type}/{art_type}", 'mame', art_type))
                    for swl in subdirs:
                        if swl == art_type:
                            continue
                        units.append((source_name, root_key, path,
                                      f"{art_type}/{swl}", swl, art_type))

            total = len(units)
            log(f"UMSA artwork scan: discovered {total} units")

            for i, (src, rkey, rpath, urel, swl_name, atype) in enumerate(units):
                if self._cancelled(cancel_event):
                    cancelled = True
                    log("UMSA artwork scan: cancelled before unit")
                    break
                self._report(int((i / total) * 100) if total else 100, urel)

                if resume:
                    status = repo.get_scan_unit_status(src, rkey, urel)
                    if status == 'done':
                        skipped += 1
                        continue

                # Resolve the software list before touching any artwork. A
                # software list missing from the UMSA database (mame included)
                # must never lead to deleting the unit's existing records or
                # marking it done.
                gdbc.execute("SELECT id FROM swl WHERE name = ?", (swl_name,))
                swl_id_row = gdbc.fetchone()
                if swl_id_row is None:
                    errors += 1
                    log(f"UMSA artwork scan: software list '{swl_name}' missing "
                        f"from UMSA database for unit '{urel}' "
                        f"(source '{src}'), preserving existing artwork",
                        level='error')
                    msg = f"software list '{swl_name}' missing"
                    try:
                        repo.set_scan_unit_error(src, rkey, urel, msg, db_cursor=dbc)
                    except Exception as status_exc:
                        log(f"UMSA artwork scan: could not record error status "
                            f"for unit '{urel}': {status_exc}", level='error')
                    continue
                swl_dict = {}
                gdbc.execute("SELECT id,name FROM sets WHERE swllink_id=?",
                             (swl_id_row[0],))
                for s in gdbc.fetchall():
                    swl_dict[s[1]] = s[0]

                # Mark the unit running before the inventory starts so an
                # interrupted process can be identified on resume.
                try:
                    repo.set_scan_unit_running(src, rkey, urel, db_cursor=dbc)
                except Exception as status_exc:
                    log(f"UMSA artwork scan: could not mark unit '{urel}' as "
                        f"running: {status_exc}", level='warning')

                unit_path = os.path.join(rpath, urel)
                files = listing(unit_path, urel)
                if files is None:
                    if self._cancelled(cancel_event):
                        # Cancellation, not a filesystem failure: stop without
                        # marking the (not yet refreshed) unit as errored.
                        cancelled = True
                        log(f"UMSA artwork scan: cancelled during unit '{urel}'")
                        break
                    errors += 1
                    log(f"UMSA artwork scan: skipping unit '{urel}' "
                        "(listing failed)", level='error')
                    try:
                        repo.set_scan_unit_error(src, rkey, urel, 'listing failed', db_cursor=dbc)
                    except Exception as status_exc:
                        log(f"UMSA artwork scan: could not record error status "
                            f"for unit '{urel}': {status_exc}", level='error')
                    continue

                # Enumerate the unit completely before opening the write
                # transaction, so no database lock is held while reading the
                # directory.
                matched_rows = []
                interrupted = False
                for f in files:
                    if self._cancelled(cancel_event):
                        interrupted = True
                        break
                    name, ext = os.path.splitext(f)
                    ext_clean = ext.removeprefix('.')
                    if not ext_clean:
                        continue
                    if name in swl_dict:
                        matched_rows.append(
                            (swl_dict[name], src, rkey, urel, atype,
                             ext_clean, None, None))
                if interrupted:
                    cancelled = True
                    log(f"UMSA artwork scan: cancelled during unit '{urel}'")
                    break

                # Replace the unit's artwork and mark it done in a single
                # transaction, so a crash cannot leave fresh artwork with a
                # stale status (or a done status with old artwork).
                try:
                    repo.replace_scan_unit(src, rkey, urel, matched_rows)
                except Exception as exc:
                    errors += 1
                    log(f"UMSA artwork scan: unit '{urel}' failed: {exc}",
                        level='error')
                    try:
                        repo.set_scan_unit_error(src, rkey, urel, str(exc), db_cursor=dbc)
                    except Exception as status_exc:
                        log(f"UMSA artwork scan: could not record error status "
                            f"for unit '{urel}': {status_exc}", level='error')
                    continue

                processed += 1
                inserted += len(matched_rows)
                log(f"UMSA artwork scan: [{i + 1}/{total}] {urel} "
                    f"swl={swl_name} files={len(files)} matched={len(matched_rows)}")

            return finish()
        except _ArtworkScanResourceError as exc:
            # The filesystem ran out of file handles and a single recovery
            # retry did not help. Stop opening more paths, keep every record
            # already committed, and leave the unfinished unit for a retry.
            aborted = True
            errors += 1
            log(f"UMSA artwork scan: aborted after listing {exc.what} "
                f"'{exc.path}' failed ({_format_os_error(exc.exc)}); "
                "completed units kept, unfinished unit not marked done",
                level='error')
            return finish()
        finally:
            if gdb is not None:
                try:
                    gdb.close()
                except Exception:
                    pass
            if db_conn is not None:
                try:
                    db_conn.close()
                except Exception:
                    pass
