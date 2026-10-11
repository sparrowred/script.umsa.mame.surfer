"""Kodi adapter for resolving the UMSA Core add-on profile and shared settings."""

import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from umsa_core import CoreDataPaths, SharedSettings

CORE_ADDON_ID = "script.module.umsa.core"

VGM_WINDOW_ID = 10000
VGM_INFO_PROPERTY = "UMSA.VGM.Info"
VGM_PLAYING_PROPERTY = "UMSA.VGM.Playing"
VGM_SENDER = CORE_ADDON_ID
VGM_ACTION_METHOD = "UMSA.VGM.Action"

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
    "ssaver_musicinfo",
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

    xbmc.executebuiltin(f"Addon.OpenSettings({CORE_ADDON_ID})")


def publish_vgm_info(text: str, show: bool = True) -> None:
    """Publish the current VGM info for all add-ons on the shared window.

    The playing flag is always set so consumers (e.g. the screensaver) can
    react to VGM control keys even when the info text is hidden by settings.
    """

    window = xbmcgui.Window(VGM_WINDOW_ID)
    window.setProperty(VGM_PLAYING_PROPERTY, "true")
    if show and text:
        window.setProperty(VGM_INFO_PROPERTY, text)
    else:
        window.clearProperty(VGM_INFO_PROPERTY)


def clear_vgm_info() -> None:
    """Clear the shared VGM info and playing flag."""

    window = xbmcgui.Window(VGM_WINDOW_ID)
    window.clearProperty(VGM_INFO_PROPERTY)
    window.clearProperty(VGM_PLAYING_PROPERTY)


def vgm_active() -> bool:
    """Return whether a VGM playback is currently active."""

    return xbmcgui.Window(VGM_WINDOW_ID).getProperty(VGM_PLAYING_PROPERTY) == "true"


def send_vgm_action(action: str) -> None:
    """Ask the add-on owning the VGM process to run a control action.

    NotifyAll(sender, message) announces the message as "Other.<message>",
    so the action is appended to the shared method name and parsed back by
    the owning add-on with parse_vgm_action_method().
    """

    xbmc.executebuiltin(f"NotifyAll({VGM_SENDER},{VGM_ACTION_METHOD}.{action})")


def parse_vgm_action_method(method: str):
    """Return the VGM action carried by an onNotification method, else None."""

    marker = f"{VGM_ACTION_METHOD}."
    index = method.find(marker)
    if index < 0:
        return None
    return method[index + len(marker):]
