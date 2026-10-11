"""Small Kodi-independent logging callback used by UMSA modules."""

from collections.abc import Callable

LogCallback = Callable[..., None]

_log_callback: LogCallback | None = None


def set_log(function: LogCallback | None) -> None:
    """Register an optional logger callback supplied by the host add-on."""

    global _log_callback
    _log_callback = function


def log(*args, level: str = "debug") -> None:
    """Forward a message to the registered callback, if one is configured."""

    if _log_callback is not None:
        _log_callback(*args, level=level)
