"""Abort-aware waiting for long Core loops (Kodi-free).

Long loops (emulator run, CHD extraction, scans) wait through a ``wait``
callback instead of a plain sleep. ``wait(milliseconds)`` waits and returns
``True`` when the host asks the caller to stop - the semantics of Kodi's
``Monitor.waitForAbort``. The Kodi adapter builds such a callback
(``umsa_core_kodi.make_abort_wait``); without Kodi, ``time_wait`` never
reports a stop request.
"""

from __future__ import annotations

from collections.abc import Callable
from time import sleep as _time_sleep

Wait = Callable[[int], bool]


class ShutdownRequested(Exception):
    """The host (Kodi) asked the caller to stop at once."""


def time_wait(milliseconds: int) -> bool:
    """Sleep via ``time.sleep``; a stop is never requested."""

    _time_sleep(milliseconds / 1000.0)
    return False


def wait_from_sleep(sleep: Callable[[int], object] | None) -> Wait:
    """Wrap a legacy millisecond ``sleep`` callback as a ``Wait``.

    ``None`` maps to ``time_wait``. A wrapped sleep never requests a stop.
    """

    if sleep is None:
        return time_wait

    def wait(milliseconds: int) -> bool:
        sleep(milliseconds)
        return False

    return wait


def resolve_wait(wait: Wait | None, sleep: Callable[[int], object] | None = None) -> Wait:
    """Return ``wait`` if given, else the wrapped legacy ``sleep``."""

    return wait if wait is not None else wait_from_sleep(sleep)
