"""Kodi UI implementation for the standalone UMSA screensaver add-on.

The window classes stay here: they own the Kodi lifecycle (window
callbacks, playlist, controls) and delegate the work to the focused
modules next to them:

- ``actions`` - dispatch of the Kodi actions of the screensaver window
- ``artwork_selector`` - artwork types, path resolution, aspect handling
- ``availability`` - artwork availability check and mode planning
- ``constants`` - control ids, action codes, window properties
- ``history`` - screensaver display history
- ``image_validator`` - bad image detection
- ``rendering`` - cross/slide/wall render loop, video label fading
- ``settings`` - screensaver settings model
- ``temp_video`` - eXoDOS video extraction and cleanup
- ``video_playlist`` - playlist items and the unique id metadata
- ``wall_layout`` - wall geometry

IDEA switch mode after some time -> save time and beginning and check diff in loop
"""

from os import path

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from umsa_core_kodi import (
    get_core_settings,
    send_vgm_action,
    vgm_active,
)

from . import (
    actions,
    artwork_selector,
    availability,
    history,
    image_validator,
    rendering,
    temp_video,
    video_playlist,
    wall_layout,
)
from . import settings as screensaver_settings
from .constants import (
    ACTION_CONTEXT,
    ACTION_MOVEMENT_RIGHT,
    ACTION_PLAY_NEXTITEM,
    BACKG,
    CROSS_BACKGROUND,
    IMAGE,
    INFO_DETAIL,
    INFO_LABEL,
    MODE_PROPERTY,
    MODE_VIDEOS,
    PIC_1TO1,
    PIC_3TO4,
    PIC_4TO3,
    PIC_MACHINE,
    WINDOW_ID,
)
from .image_validator import PIL
from .video_playlist import (
    SET_ID_UNIQUE_TYPE,
    attach_set_id,
    read_set_id,
    read_software_id,
)

__all__ = [
    'ACTION_CONTEXT',
    'ACTION_MOVEMENT_RIGHT',
    'ACTION_PLAY_NEXTITEM',
    'BACKG',
    'CROSS_BACKGROUND',
    'IMAGE',
    'INFO_DETAIL',
    'INFO_LABEL',
    'MEDIA_FOLDER',
    'PIC_1TO1',
    'PIC_3TO4',
    'PIC_4TO3',
    'PIC_MACHINE',
    'PIL',
    'SET_ID_UNIQUE_TYPE',
    'Monitor',
    'Player',
    'Saver',
    'attach_set_id',
    'read_set_id',
    'read_software_id',
]

__addon__ = xbmcaddon.Addon(id='screensaver.umsa.mame.surfer')

