# -*- coding: utf-8 -*-
"""Screensaver Module for UMSA Kodi Add-on.

TODO add 60+ empty 0,0 images to layout so that priorities for software info works!
     means: change python image creation to use layout images

TODO CLENAUP Addon module usage all over!!!

TODO label:
left_pic                machine_pic
gamename                year, maker

TODO:
start video and end routine, then in onplaybackstart wait for systemexit and
restart saver again, there wait until videofinished

onPlaybackStarted
try: # general or special video loop?
    self.parent.saver.wait_loop_video()
except SystemExit:
    self.parent.saver.wait_loop()

onEnd:
try: # start a new video
    self.parent.saver.get_art()
except SystemExit:
    self.parent.saver.get_art()


remake get_art... to fetch_art
set filename +++ to self.art if pic
when videosnaps: add to playlist with infos
redo onplaybackstart: use get_art and new wait_loop method in saver


- switch mode after some time -> save time and beginning and check diff in loop
- clean up art_type
- remove parent.umsa:
  - !!! take needed ggdb.get_random_art as args < needs machine_name as return value
  - select actual video as software: move to gui.py
- needs read filters from database for standalone usage
- on init: when video is on, check if we have videos only then allow
- update screensaver settings when change settings in gui.py runs

BUG Player: 'exceptions.SystemExit' caused by Kodi killing the screensaver
"""

from os import path
from random import randint, shuffle, choice
from hashlib import md5
from functools import reduce
from zipfile import ZipFile
import xbmc
from xbmcvfs import translatePath
from xbmcaddon import Addon
from xbmcgui import WindowXMLDialog, ControlImage, ListItem
from database import DBMod
from emulation import Emulation
from utilities import set_log
try:
    from PIL import Image, ImageStat
    PIL = True
except ImportError:
    PIL = False

__addon__ = Addon(id='script.umsa.mame.surfer')

MEDIA_FOLDER = translatePath(
    path.join(__addon__.getAddonInfo('path'), 'resources', 'skins', 'default', 'media'))

# TODO only have these one time, see gui
ACTION_PLAY_NEXTITEM = (14,112)
ACTION_MOVEMENT_RIGHT = (2,)
ACTION_CONTEXT = (117,)
ACTION_CANCEL_DIALOG = (9, 10, 51, 92, 110)
INFO_LABEL = 102
INFO_DETAIL = 108
PIC_MACHINE = 105
PIC_4TO3 = 104
PIC_3TO4 = 106
PIC_1TO1 = 107
IMAGE = [1, 2]
BACKG = [5, 6]

def check_image_aspect(set_info):
    """Pseudo aspect ratio check for image.

    Returns Vertical, Horizontal or NotScaled for one set
    based on display_type, display_rotation, category and swl_name
    """

    aspect_ratio = None
    if set_info['display_rotation'] in [90, 270]:
        aspect_ratio = 'Vertical'
    else:
        aspect_ratio = 'Horizontal'
    # TODO
    # - enhance list, check display_type
    # - problem is that set is not lcd, but machine gameboy!
    # - fetch display type for s['swl_machine_id']
    if (set_info['display_type'] == 'lcd' or
            set_info['category'] in (
                'Electromechanical / Pinball', 'Handheld Game') or
            set_info['swl_name'] in (
                'gameboy', 'lynx', 'gamegear', 'vboy', 'vectrex')
       ):
        aspect_ratio = 'NotScaled'
    return aspect_ratio

def create_gui_element_from_snap(set_info, image, art_type='unset'):
    """Returns Kodi ListItem element for a snapshot."""

    # set art
    if image:
        dir_split = path.dirname(image).split('/')
        if len(dir_split) < 2:
            art = art_type
        else:
            art = dir_split[-2]
            # dir is the same as swl, then set filename as art
            if art == set_info['swl_name']:
                art = path.basename(image)[:-4]
    else:
        art = art_type

    # create listitem
    list_item = ListItem()
    list_item.setLabel("{}: {} ({})".format(
        art, set_info['detail'], set_info['swl_name']))
    list_item.setArt({'icon': image})
    # label to later set
    list_item.setProperty('detail', "{}: {} {}".format(
        art, set_info['swl_name'], set_info['detail']))
    aspect = check_image_aspect(set_info)
    if aspect == 'Vertical':
        list_item.setProperty('Vertical', '1')
        list_item.setProperty('Horizontal', '')
        list_item.setProperty('NotScaled', '')
    elif aspect == 'Horizontal':
        list_item.setProperty('Vertical', '')
        list_item.setProperty('Horizontal', '1')
        list_item.setProperty('NotScaled', '')
    elif aspect == 'NotScaled':
        list_item.setProperty('Vertical', '')
        list_item.setProperty('Horizontal', '')
        list_item.setProperty('NotScaled', '1')
    return list_item

