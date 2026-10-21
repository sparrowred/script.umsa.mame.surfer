"""Screensaver control and VGM information of the UMSA frontend.

The frontend can start and stop the standalone screensaver add-on and shows
the VGM information of the running playback.
"""

import xbmc
import xbmcgui
from umsa_core_kodi import clear_vgm_info, publish_vgm_info, set_screensaver_manual
from umsa_screensaver.arguments import encode_request

from .constants import MUSIC_INFO


def get_screensaver_mode(gui):
    """Return the active standalone screensaver mode, if any."""

    mode = xbmcgui.Window(10000).getProperty("UMSA.Screensaver.Mode")
    return mode or "no"


def start_screensaver(gui, mode, art_types=None):
    """Launch the standalone screensaver with a validated request token.

    Also activates the manual-screensaver inhibition reason so that Kodi's
    idle screensaver does not compete with the explicitly started instance.
    """
    token = encode_request(mode, art_types)
    xbmc.executebuiltin(
        f"RunScript(screensaver.umsa.mame.surfer,{token})"
    )
    set_screensaver_manual(True)


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
