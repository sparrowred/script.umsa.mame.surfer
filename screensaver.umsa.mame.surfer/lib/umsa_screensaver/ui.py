"""Kodi UI implementation for the standalone UMSA screensaver add-on.

IDEA switch mode after some time -> save time and beginning and check diff in loop
"""

from functools import reduce
from hashlib import md5
from os import path
from random import choice, randint, sample, shuffle
from zipfile import ZipFile

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from umsa_core import check_image_aspect, resolve_artwork_path, root_key_for_path
from umsa_core.history_repository import normalize_set_id
from umsa_core_kodi import (
    get_core_settings,
    send_vgm_action,
    vgm_active,
)

try:
    from PIL import Image, ImageStat
    PIL = True
except ImportError:
    PIL = False

__addon__ = xbmcaddon.Addon(id='screensaver.umsa.mame.surfer')

MEDIA_FOLDER = xbmcvfs.translatePath(
    path.join(__addon__.getAddonInfo('path'), 'resources', 'skins', 'default', 'media'))

# TODO only have these one time, see gui
ACTION_PLAY_NEXTITEM = (14,112)
ACTION_MOVEMENT_RIGHT = (2,)
ACTION_CONTEXT = (117,)
INFO_LABEL = 102
INFO_DETAIL = 108
PIC_MACHINE = 105
PIC_4TO3 = 104
PIC_3TO4 = 106
PIC_1TO1 = 107
IMAGE = [1, 2]
BACKG = [5, 6]

# Unique-ID type label carrying the UMSA set id (sets.id) with a video.
# InfoTagVideo.setUniqueID()/getUniqueID() exist only from Kodi 20
# (@python_v20); every use below is capability-guarded, so on Kodi 19 the
# value simply never travels with the item and video history is not
# recorded (logged), while the Votes-based software-id handoff keeps working.
SET_ID_UNIQUE_TYPE = 'umsa_set_id'


def attach_set_id(video_item, set_id):
    """Attach the UMSA set id to a playlist item as ``umsa_set_id``.

    Argument order matters: the official API is
    ``setUniqueID(uniqueid, type)`` - the id value first, the type label
    second. Returns ``True`` when the value was written, ``False`` when the
    runtime lacks the Kodi 20 unique-ID API, the id is invalid or the write
    failed (each case is logged; the caller is never interrupted).
    """

    try:
        normalized = normalize_set_id(set_id)
    except ValueError:
        xbmc.log(f"UMSA SSaver: not attaching invalid set id {set_id!r}", xbmc.LOGWARNING)
        return False
    try:
        video_tag = video_item.getVideoInfoTag()
    except (AttributeError, RuntimeError) as error:
        xbmc.log(f"UMSA SSaver: no video info tag for set id: {error}", xbmc.LOGDEBUG)
        return False
    if video_tag is None or not hasattr(video_tag, 'setUniqueID'):
        xbmc.log(
            "UMSA SSaver: Kodi has no InfoTagVideo.setUniqueID (Kodi < 20); "
            "screensaver video history recording is unavailable",
            xbmc.LOGDEBUG)
        return False
    try:
        video_tag.setUniqueID(str(normalized), SET_ID_UNIQUE_TYPE)
    except (TypeError, ValueError, RuntimeError) as error:
        xbmc.log(f"UMSA SSaver: could not attach umsa_set_id {normalized}: {error}", xbmc.LOGWARNING)
        return False
    return True


def read_set_id(video_tag):
    """Return the positive ``set_id`` carried by ``video_tag``, or ``None``.

    ``None`` means "no recordable set id": the runtime has no
    ``InfoTagVideo.getUniqueID`` (Kodi < 20), the ``umsa_set_id`` value is
    absent, or it does not validate as a positive decimal ``sets.id`` (the
    latter is logged). The value is never replaced by any other id.
    """

    if video_tag is None or not hasattr(video_tag, 'getUniqueID'):
        return None
    try:
        raw = video_tag.getUniqueID(SET_ID_UNIQUE_TYPE)
    except (TypeError, ValueError, RuntimeError) as error:
        xbmc.log(f"UMSA SSaver: could not read umsa_set_id: {error}", xbmc.LOGWARNING)
        return None
    if raw is None or raw == '':
        return None
    try:
        return normalize_set_id(raw)
    except ValueError:
        xbmc.log(f"UMSA SSaver: ignoring invalid umsa_set_id {raw!r}", xbmc.LOGWARNING)
        return None


