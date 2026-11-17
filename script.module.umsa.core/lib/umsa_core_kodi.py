"""Kodi adapter of Core: profile paths, settings, shared window properties, notifications.

The only module of the Core add-on that imports Kodi.
"""

import dataclasses
import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from umsa_core import CoreDataPaths, SharedSettings
from umsa_core.window_properties import (
    EMULATOR_RUNNING_PROPERTY,
    FRONTEND_RUNNING_PROPERTY,
    SCREENSAVER_MANUAL_PROPERTY,
    SCREENSAVER_MODE_PROPERTY,
    SCREENSAVER_RUNNING_PROPERTY,
    SHARED_WINDOW_ID,
)

CORE_ADDON_ID = "script.module.umsa.core"

VGM_WINDOW_ID = 10000
VGM_INFO_PROPERTY = "UMSA.VGM.Info"
VGM_PLAYING_PROPERTY = "UMSA.VGM.Playing"
VGM_SENDER = CORE_ADDON_ID
VGM_ACTION_METHOD = "UMSA.VGM.Action"

SOFTWARE_OPEN_METHOD = "UMSA.Software.Open"
FRONTEND_CLOSE_METHOD = "UMSA.Frontend.Close"

# Used for extracted ROMs/CHDs when the rom_temp_dir setting is empty.
DEFAULT_ROM_TEMP_DIR = "special://temp/umsa"


def _recompute_screensaver_inhibition() -> None:
    """Inhibit Kodi's screensaver while an emulator or a manual UMSA screensaver runs.

    ``InhibitScreensaver(false)`` is sent only when no reason remains.
    """
    window = xbmcgui.Window(SHARED_WINDOW_ID)
    emulator_active = window.getProperty(EMULATOR_RUNNING_PROPERTY) == "true"
    screensaver_manual_active = window.getProperty(SCREENSAVER_MANUAL_PROPERTY) == "true"

    if emulator_active or screensaver_manual_active:
        xbmc.executebuiltin("InhibitScreensaver(true)")
    else:
        xbmc.executebuiltin("InhibitScreensaver(false)")


def set_emulator_running(running: bool) -> None:
    """Set or clear the emulator-running property and recompute the inhibition."""
    window = xbmcgui.Window(SHARED_WINDOW_ID)
    if running:
        window.setProperty(EMULATOR_RUNNING_PROPERTY, "true")
    else:
        window.clearProperty(EMULATOR_RUNNING_PROPERTY)
    _recompute_screensaver_inhibition()


def is_emulator_running() -> bool:
    return xbmcgui.Window(SHARED_WINDOW_ID).getProperty(EMULATOR_RUNNING_PROPERTY) == "true"


def set_screensaver_manual(manual: bool) -> None:
    """Set or clear the manual-screensaver property and recompute the inhibition.

    Manual means started by the user via ``RunScript``, not Kodi's idle
    screensaver. Only the screensaver itself sets it.
    """
    window = xbmcgui.Window(SHARED_WINDOW_ID)
    if manual:
        window.setProperty(SCREENSAVER_MANUAL_PROPERTY, "true")
    else:
        window.clearProperty(SCREENSAVER_MANUAL_PROPERTY)
    _recompute_screensaver_inhibition()


def clear_stale_screensaver_state() -> None:
    """Drop screensaver window properties a killed screensaver left behind.

    The screensaver clears ``Running``, ``Mode`` and ``Manual`` when it ends.
    After a hard kill they stay set until Kodi restarts: every later start
    reports another active instance and Kodi's idle screensaver stays
    inhibited. The frontend calls this once when it starts - no UMSA
    screensaver is alive then (its dialogs are modal and take every input).
    """
    window = xbmcgui.Window(SHARED_WINDOW_ID)
    names = (
        SCREENSAVER_RUNNING_PROPERTY,
        SCREENSAVER_MODE_PROPERTY,
        SCREENSAVER_MANUAL_PROPERTY,
    )
    stale = [name for name in names if window.getProperty(name)]
    if not stale:
        return
    xbmc.log(
        f"UMSA core: clearing stale screensaver state: {', '.join(stale)}",
        xbmc.LOGWARNING,
    )
    for name in stale:
        window.clearProperty(name)
    _recompute_screensaver_inhibition()


def get_core_data_paths(create: bool = True) -> CoreDataPaths:
    addon = xbmcaddon.Addon(id=CORE_ADDON_ID)
    profile_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    return CoreDataPaths(profile_path, create=create)


def get_core_vgmplay_script() -> str:
    addon = xbmcaddon.Addon(id=CORE_ADDON_ID)
    addon_path = xbmcvfs.translatePath(addon.getAddonInfo("path"))
    return os.path.join(addon_path, "resources", "vgmplay.lua")


