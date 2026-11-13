"""Run a scan in a worker thread while the GUI shows its progress."""

from __future__ import annotations

import threading

from .abort import ShutdownRequested, resolve_wait
from .logging import log

SHUTDOWN_JOIN_TIMEOUT = 3.0


def run_scan_with_progress(state, name, scan, progress, title, sleep,
                           wait=None, is_cancelled=None):
    """Run ``scan()`` in a thread while reporting progress.

    ``state`` is the :class:`umsa_core.scans.ScanState` the scan reports to
    (``Scans.state``), ``scan`` a callable without arguments (for example
    ``lambda: scans.dats(datdir)``) and ``name`` only names it in the log.

    The poll waits through ``wait(1000)`` (``umsa_core.abort.Wait``, the GUI
    passes an abort-aware ``Monitor.waitForAbort`` callback); without it the
    legacy ``sleep`` is invoked as ``sleep(1000)``. ``progress`` is called as
    ``progress(percent, title, message)``.

    The worker takes the shared scan lock (``state.own``) *before* the state
    fields are initialised, so only the invocation that genuinely owns the scan
    may set them. A competing invocation that cannot take the lock calls the
    scan anyway - the lock-aware scanners return their ``busy`` summary without
    touching the state - and returns that result without resetting the active
    scan's progress or cancellation signal.

    Stopping a scan calls ``state.request_stop()`` (the signal every scanner
    polls through its ``is_cancelled``), and only when this invocation owns the
    scan:

    - ``is_cancelled()`` returning ``True`` (the user pressed cancel): the
      scanner stops at its next unit boundary, the worker is joined and its
      summary returned as usual;
    - ``wait`` returning ``True`` (the host shuts down): the worker is joined
      for at most ``SHUTDOWN_JOIN_TIMEOUT`` seconds, then ``ShutdownRequested``
      is raised.

    Returns the scan's return value (the scanner summary dictionary), or
    ``None`` when the worker failed.
    """

    wait = resolve_wait(wait, sleep)

    result = {}
    owner = threading.Event()
    finished = threading.Event()

    def worker():
        try:
            with state.own('') as owns:
                if owns:
                    owner.set()
                result['value'] = scan()
        except Exception as exc:  # noqa: BLE001 - a scan must never stay stuck
            log(f"UMSA scan: '{name}' worker failed: {exc}", level='error')
        finally:
            finished.set()

    def request_stop(reason):
        if owner.is_set() and not finished.is_set():
            log(f"UMSA scan: '{name}' {reason}, stopping the scan", level='info')
            state.request_stop()

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
                        f"UMSA scan: '{name}' did not stop within "
                        f"{SHUTDOWN_JOIN_TIMEOUT:.0f} s",
                        level='warning')
                raise ShutdownRequested(f"shutdown during scan '{name}'")
            if finished.is_set():
                break
            if not cancel_sent and is_cancelled is not None and is_cancelled():
                request_stop('cancelled by the user')
                cancel_sent = True
            progress(state.percent, title, f'scanning {state.what}')
    finally:
        # a shutdown joined with a bound already
        if not shutting_down:
            scan_thread.join()
    progress(100, title, 'saving')
    return result.get('value')
