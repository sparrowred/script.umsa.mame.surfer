"""Centralized scan coordination to serialize all covered scan workflows.

This module provides a single process-wide lock shared by every covered scan
workflow:

* DAT scans that use the shared staging tables (``DatScanner`` /
  ``DBMod.scan_dats``).
* The MAME artwork scan (``ArtworkScanner`` / ``DBMod.scan_artwork``).
* The GB64 scan, including its DAT metadata work
  (``GB64Scanner`` / ``DBMod.scan_gb64_to_db``).
* The eXoDOS scan, including its DAT metadata work
  (``DBMod.scan_exodos_to_db``).

The lock is process-local: it does not coordinate separate Python processes
that may access the same database files.

Acquisition is non-blocking. A scan that cannot take the lock returns an
explicit ``busy`` result immediately instead of waiting. Acquisition is
re-entrant per thread: an internal helper that re-enters while the *same*
thread owns the lock does not deadlock and does not release the lock early.
Only the outermost acquisition releases the underlying lock.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Self


class ScanCoordinator:
    """Process-wide, thread-owned, re-entrant scan lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner_ident: int | None = None
        self._depth = 0

    def acquire(self) -> bool:
        """Try to take the lock without blocking.

        Returns ``True`` when the lock is now held: either it was just acquired
        by the current thread, or the current thread already owned it (a nested
        call). Returns ``False`` when another thread owns it.
        """

        ident = threading.get_ident()
        if self._owner_ident == ident:
            self._depth += 1
            return True

        if self._lock.acquire(False):
            self._owner_ident = ident
            self._depth = 1
            return True
        return False

    def release(self) -> None:
        """Release one acquisition if the current thread owns the lock.

        The underlying lock is released only when the outermost acquisition is
        released, so a nested internal helper never frees the outer scan.
        """

        ident = threading.get_ident()
        if self._owner_ident != ident:
            return
        self._depth -= 1
        if self._depth == 0:
            self._owner_ident = None
            self._lock.release()

    def owned_by_current_thread(self) -> bool:
        """Return ``True`` when the current thread owns the lock."""

        return self._owner_ident == threading.get_ident()

    def is_locked(self) -> bool:
        """Return ``True`` when any thread owns the lock."""

        return self._owner_ident is not None


# The single shared coordinator instance used by every covered scan workflow.
scan_coordinator = ScanCoordinator()


class ScanBusyError(Exception):
    """Raised when a scan cannot start because another scan is active."""

    def __init__(self, message: str = "Another scan is already running"):
        super().__init__(message)
        self.message = message


class ScanLockContext:
    """Context manager that holds the shared scan lock for one workflow.

    Raises :class:`ScanBusyError` when the lock is already owned by another
    thread. Used as::

        with ScanLockContext(scan_coordinator):
            ...
    """

    def __init__(self, coordinator: ScanCoordinator | None = None) -> None:
        self._coordinator = coordinator or scan_coordinator
        self._acquired = False

    def __enter__(self) -> Self:
        if not self._coordinator.acquire():
            raise ScanBusyError()
        self._acquired = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._acquired:
            self._coordinator.release()
            self._acquired = False
