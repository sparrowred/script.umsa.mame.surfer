"""Kodi UI implementation for the standalone UMSA screensaver add-on.

The window classes stay here: they own the Kodi lifecycle (window
callbacks, playlist, controls) and delegate the work to the focused
modules next to them:

- ``actions`` - dispatch of the Kodi actions of the screensaver window
- ``artwork_selector`` - artwork types, path resolution, aspect handling
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
    PIC_1TO1,
    PIC_3TO4,
    PIC_4TO3,
    PIC_MACHINE,
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
        # track temporary extracted video files for cleanup: {set_id: temp_path}
        self._temp_video_files = {}
        # known broken images, the list depends on the Pillow support
        self.bad_image_list = list(image_validator.bad_image_list(PIL))

        self.read_settings()

    def onInit(self):
        """Kodi onInit"""

        xbmc.log("UMSA SSaver: onInit", xbmc.LOGDEBUG)
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
            art, source_roots, self._temp_video_files, xbmcvfs, xbmc)

    def _cleanup_temp_videos(self, keep_keys=None):
        """Clean up temporary video files no longer needed.

        Args:
            keep_keys: Set of cache keys (set_id:member) to preserve. If None,
                cleans all temp files (used on screensaver shutdown).
        """
        temp_video.cleanup_temp_videos(
            self._temp_video_files, keep_keys, vfs=xbmcvfs, kodi=xbmc)

    def add_video_to_playlist(self):
        """Add a new video to the playlist"""

        xbmc.log("UMSA SSaver: add video to playlist", xbmc.LOGDEBUG)
        rand_vid = self.parent.umsa.ggdb.get_random_art(['videosnaps'])
        if not rand_vid:
            xbmc.log("UMSA SSaver: did not find any videos", xbmc.LOGWARNING)
            xbmc.executebuiltin('XBMC.Notification(Screensaver,no videos found,3000)')
            self.parent.player.stop()
            self.running = 'no'
            self.close()
            self.snapshot_crossover(['covers', 'flyers'])
            return
        source_roots = artwork_selector.source_roots(
            self.path, self.parent.umsa)

        # For eXoDOS archive videos, extract to temp instead of using zip:// URL
        filename = self._extract_exodos_video(rand_vid, source_roots)
        if filename is None:
            # Fall back to standard resolution (zip:// URL or regular path)
            filename = self.resolve_art_path(rand_vid, source_roots)

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
        xbmc.log(f"UMSA SSaver: playlist size {self.playlist.size()}, pos {self.playlist.getposition()}", xbmc.LOGDEBUG)
        return True

    def get_art_and_call_saver(self):
        """ Get artwork and call Screensaver """

        session = rendering.RenderSession(self, gui=xbmcgui, kodi=xbmc)
        if not session.run():
            # the video mode took over, the window stays open
            return

        # Clean up temporary extracted video files
        self._cleanup_temp_videos()

        self.close()
        xbmc.log("UMSA SSaver - call screensaver deactivate", xbmc.LOGINFO)
        self.parent.onScreensaverDeactivated()

    def create_wall(self):
        """Create UI elements for wall mode depending on settings.

        - count evspace and ehspace together / 2 and then calc again with new space, see 4 rows
        - fade out and in so the background can be seen
        - in wall mode make one position a video
        """

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

    def _av_instance_token(self):
        """Return an identity for the current playback instance, or ``None``.

        The token combines the playback instance counter (bumped by
        ``onPlayBackStarted``), the playlist position and the playing file,
        so duplicate ``onAVStarted`` callbacks for one playback instance
        collapse to a single record while a later playback of the same set
        (a new instance / playlist position) is recorded again.
        """

        return history.playback_token(self, self._playback_instance)

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
        try:
            xbmc.log("UMSA SSaver Player: onPlayBackStarted", xbmc.LOGINFO)
            # when video ssaver runs
            if self.parent.saver.running == 'videos':
                xbmc.log("UMSA SSaver Player: monitor mode is video", xbmc.LOGINFO)
                rendering.run_playback_labels(self, kodi=xbmc)
            xbmc.log("UMSA SSaver Player: onPlayBackStarted: routine ended", xbmc.LOGINFO)
        except SystemExit as err:
            xbmc.log(f"UMSA SSaver SystemExit onPlayBackStarted: {err}", xbmc.LOGWARNING)

    def onPlayBackEnded(self):
        """Reacts to Kodi event 'onPlayBackEnded'"""

        try:
            xbmc.log("UMSA SSaver Player: onPlayBackEnded", xbmc.LOGINFO)
            self.runp = False

            if self.parent.saver.running == 'videos':
                xbmc.log("UMSA SSaver Player: add video to playlist", xbmc.LOGINFO)
                self.parent.saver.add_video_to_playlist()
        except SystemExit as err:
            xbmc.log(f"UMSA SystemExit onPlayBackStarted: {err}", xbmc.LOGWARNING)


class Monitor(xbmc.Monitor):
    """Kodi Monitor Class"""

    def __init__(self, **kwargs):
        self.umsa = kwargs['itself']
        __addon__ = xbmcaddon.Addon(id='screensaver.umsa.mame.surfer')
        self.player = Player(itself=self)
        self.vgmaction = False
        self.saver = Saver(
            "umsa_saver.xml", __addon__.getAddonInfo('path'), "default", "720p", itself=self)

    def startme(self):
        """Start screensaver when emulator is not running."""

        xbmc.log("UMSA SSaver Monitor: screensaver activated", xbmc.LOGINFO)
        # only when not already running and no emulator running
        if self.saver.running == "no":
            # no videos when audio is running
            if self.player.isPlayingAudio() and 'videos' in self.saver.settings['type']:
                self.saver.settings['type'].remove('videos')
                self.saver.running = screensaver_settings.choose_mode(
                    self.saver.settings['type'])
                self.saver.settings['type'].append('videos')
            else:
                # check if any screensaver types are active
                if self.saver.settings['type']:
                    self.saver.running = screensaver_settings.choose_mode(
                        self.saver.settings['type'])
                else:
                    xbmc.log("UMSA SSaver Monitor: no screensaver mode active, can't start.", xbmc.LOGWARNING)
                    return
            self.saver.art_types = None
            xbmcgui.Window(10000).setProperty(
                "UMSA.Screensaver.Mode", self.saver.running)
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
        loop and lets ``doModal`` return.
        """

        xbmc.log("UMSA SSaver Monitor: now really deactive screensaver", xbmc.LOGINFO)
        self.saver.running = 'no'
        # Clean up temporary extracted video files
        self.saver._cleanup_temp_videos()
        xbmcgui.Window(10000).setProperty("UMSA.Screensaver.Mode", "no")

    def onDPMSActivated(self):
        """Stop screensaver when DPMS is activated."""
        self.onScreensaverDeactivated()
