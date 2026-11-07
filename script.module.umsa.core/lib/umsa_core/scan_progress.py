"""Scan progress and shared scan-state coordination."""

from __future__ import annotations

import threading
from contextlib import contextmanager

from .abort import ShutdownRequested, resolve_wait
from .logging import log
from .scan_coordinator import ScanBusyError, ScanLockContext, scan_coordinator


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


SHUTDOWN_JOIN_TIMEOUT = 3.0


def run_scan_with_progress(db, scan_method, scan_args, progress, title, sleep,
                           wait=None, is_cancelled=None):
    """Run a DBMod scan method in a thread while reporting progress.

    The poll waits through ``wait(1000)`` (``umsa_core.abort.Wait``, the GUI
    passes an abort-aware ``Monitor.waitForAbort`` callback); without it the
    legacy ``sleep`` is invoked as ``sleep(1000)``. ``progress`` is called as
    ``progress(percent, title, message)``.

    The worker takes the shared scan lock *before* it initialises
    ``scan_perc``/``scan_what``/``scan_status``, so only the invocation that
    genuinely owns the scan may set them. A competing invocation that cannot
    take the lock calls the scan method anyway - the lock-aware methods return
    their ``busy`` summary without touching the shared fields - and returns that
    result without resetting the active scan's progress or cancellation signal.

    Stopping a scan clears ``db.scan_status`` (the signal every scanner polls
    through its ``is_cancelled``), and only when this invocation owns the scan:

    - ``is_cancelled()`` returning ``True`` (the user pressed cancel): the
      scanner stops at its next unit boundary, the worker is joined and its
      summary returned as usual;
    - ``wait`` returning ``True`` (the host shuts down): the worker is joined
      for at most ``SHUTDOWN_JOIN_TIMEOUT`` seconds, then ``ShutdownRequested``
      is raised.

    Returns the scan method's return value (for example the scanner summary
    dictionary), or ``None`` when the worker failed. Existing callers that
    ignore the result are unaffected.
    """

    scan_func = getattr(db, scan_method)
    wait = resolve_wait(wait, sleep)

    result = {}
    owner = threading.Event()
    finished = threading.Event()

    def worker():
        try:
            with _scan_state_ownership(db, '') as owns:
                if owns:
                    owner.set()
                result['value'] = scan_func(*scan_args)
        except Exception as exc:  # noqa: BLE001 - a scan must never stay stuck
            log(f"UMSA scan: '{scan_method}' worker failed: {exc}", level='error')
        finally:
            finished.set()

    def request_stop(reason):
        if owner.is_set() and not finished.is_set():
            log(f"UMSA scan: '{scan_method}' {reason}, stopping the scan", level='info')
            db.scan_status = False

    scan_thread = threading.Thread(target=worker)
    scan_thread.start()
    cancel_sent = False
    shutting_down = False
    try:
        while not finished.is_set():
            if wait(1000):
                shutting_down = True
                request_stop('shutdown requested')
                scan_thread.join(SHUTDOWN_JOIN_TIMEOUT)
                if scan_thread.is_alive():
                    log(
                        f"UMSA scan: '{scan_method}' did not stop within "
                        f"{SHUTDOWN_JOIN_TIMEOUT:.0f} s",
                        level='warning')
                raise ShutdownRequested(f"shutdown during scan '{scan_method}'")
            if finished.is_set():
                break
            if not cancel_sent and is_cancelled is not None and is_cancelled():
                request_stop('cancelled by the user')
                cancel_sent = True
            progress(db.scan_perc, title, f'scanning {db.scan_what}')
    finally:
        # a shutdown joined with a bound already
        if not shutting_down:
            scan_thread.join()
    progress(100, title, 'saving')
    return result.get('value')
