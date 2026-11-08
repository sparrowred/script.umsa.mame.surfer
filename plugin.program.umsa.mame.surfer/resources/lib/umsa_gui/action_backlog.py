"""Drop onAction callbacks that queued up behind a slow handler.

Kodi queues ``onAction`` callbacks while a handler runs. Holding a key
therefore piles up callbacks that keep running after the key is released.
Queued callbacks start right after the previous handler ended, real key
presses and repeats arrive with a gap: callbacks within ``threshold``
seconds of the previous end are treated as backlog.
"""

import time

from .constants import ACTION_BACKLOG_THRESHOLD


class ActionBacklog:
    """Gap-based detection of queued callbacks for one kind of action."""

    def __init__(self, threshold=ACTION_BACKLOG_THRESHOLD, clock=time.monotonic):
        self.threshold = threshold
        self._clock = clock
        self._last_done = None

    def is_backlog(self):
        """True when this callback was queued behind the previous handler."""
        if self._last_done is None:
            return False
        return self._clock() - self._last_done < self.threshold

    def done(self):
        """Record the end of a handler (processed or skipped)."""
        self._last_done = self._clock()