def get_core_settings() -> SharedSettings:
    """Return all UMSA settings (they are owned by the Core add-on).

    An empty ``rom_temp_dir`` is replaced by the Kodi temp folder.
    """

    addon = xbmcaddon.Addon(id=CORE_ADDON_ID)
    settings = SharedSettings.from_raw(addon.getSetting)
    if not settings.rom_temp_dir:
        settings = dataclasses.replace(
            settings, rom_temp_dir=xbmcvfs.translatePath(DEFAULT_ROM_TEMP_DIR))
    return settings


def open_core_settings() -> None:
    """Open the UMSA settings dialog and return when it is closed.

    Blocking, so a caller (the frontend) can read the settings again
    afterwards.
    """

    xbmcaddon.Addon(id=CORE_ADDON_ID).openSettings()


def set_frontend_running(running: bool) -> None:
    """Mark the frontend window as open/closed for the maintenance script."""

    window = xbmcgui.Window(SHARED_WINDOW_ID)
    if running:
        window.setProperty(FRONTEND_RUNNING_PROPERTY, "true")
    else:
        window.clearProperty(FRONTEND_RUNNING_PROPERTY)


def is_frontend_running() -> bool:
    return xbmcgui.Window(SHARED_WINDOW_ID).getProperty(
        FRONTEND_RUNNING_PROPERTY) == "true"


def is_screensaver_running() -> bool:
    return bool(xbmcgui.Window(SHARED_WINDOW_ID).getProperty(
        SCREENSAVER_RUNNING_PROPERTY))


def request_frontend_close() -> None:
    xbmc.executebuiltin(f"NotifyAll({VGM_SENDER},{FRONTEND_CLOSE_METHOD})")


def is_frontend_close_method(method: str) -> bool:
    return method.endswith(FRONTEND_CLOSE_METHOD)


def publish_vgm_info(text: str, show: bool = True) -> None:
    """Publish the VGM info text and the playing flag on the shared window.

    The playing flag is always set, so the screensaver reacts to the VGM
    control keys also when the setting hides the text.
    """

    window = xbmcgui.Window(VGM_WINDOW_ID)
    window.setProperty(VGM_PLAYING_PROPERTY, "true")
    if show and text:
        window.setProperty(VGM_INFO_PROPERTY, text)
    else:
        window.clearProperty(VGM_INFO_PROPERTY)


def clear_vgm_info() -> None:
    window = xbmcgui.Window(VGM_WINDOW_ID)
    window.clearProperty(VGM_INFO_PROPERTY)
    window.clearProperty(VGM_PLAYING_PROPERTY)


def vgm_active() -> bool:
    return xbmcgui.Window(VGM_WINDOW_ID).getProperty(VGM_PLAYING_PROPERTY) == "true"


def send_vgm_action(action: str) -> None:
    """Ask the add-on owning the VGM process to run a control action.

    ``NotifyAll(sender, message)`` announces the message as
    ``Other.<message>``, so the action is appended to the method name and
    parsed back with :func:`parse_vgm_action_method`.
    """

    xbmc.executebuiltin(f"NotifyAll({VGM_SENDER},{VGM_ACTION_METHOD}.{action})")


def parse_vgm_action_method(method: str):
    """Return the VGM action of an ``onNotification`` method, else ``None``."""

    marker = f"{VGM_ACTION_METHOD}."
    index = method.find(marker)
    if index < 0:
        return None
    return method[index + len(marker):]


def send_software_open(software_id: int) -> None:
    """Ask a running frontend to select and display a software item.

    Announced as ``Other.<method>.<id>`` and parsed back with
    :func:`parse_software_open_method`.
    """

    xbmc.executebuiltin(
        f"NotifyAll({VGM_SENDER},{SOFTWARE_OPEN_METHOD}.{int(software_id)})")


def parse_software_open_method(method: str):
    """Return the software id of an ``onNotification`` method, else ``None``."""

    marker = f"{SOFTWARE_OPEN_METHOD}."
    index = method.find(marker)
    if index < 0:
        return None
    value = method[index + len(marker):]
    try:
        return int(value)
    except ValueError:
        return None


def make_abort_wait(monitor=None):
    """Return an abort-aware ``wait(milliseconds) -> bool`` for Core loops.

    The callback waits through ``Monitor.waitForAbort`` and returns ``True``
    as soon as Kodi asks the script to end (:data:`umsa_core.abort.Wait`).
    Pass the caller's own monitor; without one a new ``xbmc.Monitor`` is used.
    """

    if monitor is None:
        monitor = xbmc.Monitor()

    def wait(milliseconds):
        return bool(monitor.waitForAbort(max(0, milliseconds) / 1000.0))

    return wait
