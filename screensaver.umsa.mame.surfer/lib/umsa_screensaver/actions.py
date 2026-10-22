"""Kodi action dispatch of the screensaver window.

The window forwards every action to this module: the context menu hands
the shown software to the frontend, the video mode advances the playlist
and the image modes forward the volume/next/stop commands to the running
VGM music.
"""

from .constants import (
    ACTION_CONTEXT,
    ACTION_MOVEMENT_RIGHT,
    ACTION_PLAY_NEXTITEM,
    ACTION_STOP,
    ACTION_VOLUME_DOWN,
    ACTION_VOLUME_UP,
)

# Modes showing artwork
IMAGE_MODES = ('cross', 'wall', 'slide')


def _stop_saver(saver):
    """Stop the screensaver window."""

    saver.parent.reallyDeactivateScreensaver()
    saver.running = 'no'
    saver.close()


def _send_vgm_action(saver, action_id, kodi, send_vgm_action):
    """Send the VGM command of an action id.

    Returns ``True`` when a command was sent, ``False`` for every other
    action id - the caller then stops the screensaver.
    """

    if action_id == ACTION_VOLUME_UP:
        saver.parent.vgmaction = True
        send_vgm_action('volume_up')
        kodi.log("UMSA SSaver: sound volume + dont end saver", kodi.LOGDEBUG)
    elif action_id == ACTION_VOLUME_DOWN:
        saver.parent.vgmaction = True
        send_vgm_action('volume_down')
        kodi.log("UMSA SSaver: sound volume - dont end saver", kodi.LOGDEBUG)
    elif action_id in ACTION_PLAY_NEXTITEM+ACTION_MOVEMENT_RIGHT:
        saver.parent.vgmaction = True
        send_vgm_action('next')
        kodi.log("UMSA SSaver: next song - dont end saver", kodi.LOGDEBUG)
    elif action_id == ACTION_STOP:
        saver.parent.vgmaction = True
        send_vgm_action('stop')
    else:
        return False
    return True


def handle_action(saver, action, kodi, vgm_active, send_vgm_action):
    """Dispatch an action of the screensaver window.

    ``vgm_active`` tells whether a VGM track is running, ``send_vgm_action``
    forwards a command to it.
    """

    kodi.log(f"UMSA SSaver: onAction {saver.running}", kodi.LOGDEBUG)
    if saver.opening:
        kodi.log("UMSA SSaver: handoff already in progress, ignoring action", kodi.LOGDEBUG)
        return
    if saver.running == 'videos':
        # next video
        if action.getId() in ACTION_PLAY_NEXTITEM+ACTION_MOVEMENT_RIGHT:
            if not saver.add_video_to_playlist():
                # the database holds no video anymore: leave the video mode
                saver.handle_missing_video()
                return
            saver.parent.player.playnext()
        # show actual game in gui
        elif action.getId() in ACTION_CONTEXT:
            # software id hidden in votes
            s_id = None
            try:
                s_id = int(saver.parent.player.getVideoInfoTag().getVotes())
            except (TypeError, ValueError):
                kodi.log("UMSA SSaver: no software id for video context", kodi.LOGWARNING)
            saver.open_software(s_id)
            # stop the playback and release the playlist and the temp files
            saver.shutdown_video_mode()
            saver.running = 'no'
            saver.close()
        # volume change, do not quit
        elif action.getId() in (ACTION_VOLUME_UP, ACTION_VOLUME_DOWN):
            pass
        # else stop saver
        else:
            # stop the playback and release the playlist and the temp files
            saver.shutdown_video_mode()
            saver.running = 'no'
            saver.close()
    elif saver.running in IMAGE_MODES:
        # show actual game in gui
        if action.getId() in ACTION_CONTEXT:
            saver.open_software(saver.current_software_id)
            saver.parent.reallyDeactivateScreensaver()
            saver.running = 'no'
            saver.close()
        # allow changing volume with plus/minus
        # also allow playnext and right should button for next vgm
        elif vgm_active():
            if not _send_vgm_action(saver, action.getId(), kodi, send_vgm_action):
                _stop_saver(saver)
        else:
            _stop_saver(saver)
