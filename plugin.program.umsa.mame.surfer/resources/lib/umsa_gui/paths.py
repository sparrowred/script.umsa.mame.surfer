"""Add-on handle and paths shared by the UMSA frontend workflows.

The Kodi add-on handle is created once here so that the workflow modules and
``gui.py`` share a single instance (as before the split).
"""

import os

import xbmcaddon
import xbmcvfs

ADDON_ID = "plugin.program.umsa.mame.surfer"

ADDON = xbmcaddon.Addon(id=ADDON_ID)
ADDON_PATH = ADDON.getAddonInfo("path")
RESOURCE_LIB = xbmcvfs.translatePath(os.path.join(ADDON_PATH, "resources", "lib"))
SKIN_MEDIA_FOLDER = os.path.join(ADDON_PATH, "resources", "skins", "default", "media")
