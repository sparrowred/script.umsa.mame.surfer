"""Kodi UI implementation for the standalone UMSA screensaver add-on.

The window classes stay here: they own the Kodi lifecycle (window
callbacks, playlist, controls) and delegate the work to the focused
modules next to them:

- ``actions`` - dispatch of the Kodi actions of the screensaver window
- ``artwork_selector`` - artwork types, path resolution, aspect handling
- ``availability`` - artwork availability check and mode planning
- ``constants`` - control ids, action codes, window properties
- ``history`` - screensaver display history
- ``image_validator`` - bad image detection, image size
- ``left_art`` - geometry of the left artwork in the overlay
- ``rendering`` - cross/slide/wall render loop, video label fading
- ``settings`` - screensaver settings model
- ``temp_video`` - eXoDOS video extraction and cleanup
- ``video_mute`` - silent start of the videos, restore of the Kodi sound
- ``video_playlist`` - playlist items and the unique id metadata
- ``wall_layout`` - wall geometry
"""

from collections import deque
from os import path
from time import monotonic

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from umsa_core_kodi import (
    get_core_settings,
    is_frontend_running,
    send_vgm_action,
    set_screensaver_manual,
    vgm_active,
)

from . import (
    actions,
    artwork_selector,
    availability,
    history,
    image_validator,
    left_art,
    rendering,
    temp_video,
    video_mute,
    video_playlist,
    video_session,
    wall_layout,
)
from . import settings as screensaver_settings
from . import strings as S
from .constants import (
    ACTION_CONTEXT,
    ACTION_MOVEMENT_RIGHT,
    ACTION_PLAY_NEXTITEM,
    BACKG,
    IMAGE,
    INFO_DETAIL,
    INFO_LABEL,
    KODI_SCREENSAVER_STOP_ALARM,
    LEFT_ART,
    MODE_PROPERTY,
    MODE_VIDEOS,
    OVERLAY_XML,
    PIC_MACHINE,
    SAVER_XML,
    SKIN_NAME,
    SKIN_RESOLUTION,
    WINDOW_ID,
)
from .image_validator import PIL
from .strings import tr
from .video_playlist import (
    attach_set_id,
    read_set_id,
    read_software_id,
)

__all__ = [
    'ACTION_CONTEXT',
    'ACTION_MOVEMENT_RIGHT',
    'ACTION_PLAY_NEXTITEM',
    'BACKG',
    'IMAGE',
    'INFO_DETAIL',
    'INFO_LABEL',
    'LEFT_ART',
    'MEDIA_FOLDER',
    'PIC_MACHINE',
    'PIL',
    'Monitor',
    'Overlay',
    'Player',
    'Saver',
    'attach_set_id',
    'read_set_id',
]

__addon__ = xbmcaddon.Addon(id='screensaver.umsa.mame.surfer')

MEDIA_FOLDER = xbmcvfs.translatePath(path.join(
    __addon__.getAddonInfo('path'), 'resources', 'skins', 'default', 'media'))

# log levels of the Kodi-free helper modules
_LOG_LEVELS = {
    'debug': xbmc.LOGDEBUG,
    'info': xbmc.LOGINFO,
    'warning': xbmc.LOGWARNING,
    'error': xbmc.LOGERROR,
}


def _log(message, level='debug'):
    """Write a message of a Kodi-free helper module to the Kodi log."""

    xbmc.log(message, _LOG_LEVELS.get(level, xbmc.LOGDEBUG))


class Overlay(xbmcgui.WindowXMLDialog):
    """Transparent foreground window above the screensaver window.

    Kodi hands the input to the topmost dialog, so every action is
    forwarded to the saver - the overlay never handles input itself.
    """

    def __init__(self, *args, **kwargs):
        self.saver = kwargs['saver']

    def onAction(self, action):
        """Forward the action to the screensaver window.

        ``super().onAction`` is not called on purpose: Kodi's default
        would close only the overlay on a back action.
        """

        xbmc.log(
            f"UMSA SSaver overlay: forwarding action {action.getId()}",
            xbmc.LOGDEBUG)
        self.saver.onAction(action)


