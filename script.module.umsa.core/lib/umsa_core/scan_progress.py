"""Run a scan in a worker thread while the GUI shows its progress."""

from __future__ import annotations

import threading
import traceback

from .abort import ShutdownRequested, resolve_wait
from .logging import log

SHUTDOWN_JOIN_TIMEOUT = 3.0


def run_scan_with_progress(state, name, scan, progress, title, sleep,
                           wait=None, is_cancelled=None):
    """Run ``scan()`` in a thread while reporting progress.

    The worker takes the scan lock (``state.own``) before the state is set; a
    competing call runs the scan anyway (the scanners return ``busy``) and
    leaves the active scan's state alone. Only the owner sends a stop:
    ``is_cancelled()`` stops the scan at its next unit and the summary is
    returned as usual; ``wait`` returning ``True`` (shutdown) joins the worker
    for at most ``SHUTDOWN_JOIN_TIMEOUT`` seconds.

    Args:
        state: The :class:`umsa_core.scans.ScanState` the scan reports to.
        name: Names the scan in the log.
        scan: Callable without arguments, e.g. ``lambda: scans.dats(datdir)``.
        progress: Called as ``progress(percent, title, message)``.
        sleep: Fallback poll, called as ``sleep(1000)`` when ``wait`` is ``None``.
        wait: Abort-aware ``wait(ms) -> bool`` (:data:`umsa_core.abort.Wait`).

    Returns:
        The scanner summary dictionary, or ``None`` when the worker failed.

    Raises:
        ShutdownRequested: When ``wait`` reports a shutdown.
    """

    wait = resolve_wait(wait, sleep)

    result = {}
    owner = threading.Event()
    finished = threading.Event()

    def worker():
        """Run the scan under the scan lock and record its result."""
        try:
            with state.own('') as owns:
                if owns:
                    owner.set()
                result['value'] = scan()
        except Exception as exc:  # noqa: BLE001 - a scan must never stay stuck
            log(f"UMSA scan: '{name}' worker failed: {exc}\n"
                f"{traceback.format_exc()}", level='error')
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
        # A shutdown joined with a bound already.
        if not shutting_down:
            scan_thread.join()
    progress(100, title, 'saving')
    return result.get('value')
