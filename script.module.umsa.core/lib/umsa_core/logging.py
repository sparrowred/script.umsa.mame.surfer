"""Logging for Core: the host add-on registers a callback with :func:`set_log`."""

from collections.abc import Callable

LogCallback = Callable[..., None]

_log_callback: LogCallback | None = None


def set_log(function: LogCallback | None) -> None:
    """Register the logger callback of the host add-on (``None`` silences the log)."""

    global _log_callback
    _log_callback = function


def log(*args, level: str = "debug") -> None:
    """Forward a message to the registered callback, if there is one."""

    if _log_callback is not None:
        _log_callback(*args, level=level)