class Saver(xbmcgui.WindowXMLDialog):
    """Screensaver implementation.

    Opens a new Kodi Window with it's on skin

    IMPORTANT: as soon as video plays the kodi screensaver mode gets deactivated
    this means we still need to feed the playlist and wait for interaction from user
    to stop playing videos
    """

    def __init__(self, *args, **kwargs):
        self.parent = kwargs['itself']
        self.__addon__ = xbmcaddon.Addon(id='screensaver.umsa.mame.surfer')
        self.playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        self.running = "no"
        self.art_types: list | None = []
        self.wall = {}
        self.settings = {}
        # identity of the software currently on screen, for the handoff
        self.current_software_id = None
        # guard so one ContextMenu does not dispatch twice
        self.opening = False
        # the controls this saver created dynamically (cross pictures, wall mesh)
        self._dynamic_controls = []
        # the wall layout exists exactly once per wall session
        self._wall_created = False
        # the extracted video that is playing right now
        self._active_temp_video = None
        # the videos this saver added to the playlist
        self._video_playlist_urls = []
        # the video mode was torn down (or is being torn down)
        self.video_teardown = False
        # whether the screensaver owns the current video playback
        self._playback_owned = False
        # known broken images, the list depends on the Pillow support
        self.bad_image_list = list(image_validator.bad_image_list(PIL))
        # the timed mode switch only rotates an automatically started saver
        self.rotate_modes = False
        # start of the current video mode (monotonic clock), for the switch
        self._video_started = None
        # the mode that follows the videos once the last queued one ended
        self._pending_mode = None
        # "next video" found no video: the video loop leaves the video mode
        self._video_fallback_requested = False
        # Kodi asked the script to end and the shutdown has started
        self._aborting = False
        # the Kodi mute of the silent videos (ssaver_video_mute)
        self._video_mute = video_mute.VideoMute(xbmc.executeJSONRPC, _log)
        # the transparent foreground window with the game and music info,
        # shown while this window is open
        self._overlay = Overlay(
            OVERLAY_XML, self.__addon__.getAddonInfo('path'),
            SKIN_NAME, SKIN_RESOLUTION, saver=self)
        self._overlay_shown = False

        self.read_settings()

    def onInit(self):
        """Kodi onInit"""

        xbmc.log("UMSA SSaver: onInit", xbmc.LOGDEBUG)
        # Clear the Kodi video playlist to remove stale entries from previous
        # screensaver sessions. This is done once during initialization.
        self.playlist.clear()
        # the render loop runs inside onInit and fills the overlay controls:
        # show the overlay first
        self.show_overlay()
        self.get_art_and_call_saver()

    def onAction(self, action):
        """Kodi onAction"""

        actions.handle_action(
            self, action, kodi=xbmc,
            vgm_active=vgm_active,
            send_vgm_action=send_vgm_action,
            can_start_vgm=self.can_start_vgm)

    def can_start_vgm(self):
        """True when the frontend can start the random VGM playback.

        The playback belongs to the frontend, so it must be running; a VGM
        on top of Kodi's music is not wanted.
        """

        return is_frontend_running() and not self.parent.player.isPlayingAudio()

    def show_overlay(self):
        """Show the foreground overlay once per window session."""

        if self._overlay_shown:
            return
        try:
            self._overlay.show()
            self._overlay_shown = True
            self.apply_overlay_settings()
        except Exception as error:  # noqa: BLE001 - logged, the render loop reports the missing controls
            xbmc.log(
                f"UMSA SSaver: could not show the overlay: {error}",
                xbmc.LOGERROR)

    def apply_overlay_settings(self):
        """Hide the parts of the overlay the user switched off.

        ``ssaver_info`` hides the game info (name, year/maker, machine and
        left picture), the Core setting ``show_music_info`` the Kodi music
        line; the VGM info follows ``show_music_info`` already, the
        frontend does not publish it then. Both are on by default.
        """

        hidden = {
            'GameInfo.Hidden': not self.settings.get('info', True),
            'MusicInfo.Hidden': not self.settings.get('music_info', True),
        }
        for name, value in hidden.items():
            self._overlay.setProperty(name, 'true' if value else 'false')

    def close_overlay(self):
        """Close the foreground overlay; repeated calls are safe."""

        if not self._overlay_shown:
            return
        self._overlay_shown = False
        try:
            self._overlay.close()
        except Exception as error:  # noqa: BLE001 - the cleanup must not raise
            xbmc.log(
                f"UMSA SSaver: could not close the overlay: {error}",
                xbmc.LOGWARNING)

    def overlay_control(self, control_id):
        """Return a control of the foreground overlay.

        The game info, the left snap and the machine picture live in the
        overlay, not in this window.
        """

        return self._overlay.getControl(control_id)

    def show_left_art(self, filename, kind=left_art.ARTWORK, display=None, use_cache=True):
        """Show the small artwork in the bottom left corner of the overlay.

        The control is sized to the aspect ratio of the artwork: a game
        screen (``left_art.SCREEN``) gets 4:3 or 3:4 from its ``display``
        orientation, every other artwork keeps the proportions of its file.
        An empty ``filename`` clears the picture.
        """

        control = self.overlay_control(LEFT_ART)
        if not filename:
            control.setImage('')
            return
        aspect = left_art.target_aspect(
            kind, display, image_validator.image_size(filename))
        pos_x, pos_y, width, height = left_art.fit_rect(
            aspect, self.settings['ar_norm'], self.settings['ar_x'])
        control.setPosition(pos_x, pos_y)
        control.setWidth(width)
        control.setHeight(height)
        control.setImage(filename, use_cache)

    def set_label_fade(self, value):
        """Fade the game info of the overlay in (``'0'``) or out (``'1'``)."""

        self._overlay.setProperty('LabelView.Fade', value)

    def hide_label_now(self):
        """Hide the game info at once, without the fade-out.

        Called before new content goes into the game info: a fade-out that
        is still running would show the new name and pictures for a moment.
        The skin only fades out for ``'1'``; an empty value hides at once.
        """

        self._overlay.setProperty('LabelView.Fade', '')

    def close(self):
        """Close the overlay first, then the screensaver window.

        Every close path of the screensaver ends here, so the overlay
        never outlives the window.
        """

        self.close_overlay()
        super().close()

    def addControl(self, control):
        """Add a control to the window and remember it.

        Every control the screensaver creates dynamically is tracked, so
        the cleanup path can remove all of them again.
        """

        super().addControl(control)
        if control not in self._dynamic_controls:
            self._dynamic_controls.append(control)

    def removeControl(self, control):
        """Remove a control from the window and forget it."""

        super().removeControl(control)
        if control in self._dynamic_controls:
            self._dynamic_controls.remove(control)

    def remove_dynamic_controls(self):
        """Remove every control this saver created dynamically.

        The controls are removed through the normal cleanup path, also
        when a mode is left exceptionally.
        """

        for control in list(self._dynamic_controls):
            try:
                self.removeControl(control)
            except Exception as error:  # noqa: BLE001 - the cleanup must not raise
                xbmc.log(
                    f"UMSA SSaver: could not remove control: {error}",
                    xbmc.LOGWARNING)
        self._dynamic_controls = []

    def remember_art(self, art):
        """Remember the software id of the artwork being rendered."""

        self.current_software_id = art['s_id'] if art else None

    def record_display(self, art):
        """Record the displayed set in the shared screensaver history.

        Called once per completed cross/slide/wall render, after the
        display-success boundary and before the wait loop. A missing or
        invalid ``set_id`` is ignored; database failures are logged and never
        allowed to break rendering. Returns ``True`` only when the history
        write succeeded.
        """

        return history.record_display(self.parent.umsa.ggdb, art, kodi=xbmc)

    def open_software(self, software_id):
        """Hand the currently displayed software to the frontend.

        A missing or invalid identifier is logged and ignored; the caller
        still dismisses the screensaver without selecting anything else.
        """

        self.opening = True
        if software_id is None:
            xbmc.log("UMSA SSaver: no displayed software for context handoff", xbmc.LOGWARNING)
            return
        try:
            self.parent.umsa.open_software(int(software_id))
        except (TypeError, ValueError):
            xbmc.log(
                f"UMSA SSaver: invalid software id for handoff: {software_id!r}",
                xbmc.LOGWARNING,
            )
        except Exception as error:  # noqa: BLE001 - never break screensaver dismissal
            xbmc.log(f"UMSA SSaver: software handoff failed: {error}", xbmc.LOGERROR)

    def read_settings(self):
        """Read shared Core settings and screensaver-specific settings."""

        core_settings = get_core_settings()
        self.path = (core_settings.own_artwork_dir, core_settings.progettosnaps_dir)
        parsed = screensaver_settings.ScreensaverSettings.from_addon(
            self.__addon__, core_settings)
        self.settings = parsed.as_legacy_dict()

    def notify_user(self, message):
        """Show a short notification to the user."""

        xbmc.executebuiltin(
            f'XBMC.Notification({tr(S.NOTIFICATION_HEADING)},{message},3000)')

    def set_mode_property(self, mode):
        """Publish the running mode on the shared window."""

        xbmcgui.Window(WINDOW_ID).setProperty(MODE_PROPERTY, mode)

    def check_snapshot(self, snapshot):
        """Return true when snapshot is Ok.

        Ok means it's not in the bad list and not only one color.
        """

        return image_validator.check_snapshot(
            snapshot,
            bad_images=self.bad_image_list,
            pil_available=PIL,
            kodi=xbmc)

    def get_machine_pic(self, use_set):
        """Return full path for a machine picture based on set

        Scanned cabinets from the artwork database first (own artwork before
        progettosnaps), internal pictures for pinballs, reels and arcade.
        """

        umsa = self.parent.umsa
        return artwork_selector.machine_picture(
            use_set, umsa.ggdb, artwork_selector.source_roots(self.path, umsa),
            MEDIA_FOLDER)

    def get_set_artwork(self, art, art_type, source_roots):
        """Return an artwork of the set of ``art`` from the artwork database.

        Core's ``DBMod.get_set_artwork``: the set itself, else its parent,
        else another clone; own artwork first. ``''`` when none is found.
        """

        return self.parent.umsa.ggdb.get_set_artwork(art['id'], art_type, source_roots)

    def resolve_art_path(self, art, source_roots):
        """Resolve the path of an artwork row with the shared Core resolver.

        ``art`` carries the ``art_set`` fields (source, root_key,
        relative_path, archive_member).
        """

        return artwork_selector.resolve_art_path(art, source_roots)

    def _extract_exodos_video(self, art, source_roots):
        """Extract an eXoDOS videosnap from a ZIP archive to Kodi's temp directory.

        Args:
            art: Artwork metadata dict with source, relative_path, archive_member, id (set_id)
            source_roots: Mapping of source names to root paths

        Returns:
            Extracted file path (str) or None if extraction failed or not applicable
        """
        if not temp_video.is_archive_videosnap(art):
            return None
        return temp_video.extract_exodos_video(
            art, source_roots, xbmcvfs, xbmc)

    def cleanup_temp_videos(self):
        """Remove the leftover files of the screensaver temp directory.

        The directory is inspected directly, so incomplete files of a
        failed extraction are removed as well. The directory itself is
        kept.
        """

        temp_video.cleanup_temp_dir(xbmcvfs, xbmc)

    def note_playing_video(self, playing_file):
        """Remember the extracted video that is playing right now.

        Only files of the screensaver temp directory are tracked: they are
        the ones the screensaver may delete when the video ends.
        """

        if playing_file and temp_video.is_in_temp_dir(playing_file, xbmcvfs):
            self._active_temp_video = playing_file
        else:
            self._active_temp_video = None

    def release_playing_video(self):
        """Delete the extracted file of the video that just ended.

        A file that is still queued for playback is never touched: only
        the video that was playing is released.
        """

        file_path = self._active_temp_video
        self._active_temp_video = None
        if not file_path:
            return
        temp_video.delete_temp_file(file_path, xbmcvfs, xbmc)

    def add_video_to_playlist(self):
        """Add a new video to the playlist.

        Returns ``True`` when a video was queued and ``False`` when the
        database holds no video at all - the caller decides what to do
        then.

        Skips candidates that cannot be played (e.g. failed eXoDOS extraction)
        and tries the next random video, up to a bounded number of attempts.
        """

        xbmc.log("UMSA SSaver: add video to playlist", xbmc.LOGDEBUG)
        source_roots = artwork_selector.source_roots(
            self.path, self.parent.umsa)

        # Try up to 10 candidates to handle cases where some videos
        # are not playable (e.g. failed eXoDOS extraction)
        for _attempt in range(10):
            rand_vid = self.parent.umsa.ggdb.get_random_art(['videosnaps'])
            if not rand_vid:
                xbmc.log("UMSA SSaver: did not find any videos", xbmc.LOGWARNING)
                return False

            # For eXoDOS archive videos, extract to temp instead of using zip:// URL.
            # If extraction is required (archive_member present) and fails, reject
            # this candidate - do not fall back to the archive-backed path.
            if temp_video.is_archive_videosnap(rand_vid):
                filename = self._extract_exodos_video(rand_vid, source_roots)
                if filename is None:
                    xbmc.log(
                        f"UMSA SSaver: required extraction failed for eXoDOS video "
                        f"(set_id={rand_vid.get('id')}, member={rand_vid.get('archive_member')}), "
                        "trying next candidate",
                        xbmc.LOGWARNING)
                    continue  # Try next candidate
            else:
                filename = self.resolve_art_path(rand_vid, source_roots)
                if not filename:
                    xbmc.log("UMSA SSaver: no playable video file found, trying next candidate", xbmc.LOGWARNING)
                    continue  # Try next candidate

            xbmc.log(f"UMSA SSaver: videoadd: added {filename}", xbmc.LOGDEBUG)
            machine_pic = self.get_machine_pic(rand_vid)
            # left picture: flyer/cover (eXoDOS/GB64 bring it along)
            snapshot = rand_vid.get('left_pic') or self.get_set_artwork(
                rand_vid, artwork_selector.left_picture_type(rand_vid), source_roots)
            xbmc.log(f"UMSA SSaver {snapshot}", xbmc.LOGDEBUG)
            video_item = video_playlist.build_video_item(
                rand_vid, machine_pic, snapshot, attach_set_id, xbmcgui)
            self.playlist.add(url=filename, listitem=video_item)
            self._video_playlist_urls.append(filename)
            xbmc.log(f"UMSA SSaver: playlist size {self.playlist.size()}, pos {self.playlist.getposition()}", xbmc.LOGDEBUG)
            return True

        xbmc.log("UMSA SSaver: exhausted candidate attempts, no playable video found", xbmc.LOGWARNING)
        return False

    def stop_video_playback(self):
        """Stop the video playback of the screensaver.

        Only stops playback when the screensaver owns it (i.e. started it).
        """

        if not self._playback_owned:
            return
        player = getattr(self.parent, 'player', None)
        if player is None:
            return
        try:
            player.stop()
        except Exception as error:  # noqa: BLE001 - stopping must never raise
            xbmc.log(
                f"UMSA SSaver: could not stop the video playback: {error}",
                xbmc.LOGWARNING)

    def mute_videos(self):
        """Prepare the sound before the videos start.

        With ``ssaver_video_mute`` Kodi is muted. Videos with sound would
        play on top of a running UMSA VGM (single track or random playback
        of the frontend), so the VGM is stopped instead.
        """

        if self.settings.get('video_mute'):
            self._video_mute.mute()
        elif vgm_active():
            xbmc.log("UMSA SSaver: videos with sound, stopping the VGM playback",
                     xbmc.LOGINFO)
            send_vgm_action('stop')

    def restore_video_sound(self):
        """Give Kodi its sound back when the screensaver muted it.

        Called after the video playback stopped; repeated calls are safe.
        """

        self._video_mute.restore()

    def shutdown_video_mode(self):
        """Stop the video playback and clean up temporary files.

        Called when the screensaver really exits: the playback is stopped
        (only if the screensaver owns it) and the temporary files are
        cleaned up afterwards. The Kodi video playlist is NOT cleared -
        the user's playlist entries are preserved. Repeated calls are safe.
        """

        if self.video_teardown:
            return
        self.video_teardown = True
        xbmc.log("UMSA SSaver: shutting the video mode down", xbmc.LOGDEBUG)
        self.stop_video_playback()
        self._playback_owned = False
        self.restore_video_sound()
        # Do not clear the playlist - the user's playlist must not be modified.
        # Only clean up temporary files that are no longer needed.
        self.cleanup_temp_videos()

    def reset_render_state(self):
        """Drop the artwork and the controls of the previous mode."""

        self.remove_dynamic_controls()
        self.wall = {}
        self._wall_created = False
        self.art_types = None
        self.current_software_id = None

    def prepare_artwork_mode(self):
        """Prepare the screensaver for an artwork mode.

        The obsolete video playback is stopped and the artwork and the
        controls of the previous mode are reset. An artwork mode whose
        artwork is available is selected - the configured image modes
        come first.

        Returns the new mode or ``None`` when no artwork is available.
        """

        xbmc.log("UMSA SSaver: preparing an artwork mode", xbmc.LOGDEBUG)
        self.stop_video_playback()
        self._playback_owned = False
        self.restore_video_sound()
        candidates = availability.image_fallback_modes(
            self.parent.umsa.ggdb, list(self.settings.get('type') or []))
        if not candidates:
            xbmc.log(
                "UMSA SSaver: no artwork mode with available artwork",
                xbmc.LOGWARNING)
            return None
        mode = screensaver_settings.choose_mode(candidates)
        self.reset_render_state()
        self.running = mode
        self.art_types = None
        self.set_mode_property(mode)
        xbmc.log(f"UMSA SSaver: switched to the {mode} mode", xbmc.LOGINFO)
        return mode

    def request_video_fallback(self):
        """Ask the video loop to leave the video mode: no video was found.

        Called from an action ("next video"). Only a flag is set: the video
        loop (``video_session.VideoSession``) switches to an artwork mode,
        so no render loop starts inside a Kodi callback.
        """

        xbmc.log(
            "UMSA SSaver: no screensaver video found while running",
            xbmc.LOGWARNING)
        self._video_fallback_requested = True

    def take_video_fallback_request(self):
        """Return and clear the request of ``request_video_fallback``."""

        requested = getattr(self, '_video_fallback_requested', False)
        self._video_fallback_requested = False
        return requested

    def abort_requested(self):
        """Return whether Kodi asked this script to end.

        Kodi sets the abort flag (``trigger Monitor abort request``) and
        kills the script 5 s later; a script with open modal dialogs and a
        running playback hung Kodi then. Errors count as no request.
        """

        try:
            return bool(self.parent.abortRequested())
        except Exception:  # noqa: BLE001 - a stand-in parent has no abort flag
            return False

    def abort_screensaver(self, reason):
        """End the screensaver because Kodi asked the script to end.

        The playback is stopped, the sound restored and the extracted
        videos removed (``reallyDeactivateScreensaver``). The loop of the
        running mode (video loop or render loop) sees ``running == 'no'``
        and ends; ``get_art_and_call_saver`` closes the windows in its
        ``finally``. Repeated calls are safe.
        """

        if self._aborting:
            return
        self._aborting = True
        xbmc.log(f"UMSA SSaver: Kodi asked to stop ({reason}), shutting down", xbmc.LOGWARNING)
        self.parent.reallyDeactivateScreensaver()

    def finish_screensaver(self):
        """Release the screensaver resources and close the window."""

        self.shutdown_video_mode()
        self.remove_dynamic_controls()
        self.close()
        xbmc.log("UMSA SSaver - call screensaver deactivate", xbmc.LOGINFO)
        self.parent.onScreensaverDeactivated()

    def _reset_session_state(self):
        """Reset state that must be cleared at the start of each new screensaver session.

        The Saver instance is reused across multiple activations (the Monitor
        creates it once and calls doModal() each time). This method ensures
        that session-specific flags like video_teardown are cleared so that
        a new session can start playback and handle callbacks normally.
        """
        self.video_teardown = False
        self._playback_owned = False
        self._active_temp_video = None
        self._video_playlist_urls = []
        self.running = "no"
        self.art_types = None
        self.current_software_id = None
        self.opening = False
        self._video_started = None
        self._pending_mode = None
        self._video_fallback_requested = False
        self._aborting = False

    def next_rotation_mode(self):
        """Return the image mode the timed mode switch continues with.

        ``None`` keeps the current mode: no other configured image mode has
        artwork, or the availability check failed.
        """

        configured = list(self.settings.get('type') or [])
        try:
            candidates = availability.rotation_candidates(
                self.parent.umsa.ggdb, configured,
                include_videos=self._videos_may_rotate())
        except availability.AvailabilityError as error:
            xbmc.log(
                f"UMSA SSaver: mode switch check failed, keeping {self.running}: {error}",
                xbmc.LOGWARNING)
            return None
        mode = availability.next_rotation_mode(self.running, candidates)
        if mode is None:
            xbmc.log(
                f"UMSA SSaver: no other mode with artwork, keeping {self.running}",
                xbmc.LOGINFO)
        return mode

    def _videos_may_rotate(self):
        """Return whether the video mode may join the timed mode switch.

        Only muted videos rotate (``ssaver_video_mute``), and never while
        Kodi music or a VGM track plays: a starting video would stop them.
        """

        if not self.settings.get('video_mute'):
            return False
        return not (self.parent.player.isPlayingAudio() or vgm_active())

    def mark_video_start(self):
        """Start the mode time of the video mode (playback was started)."""

        self._video_started = monotonic()

    def video_mode_expired(self):
        """Return whether the muted video mode ran for its mode time.

        Like the image modes, only an automatically started screensaver
        rotates, and only muted videos leave the mode on time.
        """

        minutes = self.settings.get('mode_switch_minutes') or 0
        if (minutes <= 0 or not self.rotate_modes or self._video_started is None
                or not self.settings.get('video_mute')):
            return False
        return monotonic() - self._video_started >= minutes * 60

    def start_video_drain(self):
        """Let the video mode run out when its mode time is up.

        Called at the end of a video. No further video is queued: the one
        Kodi just started is the last of the playlist. When it ends, Kodi
        ends the playlist by itself and resets its playlist player - only
        then does the next fullscreen start work again. Stopping the next
        video right after Kodi started it would leave that reset out, and
        every later video would play in the small video window of the skin.

        Returns ``False`` when no other mode is available: the videos
        continue and their mode time starts again.
        """

        next_mode = self.next_rotation_mode()
        if next_mode is None or next_mode == MODE_VIDEOS:
            self.mark_video_start()
            return False
        self._pending_mode = next_mode
        xbmc.log(
            f"UMSA SSaver: video time is up, {next_mode} follows after the last queued video",
            xbmc.LOGINFO)
        return True

    def video_drain_done(self):
        """Return whether the videos ran out and the next mode is waiting."""

        return self._pending_mode is not None

    def end_video_drain(self):
        """Finish the run-out video mode and return the waiting mode.

        Called by the video loop at the end of the last queued video: the
        playlist has ended, Kodi has reset its playlist player. A video the
        user started with "next" is still stopped. The sound is restored
        and the extracted videos removed; ``run_render_sessions`` then
        enters the returned mode.
        """

        next_mode = self._pending_mode
        self._pending_mode = None
        self.stop_video_playback()
        self._playback_owned = False
        self.restore_video_sound()
        self.cleanup_temp_videos()
        self._video_started = None
        return next_mode

    def enter_next_mode(self, mode):
        """Switch from the finished mode to ``mode`` (timed mode switch).

        The render session of the old mode has already cleaned up its
        pictures. The dynamic controls, the wall and the slide/background
        properties of the old mode are reset, so nothing carries over.
        """

        xbmc.log(
            f"UMSA SSaver: mode time is up, switching from {self.running} to {mode}",
            xbmc.LOGINFO)
        self.reset_render_state()
        for name in ('SlideView.Slide1', 'SlideView.Slide2',
                     'SlideView.Fade11', 'SlideView.Fade12'):
            self.clearProperty(name)
        self.hide_label_now()
        self.running = mode
        self.set_mode_property(mode)

    def run_render_sessions(self):
        """Run one session per mode until the screensaver stops.

        One session runs at a time: the video loop for the video mode, a
        render session for an image mode. When the timed mode switch ends a
        session (``next_mode``) or the video mode fell back to an artwork
        mode, the next mode starts in a new session - no recursion and no
        loop inside a Kodi player callback.
        """

        while self.running != 'no':
            mode = self.running
            if mode == MODE_VIDEOS:
                session = video_session.VideoSession(self, kodi=xbmc)
            else:
                session = rendering.RenderSession(self, gui=xbmcgui, kodi=xbmc)
            session.run()
            if self.running == 'no':
                return
            if session.next_mode is not None:
                self.enter_next_mode(session.next_mode)
            elif self.running == mode:
                # the session ended without a stop and without another mode
                return

    def get_art_and_call_saver(self):
        """ Get artwork and call Screensaver """

        try:
            self.run_render_sessions()
        finally:
            # Ensure finish_screensaver is called even if a session raises
            # an unexpected exception. The render session's own finally
            # block cleans up dynamic controls; this ensures the outer
            # lifecycle (video teardown, window close) runs too.
            self.finish_screensaver()

    def _available_wall_art_types(self):
        """Return the wall artwork types the artwork database holds.

        A failed availability check counts as "everything available": the
        wall then follows the setting and the render loop handles missing
        artwork.
        """

        ggdb = self.parent.umsa.ggdb
        try:
            return [
                art_type for art_type in wall_layout.WALL_ART_TYPES
                if availability.has_artwork(ggdb, [art_type])]
        except availability.AvailabilityError as error:
            xbmc.log(
                f"UMSA SSaver: wall artwork check failed: {error}",
                xbmc.LOGWARNING)
            return list(wall_layout.WALL_ART_TYPES)

    def create_wall(self):
        """Create UI elements for wall mode depending on settings.

        - count evspace and ehspace together / 2 and then calc again with new space, see 4 rows
        - fade out and in so the background can be seen
        - in wall mode make one position a video

        The controls are created exactly once per wall session: a second
        call does nothing. A new wall session (mode change) starts from
        ``reset_render_state`` and lays the wall out again.
        """

        if self._wall_created:
            xbmc.log("UMSA SSaver: wall already created", xbmc.LOGDEBUG)
            return
        rows, art_types, known = wall_layout.resolve_wall(
            self.settings['wall'], self._available_wall_art_types())
        if not known:
            xbmc.log(
                "UMSA SSaver: unknown wall titles mode "
                f"{self.settings['wall']['titles']!r}, showing snaps",
                xbmc.LOGWARNING)
        self.wall['art_types'] = art_types
        grid = wall_layout.compute_grid(
            rows, self.settings['ar_norm'], self.settings['ar_x'])
        # width, height and the vertical image geometry
        self.wall['width'] = grid['width']
        self.wall['height'] = grid['height']
        self.wall['vert_width'] = grid['vert_width']
        self.wall['vert_x'] = grid['vert_x']
        # create lists
        self.wall['pics'] = grid['pics']
        self.wall['pos'] = list(range(self.wall['pics']))
        # one stretch and one keep control per cell, created once and reused
        # by render_wall for every picture of this wall session
        self.wall['cells'] = wall_layout.cell_positions(
            rows, grid['cols'], grid['width'], grid['height'], grid['evspace'])
        self.wall['slots'] = []
        for pos_x, pos_y in self.wall['cells']:
            slot = {
                wall_layout.STRETCH: xbmcgui.ControlImage(
                    pos_x, pos_y, self.wall['width'], self.wall['height'], ''),
                wall_layout.KEEP: xbmcgui.ControlImage(
                    pos_x, pos_y, self.wall['width'], self.wall['height'], '', 2),
            }
            for control in slot.values():
                self.addControl(control)
            self.wall['slots'].append(slot)

        # shuffle position list
        wall_layout.shuffle_positions(self.wall['pos'])
        # how many free
        if self.settings['wall']['free'] == 0:
            self.wall['free'] = 0
        else:
            self.wall['free'] = wall_layout.free_slot_count(
                self.wall['pics'], self.settings['wall']['free'])
            self.wall['freelist'] = []

        self._wall_created = True


