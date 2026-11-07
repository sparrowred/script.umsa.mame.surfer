"""Maintenance actions of the UMSA settings (Core add-on script entry).

The Maintenance section of ``resources/settings.xml`` runs
``RunScript(script.module.umsa.core,<command>)``. This file lives outside
``lib/umsa_core`` because it uses Kodi; the file selection itself is the
Kodi-free ``umsa_core.data_paths.maintenance_targets``.

A running frontend holds umsa.db/status.db open, so it is asked to close
(``request_frontend_close``) before anything is deleted.
"""

import os
import sys

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon(id="script.module.umsa.core")
sys.path.append(os.path.join(ADDON.getAddonInfo("path"), "lib"))

# imported after the lib path is on sys.path
from umsa_core.data_paths import (
    MAINTENANCE_COMMANDS,
    maintenance_targets,
)
from umsa_core_kodi import (
    get_core_data_paths,
    is_frontend_running,
    is_screensaver_running,
    request_frontend_close,
)

HEADING = "UMSA maintenance"
DESCRIPTIONS = {
    "delete_umsa_db": "the UMSA database (umsa.db)",
    "delete_status_db": "the status database (status.db: history, filters, emulators)",
    "delete_media_db": "the artwork and support info (artwork.db, dat.db)",
}
CLOSE_TIMEOUT = 10.0
CLOSE_POLL = 0.5


def _log(message, level=xbmc.LOGINFO):
    xbmc.log(f"UMSA maintenance: {message}", level)


def _wait_for_frontend_close(monitor):
    """Ask the frontend to close; return True once it is gone."""

    request_frontend_close()
    waited = 0.0
    while waited < CLOSE_TIMEOUT:
        if not is_frontend_running():
            return True
        if monitor.waitForAbort(CLOSE_POLL):
            return False
        waited += CLOSE_POLL
    return not is_frontend_running()


def _delete(paths):
    """Delete ``paths``; return (deleted names, error messages)."""

    deleted, errors = [], []
    for path in paths:
        try:
            os.remove(path)
            deleted.append(os.path.basename(path))
        except FileNotFoundError:
            pass
        except OSError as error:
            errors.append(f"{os.path.basename(path)}: {error}")
    return deleted, errors


def run(command, dialog=None, monitor=None):
    """Run one maintenance ``command``; return True if files were deleted."""

    dialog = dialog or xbmcgui.Dialog()
    monitor = monitor or xbmc.Monitor()

    if command not in MAINTENANCE_COMMANDS:
        _log(f"unknown command {command!r}", xbmc.LOGWARNING)
        return False
    if command == "clean_status":
        dialog.notification(HEADING, "Clean up status: not implemented yet",
                            xbmcgui.NOTIFICATION_INFO, 4000)
        return False

    if is_screensaver_running():
        dialog.notification(HEADING, "Stop the screensaver first",
                            xbmcgui.NOTIFICATION_WARNING, 4000)
        return False

    what = DESCRIPTIONS[command]
    frontend = is_frontend_running()
    question = f"Delete {what}?"
    if frontend:
        question = f"UMSA is running and will be closed.[CR]{question}"
    if not dialog.yesno(HEADING, question):
        return False

    if (frontend and not _wait_for_frontend_close(monitor)
            and not dialog.yesno(HEADING, f"UMSA did not close.[CR]Delete {what} anyway?")):
        return False

    targets = maintenance_targets(get_core_data_paths(create=False), command)
    deleted, errors = _delete(targets)
    _log(f"{command}: deleted {deleted}, errors {errors}")
    if errors:
        dialog.notification(HEADING, "Could not delete " + "; ".join(errors),
                            xbmcgui.NOTIFICATION_ERROR, 6000)
    elif deleted:
        dialog.notification(HEADING, "Deleted " + ", ".join(deleted),
                            xbmcgui.NOTIFICATION_INFO, 4000)
    else:
        dialog.notification(HEADING, "Nothing to delete",
                            xbmcgui.NOTIFICATION_INFO, 4000)
    return bool(deleted)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "")
