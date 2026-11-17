"""Abort-aware waiting for long Core loops (emulator run, CHD extraction, scans).

``wait(milliseconds)`` waits and returns ``True`` when the host asks the caller
to stop, like Kodi's ``Monitor.waitForAbort`` (``umsa_core_kodi.make_abort_wait``);
without Kodi, :func:`time_wait` never reports a stop request.
"""

from __future__ import annotations

from collections.abc import Callable
from time import sleep as _time_sleep

Wait = Callable[[int], bool]


class ShutdownRequested(Exception):
    """Raised when the host (Kodi) asks the caller to stop at once."""


def time_wait(milliseconds: int) -> bool:
    _time_sleep(milliseconds / 1000.0)
    return False


def wait_from_sleep(sleep: Callable[[int], object] | None) -> Wait:
    """Wrap a millisecond ``sleep`` callback as a ``Wait``.

    ``None`` maps to ``time_wait``. A wrapped sleep never requests a stop.
    """

    if sleep is None:
        return time_wait

    def wait(milliseconds: int) -> bool:
        sleep(milliseconds)
        return False

    return wait


def resolve_wait(wait: Wait | None, sleep: Callable[[int], object] | None = None) -> Wait:
    return wait if wait is not None else wait_from_sleep(sleep)
