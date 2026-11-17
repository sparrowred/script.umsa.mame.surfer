"""One process-wide lock that serializes the DAT, artwork, GB64 and eXoDOS scans.

Acquisition is non-blocking (a scan that cannot take it returns ``busy``) and
re-entrant per thread; only the outermost release frees it. The lock does not
coordinate separate processes.
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
        """Take the lock without blocking; ``False`` when another thread owns it."""

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

        Only the outermost release frees the lock, so a nested helper never
        frees the outer scan.
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


# The shared coordinator of every scan.
scan_coordinator = ScanCoordinator()


class ScanBusyError(Exception):
    """Raised when a scan cannot start because another scan is active."""

    def __init__(self, message: str = "Another scan is already running"):
        super().__init__(message)
        self.message = message


class ScanLockContext:
    """Context manager that holds the shared scan lock for one workflow.

    Raises :class:`ScanBusyError` on entry when another thread owns the lock.
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