def read_software_id(video_tag):
    """Return the software id carried in the video ``Votes`` label, or ``None``.

    ``Votes`` keeps holding the software id (``sets.softwarelink_id``) exactly
    as the context-menu handoff reads it today; it is never repurposed for the
    set id.
    """

    if video_tag is None or not hasattr(video_tag, 'getVotes'):
        return None
    try:
        return int(video_tag.getVotes())
    except (TypeError, ValueError):
        return None


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
        self.art_types = []
        self.wall = {}
        self.settings = {}
        # identity of the software currently on screen, for the handoff
        self.current_software_id = None
        # guard so one ContextMenu does not dispatch twice
        self.opening = False

        if PIL:
            self.bad_image_list = [
                "98f4b5e0981192d781c35be7181c7b57", # cover psx demo
                "8d80173851047da4aca3a9901a3b82c5", # device
                "acf2a6f1537c82a19d3228f188c635f3", # device
                "030d8394efbe41d0f4784ca8985d5b48", # mechanical
                "92f04e810171e83ce868ce17f4e93737", # mechanical
                "afdb9915c2b64e66e6af3dd00f637540", # mechanical
                "844e8d74c384788196dc964686d1d5d0", # mechanical
                "ca9cdda35a258466328d7fca93f445b4", # screenless
                "3b43fd4467ace20511952f69c7889439", # screenless
                "9b24d00807f94179a28f09619bc4e258", # screenless
            ]
        else:
            self.bad_image_list = [
                "cd773c91cffdb80457ab1c83bbd6cca5", # cover psx demo
                "e2b8f257fea66b661ee70efc73b6c84a", # device ingame
                "1b7928278186f053777dea680b0a2b2d", # device ingame
                "47d7f4d18f0c9b4dcd87423e00c9917d", # device ingame
                "0734aca010260cee0bbf08b08e642fed", # device ingame
                "e940a4fdfd01163dae42bc0fe489c0e9", # device ingame
                "b486065e909640d843dd4df98a0742fe", # device title
                "7e8b76745b9daad337108fd2d09159bc", # device title
                "8862b370e7c1785c336be63d464f14c7", # device title
                "4330217adee809149c8e784e587e1f40", # device title
                "30ab4d58332ef5332affe5f3320c647a", # mechanical ingame
                "26bdf324b11da6190f38886a3b0f7598", # mechanical ingame
                "f28cffce4c580b1c28ef0c24e8e25f80", # mechanical ingame
                "11cf90ef6332e4e7643d5e4e84e411ba", # mechanical title
                "cd3ada96083b26749cdb64f57662f0dc", # mechanical title
                "eb910d22e89a24d09cb57bf111548f80", # mechanical title
                "76707f5e81e41cb811a8a9f6050ccac7", # screenless system
                "1b62951c72c91d2927da5a044af7e0bd", # screenless system
                "6a4ca1ab352df8af4a25c50a65bb8963", # screenless system
                "062a4b154b0aa03461ea3cdfe4f42172", # screenless system
                "a766be38df34c5db61ad5cd559919487", # screenless system
            ]

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

        xbmc.log(f"UMSA SSaver: onAction {self.running}", xbmc.LOGDEBUG)
        if self.opening:
            xbmc.log("UMSA SSaver: handoff already in progress, ignoring action", xbmc.LOGDEBUG)
            return
        if self.running == 'videos':
            # next video
            if action.getId() in ACTION_PLAY_NEXTITEM+ACTION_MOVEMENT_RIGHT:
                self.add_video_to_playlist()
                self.parent.player.playnext()
            # show actual game in gui
            elif action.getId() in ACTION_CONTEXT:
                # software id hidden in votes
                s_id = None
                try:
                    s_id = int(self.parent.player.getVideoInfoTag().getVotes())
                except (TypeError, ValueError):
                    xbmc.log("UMSA SSaver: no software id for video context", xbmc.LOGWARNING)
                self.open_software(s_id)
                self.parent.player.stop()
                self.running = 'no'
                self.close()
            # volume change, do not quit
            elif action.getId() in (88, 89):
                pass
            # else stop saver
            else:
                self.parent.player.stop()
                self.running = 'no'
                self.close()
        elif self.running in ('cross', 'wall', 'slide'):
            # show actual game in gui
            if action.getId() in ACTION_CONTEXT:
                self.open_software(self.current_software_id)
                self.parent.reallyDeactivateScreensaver()
                self.running = 'no'
                self.close()
            # allow changing volume with plus/minus
            # also allow playnext and right should button for next vgm
            elif vgm_active():
                if action.getId() == 88:
                    self.parent.vgmaction = True
                    send_vgm_action('volume_up')
                    xbmc.log("UMSA SSaver: sound volume + dont end saver", xbmc.LOGDEBUG)
                elif action.getId() == 89:
                    self.parent.vgmaction = True
                    send_vgm_action('volume_down')
                    xbmc.log("UMSA SSaver: sound volume - dont end saver", xbmc.LOGDEBUG)
                elif action.getId() in ACTION_PLAY_NEXTITEM+ACTION_MOVEMENT_RIGHT:
                    self.parent.vgmaction = True
                    send_vgm_action('next')
                    xbmc.log("UMSA SSaver: next song - dont end saver", xbmc.LOGDEBUG)
                elif action.getId() == 13:
                    self.parent.vgmaction = True
                    send_vgm_action('stop')
                else:
                    self.parent.reallyDeactivateScreensaver()
                    self.running = 'no'
                    self.close()
            else:
                self.parent.reallyDeactivateScreensaver()
                self.running = 'no'
                self.close()

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

        set_id = art.get('id') if art else None
        software_id = art.get('s_id') if art else None
        try:
            normalized_set_id = normalize_set_id(set_id)
        except ValueError:
            xbmc.log(
                f"UMSA SSaver: no valid set id for history: {set_id!r}",
                xbmc.LOGWARNING)
            return False
        try:
            self.parent.umsa.ggdb.record_screensaver_display(
                normalized_set_id, software_id)
        except Exception as error:  # noqa: BLE001 - history must never break rendering
            xbmc.log(
                f"UMSA SSaver: history recording failed: {error}",
                xbmc.LOGWARNING)
            return False
        xbmc.log(
            f"UMSA SSaver: recorded screensaver history for set {normalized_set_id}",
            xbmc.LOGDEBUG)
        return True

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
        self.settings = {}

        ar_norm = 1.7777 # 16:9
        self.settings['ar_norm'] = ar_norm
        self.settings['ar_x'] = core_settings.aspect_ratio_factor

        self.settings['time'] = int(self.__addon__.getSetting('ssaver_time'))
        self.settings['info'] = False
        if self.__addon__.getSetting('ssaver_info') == 'true':
            self.settings['info'] = True

        self.settings['type'] = []
        if self.__addon__.getSetting('ssaver_videos') == 'true':
            self.settings['type'].append('videos')
        if self.__addon__.getSetting('ssaver_slide') == 'true':
            self.settings['type'].append('slide')
        if self.__addon__.getSetting('ssaver_wall') == 'true':
            self.settings['type'].append('wall')
        if self.__addon__.getSetting('ssaver_cross') == 'true':
            self.settings['type'].append('cross')
        self.settings['wall'] = {
            'trows': int(self.__addon__.getSetting('ssaver_trows')),
            'trows_b': int(self.__addon__.getSetting('ssaver_trows_b')),
            'srows': int(self.__addon__.getSetting('ssaver_srows')),
            'srows_b': int(self.__addon__.getSetting('ssaver_srows_b')),
            'free': int(self.__addon__.getSetting('ssaver_free')),
            'titles': self.__addon__.getSetting('ssaver_titles'),
        }

    def check_snapshot(self, snapshot):
        """Return true when snapshot is Ok.

        Ok means it's not in the bad list and not only one color.
        """

        ret = True
        if PIL:
            img = False
            try:
                img = Image.open(snapshot)
            except OSError:
                ret = False

            if img:
                try:
                    imgmd5 = md5(img.tobytes()).hexdigest()
                except OSError as error:
                    xbmc.log(f"UMSA SSaver: {snapshot} error md5sum: {error}", xbmc.LOGWARNING)
                    ret = False
                else:
                    imgv = ImageStat.Stat(img).var
                    img.close()
                    if imgmd5 in self.bad_image_list or reduce(lambda x, y: x and y < 0.010, imgv, True):
                        ret = False
        else:
            img = False
            try:
                img = open(snapshot, 'rb')
            except OSError:
                ret = False

            if img:
                imgmd5 = md5(img.read()).hexdigest()
                img.close()
                if imgmd5 in self.bad_image_list:
                    ret = False
                else:
                    ret = True
        return ret

    def get_machine_pic(self, use_set):
        """Return full path for a machine picture based on set

        TODO all_art > to get cabinets/artpreview

        Uses internal picture for pinballs, reels and arcade
        """

        cab_path = path.join(self.path[1], 'cabinets/cabinets')
        pic = None
        # TODO bad solution, needs grouping of categories like Handheld.*
        categories = (
            'Handheld / Electronic Game', "Handheld / Plug n' Play TV Game",
            'Electromechanical / Reels', 'Casino / Reels',
            'Slot Machine / Reels', 'Slot Machine / Video Slot'
        )
        # set machine pic for mame
        if use_set['machine_name'] == 'mame':
            if use_set['is_machine']:
                pic = path.join(cab_path, use_set['name']+'.png')
            elif use_set['category'] == 'Electromechanical / Pinball':
                pic = path.join(MEDIA_FOLDER, "pinball.png")
            elif use_set['category'] in categories:
                # TODO check if cabinet or artpreview is available for set

                # fallback
                if not pic:
                    if 'Reels' in use_set['category']:
                        pic = path.join(MEDIA_FOLDER, "reels.png")
                    if not pic:
                        pic = path.join(MEDIA_FOLDER, "arcade.png")
            else:
                if not pic:
                    pic = path.join(MEDIA_FOLDER, "arcade.png")
        # set machine pic for swl
        else:
            if not pic:
                # TODO fallback media pic for missing swl machine cab
                pic = path.join(cab_path, use_set['machine_name']+'.png')
        return pic

    def resolve_art_path(self, art, source_roots, art_type=None, extension=None):
        """Resolve an artwork path with the shared Core resolver.

        ``art`` carries the new ``art_set`` fields (source, root_key,
        relative_path, archive_member). When ``art_type`` is given, an
        alternate artwork of the same set (the flyer, cover or snap shown
        next to the main image) is resolved instead of the stored row.
        """

        if art_type is None:
            return resolve_artwork_path(art, art, source_roots)

        derived = dict(art)
        derived['type'] = art_type
        derived['relative_path'] = None
        derived['archive_member'] = None
        if extension is not None:
            derived['extension'] = extension
        return resolve_artwork_path(derived, art, source_roots)

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
        source_roots = {"progettosnaps": self.path[1] if len(self.path) > 1 else self.path[0],
                         "own_artwork": self.path[0] if len(self.path) > 0 else "",
                         "exodos": self.parent.umsa.nonmame.get("exodos") if hasattr(self.parent.umsa, "nonmame") else "",
                         "gb64": self.parent.umsa.nonmame.get("gb64") if hasattr(self.parent.umsa, "nonmame") else ""}
        filename = self.resolve_art_path(rand_vid, source_roots)
        xbmc.log(f"UMSA SSaver: videoadd: added {filename}", xbmc.LOGDEBUG)
        # For archive-contained videos, Kodi can play zip:// paths directly
        machine_pic = self.get_machine_pic(rand_vid)
        # get left pic
        # TODO get left pic: snap = cross,slide ; cover/flyer = video, wall
        # TODO needs fetch info for snap from db for aspect ratio
        snapshot = rand_vid.get('left_pic')
        if not snapshot:
            left_type = 'flyers' if rand_vid['swl_name'] == 'mame' else 'covers'
            snapshot = self.resolve_art_path(
                rand_vid, source_roots, art_type=left_type, extension='png')
        xbmc.log(f"UMSA SSaver {snapshot}", xbmc.LOGDEBUG)
        video_item = xbmcgui.ListItem(rand_vid['gamename'])
        video_item.setInfo('video', {
            'Title': rand_vid['gamename'],
            'Genre': "{}, {}".format(rand_vid['year'], rand_vid['maker']),
            'Trailer': machine_pic,
            'Director': snapshot,
            'Votes': rand_vid['s_id']})
        # carry the set id alongside the Votes software id so the playback
        # callback can record history; degrades to a logged no-op on Kodi < 20
        attach_set_id(video_item, rand_vid.get('id'))
        self.playlist.add(url=filename, listitem=video_item)
        xbmc.log(f"UMSA SSaver: playlist size {self.playlist.size()}, pos {self.playlist.getposition()}", xbmc.LOGDEBUG)
        return True

    def get_art_and_call_saver(self):
        """ Get artwork and call Screensaver """

        if not self.art_types:
            if self.running == 'videos':
                self.art_types = ['videosnaps']
            elif self.running == 'cross':
                self.art_types = ['covers', 'flyers']
            elif self.running == 'slide':
                self.art_types = ["covers", "flyers", "cabinets", "cpanel", "marquees"] #artpreview
            elif self.running == 'wall':
                self.art_types = ['snap']
                self.create_wall()

        if self.running == 'videos':
                xbmc.log("UMSA SSaver: screensaver: video", xbmc.LOGDEBUG)
                self.add_video_to_playlist()
                self.add_video_to_playlist()
                self.parent.player.play(self.playlist)
                return

        if self.running == 'wall':
            self.create_wall()
            lastpos = None
            self.setProperty('SlideView.Background', 'show')

        elif self.running == 'slide':
            self.setProperty('SlideView.Background', 'show')

        elif self.running == 'cross':
            self.getControl(109).setVisible(False)
            self.getControl(BACKG[0]).setVisible(False)
            self.getControl(BACKG[1]).setVisible(False)
            piclist = []

        # screensaver loop
        order = [0, 1]
        while self.running != 'no':
            art = self.parent.umsa.ggdb.get_random_art(self.art_types)
            # remember the software being rendered for the context handoff
            self.remember_art(art)
            # no artwork to render: nothing was displayed, so nothing may be
            # recorded (and there is no path to resolve)
            if not art:
                xbmc.log("UMSA SSaver: no artwork returned, skipping iteration", xbmc.LOGDEBUG)
                continue

            source_roots = {"progettosnaps": self.path[1] if len(self.path) > 1 else self.path[0],
                             "own_artwork": self.path[0] if len(self.path) > 0 else "",
                             "exodos": self.parent.umsa.nonmame.get("exodos") if hasattr(self.parent.umsa, "nonmame") else "",
                             "gb64": self.parent.umsa.nonmame.get("gb64") if hasattr(self.parent.umsa, "nonmame") else ""}
            filename = self.resolve_art_path(art, source_roots)

            # check for bad image
            if art['type'] in ('snap', 'titles', 'covers'):
                if not self.check_snapshot(filename):
                    continue

            # set scaling
            if art['type'] not in ('snap', 'titles'):
                aspect = 'NotScaled'
            else:
                aspect = check_image_aspect(art)

            # get machine pic
            self.getControl(PIC_MACHINE).setImage(
                self.get_machine_pic(art), False)

            # get left pic
            # TODO get left pic: snap = cross,slide ; cover/flyer = video, wall
            # TODO needs fetch info for snap from db for aspect ratio
            if 'left_pic' in art:
                if art['type'] in ('snap', 'titles', 'videosnaps'):
                    self.getControl(PIC_1TO1).setImage(art['left_pic'])
                    self.getControl(PIC_4TO3).setImage('')
                    self.getControl(PIC_3TO4).setImage('')
                else:
                    self.getControl(PIC_1TO1).setImage('')
                    self.getControl(PIC_4TO3).setImage(art['left_pic'])
                    self.getControl(PIC_3TO4).setImage('')
            elif art['type'] in ('snap', 'titles', 'videosnaps'):
                left_type = 'flyers' if art['swl_name'] == 'mame' else 'covers'
                snapshot = self.resolve_art_path(art, source_roots, art_type=left_type)
                self.getControl(PIC_1TO1).setImage(snapshot, False)
                self.getControl(PIC_4TO3).setImage('')
                self.getControl(PIC_3TO4).setImage('')
            else:
                # TODO dirty hack, get from db! maybe get_random_art should return it!
                snapshot = self.resolve_art_path(
                    art, source_roots, art_type='snap', extension='png')
                snapctrl = PIC_4TO3
                if self.check_snapshot(snapshot):
                    self.getControl(snapctrl).setImage(snapshot, False)

                # no snapshot = clear all 3 snap views
                else:
                    self.getControl(PIC_4TO3).setImage('')
                    self.getControl(PIC_3TO4).setImage('')
                    self.getControl(PIC_1TO1).setImage('')

            # set info label
            self.getControl(INFO_LABEL).setLabel(f"{art['gamename']}")
            self.getControl(INFO_DETAIL).setLabel(
                "{}, {}".format(art['year'], art['maker']))

            # call saver
            if self.running == 'cross':
                x_axis = randint(0, 1280)
                y_axis = randint(0, 720)
                if aspect == 'Vertical':
                    # TODO look up aspect calc from ssaver
                    piclist.append(xbmcgui.ControlImage(x_axis-120, y_axis-160, 240, 320, filename))
                elif aspect == 'NotScaled':
                    piclist.append(xbmcgui.ControlImage(x_axis-180, y_axis-180, 360, 360, filename, 2))
                else:
                    piclist.append(xbmcgui.ControlImage(x_axis-180, y_axis-135, 360, 270, filename))
                # show pic
                self.addControl(piclist[-1])
                if len(piclist) > 60:
                    self.removeControl(piclist[0])
                    del piclist[0]

            elif self.running == 'slide':
                self.getControl(IMAGE[order[0]]).setImage(filename)
                self.setProperty(f'SlideView.Slide{order[0]+1}', '0')
                self.setProperty(f'SlideView.Slide{order[1]+1}', '1')
                self.setProperty(f'SlideView.Fade1{order[0]+1}', '0')
                self.setProperty(f'SlideView.Fade1{order[1]+1}', '1')
                self.getControl(BACKG[order[0]]).setImage(filename)

            elif self.running == 'wall':
                # refill position list when empty
                if not self.wall['pos']:
                    pos = sample(range(self.wall['pics']), self.wall['pics'])
                    # the last element is popped first: it must not repeat the previous position
                    if len(pos) > 1 and pos[-1] == lastpos:
                        pos[0], pos[-1] = pos[-1], pos[0]
                    self.wall['pos'] = pos
                # pop new position from list
                lastpos = self.wall['pos'].pop()

                if self.wall['free'] != 0:
                    self.wall['freelist'].append(lastpos)
                    if len(self.wall['freelist']) == self.wall['free']:
                        tofree = self.wall['freelist'].pop(
                            randint(0, round(len(self.wall['freelist'])/2)))
                        self.wall['pos'].insert(0, tofree)
                        # make image empty
                        self.removeControl(self.wall['mesh'][tofree])
                        self.wall['mesh'][tofree].setImage('')
                        # TODO unneeded?
                        self.addControl(self.wall['mesh'][tofree])

                # check if image is horizontal, vertical or aspect ratio must be keeped
                # get image position
                pos_x, pos_y = self.wall['mesh'][lastpos].getPosition()
                # width not standard =
                # image was vertical > correct pos_x position
                if self.wall['mesh'][lastpos].getWidth() != self.wall['width']:
                    pos_x = pos_x-self.wall['vert_x']
                # remove image control
                # TODO only when image exists
                self.removeControl(self.wall['mesh'][lastpos])
                # TODO switch to create_gui_element, it also does snaporientation
                # create new image control for horz, vert or ar=keep
                if aspect == 'Horizontal':
                    self.wall['mesh'][lastpos] = xbmcgui.ControlImage(
                        pos_x, pos_y, self.wall['width'], self.wall['height'], '')
                elif aspect == 'Vertical':
                    self.wall['mesh'][lastpos] = xbmcgui.ControlImage(
                        pos_x + self.wall['vert_x'], pos_y,
                        self.wall['vert_width'], self.wall['height'], '')
                elif aspect == 'NotScaled':
                    self.wall['mesh'][lastpos] = xbmcgui.ControlImage(
                        pos_x, pos_y, self.wall['width'], self.wall['height'], '', 2)
                # set image
                self.wall['mesh'][lastpos].setImage(filename, False)
                # add new image control
                self.addControl(self.wall['mesh'][lastpos])
                self.getControl(BACKG[order[0]]).setImage(filename)
                self.setProperty(f'SlideView.Fade1{order[0]+1}', '0')
                self.setProperty(f'SlideView.Fade1{order[1]+1}', '1')

            # the render path completed for cross/slide/wall: this is the
            # display-success boundary (Kodi gives no image-load callback),
            # so record the set now, once, immediately before the wait loop.
            # Anything raised above skips this call - no partial render is
            # ever recorded.
            self.record_display(art)

            # set wait_time
            if self.running == 'videos':
                xbmc.log(f"UMSA SSaver isPlayingVideo {self.parent.player.isPlayingVideo()}", xbmc.LOGDEBUG)
                while not self.parent.player.isPlayingVideo():
                    xbmc.sleep(250)
                    xbmc.log(f"UMSA SSaver isPlayingVideo {self.parent.player.isPlayingVideo()}", xbmc.LOGDEBUG)
                # get total time in sec
                wait_time = int(self.parent.player.getTotalTime())+1
                xbmc.log("UMSA SSaver wait_time {wait_time}", xbmc.LOGDEBUG)
            else:
                wait_time = self.settings['time']

            # wait_loop
            count = 0
            while count < wait_time:
                if count == 1:
                    self.setProperty('LabelView.Fade', '0')
                if count == wait_time-1:
                    self.setProperty('LabelView.Fade', '1')
                count += 1
                xbmc.sleep(1000)
                if self.running == 'no':
                    break

            order.reverse()

        # cleanup
        if self.running == 'slide':
            self.getControl(IMAGE[0]).setImage('blank.png')
            self.getControl(IMAGE[1]).setImage('blank.png')
            self.getControl(BACKG[0]).setImage('blank.png')
            self.getControl(BACKG[1]).setImage('blank.png')
        elif self.running == 'cross':
            piclist.reverse()
            for i in piclist:
                self.removeControl(i)
        elif self.running == 'wall':
            for i in self.wall['mesh']:
                self.removeControl(i)
                #i.setImage('blank.png')
            self.getControl(BACKG[0]).setImage('blank.png')
            self.getControl(BACKG[1]).setImage('blank.png')

        self.close()
        xbmc.log("UMSA SSaver - call screensaver deactivate", xbmc.LOGINFO)
        self.parent.onScreensaverDeactivated()

    def create_wall(self):
        """Create UI elements for wall mode depending on settings.

        - count evspace and ehspace together / 2 and then calc again with new space, see 4 rows
        - fade out and in so the background can be seen
        - in wall mode make one position a video
        """

        rows = self.settings['wall']['srows']
        rows_b = self.settings['wall']['srows_b']
        if self.settings['wall']['titles'] == "Titles":
            rows = self.settings['wall']['trows']
            rows_b = self.settings['wall']['trows_b']
        elif self.settings['wall']['titles'] == "Random":
            if randint(0, 1):
                rows = self.settings['wall']['trows']
                rows_b = self.settings['wall']['trows_b']
        else:
            xbmc.log("UMSA SSaver: create_wall error rows.", xbmc.LOGWARNING)

        # generate image and position list
        # TODO: make vars from spacing and other numbers
        x_space = 20
        y_space = 10
        x_max = 1280
        y_max = 660

        # how many rows
        if rows < rows_b:
            rows = randint(rows, rows_b)
        else:
            rows = randint(rows_b, rows)
        # width
        self.wall['width'] = int((x_max-(rows+1)*x_space)/rows)
        # height
        self.wall['height'] = int(
            self.wall['width']/1.3333/self.settings['ar_norm']*self.settings['ar_x'])
        # TODO: check spacing on big screen
        # idea is that info at the bottom is always visible
        cols = int((y_max-20)/self.wall['height'])
        evspace = int((y_max-self.wall['height']*cols)/(cols+1))
        # calculate width and x for vertical images
        self.wall['vert_width'] = int(
            self.wall['height']/1.3333*self.settings['ar_norm']/self.settings['ar_x'])
        self.wall['vert_x'] = int((self.wall['width']-self.wall['vert_width'])/2)
        # create lists
        self.wall['pics'] = rows*cols
        self.wall['pos'] = list(range(self.wall['pics']))
        # generate image list
        actual_x = x_space
        actual_y = y_space
        self.wall['mesh'] = []
        # TODO rework for, for
        for i in range(cols):
            for j in range(rows):
                self.wall['mesh'].append(
                    xbmcgui.ControlImage(actual_x, actual_y, self.wall['width'], self.wall['height'], ''))
                actual_x += self.wall['width']+x_space
            actual_y += self.wall['height']+evspace
            actual_x = x_space

        # TODO really needed? acutally coz run_wall does removeControl
        # if we could remove addControl here, no need for doModal before create_wall
        # add images to window
        for i in self.wall['mesh']:
            self.addControl(i)

        # shuffle position list
        shuffle(self.wall['pos'])
        # how many free
        if self.settings['wall']['free'] == 0:
            self.wall['free'] = 0
        else:
            self.wall['free'] = round(
                self.wall['pics']-(self.wall['pics']*self.settings['wall']['free']/100))
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
        # by onPlayBackStarted, the token identifies the playlist item whose
        # history has already been recorded (or deliberately skipped).
        self._playback_instance = 0
        self._av_recorded_token = None

    def _av_instance_token(self):
        """Return an identity for the current playback instance, or ``None``.

        The token combines the playback instance counter (bumped by
        ``onPlayBackStarted``), the playlist position and the playing file,
        so duplicate ``onAVStarted`` callbacks for one playback instance
        collapse to a single record while a later playback of the same set
        (a new instance / playlist position) is recorded again.
        """

        try:
            position = self.parent.saver.playlist.getposition()
        except (AttributeError, TypeError, ValueError, RuntimeError):
            position = None
        try:
            playing_file = self.getPlayingFile()
        except RuntimeError:
            playing_file = None
        if position is None and playing_file is None:
            return None
        return (self._playback_instance, position, playing_file)

    def onAVStarted(self):
        """Record the displayed video once a stream is actually available.

        Exactly once per playback instance (deduplicated by the instance
        token) and only while the screensaver runs in video mode. Missing or
        invalid ``umsa_set_id`` metadata (including Kodi < 20, which has no
        unique-ID API) and database failures are logged without disrupting
        playback; no exception ever escapes this callback.
        """

        try:
            saver = getattr(self.parent, 'saver', None)
            if saver is None or saver.running != 'videos':
                return

            token = self._av_instance_token()
            if token is not None and token == self._av_recorded_token:
                xbmc.log(
                    "UMSA SSaver Player: onAVStarted duplicate for the current "
                    "playback instance, not recording again",
                    xbmc.LOGDEBUG)
                return
            # this playback instance is handled from here on, whether or not
            # a record can be written (prevents duplicate log spam too)
            self._av_recorded_token = token

            xbmc.log("UMSA SSaver Player: onAVStarted", xbmc.LOGDEBUG)
            try:
                video_tag = self.getVideoInfoTag()
            except (AttributeError, RuntimeError) as error:
                xbmc.log(
                    f"UMSA SSaver Player: no video info tag yet: {error}",
                    xbmc.LOGWARNING)
                return
            if video_tag is None or not hasattr(video_tag, 'getUniqueID'):
                xbmc.log(
                    "UMSA SSaver Player: video history recording unavailable "
                    "(Kodi has no InfoTagVideo.getUniqueID)",
                    xbmc.LOGWARNING)
                return
            set_id = read_set_id(video_tag)
            if set_id is None:
                xbmc.log(
                    "UMSA SSaver Player: no valid umsa_set_id in video "
                    "metadata, history not recorded",
                    xbmc.LOGWARNING)
                return
            software_id = read_software_id(video_tag)

            ggdb = getattr(getattr(self.parent, 'umsa', None), 'ggdb', None)
            if ggdb is None:
                xbmc.log(
                    "UMSA SSaver Player: no database handle, history not recorded",
                    xbmc.LOGWARNING)
                return
            ggdb.record_screensaver_display(set_id, software_id)
            xbmc.log(
                f"UMSA SSaver Player: recorded screensaver history for "
                f"set {set_id}",
                xbmc.LOGDEBUG)
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
                # clear video label
                self.parent.saver.setProperty('LabelView.Fade', '1')
                # get total time in sec
                total_time = int(self.getTotalTime())
                # wait until video starts
                while total_time == 0:
                    xbmc.sleep(250)
                    total_time = int(self.getTotalTime())
                # calc show times
                if total_time > 28:
                    timecount1 = 10
                    timecount2 = total_time-10
                elif total_time > 16:
                    timecount1 = 8
                    timecount2 = total_time-2
                else:
                    timecount1 = 4
                    timecount2 = total_time-1
                self.runp = True
                count_seconds = 0
                xbmc.log(f"UMSA SSaver Player: time: {total_time}, start {timecount1}, end {timecount2}", xbmc.LOGINFO)
                # set labels
                self.parent.saver.getControl(INFO_LABEL).setLabel(
                    self.getVideoInfoTag().getTitle()
                )
                self.parent.saver.getControl(INFO_DETAIL).setLabel(
                    self.getVideoInfoTag().getGenre()
                )
                self.parent.saver.getControl(PIC_MACHINE).setImage(
                    self.getVideoInfoTag().getTrailer()
                )
                xbmc.log(f"UMSA SSaver director {self.getVideoInfoTag().getDirector()}", xbmc.LOGINFO)
                self.parent.saver.getControl(PIC_1TO1).setImage(
                    self.getVideoInfoTag().getDirector()
                )

                while self.runp:
                    if self.isPlayingVideo():
                        if count_seconds == timecount1:
                            self.parent.saver.setProperty('LabelView.Fade', '0')
                        elif count_seconds == timecount2:
                            self.parent.saver.setProperty('LabelView.Fade', '1')
                            self.runp = False
                            continue
                    else:
                        self.runp = False
                        continue
                    xbmc.sleep(1000)
                    count_seconds += 1
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
                self.saver.running = choice(self.saver.settings['type'])
                self.saver.settings['type'].append('videos')
            else:
                # check if any screensaver types are active
                if self.saver.settings['type']:
                    self.saver.running = choice(self.saver.settings['type'])
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
        xbmcgui.Window(10000).setProperty("UMSA.Screensaver.Mode", "no")

    def onDPMSActivated(self):
        """Stop screensaver when DPMS is activated."""
        self.onScreensaverDeactivated()