class Player(xbmc.Player):
    """Kodi Video Player Class

    Reacts to:
     onPlayBackStarted
     onAVStarted
     onPlayBackEnded / onPlayBackStopped / onPlayBackError

    Used by video screensaver as Kodi Monitor ends when a video is started.

    The callbacks stay short: start and end of a playback only put an event
    into ``events``. The video loop (``video_session.VideoSession``) takes
    the events and does the work - queueing the next video, the labels,
    the mode switch. Kodi delivers the callbacks inside the ``sleep`` of
    that loop, so a callback that waited itself would nest the following
    callbacks.

    History recording happens only in ``onAVStarted``: that callback is the
    Kodi-recommended point at which an actual audio/video stream exists,
    whereas ``onPlayBackStarted`` may fire while the item is merely queued or
    not yet delivering a stream. Nothing is ever recorded at enqueue time.
    """

    # events nobody takes (playback outside the video mode) must not pile up
    MAX_EVENTS = 64

    def __init__(self, **kwargs):
        self.parent = kwargs['itself']
        # per-playback-instance bookkeeping: the instance counter is bumped
        # by onPlayBackStarted, the guard identifies the playlist item whose
        # history has already been recorded (or deliberately skipped).
        self._playback_instance = 0
        self._history = history.PlaybackHistoryGuard()
        # per-playback-instance completion guard: prevents duplicate processing
        # of onPlayBackEnded/onPlayBackStopped/onPlayBackError for the same
        # playback instance. Key is the playback instance number, value is True
        # once finalization has run.
        self._playback_finalized = set()
        # (kind, playback instance, playing file) for the video loop
        self.events = deque(maxlen=self.MAX_EVENTS)

    def take_events(self):
        """Return the queued player events, oldest first, and clear them."""

        events = list(self.events)
        self.events.clear()
        return events

    def get_playing_file(self):
        """Return the file that is playing, or ``None``."""

        try:
            return self.getPlayingFile()
        except RuntimeError:
            return None

    def onAVStarted(self):
        """Record the displayed video once a stream is actually available.

        Exactly once per playback instance (deduplicated by the instance
        token) and only while the screensaver runs in video mode. Missing or
        invalid ``umsa_set_id`` metadata (including Kodi < 20, which has no
        unique-ID API) and database failures are logged without disrupting
        playback; no exception ever escapes this callback.
        """

        try:
            history.record_video_playback(
                self, self._history, kodi=xbmc,
                read_set_id=read_set_id,
                read_software_id=read_software_id)
        except SystemExit:
            # Kodi is killing the script: end the screensaver cleanly
            self.parent.saver.abort_screensaver('SystemExit')
        except Exception as err:  # noqa: BLE001 - a history failure must never escape into Kodi's player callback
            xbmc.log(
                f"UMSA SSaver Player: onAVStarted history recording failed: {err}",
                xbmc.LOGWARNING)

    def onPlayBackStarted(self):
        """Reacts to Kodi event 'onPlayBackStarted': queue a start event."""

        # a new playback instance begins; history is never written here
        # (the stream may not exist yet) - onAVStarted does that
        self._playback_instance += 1
        # reset the completion guard for this new playback instance
        self._playback_finalized.discard(self._playback_instance)
        try:
            xbmc.log("UMSA SSaver Player: onPlayBackStarted", xbmc.LOGINFO)
            self.events.append((
                video_session.EVENT_STARTED, self._playback_instance,
                self.get_playing_file()))
        except SystemExit as err:
            xbmc.log(f"UMSA SSaver SystemExit onPlayBackStarted: {err}", xbmc.LOGWARNING)
            self.parent.saver.abort_screensaver('SystemExit')

    def onPlayBackEnded(self):
        """Reacts to Kodi event 'onPlayBackEnded'"""

        self._handle_playback_stopped()

    def onPlayBackStopped(self):
        """Reacts to Kodi event 'onPlayBackStopped'.

        Called when playback is explicitly stopped (e.g. user action).
        """

        self._handle_playback_stopped()

    def onPlayBackError(self):
        """Reacts to Kodi event 'onPlayBackError'.

        Called when playback fails.
        """

        self._handle_playback_stopped()

    def _handle_playback_stopped(self):
        """Shared handler for playback end, stop, and error.

        Queues one end event per playback instance; the video loop releases
        the temp video and queues the next video.

        Idempotent: only processes the first callback for each playback
        instance. Subsequent callbacks (e.g. error followed by stopped)
        are ignored.
        """

        # Check if this playback instance has already been finalized
        instance = self._playback_instance
        if instance in self._playback_finalized:
            xbmc.log(
                f"UMSA SSaver Player: duplicate playback finalization for "
                f"instance {instance}, ignoring",
                xbmc.LOGDEBUG)
            return
        self._playback_finalized.add(instance)

        try:
            xbmc.log("UMSA SSaver Player: playback stopped/ended/error", xbmc.LOGINFO)
            self.events.append((video_session.EVENT_ENDED, instance, None))
        except SystemExit as err:
            xbmc.log(f"UMSA SystemExit onPlayBackStopped: {err}", xbmc.LOGWARNING)
            self.parent.saver.abort_screensaver('SystemExit')


