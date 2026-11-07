"""Screensaver control and VGM information of the UMSA frontend.

The frontend can start and stop the standalone screensaver add-on and shows
the VGM information of the running playback.
"""

import xbmc
import xbmcgui
from umsa_core.screensaver_request import encode_request
from umsa_core.window_properties import SCREENSAVER_MODE_PROPERTY, SHARED_WINDOW_ID
from umsa_core_kodi import clear_vgm_info, publish_vgm_info, set_screensaver_manual

from .constants import MUSIC_INFO

# optional dependency in addon.xml: check before every start
SCREENSAVER_ADDON_ID = "screensaver.umsa.mame.surfer"


def screensaver_available():
    """True when the optional screensaver add-on is installed and enabled."""

    return bool(xbmc.getCondVisibility(
        f"System.HasAddon({SCREENSAVER_ADDON_ID}) + "
        f"System.AddonIsEnabled({SCREENSAVER_ADDON_ID})"))


def ensure_screensaver_available(gui):
    """Return True if the screensaver add-on can be started, else notify."""

    if screensaver_available():
        return True
    xbmc.log(f"UMSA gui: screensaver add-on {SCREENSAVER_ADDON_ID} is not "
             "installed or disabled", xbmc.LOGWARNING)
    gui.dialog.notification(
        "Screensaver", "screensaver add-on is not installed or disabled",
        xbmcgui.NOTIFICATION_WARNING, 5000)
    return False


def get_screensaver_mode(gui):
    """Return the active standalone screensaver mode, if any."""

    mode = xbmcgui.Window(SHARED_WINDOW_ID).getProperty(SCREENSAVER_MODE_PROPERTY)
    return mode or "no"


def start_screensaver(gui, mode, art_types=None):
    """Launch the standalone screensaver with a validated request token.

    Also activates the manual-screensaver inhibition reason so that Kodi's
    idle screensaver does not compete with the explicitly started instance.
    Returns False (after a notification) when the optional screensaver add-on
    is missing or disabled; then nothing is started and no inhibit is set.
    """
    token = encode_request(mode, art_types)
    if not ensure_screensaver_available(gui):
        return False
    xbmc.executebuiltin(f"RunScript({SCREENSAVER_ADDON_ID},{token})")
    set_screensaver_manual(True)
    return True


def stop_screensaver(gui):
    """Close an active standalone screensaver dialog.

    Also clears the manual-screensaver inhibition reason when the instance
    is stopped from the GUI.
    """
    if get_screensaver_mode(gui) != "no":
        xbmc.executebuiltin("Action(Close)")
    set_screensaver_manual(False)


def show_vgm_info(gui, message):
    """Publish VGM info to the shared window and to this window's label."""

    publish_vgm_info(message, show=gui.musicinfo)
    try:
        control = gui.getControl(MUSIC_INFO)
        control.setLabel(message)
        control.setVisibleCondition('True')
    except Exception as error:
        xbmc.log(f"UMSA gui: could not update VGM label: {error}", xbmc.LOGDEBUG)


def hide_vgm_info(gui):
    """Clear the shared VGM info and restore this window's music label."""

    clear_vgm_info()
    try:
        control = gui.getControl(MUSIC_INFO)
        control.setVisibleCondition('Player.HasAudio')
        control.setLabel(
            "$INFO[MusicPlayer.Artist] - $INFO[MusicPlayer.Title] "
            "(-$INFO[MusicPlayer.TimeRemaining])"
        )
    except Exception as error:
        xbmc.log(f"UMSA gui: could not reset VGM label: {error}", xbmc.LOGDEBUG)


def handle_vgm_action(gui, action):
    """Run a VGM control action requested by another add-on."""

    if not gui.emulation.playvgm:
        return
    xbmc.log(f"UMSA gui: VGM action from screensaver: {action}", xbmc.LOGDEBUG)
    if action == 'stop':
        gui.emulation.playrandomvgm = False
        clear_vgm_info()
        gui.emulation.send_vgmaction(b'exit')
    elif action == 'next':
        gui.emulation.send_vgmaction(b'exit')
    elif action in ('volume_up', 'volume_down'):
        gui.emulation.send_vgmaction(action.encode())
