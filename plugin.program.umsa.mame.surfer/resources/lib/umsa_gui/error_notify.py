"""Error notifications of the frontend (E-1).

Every failed user action ends in one short Kodi notification: the heading
says *what* failed ("FS-UAE could not start"), the message a short *reason*
plus the hint to the log ("working folder not found - see kodi.log"). The
reason comes from a classification of the exception (``REASONS``); the text
of the exception itself never reaches the notification, the full error with
its traceback goes to the log only.

This is no workflow module: it has no context, the first argument is the
Kodi dialog.
"""

import socket
import sqlite3
import traceback
import zipfile
from threading import Lock
from time import monotonic
from urllib.error import URLError

import xbmc
import xbmcgui
from umsa_core.chd_extractor import CHDExtractionError
from umsa_core.process import (
    LAUNCH_PERMISSION_DENIED,
    LAUNCH_PROGRAM_MISSING,
    LAUNCH_WORKING_DIR_MISSING,
    ProcessLaunchError,
)
from umsa_core.umsa_db_download import UmsaDbDownloadError

from . import strings as S
from .strings import tr

# display time of an error notification
NOTIFY_ERROR_MS = 6000
# an identical notification within this time is not shown again
REPEAT_SECONDS = 5

_LAUNCH_REASONS = {
    LAUNCH_WORKING_DIR_MISSING: S.REASON_WORKING_DIR_MISSING,
    LAUNCH_PROGRAM_MISSING: S.REASON_PROGRAM_MISSING,
    LAUNCH_PERMISSION_DENIED: S.REASON_PERMISSION_DENIED,
}


def _launch_reason(error):
    return _LAUNCH_REASONS.get(getattr(error, 'reason', None), S.REASON_LAUNCH_FAILED)


# (exception classes, string id or function of the error); the first match
# wins: many of the classes are OSErrors, so the order matters
REASONS = [
    (ProcessLaunchError, _launch_reason),
    (CHDExtractionError, S.REASON_CHD_FAILED),
    ((UmsaDbDownloadError, URLError, socket.timeout, TimeoutError), S.REASON_NETWORK),
    (zipfile.BadZipFile, S.REASON_ARCHIVE_BROKEN),
    (sqlite3.Error, S.REASON_DATABASE),
    (FileNotFoundError, S.REASON_FILE_MISSING),
    (PermissionError, S.REASON_PERMISSION_DENIED),
    (OSError, S.REASON_IO),
]

# last shown notification: (heading, message, monotonic time)
_last = None
_last_lock = Lock()


def reason_id(error):
    """String id of the short reason text for ``error``."""

    for classes, reason in REASONS:
        if isinstance(error, classes):
            return reason(error) if callable(reason) else reason
    return S.REASON_UNEXPECTED


def _reason_of(error):
    # notify_error has a parameter of the same name
    return reason_id(error)


def _repeated(heading, message):
    """True when the same notification was shown less than REPEAT_SECONDS ago."""

    global _last
    now = monotonic()
    with _last_lock:
        if (_last is not None and _last[:2] == (heading, message)
                and now - _last[2] < REPEAT_SECONDS):
            return True
        _last = (heading, message, now)
        return False


def notify_error(dialog, title_id, *title_args, error=None, reason_id=None):
    """Show the error notification ``tr(title_id, *title_args)``.

    The message is the reason ``reason_id`` (a string id) or, without one,
    the reason of ``error`` (``REASONS``), followed by the hint to the log.
    The caller logs the error itself. An identical notification within
    ``REPEAT_SECONDS`` is skipped; a failing dialog is only logged.
    """

    reason = reason_id if reason_id is not None else _reason_of(error)
    heading = tr(title_id, *title_args)
    message = tr(S.ERR_SEE_LOG, tr(reason))
    if _repeated(heading, message):
        xbmc.log(f"UMSA gui: repeated notification skipped: {heading} / {message}",
                 xbmc.LOGDEBUG)
        return
    try:
        dialog.notification(heading, message, xbmcgui.NOTIFICATION_ERROR, NOTIFY_ERROR_MS)
    except Exception as notify_failure:  # noqa: BLE001 - only a report
        xbmc.log(f"UMSA gui: could not show the error notification "
                 f"{heading!r}: {notify_failure}", xbmc.LOGWARNING)


def report_unexpected(dialog, where, error, notify=True):
    """Log an unexpected error with its traceback and, with ``notify``, tell the user."""

    details = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    xbmc.log(f"UMSA gui: unexpected error in {where}: {error}\n{details}", xbmc.LOGERROR)
    if notify:
        notify_error(dialog, S.ERR_UNEXPECTED_TITLE, error=error)