class Saver(WindowXMLDialog):
    """Screensaver implementation.

    Opens a new Kodi Window with it's on skin

    IMPORTANT: as soon as video plays the kodi screensaver mode gets deactivated
    this means we still need to feed the playlist and wait for interaction from user
    to stop playing videos

    TODO
     - keep playlist to a size of ??? videos, else grows
    """

    def __init__(self, *args, **kwargs):
        self.parent = kwargs['itself']
        self.__addon__ = Addon(id='script.umsa.mame.surfer')
        self.playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        self.running = "no"
        self.art_types = []
        self.wall = {}
        self.lastgames = []
        self.settings = {}

        if PIL:
            self.pil = True
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
            self.pil = False
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
        # monitor in video mode?
        if self.running == 'videos':
            if action.getId() in ACTION_PLAY_NEXTITEM+ACTION_MOVEMENT_RIGHT:
                # next video
                self.add_video_to_playlist()
                self.parent.player.playnext()
            elif action.getId() in ACTION_CONTEXT:
                # stop and show game
                # software id hidden in votes
                s_id = int(self.parent.player.getVideoInfoTag().getVotes())
                self.parent.umsa.lastptr += 1
                self.parent.umsa.last.insert(self.parent.lastptr, s_id)
                self.parent.umsa.select_software(self.parent.last[self.parent.lastptr])
                self.parent.player.stop()
                self.running = 'no'
                self.close()
            elif action.getId() in (88, 89):
                # allow changing volume with plus/minus
                pass
            else:
                self.parent.player.stop()
                self.running = 'no'
                self.close()
        elif self.running in ('cross', 'wall', 'slide'):
            # allow changing volume with plus/minus
            # also allow playnext and right should button for next vgm
            if self.parent.emulation.playrandomvgm or self.parent.emulation.playvgm:
                if action.getId() == 88:
                    self.parent.vgmaction = True
                    self.parent.umsa.monitor.emulation.send_vgmaction(b'volume_up')
                    xbmc.log("UMSA SSaver: sound volume + dont end saver", xbmc.LOGDEBUG)
                elif action.getId() == 89:
                    self.parent.vgmaction = True
                    self.parent.umsa.monitor.emulation.send_vgmaction(b'volume_down')
                    xbmc.log("UMSA SSaver: sound volume - dont end saver", xbmc.LOGDEBUG)
                elif action.getId() in ACTION_PLAY_NEXTITEM+ACTION_MOVEMENT_RIGHT:
                    self.parent.vgmaction = True
                    self.parent.umsa.monitor.emulation.send_vgmaction(b'exit')
                    xbmc.log("UMSA SSaver: next song - dont end saver", xbmc.LOGDEBUG)
                elif action.getId() == 13:
                    self.parent.emulation.playrandomvgm = False
                    self.parent.vgmaction = True
                    self.parent.umsa.monitor.emulation.send_vgmaction(b'exit')
                    # TODO check gui, clean music info
                else:
                    self.parent.reallyDeactivateScreensaver()
                    self.running = 'no'
                    self.close()
            else:
                self.parent.reallyDeactivateScreensaver()
                self.running = 'no'
                self.close()

    def read_settings(self):
        """Read screensaver settings from UMSA settings.xml."""

        self.path = (self.__addon__.getSetting('otherart'), self.__addon__.getSetting('progetto'))
        self.settings = {}

        aratio = self.__addon__.getSetting('aspectratio')
        ar_norm = 1.7777 # 16:9
        ar_x = 1.7777
        # for everything which is not 16:9
        if aratio == "16:10":
            ar_x = 1.6
        elif aratio == "5:4":
            ar_x = 1.25
        elif aratio == "4:3":
            ar_x = 1.3333
        self.settings['ar_norm'] = ar_norm
        self.settings['ar_x'] = ar_x

        self.settings['time'] = int(self.__addon__.getSetting('ssaver_time'))
        self.settings['info'] = False
        if self.__addon__.getSetting('ssaver_info') == 'true':
            self.settings['info'] = True
        self.settings['musicinfo'] = self.__addon__.getSetting('ssaver_musicinfo')

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
            except IOError:
                ret = False

            if img:
                try:
                    imgmd5 = md5(img.tobytes()).hexdigest()
                except IOError as error:
                    xbmc.log(f"UMSA SSaver: {snapshot} error md5sum: {error}", xbmc.LOGWARNING)
                    ret = False
                else:
                    imgv = ImageStat.Stat(img).var
                    img.close()
                    if imgmd5 in self.bad_image_list:
                        ret = False
                    elif reduce(lambda x, y: x and y < 0.010, imgv, True): # 0.005
                        ret = False
        else:
            img = False
            try:
                img = open(snapshot, 'rb')
            except IOError:
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
                        pic = path.join("reels.png")
                    if not pic:
                        pic = path.join(MEDIA_FOLDER, "arcade.png")
            else:
                if not pic:
                    pic = path.join(MEDIA_FOLDER, "arcade.png")
        # set machine pic for swl
        else:
            # TODO do with use_set['machine_name']... needs id
            # for swl_machine_art in self.ggdb.get_artwork_for_set(use_set['machine_id']):
            #    if swl_machine_art['type'] == 'cabinets':
            #        pic = path.join(
            #            cab_path, use_set['name']+swl_machine_art['extension'])
            if not pic:
                # TODO fallback media pic for missing swl machine cab
                pic = path.join(cab_path, use_set['machine_name']+'.png')
        return pic

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
        if rand_vid['swl_name'] == 'exodos':
            xbmc.log("UMSA SSaver: videoadd: found exodos video", xbmc.LOGDEBUG)
            # TODO zip://zipfile/videofile does not work
            # seems like kodi can't cope with Videos/MS-DOS/video.mp4
            zip_file, video_file = rand_vid['filename'][6:].split('.zip')
            temp_dir = translatePath("special://temp/")
            xbmc.log(f"UMSA SSaver: videoadd: extracting {video_file} from {zip_file}.zip", xbmc.LOGDEBUG)
            with ZipFile(f"{zip_file}.zip", "r") as z:
                #xbmc.log(f"videoadd: namelist in zip: {z.namelist()}", xbmc.LOGDEBUG)
                if video_file not in z.namelist():
                    xbmc.log("UMSA SSaver: videoadd: video not found", xbmc.LOGWARNING)
                    return False
                else:
                    filename = path.join(temp_dir, path.basename(video_file))
                    with z.open(video_file) as src, open(filename, "wb") as dst:
                        dst.write(src.read())
                    xbmc.log(f"UMSA SSaver: videoadd: extracted to {filename}", xbmc.LOGDEBUG)
        else:
            filename = path.join(
                self.path[rand_vid['path']],
                'videosnaps',
                rand_vid['swl_name'].replace('mame', 'videosnaps'),
                "{}.{}".format(rand_vid['name'], rand_vid['extension'])
            )
            xbmc.log(f"UMSA SSaver: videoadd: added {filename}", xbmc.LOGDEBUG)
        machine_pic = self.get_machine_pic(rand_vid)
        # get left pic
        # TODO get left pic: snap = cross,slide ; cover/flyer = video, wall
        # TODO needs fetch info for snap from db for aspect ratio
        if rand_vid['swl_name'] == 'mame':
            snapshot = path.join(
                self.path[rand_vid['path']], 'flyers/flyers',
                "{}.png".format(rand_vid['name']))
        else:
            snapshot = path.join(
                self.path[rand_vid['path']], 'covers', rand_vid['swl_name'],
                "{}.png".format(rand_vid['name']))
        xbmc.log("UMSA SSaver {}".format(snapshot), xbmc.LOGDEBUG)
        video_item = ListItem(rand_vid['gamename'])
        video_item.setInfo('video', {
            'Title': rand_vid['gamename'],
            'Genre': "{}, {}".format(rand_vid['year'], rand_vid['maker']),
            'Trailer': machine_pic,
            'Director': snapshot,
            'Votes': rand_vid['s_id']})
        self.playlist.add(url=filename, listitem=video_item)
        xbmc.log(f"UMSA SSaver: playlist size {self.playlist.size()}, pos {self.playlist.getposition()}", xbmc.LOGDEBUG)
        return True

    def get_art_and_call_saver(self):
        """blah."""

        # set art_types according to run mode
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
        # prepare run
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
            #self.getControl(103).setVisible(False)
            piclist = []
        order = [0, 1]
        # screensaver loop
        while self.running != 'no':
            # get random art
            art = self.parent.umsa.ggdb.get_random_art(self.art_types)
            # set file path
            if (art['swl_name'] == 'exodos') or (art['swl_name'][:5] == 'gb64_'):
                filename = art['filename']
            else:
                filename = path.join(
                    self.path[art['path']], art['type'],
                    art['swl_name'].replace('mame', art['type']),
                    "{}.{}".format(art['name'], art['extension']))
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
                if art['swl_name'] == 'mame':
                    snapshot = path.join(
                        self.path[art['path']], 'flyers/flyers',
                        "{}.{}".format(art['name'], art['extension']))
                else:
                    snapshot = path.join(
                        self.path[art['path']], 'covers', art['swl_name'],
                        "{}.{}".format(art['name'], art['extension']))
                #xbmc.log(snapshot, xbmc.LOGDEBUG)
                self.getControl(PIC_1TO1).setImage(snapshot, False)
                self.getControl(PIC_4TO3).setImage('')
                self.getControl(PIC_3TO4).setImage('')
            else:
                # TODO dirty hack, get from db! maybe get_random_art should return it!
                snapshot = path.join(
                    self.path[1], 'snap',
                    art['swl_name'].replace('mame', 'snap'),
                    "{}.{}".format(art['name'], 'png'))
                #xbmc.log("UMSA screensaver: bottom left snap - %s" % (snapshot), xbmc.LOGDEBUG)
                #xbmc.log("UMSA screensaver: real filename    - %s" % (filename), xbmc.LOGDEBUG)
                snapctrl = PIC_4TO3
                if self.check_snapshot(snapshot):
                    self.getControl(snapctrl).setImage(snapshot, False)
                # no snapshot = clear all 3 snap views
                else:
                    self.getControl(PIC_4TO3).setImage('')
                    self.getControl(PIC_3TO4).setImage('')
                    self.getControl(PIC_1TO1).setImage('')
            # set info label
            # dont use bold the net says for subtitles
            #self.getControl(INFO_LABEL).setLabel("[B]{}[/B]".format(art['gamename']))
            self.getControl(INFO_LABEL).setLabel(f"{art['gamename']}")
            self.getControl(INFO_DETAIL).setLabel(
                "{}, {}".format(art['year'], art['maker']))

            # call saver
            if self.running == 'cross':
                x_axis = randint(0, 1280)
                y_axis = randint(0, 720)
                if aspect == 'Vertical':
                    # TODO look up aspect calc from ssaver
                    piclist.append(ControlImage(x_axis-120, y_axis-160, 240, 320, filename))
                elif aspect == 'NotScaled':
                    piclist.append(ControlImage(x_axis-180, y_axis-180, 360, 360, filename, 2))
                else:
                    piclist.append(ControlImage(x_axis-180, y_axis-135, 360, 270, filename))
                # show pic
                self.addControl(piclist[-1])
                if len(piclist) > 60:
                    self.removeControl(piclist[0])
                    del piclist[0]
            elif self.running == 'slide':
                self.getControl(IMAGE[order[0]]).setImage(filename)
                self.setProperty('SlideView.Slide{}'.format(order[0]+1), '0')
                self.setProperty('SlideView.Slide{}'.format(order[1]+1), '1')
                self.setProperty('SlideView.Fade1{}'.format(order[0]+1), '0')
                self.setProperty('SlideView.Fade1{}'.format(order[1]+1), '1')
                self.getControl(BACKG[order[0]]).setImage(filename)
            elif self.running == 'wall':
                # refill position list when empty
                if len(self.wall['pos']) == 0:
                    self.wall['pos'] = range(self.wall['pics'])
                    shuffle(self.wall['pos'])
                    # dont let the last entry in list
                    # be the last position choosen'
                    while self.wall['pos'][-1] == lastpos:
                        shuffle(self.wall['pos'])
                # pop new position from list
                lastpos = self.wall['pos'].pop()
                # TODO does not work with my 3 pics of 6 kacheln
                # delete one of the last pics
                if self.wall['free'] != 0:
                    self.wall['freelist'].append(lastpos)
                    #print("IMAGELIST:")
                    #print(self.wall['pos'])
                    #print("FREELIST:")
                    #print(self.wall['freelist'])
                    if len(self.wall['freelist']) == self.wall['free']:
                        tofree = self.wall['freelist'].pop(
                            randint(0, round(len(self.wall['freelist'])/2)))
                        # print "TO MAKE FREE: %s" % (tofree)
                        # insert actual to be cleaned image pos
                        # to wall['pos']
                        self.wall['pos'].insert(0, tofree)
                        # make image empty
                        self.removeControl(self.wall['mesh'][tofree])
                        self.wall['mesh'][tofree].setImage('')
                        # TODO unneeded?
                        self.addControl(self.wall['mesh'][tofree])
                # check if image is horizontal, vertical
                # or aspect ratio must be keeped
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
                    self.wall['mesh'][lastpos] = ControlImage(
                        pos_x, pos_y, self.wall['width'], self.wall['height'], '')
                elif aspect == 'Vertical':
                    self.wall['mesh'][lastpos] = ControlImage(
                        pos_x + self.wall['vert_x'], pos_y,
                        self.wall['vert_width'], self.wall['height'], '')
                elif aspect == 'NotScaled':
                    self.wall['mesh'][lastpos] = ControlImage(
                        pos_x, pos_y, self.wall['width'], self.wall['height'], '', 2)
                # set image
                self.wall['mesh'][lastpos].setImage(filename, False)
                # add new image control
                self.addControl(self.wall['mesh'][lastpos])
                self.getControl(BACKG[order[0]]).setImage(filename)
                self.setProperty('SlideView.Fade1{}'.format(order[0]+1), '0')
                self.setProperty('SlideView.Fade1{}'.format(order[1]+1), '1')

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
            # change order
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

        #print("UMSA: Saver - clear Properties and close")
        #self.clearProperties()
        #self.clearList()
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
        #ehspace = (x_max-self.wall['width']*rows)/(rows+1)
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
                    ControlImage(actual_x, actual_y, self.wall['width'], self.wall['height'], ''))
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
     onPlayBackEnded

    Used by video screensaver as Kodi Monitor ends when a video is started.
    Controls after how many seconds the video label blends in.
    """

    def __init__(self, **kwargs):
        self.parent = kwargs['itself']
        self.runp = False

    def onPlayBackStarted(self):
        """Reacts to Kodi event 'onPlayBackStarted'"""

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
                #while not self.parent.player.isPlayingVideo():
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
            #self.parent.saver.setProperty('LabelView.Fade', '1')
            self.runp = False

            if self.parent.saver.running == 'videos':
                xbmc.log("UMSA SSaver Player: add video to playlist", xbmc.LOGINFO)
                self.parent.saver.add_video_to_playlist()
        except SystemExit as err:
            xbmc.log(f"UMSA SystemExit onPlayBackStarted: {err}", xbmc.LOGWARNING)

        # when alreadyplaying is stopped set playvideo according to settings
        # TODO: test, maybe have to use "def OnStop(self):"
        #elif self.parent.already_playing:
        #    self.parent.already_playing = None
        #    if self.__addon__.getSetting('playvideo') == 'true':
        #        self.parent.playvideo = True
        #else:
        #    pass
            # multiimage not supported
            # xbmc.log("UMSA SSaver ### revert right image size", xbmc.LOGDEBUG)
            # self.parent.getControl(IMAGE_RIGHT).setPosition(600,35)
            # self.parent.getControl(IMAGE_RIGHT).setHeight(650)

class Monitor(xbmc.Monitor):
    """Kodi Monitor Class"""

    def __init__(self, **kwargs):
        self.umsa = kwargs['itself']
        __addon__ = Addon(id='script.umsa.mame.surfer')
        self.player = Player(itself=self)
        self.vgmaction = False
        self.saver = Saver(
            "umsa_saver.xml", __addon__.getAddonInfo('path'), "default", "720p", itself=self)
        # initalize Emulation class
        self.emulation = Emulation(
            mame_ini_file=self.umsa.mameini,
            mame_dir=self.umsa.mame_dir,
            mame_exe=self.umsa.mame_exe,
            vgmplay_exe=self.umsa.vgmplay_exe,
            vgmlua_script=path.join(
                translatePath(__addon__.getAddonInfo('path')), 'resources/lib/vgmplay.lua'),
            monitor_self=self,
        )

    def play_saver(self, saver, art_types=None):
        """Start specific screensaver.
        
        TODO: remove calls and use xbmc.executebuiltin('ActivateScreensaver') instead
        """
        # TODO make also setting
        #if not self.emulation.playrandomvgm:
        #    self.play_random_vgm()
        self.saver.running = saver
        self.saver.art_types = art_types
        self.saver.doModal()

    #def play_vgm(self):
    #    self.emulation.play_vgm(vgm, sec2run, sleep, intro)

    def play_random_vgm(self):
        self.emulation.play_random_vgm(
            ggdb=self.umsa.ggdb, db_path=self.umsa.settings_folder, sleep=xbmc.sleep)

    def startme(self):
    #def onScreensaverActivated(self):
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
            set_log(lambda *args, level='debug': xbmc.log(' '.join(map(str, args)),
                {'debug': xbmc.LOGDEBUG, 'info': xbmc.LOGINFO, 'warning': xbmc.LOGWARNING,
                 'error': xbmc.LOGERROR}
                .get(level, xbmc.LOGDEBUG)))
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
        elif self.emulation.playrandomvgm:
            xbmc.log("UMSA SSaver Monitor: dont stop as random vgm plays and it could be a command", xbmc.LOGDEBUG)
        else:
            xbmc.log("UMSA SSaver Monitor: no vgm playing, stopping screensaver", xbmc.LOGDEBUG)
            self.reallyDeactivateScreensaver()

            # TODO only when started by screensaver
            #if self.emulation.playrandomvgm:
            #    self.emulation.send_vgmaction(b'x')
            #    self.emulation.playrandomvgm = None
            #self.saver.running = 'no'
            #del self.saver
            #__addon__ = Addon(id='script.umsa.mame.surfer')
            #self.saver = Saver(
            #    "umsa_saver.xml", __addon__.getAddonInfo('path'), "default", "720p", itself=self)

    def reallyDeactivateScreensaver(self):

        xbmc.log("UMSA SSaver Monitor: now really deactive screensaver", xbmc.LOGINFO)
        self.saver.running = 'no'
        del self.saver
        __addon__ = Addon(id='script.umsa.mame.surfer')
        self.saver = Saver(
            "umsa_saver.xml", __addon__.getAddonInfo('path'), "default", "720p", itself=self)

    def onDPMSActivated(self):
        """Stop screensaver when DPMS is activated."""
        self.onScreensaverDeactivated()

class Screensaver():
    """Class is used for calling from outside UMSA Addon, like Kodi Picture Screensaver."""

    def __init__(self):
        self.ggdb = None
        self.monitor = None

    def run(self):
        """Kodi onInit."""

        self.settings_folder = translatePath(__addon__.getAddonInfo('profile'))
        if path.isfile(path.join(self.settings_folder, 'umsa.db')):
            self.ggdb = DBMod(self.settings_folder)
        else:
            xbmc.log("UMSA SSaver: No UMSA database for Screensaver run.", xbmc.LOGWARNING)
        # get mame exe and dir needed by monitor init for vgm play which needs emulation init
        self.mame_exe = __addon__.getSetting('mame')
        self.mame_dir = __addon__.getSetting('mamedir')
        self.mameini = __addon__.getSetting('mameini')
        # TODO TEST again without filter = False
        self.ggdb.use_filter = False
        self.monitor = Monitor(itself=self)
        # TODO make setting
        # self.monitor.play_random_vgm( )
        self.monitor.startme()
        #self.monitor.onScreensaverActivated()