MEDIA_FOLDER = xbmcvfs.translatePath(path.join(
    __addon__.getAddonInfo('path'), 'resources', 'skins', 'default', 'media'))


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

        self.read_settings()

    def onInit(self):
        """Kodi onInit"""

        xbmc.log("UMSA SSaver: onInit", xbmc.LOGDEBUG)
        # Clear the Kodi video playlist to remove stale entries from previous
        # screensaver sessions. This is done once during initialization.
        self.playlist.clear()
        # correct aspect ratio for snap in bottom left position
        _4to3 = self.getControl(PIC_4TO3).getWidth()
        _3to4 = self.getControl(PIC_3TO4).getWidth()
        self.getControl(PIC_4TO3).setWidth(int(
            _4to3/self.settings['ar_x']*self.settings['ar_norm']))
        self.getControl(PIC_3TO4).setWidth(int(
            _3to4*self.settings['ar_norm']/self.settings['ar_x']))

        self.get_art_and_call_saver()

    def onAction(self, action):
        """Kodi onAction"""

        actions.handle_action(
            self, action, kodi=xbmc,
            vgm_active=vgm_active,
            send_vgm_action=send_vgm_action)

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
        self.path = (core_settings.own_artwork, core_settings.progettosnaps)
        parsed = screensaver_settings.ScreensaverSettings.from_addon(
            self.__addon__, core_settings)
        self.settings = parsed.as_legacy_dict()

    def notify_user(self, message):
        """Show a short notification to the user."""

        xbmc.executebuiltin(f'XBMC.Notification(Screensaver,{message},3000)')

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

        TODO all_art > to get cabinets/artpreview

        Uses internal picture for pinballs, reels and arcade
        """

        return artwork_selector.machine_picture(
            use_set, self.path[1], MEDIA_FOLDER)

    def resolve_art_path(self, art, source_roots, art_type=None, extension=None):
        """Resolve an artwork path with the shared Core resolver.

        ``art`` carries the new ``art_set`` fields (source, root_key,
        relative_path, archive_member). When ``art_type`` is given, an
        alternate artwork of the same set (the flyer, cover or snap shown
        next to the main image) is resolved instead of the stored row.
        """

        return artwork_selector.resolve_art_path(
            art, source_roots, art_type=art_type, extension=extension)

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
            # get left pic
            # TODO get left pic: snap = cross,slide ; cover/flyer = video, wall
            # TODO needs fetch info for snap from db for aspect ratio
            snapshot = rand_vid.get('left_pic')
            if not snapshot:
                left_type = artwork_selector.left_picture_type(rand_vid)
                snapshot = self.resolve_art_path(
                    rand_vid, source_roots, art_type=left_type, extension='png')
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

    def handle_missing_video(self):
        """Handle a video lookup that found nothing while running.

        The user is told, the obsolete video playback is stopped and the
        screensaver continues with an artwork mode whose artwork is
        available. Without any artwork the screensaver stops cleanly.
        """

        xbmc.log(
            "UMSA SSaver: no screensaver video found while running",
            xbmc.LOGWARNING)
        self.notify_user("no screensaver videos found")
        new_mode = self.prepare_artwork_mode()
        if new_mode is None:
            self.notify_user("no screensaver artwork available")
            self.running = 'no'
            self.finish_screensaver()
            return
        session = rendering.RenderSession(self, gui=xbmcgui, kodi=xbmc)
        try:
            session.run()
        finally:
            # Ensure cleanup even if render loop raises unexpectedly
            if self.running != 'videos' or self.video_teardown:
                self.finish_screensaver()

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

    def get_art_and_call_saver(self):
        """ Get artwork and call Screensaver """

        session = rendering.RenderSession(self, gui=xbmcgui, kodi=xbmc)
        try:
            if not session.run():
                # the video mode took over, the window stays open
                return
        finally:
            # Ensure finish_screensaver is called even if render loop
            # raises an unexpected exception. The render session's own
            # finally block cleans up dynamic controls; this ensures
            # the outer lifecycle (video teardown, window close) runs too.
            if self.running != 'videos' or self.video_teardown:
                self.finish_screensaver()

    def create_wall(self):
        """Create UI elements for wall mode depending on settings.

        - count evspace and ehspace together / 2 and then calc again with new space, see 4 rows
        - fade out and in so the background can be seen
        - in wall mode make one position a video

        The controls are created exactly once per wall session: a second
        call does nothing.
        """

        if self._wall_created:
            xbmc.log("UMSA SSaver: wall already created", xbmc.LOGDEBUG)
            return
        rows, known = wall_layout.resolve_rows(self.settings['wall'])
        if not known:
            xbmc.log("UMSA SSaver: create_wall error rows.", xbmc.LOGWARNING)
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
        # generate image list
        self.wall['mesh'] = []
        positions = wall_layout.cell_positions(
            rows, grid['cols'], grid['width'], grid['height'], grid['evspace'])
        # TODO rework for, for
        for pos_x, pos_y in positions:
            self.wall['mesh'].append(
                xbmcgui.ControlImage(pos_x, pos_y, self.wall['width'], self.wall['height'], ''))

        # TODO really needed? acutally coz run_wall does removeControl
        # if we could remove addControl here, no need for doModal before create_wall
        # add images to window
        for control in self.wall['mesh']:
            self.addControl(control)

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
     onPlayBackEnded

    Used by video screensaver as Kodi Monitor ends when a video is started.
    Controls after how many seconds the video label blends in.

    History recording happens only in ``onAVStarted``: that callback is the
    Kodi-recommended point at which an actual audio/video stream exists,
    whereas ``onPlayBackStarted`` may fire while the item is merely queued or
    not yet delivering a stream. Nothing is ever recorded at enqueue time.
    """

    def __init__(self, **kwargs):
        self.parent = kwargs['itself']
        self.runp = False
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

    def _av_instance_token(self):
        """Return an identity for the current playback instance, or ``None``.

        The token combines the playback instance counter (bumped by
        ``onPlayBackStarted``), the playlist position and the playing file,
        so duplicate ``onAVStarted`` callbacks for one playback instance
        collapse to a single record while a later playback of the same set
        (a new instance / playlist position) is recorded again.
        """

        return history.playback_token(self, self._playback_instance)

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
        except (SystemExit, Exception) as err:  # noqa: BLE001 - a history failure must never escape into Kodi's player callback
            xbmc.log(
                f"UMSA SSaver Player: onAVStarted history recording failed: {err}",
                xbmc.LOGWARNING)

    def onPlayBackStarted(self):
        """Reacts to Kodi event 'onPlayBackStarted'"""

        # a new playback instance begins; history is never written here
        # (the stream may not exist yet) - onAVStarted does that
        self._playback_instance += 1
        # reset the completion guard for this new playback instance
        self._playback_finalized.discard(self._playback_instance)
        try:
            xbmc.log("UMSA SSaver Player: onPlayBackStarted", xbmc.LOGINFO)
            saver = self.parent.saver
            # remember the extracted file of the video that plays now
            saver.note_playing_video(self.get_playing_file())
            # when video ssaver runs
            if saver.running == 'videos':
                xbmc.log("UMSA SSaver Player: monitor mode is video", xbmc.LOGINFO)
                rendering.run_playback_labels(self, kodi=xbmc)
            xbmc.log("UMSA SSaver Player: onPlayBackStarted: routine ended", xbmc.LOGINFO)
        except SystemExit as err:
            xbmc.log(f"UMSA SSaver SystemExit onPlayBackStarted: {err}", xbmc.LOGWARNING)

    def onPlayBackEnded(self):
        """Reacts to Kodi event 'onPlayBackEnded'"""

        self._handle_playback_stopped()

    def onPlayBackStopped(self):
        """Reacts to Kodi event 'onPlayBackStopped'.

        Called when playback is explicitly stopped (e.g. user action).
        Handles cleanup without restarting playback during shutdown.
        """

        self._handle_playback_stopped()

    def onPlayBackError(self):
        """Reacts to Kodi event 'onPlayBackError'.

        Called when playback fails. Handles cleanup without restarting
        playback during shutdown.
        """

        self._handle_playback_stopped()

    def _handle_playback_stopped(self):
        """Shared handler for playback end, stop, and error.

        Releases the active temp video and, if the screensaver is still
        running in video mode and not shutting down, queues the next video.

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
            self.runp = False
            saver = self.parent.saver
            # the extracted file of the video that ended is not needed anymore
            saver.release_playing_video()
            if saver.running == 'videos' and not saver.video_teardown:
                xbmc.log("UMSA SSaver Player: add video to playlist", xbmc.LOGINFO)
                if not saver.add_video_to_playlist():
                    # the database holds no video anymore: leave the video mode
                    saver.handle_missing_video()
        except SystemExit as err:
            xbmc.log(f"UMSA SystemExit onPlayBackStopped: {err}", xbmc.LOGWARNING)


class Monitor(xbmc.Monitor):
    """Kodi Monitor Class"""

    def __init__(self, **kwargs):
        self.umsa = kwargs['itself']
        __addon__ = xbmcaddon.Addon(id='screensaver.umsa.mame.surfer')
        self.player = Player(itself=self)
        self.vgmaction = False
        self.saver = Saver(
            "umsa_saver.xml", __addon__.getAddonInfo('path'), "default", "720p", itself=self)

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
            self.saver.notify_user(
                "video mode is not available while music plays")
            candidates = candidates + list(availability.IMAGE_MODES)
        return [mode for mode in candidates if mode != MODE_VIDEOS]

    def report_no_content(self, plan):
        """Tell the user that there is nothing to show."""

        xbmc.log(
            f"UMSA SSaver Monitor: no screensaver content available ({plan.reason})",
            xbmc.LOGWARNING)
        if plan.reason == availability.REASON_NO_VIDEOS:
            self.saver.notify_user("no screensaver videos available")
        if plan.reason != availability.REASON_NO_MODES:
            self.saver.notify_user("no screensaver artwork available")

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
                self.saver.notify_user("screensaver artwork check failed")
                return
            if not plan.ok:
                self.report_no_content(plan)
                return
            if plan.reason == availability.REASON_NO_VIDEOS:
                self.saver.notify_user("no screensaver videos available")
            # Reset session-specific state for the new activation
            self.saver._reset_session_state()
            self.saver.running = plan.mode
            self.saver.art_types = None
            self.saver.set_mode_property(plan.mode)
            xbmc.log(f"UMSA SSaver Monitor: starting {self.saver.running} saver", xbmc.LOGINFO)
            self.saver.doModal()
        xbmc.log("UMSA SSaver Monitor: onScreensaverActivated routine stop", xbmc.LOGINFO)

    def onScreensaverDeactivated(self):
        """Clear running argument, but let video run."""

        xbmc.log("UMSA SSaver Monitor: screensaver deactivated", xbmc.LOGINFO)
        # TOD was started after run_emulator, will this ever happen?
        if self.saver.running == 'emu':
            xbmc.log("UMSA SSaver Monitor: Emulator running, trying to close emu_dialog, why? TODO", xbmc.LOGWARNING)
            if hasattr(self.umsa, 'emu_dialog') and self.umsa.emu_dialog:
                xbmc.log("UMSA SSaver Monitor: trying to close dialog", xbmc.LOGERROR)
                self.umsa.emu_dialog.close()
            else:
                xbmc.log("UMSA SSaver Monitor: self.umsa has no emu_dialog ERROR", xbmc.LOGERROR)
        elif self.saver.running == 'videos':
            xbmc.log("UMSA SSaver Monitor: video screensaver stays active", xbmc.LOGINFO)
        elif self.vgmaction:
            xbmc.log("UMSA SSaver Monitor: only vgm command send, screensaver stays active", xbmc.LOGDEBUG)
            self.vgmaction = False
        elif vgm_active():
            xbmc.log("UMSA SSaver Monitor: dont stop as random vgm plays and it could be a command", xbmc.LOGDEBUG)
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