class Monitor(xbmc.Monitor):
    """Kodi Monitor Class"""

    def __init__(self, **kwargs):
        self.umsa = kwargs['itself']
        # this instance inhibits Kodi's idle screensaver (keep_script_running)
        self.inhibits_kodi_screensaver = False
        __addon__ = xbmcaddon.Addon(id='screensaver.umsa.mame.surfer')
        self.player = Player(itself=self)
        self.vgmaction = False
        self.saver = Saver(
            SAVER_XML, __addon__.getAddonInfo('path'), SKIN_NAME, SKIN_RESOLUTION, itself=self)

    def _mode_candidates(self, configured):
        """Return the modes that may be selected.

        Kodi stops the music when a video starts, so the video mode is not
        used while audio or a VGM track plays. When only the video mode is
        configured, the other modes are added as temporary candidates - the
        settings of the user are never changed.
        """

        candidates = list(configured)
        if MODE_VIDEOS not in candidates:
            return candidates
        if not (self.player.isPlayingAudio() or vgm_active()):
            return candidates
        others = [mode for mode in candidates if mode != MODE_VIDEOS]
        if not others:
            xbmc.log(
                "UMSA SSaver Monitor: video mode is not possible while music plays",
                xbmc.LOGINFO)
            self.saver.notify_user(tr(S.NO_VIDEO_MODE_WITH_MUSIC))
            candidates = candidates + list(availability.IMAGE_MODES)
        return [mode for mode in candidates if mode != MODE_VIDEOS]

    def report_no_content(self, plan):
        """Tell the user that there is nothing to show."""

        xbmc.log(
            f"UMSA SSaver Monitor: no screensaver content available ({plan.reason})",
            xbmc.LOGWARNING)
        if plan.reason == availability.REASON_NO_VIDEOS:
            self.saver.notify_user(tr(S.NO_VIDEOS))
        if plan.reason != availability.REASON_NO_MODES:
            self.saver.notify_user(tr(S.NO_ARTWORK))

    def startme(self):
        """Start screensaver when emulator is not running."""

        xbmc.log("UMSA SSaver Monitor: screensaver activated", xbmc.LOGINFO)
        # only when not already running and no emulator running
        if self.saver.running == "no":
            configured = list(self.saver.settings.get('type') or [])
            if not configured:
                xbmc.log("UMSA SSaver Monitor: no screensaver mode active, can't start.", xbmc.LOGWARNING)
                return
            candidates = self._mode_candidates(configured)
            try:
                plan = availability.plan_start(
                    self.umsa.ggdb, candidates, configured=configured)
            except availability.AvailabilityError as error:
                xbmc.log(
                    f"UMSA SSaver Monitor: artwork check failed: {error}",
                    xbmc.LOGERROR)
                self.saver.notify_user(tr(S.ARTWORK_CHECK_FAILED))
                return
            if not plan.ok:
                self.report_no_content(plan)
                return
            if plan.reason == availability.REASON_NO_VIDEOS:
                self.saver.notify_user(tr(S.NO_VIDEOS))
            # Reset session-specific state for the new activation
            self.saver._reset_session_state()
            # an automatic start may rotate its image modes; an explicit
            # script request keeps the requested mode
            self.saver.rotate_modes = True
            self.saver.running = plan.mode
            self.saver.art_types = None
            self.saver.set_mode_property(plan.mode)
            xbmc.log(f"UMSA SSaver Monitor: starting {self.saver.running} saver", xbmc.LOGINFO)
            self.saver.doModal()
        xbmc.log("UMSA SSaver Monitor: onScreensaverActivated routine stop", xbmc.LOGINFO)

    def keep_script_running(self):
        """Keep the screensaver script alive after Kodi woke it.

        The saver stays active on purpose in the video mode and for VGM
        commands, but Kodi treats its screensaver as ended and stops the
        script in two ways - each forced stop hung Kodi:

        - waking a Python screensaver (a starting video counts as
          activity) schedules ``StopScript`` 15 s later; the alarm is
          started before Kodi reports the deactivation, so it is cancelled;
        - once the idle time passes again, Kodi activates its screensaver
          anew and stops the still running script first. The manual
          screensaver state inhibits Kodi's idle screensaver until this
          instance ends (``ScreensaverRuntime`` clears it).
        """

        xbmc.log("UMSA SSaver Monitor: cancelling Kodi's screensaver script stop", xbmc.LOGDEBUG)
        xbmc.executebuiltin(f'CancelAlarm({KODI_SCREENSAVER_STOP_ALARM},true)')
        if not self.inhibits_kodi_screensaver:
            xbmc.log("UMSA SSaver Monitor: inhibiting Kodi's idle screensaver", xbmc.LOGINFO)
            set_screensaver_manual(True)
            self.inhibits_kodi_screensaver = True

    def onScreensaverDeactivated(self):
        """Clear running argument, but let video run."""

        xbmc.log("UMSA SSaver Monitor: screensaver deactivated", xbmc.LOGINFO)
        if self.saver.running == 'videos':
            xbmc.log("UMSA SSaver Monitor: video screensaver stays active", xbmc.LOGINFO)
            self.keep_script_running()
        elif self.vgmaction:
            xbmc.log("UMSA SSaver Monitor: only vgm command send, screensaver stays active", xbmc.LOGDEBUG)
            self.vgmaction = False
            self.keep_script_running()
        elif vgm_active():
            xbmc.log("UMSA SSaver Monitor: dont stop as random vgm plays and it could be a command", xbmc.LOGDEBUG)
            self.keep_script_running()
        else:
            xbmc.log("UMSA SSaver Monitor: no vgm playing, stopping screensaver", xbmc.LOGDEBUG)
            self.reallyDeactivateScreensaver()

    def reallyDeactivateScreensaver(self):
        """Signal the active saver to stop.

        The runtime owns the saver for the whole session and discards the
        monitor afterwards, so there is no need to delete or replace the
        saver here. Setting ``running`` to ``no`` is what breaks the artwork
        loop and lets ``doModal`` return. The video playback is stopped and
        the video playlist is released with it.
        """

        xbmc.log("UMSA SSaver Monitor: now really deactive screensaver", xbmc.LOGINFO)
        self.saver.running = 'no'
        # stop the video playback, release the playlist and the temp files
        self.saver.shutdown_video_mode()
        xbmcgui.Window(WINDOW_ID).setProperty(MODE_PROPERTY, "no")

    def onDPMSActivated(self):
        """Stop screensaver when DPMS is activated."""
        self.onScreensaverDeactivated()
