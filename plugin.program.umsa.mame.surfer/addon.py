"""Kodi-managed frontend entry point."""

import os
import sys

import xbmc
import xbmcaddon
from umsa_core_kodi import get_core_data_paths

ADDON_ID = "plugin.program.umsa.mame.surfer"

xbmc.log(f"UMSA MAME surfer: startup - sys.argv: {sys.argv}")

CORE_DATA_PATHS = get_core_data_paths(create=False)

COMMAND = sys.argv[1] if len(sys.argv) > 1 else None

if COMMAND in (None, "select_software"):
    addon = xbmcaddon.Addon(id=ADDON_ID)
    sys.path.append(os.path.join(addon.getAddonInfo("path"), "resources", "lib"))
    # start frontend
    import gui  # noqa: F401
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
else:
    xbmc.log(f"UMSA MAME surfer: unknown action: {COMMAND}")
xbmc.log("UMSA MAME surfer: stopped")
