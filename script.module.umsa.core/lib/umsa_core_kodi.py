"""Kodi adapter for resolving the UMSA Core add-on profile and shared settings."""

import os

import xbmcaddon
import xbmcvfs
from umsa_core import CoreDataPaths, SharedSettings

CORE_ADDON_ID = "script.module.umsa.core"

_SHARED_SETTING_IDS = (
    "mame",
    "mameini",
    "mamedir",
    "progetto",
    "otherart",
    "vgmplay",
    "datdir",
    "exodos",
    "gb64",
    "whdload",
    "aspectratio",
)


def get_core_data_paths(create: bool = True) -> CoreDataPaths:
    """Resolve the shared Core profile directory in Kodi."""

    addon = xbmcaddon.Addon(id=CORE_ADDON_ID)
    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    return CoreDataPaths(profile_path, create=create)


def get_core_vgmplay_script() -> str:
    """Resolve the VGM MAME script bundled with the Core add-on."""

    addon = xbmcaddon.Addon(id=CORE_ADDON_ID)
    addon_path = xbmcvfs.translatePath(addon.getAddonInfo("path"))
    return os.path.join(addon_path, "resources", "vgmplay.lua")


def get_core_settings() -> SharedSettings:
    """Read the shared settings owned by the Core add-on."""

    addon = xbmcaddon.Addon(id=CORE_ADDON_ID)
    return SharedSettings(
        **{name: addon.getSetting(name) for name in _SHARED_SETTING_IDS}
    )


def open_core_settings() -> None:
    """Open the Core add-on settings dialog from a consuming add-on."""

    import xbmc

    xbmc.executebuiltin(f"Addon.OpenSettings({CORE_ADDON_ID})")
