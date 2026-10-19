"""Kodi-managed frontend entry point."""

import os
import sqlite3
import sys

import xbmc
import xbmcaddon
import xbmcgui
from umsa_core_kodi import get_core_data_paths

ADDON_ID = "plugin.program.umsa.mame.surfer"

xbmc.log(f"UMSA MAME surfer: startup - sys.argv: {sys.argv}")

CORE_DATA_PATHS = get_core_data_paths(create=False)

COMMAND = sys.argv[1] if len(sys.argv) > 1 else None

if COMMAND in (None, "select_software"):
    addon = xbmcaddon.Addon(id=ADDON_ID)
    sys.path.append(os.path.join(addon.getAddonInfo("path"), "resources", "lib"))
    # start frontend
    import gui
    gui.main()
elif COMMAND == "del_db":
    try:
        os.remove(CORE_DATA_PATHS.umsa_db)
        os.remove(CORE_DATA_PATHS.dat_db)
        os.remove(CORE_DATA_PATHS.artwork_db)
    except FileNotFoundError:
        pass
elif COMMAND == "del_status":
    try:
        os.remove(CORE_DATA_PATHS.status_db)
    except FileNotFoundError:
        pass
elif COMMAND == "retry_import":
    # Explicit recovery from a recorded `failed` legacy-import marker: the only
    # path that may clear it. A successful or cleanup-only marker is left alone.
    core_addon = xbmcaddon.Addon(id="script.module.umsa.core")
    sys.path.append(os.path.join(core_addon.getAddonInfo("path"), "lib"))
    from umsa_core.history_import import retry_import
    from umsa_core.sqlite import connect_sqlite
    from umsa_core.status_migrations import apply_migrations
    try:
        connection = connect_sqlite(CORE_DATA_PATHS.status_db)
        connection.row_factory = sqlite3.Row
        try:
            apply_migrations(connection)
            result = retry_import(connection, CORE_DATA_PATHS)
        finally:
            connection.close()
        xbmc.log(f"UMSA MAME surfer: retry_import -> {result}")
        if result.status in ("completed", "completed_discards", "completed_no_source"):
            message = f"Import retried: {result.status}"
            if result.discarded:
                message += "; discarded: " + ", ".join(result.discarded)
            if result.pending_cleanup:
                remaining = ", ".join(
                    os.path.basename(path) for path in result.pending_cleanup
                )
                message += f"; not removed: {remaining}"
            xbmcgui.Dialog().notification(
                "UMSA migration", message,
                xbmcgui.NOTIFICATION_INFO, 5000, False)
        else:
            detail = result.error or result.status
            if result.discarded:
                detail += "; discarded: " + ", ".join(result.discarded)
            xbmcgui.Dialog().notification(
                "UMSA migration", f"Import retry did not complete: {detail}",
                xbmcgui.NOTIFICATION_ERROR, 6000, False)
    except (sqlite3.Error, OSError, RuntimeError, ValueError) as exc:
        xbmc.log(f"UMSA MAME surfer: retry_import failed: {exc}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            "UMSA migration", f"Import retry failed: {exc}",
            xbmcgui.NOTIFICATION_ERROR, 6000, False)
else:
    xbmc.log(f"UMSA MAME surfer: unknown action: {COMMAND}")
xbmc.log("UMSA MAME surfer: stopped")
