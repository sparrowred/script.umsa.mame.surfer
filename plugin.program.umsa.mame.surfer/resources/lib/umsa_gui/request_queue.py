"""Requests from Kodi's monitor callbacks, run only while no handler runs.

Kodi delivers ``Monitor.onNotification`` also in the middle of a running
window handler (inside every ``xbmc.sleep`` / ``waitForAbort``, for example
while an emulator runs). A request that closes the window or selects another
software must not run there: it is queued and handled once the window is idle.
"""

import threading
from contextlib import contextmanager

REQUEST_CLOSE = 'close'
REQUEST_OPEN_SOFTWARE = 'open_software'


class RequestQueue:
    """Queue of ``(kind, value)`` requests for one window.

    Whoever holds the handler lock (a window handler inside ``busy()`` or a
    running ``drain()``) is the one that works the queue off; everybody else
    leaves the request in the queue. The lock is only ever taken without
    blocking, so it does not matter whether Kodi delivers a callback on a
    thread of its own or nested on the script thread.

    Only the newest request of a kind is kept; ``REQUEST_CLOSE`` drops all
    others.
    """

    def __init__(self, handler):
        self._handler = handler
        # held while a window handler or a request runs
        self._running = threading.Lock()
        # guards the pending requests
        self._state = threading.Lock()
        self._pending = {}
        self._closed = False

    def post(self, kind, value=None):
        """Queue a request and run it right away when the window is idle.

        Returns False once the queue is closed.
        """
        with self._state:
            if self._closed:
                return False
            # the newest request of a kind replaces the older one
            self._pending.pop(kind, None)
            self._pending[kind] = value
        self.drain()
        return True

    @contextmanager
    def busy(self):
        """Mark a window handler as running; the outermost one drains."""
        outermost = self._running.acquire(blocking=False)
        try:
            yield
        finally:
            if outermost:
                self._running.release()
                self.drain()

    def drain(self):
        """Run the queued requests unless a handler or a request runs."""
        while True:
            with self._state:
                if not self._pending:
                    return
            if not self._running.acquire(blocking=False):
                # the holder drains when it is done
                return
            try:
                request = self._take()
                if request is not None:
                    self._handler(*request)
            finally:
                self._running.release()

    def close(self):
        """Drop the queued requests and accept no new ones."""
        with self._state:
            self._closed = True
            self._pending.clear()

    def _take(self):
        with self._state:
            if not self._pending:
                return None
            if REQUEST_CLOSE in self._pending:
                self._pending.clear()
                return REQUEST_CLOSE, None
            kind = next(iter(self._pending))
            return kind, self._pending.pop(kind)
