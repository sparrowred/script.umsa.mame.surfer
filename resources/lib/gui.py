# -*- coding: utf-8 -*-
"""Main Gui for Kodi Addon

TODO
- rework gamelist actions:
   always use top label id to decide whats in the list
   then only list with diff things like media (video,manual,replay) need yt==id
   for others we know the what the id is: software, maker, swl, cat
- create dict for sort order of artwork images
"""

import os
import sys
import time
import zipfile
from io import BytesIO
from threading import Thread
from json import dumps, loads
from subprocess import PIPE, Popen, check_output # TODO check output to tools coz demul
from random import choice, randint
# PY2: remove except part for py3 only
try:
    from urllib.request import urlopen
except ImportError:
    from urllib2 import urlopen

import xbmc
import xbmcgui
import xbmcaddon
# own modules
import tools # emulator functions
import utilmod # utility functions
from screensaver import Check, check_image_aspect, create_gui_element_from_snap
from dbmod import DBMod # database module

# TODO check what we use
__addon__ = sys.modules['__main__'].__addon__

SCRIPTID = "script.umsa.mame.surfer"
PY_VER = sys.version_info
PLATFORM = sys.platform

# folder for settings
SETTINGS_FOLDER = xbmc.translatePath(
    'special://profile/addon_data/{}'.format(SCRIPTID)
)
MEDIA_FOLDER = xbmc.translatePath(
    'special://home/addons/{}/resources/skins/Default/media/'.format(SCRIPTID)
)

#Action Codes
# See guilib/Key.h
ACTION_CANCEL_DIALOG = (9, 10, 51, 92, 110)
ACTION_PLAYFULLSCREEN = (12, 79, 227)
ACTION_MOVEMENT_LEFT = (1,)
ACTION_MOVEMENT_RIGHT = (2,)
ACTION_MOVEMENT_UP = (3,)
ACTION_MOVEMENT_DOWN = (4,)
ACTION_MOVEMENT = (1, 2, 3, 4, 5, 6, 159, 160)
ACTION_INFO = (11,)
ACTION_PLAY_NEXTITEM = (14,)
ACTION_SOUND_VOLUME = (88, 89)
ACTION_CONTEXT = (117,)
ACTION_ENTER = (7,)

#ControlIds
SERIES_LABEL = 2301
COMPILATION_LABEL = 2302
MEDIA_LABEL = 2303
VIDEO_LABEL = 2005
SOFTWARE_BUTTON = 4000
MAIN_MENU = 4901
GROUP_GAME_LIST = 407
GROUP_FILTER = 408
TEXTLIST = 4033
IMAGE_RIGHT = 2232
IMAGE_BIG_LIST = 2233
IMAGE_LIST = 2223
LEFT_IMAGE_HORI = 2222
LEFT_IMAGE_VERT = 2221
SET_LIST = 4003
SYSTEM_BORDER = 2405
SYSTEM_WRAPLIST = 4005
MACHINE_PLUS = 4210
MACHINE_SEP1 = 2406
MACHINE_SEP2 = 2407
MACHINE_SEP3 = 2408
LISTMODE_MENU = 4902
# TODO rename GAME_LIST to LISTMODE
GAME_LIST = 4007
GAME_LIST_BG = 4107
GAME_LIST_LABEL = 4117
GAME_LIST_LABEL_ID = 4217
GAME_LIST_OPTIONS = 4118
GAME_LIST_SORT = 4119
GAME_LIST_IMAGE = 4115
GAME_LIST_TEXT = 4114
FILTER_CATEGORY_LIST = 4008
FILTER_CONTENT_LIST_ACTIVE = 4088
FILTER_CONTENT_LIST_INACTIVE = 4089
FILTER_LIST_BG = 4108
FILTER_LABEL = 4109
FILTER_LABEL2 = 4110
FILTER_OPTIONS = 4116
LABEL_STATUS = 4101
SHADOW_MACHINE = 4201
SHADOW_SET = 4202
SHADOW_DAT = 4203

#menu
M_MACHINE = 21
M_ALLEMUS = 22
M_SERIES = 3
M_MEDIA = 4
M_SEARCH = 5
M_SEARCH_NEW = 51
M_ALL = 61
M_MAKER = 62
M_CAT = 63
M_YEAR = 64
M_SOURCE = 65
M_SWL = 66
M_REC = 67
M_FILTER = 7
M_UPD = 81
M_SSAVER = 82
M_PLAYSTAT = 83
M_LSSAVER = 84
M_ASETTINGS = 86
M_EXIT = 9
M_PLAYERS = 90

# xbmc.sleep times in ms
WAIT_PLAYER = 500
WAIT_GUI = 100

# TODO: use
SUPPORT_ORDER = {'History': 1, 'Info': 2, 'Command': 3, 'Series': 4, 'WIP': 5}

# filter categories
FILTER_CAT = [
    "Softwarelists", "Game Categories", "Machine Categories", "Players",
    "Years", "----------", "Load Filter", "Save Filter"
]
# order of listmode submenu for select
SUBMENU_ORDER = {
    M_ALL: 0, M_SERIES: 1, M_MAKER: 2, M_CAT: 3, M_REC: 4, M_YEAR: 5, M_PLAYERS: 6,
    M_SWL: 7, M_SOURCE: 7, M_SSAVER: 8, M_PLAYSTAT: 9
}
# list with types of art on progettosnaps
LEFT_IMAGELIST = ('snap', 'titles', 'howto', 'logo', 'bosses', 'ends',
                  'gameover', 'scores', 'select', 'versus', 'warning')
RIGHT_IMAGELIST = ('cabinets', 'cpanel', 'flyers', 'marquees',
                   'cabdevs', 'pcb', 'artpreview', 'covers',
                   'projectmess_covers')

class FSVideoSaver(xbmcgui.WindowXMLDialog):
    """Plays videos as a screensaver

    Opens a new Kodi Window with it's on skin

    IMPORTANT: as soon as video plays the kodi screensaver mode gets deactivated
    this means we still need to feed the playlist and wait for interaction from user
    to stop playing videos

    TODO
     - keep playlist to a size of ??? videos, else grows
     - put into screensaver module
    """

    def __init__(self, *args, **kwargs):
        self.parent = kwargs['itself']
        self.playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)

    def add_video_to_playlist(self):
        """Add a new video to the playlist"""

        xbmc.log("UMSA FSVideoSaver: add video to playlist")
        rand_vid = self.parent.ggdb.get_random_art(['videosnaps'])
        if not rand_vid:
            xbmc.executebuiltin('XBMC.Notification(Screensaver,no videos found,3000)')
            xbmc.log("UMSA FSVideoSaver: did not find any videos")
            self.parent.Player.stop()
            self.parent.Monitor.running = 'no'
            self.close()
            self.parent.Monitor.snapshot_crossover(['covers', 'flyers'])
            return
        filename = os.path.join(
            self.parent.progetto,
            'videosnaps',
            rand_vid['swl'].replace('mame', 'videosnaps'),
            "{}.{}".format(rand_vid['name'], rand_vid['extension'])
        )
        gameinfo = "{} ({}, {}, {})".format(
            rand_vid['gamename'], rand_vid['swl'],
            rand_vid['year'], rand_vid['maker']
        )
        video_item = xbmcgui.ListItem(rand_vid['gamename'])
        video_item.setInfo('video', {'Title': gameinfo, 'Votes': rand_vid['s_id'],})
        self.playlist.add(url=filename, listitem=video_item)
        xbmc.log("UMSA FSVideoSaver: playlist size {}, pos {}".format(
            self.playlist.size(), self.playlist.getposition()))

    def onInit(self):
        """Kodi onInit"""

        xbmc.log("UMSA FSVideoSaver: onInit")
        self.playlist.clear()
        self.add_video_to_playlist()
        self.add_video_to_playlist()
        self.parent.Player.play(self.playlist)

    #def onFocus(self, controlid):
    #    """Kodi onFocus - unused"""

    #def onClick(self, controlid):
    #    """Kodi onClick - unused"""

    def onAction(self, action):
        """Kodi onAction"""

        xbmc.log("UMSA FSVideoSaver: onAction {}".format(self.parent.Monitor.running))
        # monitor in video mode?
        if self.parent.Monitor.running == 'video':
            if action.getId() in ACTION_PLAY_NEXTITEM+ACTION_MOVEMENT_RIGHT:
                # next video
                self.add_video_to_playlist()
                self.parent.Player.playnext()
            elif action.getId() in ACTION_CONTEXT:
                # stop and show game
                # software id hidden in votes
                s_id = int(self.parent.Player.getVideoInfoTag().getVotes())
                self.parent.lastptr += 1
                self.parent.last.insert(self.parent.lastptr, s_id)
                self.parent.select_software(self.parent.last[self.parent.lastptr])
                self.parent.Player.stop()
                self.parent.Monitor.running = 'no'
                self.close()
            elif action.getId() in (88, 89):
                # allow changing volume with plus/minus
                pass
            else:
                self.parent.Player.stop()
                self.parent.Monitor.running = 'no'
                self.close()

        if action.getId() == 13: # x for Stop
            self.parent.Player.stop()
            self.parent.Monitor.running = 'no'
            self.close()
        if action.getId() in ACTION_CANCEL_DIALOG:
            self.parent.Player.stop()
            self.parent.Monitor.running = 'no'
            self.close()

class Player(xbmc.Player):
    """Kodi Video Player Class

    Reacts to:
     onPlayBackStarted
     onPlayBackEnded

    Used by video screensaver as Kodi Monitor ends when a video is started.
    Controls after how many seconds the video label blends in.
    """

    def __init__(self, *args, **kwargs):
        self.parent = kwargs['itself']
        self.runp = False

    def onPlayBackStarted(self):
        """Reacts to Kodi event 'onPlayBackStarted'"""

        xbmc.log("UMSA Player: onPlayBackStarted")
        # when video ssaver runs
        if self.parent.Monitor.running == 'video':
            xbmc.log("UMSA Player: monitor mode is video")
            # clear video label
            self.parent.VPlayer.getControl(VIDEO_LABEL).setLabel('')

            # get total time in sec
            total_time = int(self.parent.Player.getTotalTime())
            # wait until video starts
            #while not self.parent.Player.isPlayingVideo():
            while total_time == 0:
                xbmc.sleep(100)
                total_time = int(self.parent.Player.getTotalTime())
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
            xbmc.log("UMSA Player: time: {}, start {}, end {}".format(
                total_time, timecount1, timecount2))
            while self.runp:
                if self.parent.Player.isPlayingVideo():
                    if count_seconds == timecount1:
                        # set video label
                        self.parent.VPlayer.getControl(VIDEO_LABEL).setLabel(
                            self.parent.Player.getVideoInfoTag().getTitle()
                        )
                    elif count_seconds == timecount2:
                        self.parent.VPlayer.getControl(VIDEO_LABEL).setLabel('')
                        self.runp = False
                        continue
                else:
                    self.runp = False
                    continue
                xbmc.sleep(1000)
                count_seconds += 1
        xbmc.log("UMSA Player: onPlayBackStarted: routine ended")

    def onPlayBackEnded(self):
        """Reacts to Kodi event 'onPlayBackEnded'"""

        xbmc.log("UMSA Player: onPlayBackEnded")
        self.parent.VPlayer.getControl(VIDEO_LABEL).setLabel('')
        self.runp = False
        if self.parent.Monitor.running == 'video':
            xbmc.log("UMSA Player: add video to playlist")
            self.parent.VPlayer.add_video_to_playlist()
        # when alreadyplaying is stopped set playvideo according to settings
        # TODO: test, maybe have to use "def OnStop(self):"
        elif self.parent.already_playing:
            self.parent.already_playing = None
            if __addon__.getSetting('playvideo') == 'true':
                self.parent.playvideo = True
        else:
            pass
            # multiimage not supported
            # xbmc.log("### revert right image size")
            # self.parent.getControl(IMAGE_RIGHT).setPosition(600,35)
            # self.parent.getControl(IMAGE_RIGHT).setHeight(650)

class Monitor(xbmc.Monitor):
    """Kodi Monitor Class

    Used for screensaver functionality

    Reacts to
     onScreensaverActivated
     onScreensaverDeactivated

    TODO
     put everything into a module, so we can use it from kodi ssaver
     split umsa code from kodi ssaver into new module
     switch mode after some time -> needs timer class

    IDEAS
     just scroll through list with videos
     emulator run! (would be nice with list of good demos)
    """

    def __init__(self, *args, **kwargs):
        self.parent = kwargs['itself']
        self.running = "no"

    def snapshot_crossover(self, art_types):
        """snapshot crossover"""

        piclist = []
        self.running = 'pic'
        while self.running == 'pic':
            snap = self.parent.ggdb.get_random_art(art_types)
            # stop when no pics found
            if not snap:
                self.running = 'no'
                continue
            # set path
            if snap['path']:
                path = self.parent.progetto
            else:
                path = self.parent.other_artwork
            filename = os.path.join(
                path,
                snap['type'],
                snap['swl'].replace(
                    'mame', snap['type']), '{}.{}'.format(snap['name'], snap['extension'])
                )
            # check for bad image
            if snap['type'] in ('snap', 'titles', 'covers'):
                if not self.parent.util.check_snapshot(filename):
                    continue
            # set scaling
            if snap['type'] not in ('snap', 'titles'):
                aspect = 'NotScaled'
            else:
                aspect = check_image_aspect(
                    {
                        'display_rotation' : snap['display_rotation'],
                        'display_type' : snap['display_type'],
                        'category' : snap['cat'],
                        'swl_name' : snap['swl'],
                    }
                )
            x_axis = randint(0, 1280)
            y_axis = randint(0, 720)
            if aspect == 'Vertical':
                # TODO look up aspect calc from ssaver
                piclist.append(
                    xbmcgui.ControlImage(x_axis-120, y_axis-160, 240, 320, filename)
                )
            elif aspect == 'NotScaled':
                piclist.append(
                    xbmcgui.ControlImage(x_axis-180, y_axis-180, 360, 360, filename, 2)
                )
            else:
                piclist.append(
                    xbmcgui.ControlImage(x_axis-180, y_axis-135, 360, 270, filename)
                )
            # show pic
            self.parent.addControl(piclist[-1])
            if len(piclist) > 60:
                self.parent.removeControl(piclist[0])
                del piclist[0]
            xbmc.sleep(2000)
        # clean up
        piclist.reverse()
        for i in piclist:
            self.parent.removeControl(i)

    def onScreensaverActivated(self):
        """Start screensaver when emulator is not running

        TODO make crossover content selectable
        """
        xbmc.log("UMSA Monitor: screensaver activated")

        # only when not already running and no emulator running
        if self.parent.emurunning:
            self.running = "emu"
        elif self.running == "no":
            # no videos when audio is running
            if self.parent.Player.isPlayingAudio():
                self.snapshot_crossover(['covers', 'flyers'])
            # check addon setting
            elif self.parent.ssaver_type == "Random":
                if randint(0, 1):
                    self.snapshot_crossover(['covers', 'flyers'])
                else:
                    self.parent.play_random_videos()
            elif self.parent.ssaver_type == "Snaps":
                self.snapshot_crossover(['covers', 'flyers'])
            elif self.parent.ssaver_type == "Videos":
                self.parent.play_random_videos()
        xbmc.log("UMSA Monitor: onScreensaverActivated routine stop")

    def onScreensaverDeactivated(self):
        """onScreensaverDeactivated"""
        xbmc.log("UMSA Monitor: screensaver deactivated")

        # was started after run_emulator
        if self.running == "emu":
            self.parent.emu_dialog.close()

        if self.running != 'video':
            self.running = 'no'
        else:
            xbmc.log("UMSA Monitor: video screensaver stays active")

class UMSA(xbmcgui.WindowXMLDialog):
    """Main UMSA class"""

    def __init__(self, strXMLname, strFallbackPath, strDefaultName, forceFallback):

        # initialize
        self.mame_ini = None
        self.quit = False
        self.selected_control_id = SOFTWARE_BUTTON # holds the old control id from skin
        self.main_focus = SOFTWARE_BUTTON # remember main select when in gamelist
        self.info = None # contains all sets for actual software

        self.dummy = None # needed to prevent a software jump
                          # when popup is quit by left or right
        self.enter = None # set when a gamelist select happens
        self.oldset = () # needed for show_info to see if set has changed
        self.emurunning = False # to prevent ssaver when emulation is in progress
        # to assure only one thread is running
        self.scan_thread = None
        # list for last selected games, only saves the software id
        self.last = []
        # pointer for last selected games list
        self.lastptr = 9
        # old search
        self.searchold = None
        # diff emu toggle
        self.diff_emu = False

        self.Monitor = None
        self.Player = None
        self.VPlayer = None
        self.dialog = None
        self.emu_dialog = None
        self.progress_dialog = None
        self.already_playing = None
        self.playvideo = None
        self.filter_lists = None
        self.act_filter = None
        self.ggdb = None
        self.actset = None
        self.all_art = None
        self.all_dat = None
        self.played = None
        self.vidman = None
        self.emulation_start = 0

        # no settings
        if not os.path.exists(SETTINGS_FOLDER):
            __addon__.openSettings()
        self.read_settings()

        # import check_snapshot for screensaver
        self.util = Check()
        if self.util.pil:
            xbmc.log("UMSA: PIL library found")

        xbmc.log("UMSA __init__ done")

    def onInit(self):
        """Kodi onInit"""

        # make all popups unvisible
        self.getControl(MACHINE_PLUS).setVisible(False)
        self.getControl(SHADOW_DAT).setVisible(False)
        #self.getControl(SHADOW_MACHINE).setVisible(False)
        #self.getControl(SHADOW_SET).setVisible(False)
        # separators for machine wraplist
        self.getControl(MACHINE_SEP1).setVisible(False)
        self.getControl(MACHINE_SEP2).setVisible(False)
        self.getControl(MACHINE_SEP3).setVisible(False)
        # scm indicators
        self.getControl(SERIES_LABEL).setVisible(False)
        self.getControl(COMPILATION_LABEL).setVisible(False)
        self.getControl(MEDIA_LABEL).setVisible(False)

        # setup monitor and player classes
        self.Monitor = Monitor(itself=self)
        self.Player = Player(itself=self)
        self.VPlayer = FSVideoSaver(
            "umsa_vplay.xml",
            __addon__.getAddonInfo('path'),
            "Default",
            "720p",
            itself=self
        )

        # for kodi dialogs
        self.dialog = xbmcgui.Dialog()
        self.emu_dialog = xbmcgui.DialogProgress()

        # bg progress bar
        self.progress_dialog = xbmcgui.DialogProgressBG()

        # no videos when something is already running
        if self.Player.isPlayingVideo():
            self.already_playing = True

        # set aspectratio for left images depending on screen aspect
        if self.aratio == "16:10":
            _4to3 = self.getControl(LEFT_IMAGE_HORI).getWidth()
            _3to4 = self.getControl(LEFT_IMAGE_VERT).getWidth()
            self.getControl(LEFT_IMAGE_HORI).setWidth(int(_4to3 /1.6*1.77)) # 4:3
            self.getControl(LEFT_IMAGE_VERT).setWidth(int(_3to4 *1.77/1.6)) # 3:4
        elif self.aratio == "5:4":
            _4to3 = self.getControl(LEFT_IMAGE_HORI).getWidth()
            _3to4 = self.getControl(LEFT_IMAGE_VERT).getWidth()
            self.getControl(LEFT_IMAGE_HORI).setWidth(int(_4to3 /1.25*1.77)) # 4:3
            self.getControl(LEFT_IMAGE_VERT).setWidth(int(_3to4 *1.77/1.25)) # 3:4
        elif self.aratio == "4:3":
            _4to3 = self.getControl(LEFT_IMAGE_HORI).getWidth()
            _3to4 = self.getControl(LEFT_IMAGE_VERT).getWidth()
            self.getControl(LEFT_IMAGE_HORI).setWidth(int(_4to3  /1.33*1.77)) # 4:3
            self.getControl(LEFT_IMAGE_VERT).setWidth(int(_3to4  *1.77/1.33)) # 3:4

        # load mame.ini
        self.mame_ini = utilmod.parse_mame_ini(self.mameini)

        # set snap directory
        if 'snapshot_directory' in self.mame_ini:
            self.mame_ini['snapshot_directory'] = os.path.join(
                self.mame_dir,
                self.mame_ini['snapshot_directory']
            )
        else:
            self.mame_ini['snapshot_directory'] = ''

        # load filters
        self.filter_lists = utilmod.load_filter(SETTINGS_FOLDER, 'filter_default.txt')
        self.act_filter = 'default'
        self.getControl(FILTER_LABEL2).setLabel('Filter: {}'.format(self.act_filter))

        # fill filter lists
        list_items = []
        for i in FILTER_CAT:
            list_items.append(xbmcgui.ListItem(i))
        self.getControl(FILTER_CATEGORY_LIST).addItems(list_items)
        self.getControl(FILTER_OPTIONS).addItems(('all', 'none', 'invert'))

        # database connection
        if os.path.isfile(os.path.join(SETTINGS_FOLDER, 'umsa.db')):
            self.ggdb = DBMod(SETTINGS_FOLDER, self.filter_lists, self.pref_country)
        else:
            # DB download in foreground, dat+art scan in background
            self.update('db')
            self.scan_thread = Thread(target=self.update_all)
            self.scan_thread.start()

        # load filter content for swl
        #self.set_filter_content('Softwarelists')
        # TODO: set_filter_content also sets focus
        # then first keypress in gui is missed, therefore:
        #self.setFocus(self.getControl(SOFTWARE_BUTTON))

        # load last internal software list
        self.last = utilmod.load_software_list(
            SETTINGS_FOLDER, 'lastgames.txt'
        )
        # fill with random software if not 10
        while len(self.last) < 10:
            self.last.append(self.ggdb.get_random_id())
        # select software
        self.select_software(self.last[self.lastptr])

        xbmc.log("UMSA onInit: done")
        # dialog.notification(
        #     'UMSA',
        #     'GUI Init done.',
        #     xbmcgui.NOTIFICATION_INFO,
        #     5000
        # )

        if self.quit:
            self.close()
            return

    # sequence: onFocus, onClick, onAction

    def onFocus(self, control_id):
        """Kodi onFocus"""

        xbmc.log("UMSA onFocus: old: {}".format(self.selected_control_id))
        xbmc.log("UMSA onFocus: new: {}".format(control_id))

        # TODO: get rid off dummy with a list instead of the software button?
        # list item label would then be actual software button input from skin
        self.dummy = None

        # close popups
        if control_id in (SOFTWARE_BUTTON, SYSTEM_WRAPLIST, SET_LIST, TEXTLIST):
        #if control_id == SOFTWARE_BUTTON or control_id == SYSTEM_WRAPLIST:

            if self.selected_control_id in (
                    GAME_LIST, GAME_LIST_OPTIONS, GAME_LIST_SORT, LISTMODE_MENU
                ):
                #self.setFocus(self.getControl(SOFTWARE_BUTTON))
                if self.enter:
                    self.enter = None
                else:
                    self.dummy = True

            elif self.selected_control_id in (
                    FILTER_CATEGORY_LIST,
                    FILTER_CONTENT_LIST_ACTIVE,
                    FILTER_CONTENT_LIST_INACTIVE,
                ):

                self.close_filterlist()
                if self.enter:
                    self.enter = None
                else:
                    self.dummy = True

            elif self.selected_control_id == MAIN_MENU:
                self.dummy = True

        # update menu when focused
        #elif control_id == MAIN_MENU:
            # TODO sub main
            # self.build_main_menu()
            # pass

        # WORKING VERSION
        # close popups
        # if control_id == SOFTWARE_BUTTON or control_id == SYSTEM_WRAPLIST:
        #
        #     if self.selected_control_id in (
        #             GAME_LIST, GAME_LIST_OPTIONS, GAME_LIST_SORT
        #         ):
        #         self.setFocus(self.getControl(SOFTWARE_BUTTON))
        #         if self.enter:
        #             self.enter = None
        #         else:
        #             self.dummy = True
        #
        #     elif self.selected_control_id in (
        #             FILTER_CATEGORY_LIST,
        #             FILTER_CONTENT_LIST_ACTIVE,
        #             FILTER_CONTENT_LIST_INACTIVE,
        #         ):
        #
        #         self.close_filterlist()
        #         if self.enter:
        #             self.enter = None
        #         else:
        #             self.dummy = True

        # check if we have to move to next item
        # as the actual item has no or only 1 element
        # if (control_id == SYSTEM_WRAPLIST
        #      and self.getControl(SYSTEM_WRAPLIST).size() == 1
        #    ):
        #     if self.selected_control_id == SET_LIST:
        #         xbmc.log("- from SET to SOFTWARE")
        #         self.setFocus(self.getControl(SOFTWARE_BUTTON))
        #     else:
        #         xbmc.log("- from SOFTWARE to SET")
        #         self.setFocus(self.getControl(SET_LIST))
        # if control_id == SET_LIST and self.getControl(SET_LIST).size() == 1:
        #     if self.selected_control_id == SYSTEM_WRAPLIST:
        #         xbmc.log("- from MACHINE to TEXT")
        #         self.setFocus(self.getControl(TEXTLIST))
        #     else:
        #         xbmc.log("- from TEXT to MACHINE")
        #         self.setFocus(self.getControl(SYSTEM_WRAPLIST))
        if (control_id == TEXTLIST and self.getControl(TEXTLIST).size() < 2):
            if self.selected_control_id == SET_LIST:
                xbmc.log("UMSA onFocus: from SET to SOFTWARE")
                self.setFocus(self.getControl(SOFTWARE_BUTTON))
            else:
                # TODO will not happen as we go from SOFTWARE TO BOTTOM CPANEL?
                xbmc.log("UMSA onFocus: from SOFTWARE to SET")
                self.setFocus(self.getControl(SET_LIST))

        # update control_id
        self.enter = None
        self.selected_control_id = control_id

    def onClick(self, control_id):
        """Kodi onClick"""
        xbmc.log("UMSA onClick")

        # screensaver check
        if self.Monitor.running != 'no':
            xbmc.log("UMSA onClick: Monitor runs, return")
            if self.Monitor.running == 'pic':
                self.Monitor.running = 'no'
                xbmc.log("UMSA onClick: Monitor in picture mode, turned off")
            return

        # start emulator
        if control_id in (SOFTWARE_BUTTON, SET_LIST, SYSTEM_WRAPLIST):
            self.run_emulator()
            return

        item = self.getControl(control_id).getSelectedItem().getLabel()
        if control_id == TEXTLIST:
            # show series
            if item == 'Series':
                series = self.ggdb.get_series(self.last[self.lastptr])
                if series:
                    self.popup_gamelist(series, 'Series')
            # text viewer
            else:
                self.dialog.textviewer(item, self.all_dat[self.actset['id']][item])

        elif control_id == GAME_LIST_OPTIONS:
            if item == "new search":
                keyboard = xbmc.Keyboard('', "Search for", 0)
                keyboard.doModal()
                if keyboard.isConfirmed():
                    self.searchold = keyboard.getText()
                else:
                    return
                gamelist, pos, result_count = self.ggdb.get_searchresults(self.searchold)
                gl_label = '%d results for %s' % (result_count, self.searchold)
                gl_options = ('new search',)

                # check how many results
                if len(gamelist) == 0:
                    xbmc.executebuiltin('XBMC.Notification(nothing,,5000)')
                    return
                if len(gamelist) == 1:
                    self.searchold = None
                    self.lastptr += 1
                    self.last.insert(self.lastptr, gamelist[0]['id'])
                    self.select_software(self.last[self.lastptr])
                    return

                # TODO no popup, but refill
                self.popup_gamelist(gamelist, gl_label, pos=pos, options=gl_options)

            # options from play status
            elif item in ('time_played', 'last_played', 'play_count'):
                gamelist, pos = self.ggdb.get_last_played(item)
                self.getControl(GAME_LIST).reset()
                gui_list = []
                for i in gamelist:
                    list_item = xbmcgui.ListItem(i['name'], str(i['id']))
                    list_item.setInfo(
                        'video', {'Writer': i['year'], 'Studio': i['maker']}
                        )
                    gui_list.append(list_item)
                self.getControl(GAME_LIST).addItems(gui_list)
                self.setFocus(self.getControl(GAME_LIST))

            elif item in ('name', 'year', 'publisher'):
                self.ggdb.order = item
                content = int(self.getControl(GAME_LIST_LABEL_ID).getLabel())
                self.update_gamelist(content)

        elif control_id == GAME_LIST_SORT:
            self.gamelist_switch_filter()

        # FILTER: select all, none or invert lists
        elif control_id == FILTER_OPTIONS:
            filter_category_name = self.getControl(FILTER_LABEL).getLabel()
            if item == 'none':
                self.filter_lists[filter_category_name] = []
            elif item == 'all':
                self.filter_lists[filter_category_name] = []
                for i in self.ggdb.get_all_dbentries(filter_category_name):
                    self.filter_lists[filter_category_name].append(str(i[0]))
            elif item == 'invert':
                templist = []
                for i in self.ggdb.get_all_dbentries(filter_category_name):
                    if str(i[0]) not in self.filter_lists[filter_category_name]:
                        templist.append(str(i[0]))
                self.filter_lists[filter_category_name] = templist
            self.set_filter_content(filter_category_name)

            # set focus to active, when empty deactive
            if len(self.filter_lists[filter_category_name]) == 0:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_INACTIVE))
            else:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_ACTIVE))

    def onAction(self, action):
        """Kodi onAction"""

        xbmc.log("UMSA onAction: id = {}".format(action.getId()))

        if action.getId() == 0:
            return

        # check if monitor runs
        if self.Monitor.running == 'pic':
            self.Monitor.running = 'no'
            return
        if self.Monitor.running != "no":
            xbmc.log("UMSA onAction: Monitor running ? doing nothing")

        # needed for left/right exit from popup
        if self.dummy:
            xbmc.log("UMSA onAction: dummy action after exit from popup")
            self.dummy = None
            if (action.getId() in ACTION_MOVEMENT_LEFT
                    or action.getId() in ACTION_MOVEMENT_RIGHT):
                return

        # TODO: switch to fullscreen video
        # Keyboard: scancode: 0x17, sym: 0x0009, unicode: 0x0009, modifier: 0x0
        # HandleKey: tab (0xf009) pressed, action is FullScreen
        # UMSA onAction: id = 18
        # UMSA onAction: SOFTWARE_BUTTON
        if action.getId() == 18:
            self.Player.play(windowed=False)

        # exit only in main screen, otherwise close popup or stop video
        if action.getId() in ACTION_CANCEL_DIALOG:

            actual_control = self.selected_control_id
            if actual_control in (
                    GAME_LIST, GAME_LIST_OPTIONS, GAME_LIST_SORT, LISTMODE_MENU, MAIN_MENU
            ):
                self.setFocus(self.getControl(self.main_focus))
                self.enter = True
                return
            if actual_control in (
                    FILTER_CATEGORY_LIST, FILTER_CONTENT_LIST_ACTIVE,
                    FILTER_CONTENT_LIST_INACTIVE, FILTER_OPTIONS,
            ):
                self.close_filterlist()
                self.enter = True
                return
            # stop video and return
            if self.Player.isPlayingVideo() and not self.already_playing:
                self.Player.stop()
                return
            # exit add-on
            self.exit()

        # ACTION SOFTWARE_BUTTON
        if self.selected_control_id == SOFTWARE_BUTTON:
            self.main_focus = SOFTWARE_BUTTON
            if action.getId() in ACTION_MOVEMENT_RIGHT:
                self.software_move('right')
            elif action.getId() in ACTION_MOVEMENT_LEFT:
                self.software_move('left')
            elif action.getId() in ACTION_MOVEMENT_DOWN+ACTION_MOVEMENT_UP:
                self.show_artwork()
            elif action.getId() in ACTION_CONTEXT:
                self.build_main_menu(select=M_ALL)
                self.setFocus(self.getControl(MAIN_MENU))

        # MAIN MENU
        elif self.selected_control_id == MAIN_MENU:
            # TODO put action into function

            if action.getId() in ACTION_MOVEMENT_LEFT:
                self.setFocus(self.getControl(self.main_focus))
            elif action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_ENTER:

                # get menu item
                menu_item = int(self.getControl(MAIN_MENU).getSelectedItem().getLabel2())
                xbmc.log("UMSA onAction: menu = {}".format(menu_item))

                if menu_item == M_FILTER:
                    self.setFocus(self.getControl(FILTER_CATEGORY_LIST))

                elif menu_item == M_EXIT:
                    self.exit()

                elif menu_item == M_UPD:
                    self.setFocus(self.getControl(self.main_focus))
                    # sanity
                    if self.scan_thread and not self.scan_thread.isAlive():
                        self.scan_thread = None
                    if self.scan_thread:
                        xbmc.executebuiltin(
                            'XBMC.Notification(scan status,scan already running...,3000)')
                        return

                    ret = self.dialog.select(
                        'What should we do?',
                        ('Update database', 'Scan dat files', 'Scan artwork')
                    )
                    if ret == 0:
                        self.update('db')
                    elif ret == 1:
                        self.scan_thread = Thread(target=self.update, args=('dat',))
                        self.scan_thread.start()
                    elif ret == 2:
                        self.scan_thread = Thread(target=self.update, args=('art',))
                        self.scan_thread.start()

                elif menu_item == M_SSAVER:
                    self.setFocus(self.getControl(self.main_focus))
                    ret = self.dialog.select(
                        'Which show would please you?', (
                            'Play random videos',
                            'Make Artwork Crossover',
                            'MARP Replayer',
                        )
                    )
                    if ret == 0:
                        self.play_random_videos()
                    elif ret == 1:
                        art_types = self.ggdb.get_art_types()
                        ret2 = self.dialog.multiselect(
                            "What do you want to see?", art_types
                        )
                        if ret2:
                            selected_art_types = []
                            for i in ret2:
                                selected_art_types.append(art_types[i])
                            self.Monitor.snapshot_crossover(selected_art_types)
                    elif ret == 2:
                        self.marp_replayer()
                elif menu_item == M_ASETTINGS:
                    self.setFocus(self.getControl(self.main_focus))
                    __addon__.openSettings()
                    self.read_settings()
                else:
                    self.setFocus(self.getControl(GAME_LIST_LABEL))
                    self.update_gamelist(menu_item)

            elif action.getId() in ACTION_CONTEXT:

                menu_item = int(self.getControl(MAIN_MENU).getSelectedItem().getLabel2())
                # switch filter
                if menu_item == M_FILTER:
                    if self.ggdb.use_filter:
                        self.ggdb.use_filter = False
                        self.getControl(MAIN_MENU).getSelectedItem().setLabel("Filter (off)")
                    else:
                        self.ggdb.use_filter = True
                        self.getControl(MAIN_MENU).getSelectedItem().setLabel(
                            "Filter ({})".format(self.act_filter))
                # update umsa db
                elif menu_item == M_UPD:
                    self.setFocus(self.getControl(self.main_focus))
                    self.update('db')
                # shortcut to play status
                elif menu_item == M_EXIT:
                    self.update_gamelist(M_PLAYSTAT)
                # shortcut to last screensaver list
                elif menu_item == M_ASETTINGS:
                    self.update_gamelist(M_LSSAVER)
                # show all emulators
                elif menu_item == M_MACHINE:
                    self.update_gamelist(M_ALLEMUS)
                # call old search
                elif menu_item == M_SEARCH_NEW:
                    if self.searchold:
                        self.update_gamelist(M_SEARCH)
                # directly play a random youtube video
                elif menu_item == M_MEDIA:
                    yt_list = tools.youtube_search(
                        tools.split_gamename(self.actset['gamename'])[0],
                        self.actset['machine_name'])
                    playurl = "plugin://plugin.video.youtube/play/?video_id={}".format(
                        choice(yt_list)[0])
                    self.Player.play(playurl, windowed=True)
                    # PY2: youtube plugin does not work within the script
                    if PY_VER < (3, 0):
                        self.exit()
                    # close menu
                    self.setFocus(self.getControl(self.main_focus))
                # start random screensaver
                elif menu_item == M_SSAVER:
                    rand_saver = randint(1, 3)
                    # close menu
                    self.setFocus(self.getControl(self.main_focus))
                    if rand_saver == 1:
                        self.play_random_videos()
                    elif rand_saver == 2:
                        self.marp_replayer(random=True)
                    else:
                        self.Monitor.snapshot_crossover(['snap'])

        # ACTION listmode submenu
        elif self.selected_control_id == LISTMODE_MENU:
            if action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_ENTER:
                self.update_gamelist(
                    int(self.getControl(LISTMODE_MENU).getSelectedItem().getLabel2())
                )
            elif action.getId() in ACTION_MOVEMENT_LEFT:
                self.setFocus(self.getControl(self.main_focus))
            # show all maker, swl, year
            elif action.getId() in ACTION_CONTEXT:
                self.show_fulllist(
                    int(self.getControl(LISTMODE_MENU).getSelectedItem().getLabel2()),
                    self.getControl(LISTMODE_MENU).getSelectedItem().getLabel())

        # ACTION SYSTEM_WRAPLIST
        elif self.selected_control_id == SYSTEM_WRAPLIST:
            xbmc.log("UMSA onAction: MACHINE_LIST")
            self.main_focus = SYSTEM_WRAPLIST
            if action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_MOVEMENT_LEFT:
                self.machine_move()
            elif action.getId() in ACTION_MOVEMENT_DOWN+ACTION_MOVEMENT_UP:
                self.show_artwork('machine')
            elif action.getId() in ACTION_CONTEXT:
                if self.actset['swl_name'] == 'mame':
                    self.build_main_menu(M_SOURCE)
                else:
                    self.build_main_menu(M_SWL)
                self.setFocus(self.getControl(MAIN_MENU))

        # ACTION TEXTLIST
        elif self.selected_control_id == TEXTLIST:
            self.main_focus = TEXTLIST
            if action.getId() in ACTION_CONTEXT:
                self.setFocus(self.getControl(MAIN_MENU))

        # ACTION GAME_LIST
        elif self.selected_control_id == GAME_LIST:
            if action.getId() in ACTION_ENTER:
                self.gamelist_click()
            elif action.getId() in ACTION_MOVEMENT_LEFT:
                self.setFocus(self.getControl(LISTMODE_MENU))
            elif action.getId() in ACTION_CONTEXT:
                self.gamelist_context()
            elif action.getId() in ACTION_MOVEMENT_DOWN+ACTION_MOVEMENT_UP:
                self.gamelist_move()

        # ACTION FILTER_CATEGORY_LIST
        elif self.selected_control_id == FILTER_CATEGORY_LIST:
            xbmc.log("UMSA onAction: FILTER_CATEGORY_LIST")

            if action.getId() in ACTION_ENTER:
                self.filter_category()
            elif action.getId() in ACTION_MOVEMENT_LEFT:
                self.setFocus(self.getControl(self.main_focus))

        # ACTION FILTER_CONTENT_LIST_ACTIVE
        elif self.selected_control_id == FILTER_CONTENT_LIST_ACTIVE:
            xbmc.log("UMSA onAction: FILTER_CONTENT_LIST_ACTIVE")

            if action.getId() in ACTION_ENTER:
                self.filter_content('active')

        # ACTION FILTER_CONTENT_LIST_INACTIVE
        elif self.selected_control_id == FILTER_CONTENT_LIST_INACTIVE:
            xbmc.log("UMSA onAction: FILTER_CONTENT_LIST_INACTIVE")

            if action.getId() in ACTION_ENTER:
                self.filter_content('inactive')

        # ACTION SET_LIST
        elif self.selected_control_id == SET_LIST:
            self.main_focus = SET_LIST
            # update actual set
            if action.getId() in ACTION_MOVEMENT_LEFT+ACTION_MOVEMENT_RIGHT:
                pos_m = self.getControl(SYSTEM_WRAPLIST).getSelectedPosition()
                pos_s = self.getControl(SET_LIST).getSelectedPosition()
                self.actset = self.info[pos_m][pos_s]
                # update SYSTEM_WRAPLIST image
                # TODO should the icon be a part of set list
                # and machine wraplist shows pic from set?
                # - both needed, may work when only selectedlayout
                #   in skin uses image from machine wraplist and
                #   not focused uses normal image
                self.getControl(SYSTEM_WRAPLIST).getSelectedItem().setArt(
                    {'icon': self.get_machine_pic(self.actset)}
                    )
                # update pics
                self.show_artwork('set')
            # update artwork
            elif action.getId() in ACTION_MOVEMENT_DOWN+ACTION_MOVEMENT_UP:
                self.show_artwork('set')
            # popup mainmenu
            elif action.getId() in ACTION_CONTEXT:
                self.build_main_menu(select=M_MACHINE)
                self.setFocus(self.getControl(MAIN_MENU))

    def marp_replayer(self, dl_file=None, set_name=None, random=None):
        """Start MAME with a MARP Replay input file

        Random replay with no argument

        TODO
        - use complete marp info, not only set_name and dl_file
        - argument: get complete marp info
        - get version from mame executable
        """

        if not dl_file:
            rand_version = randint(178, 218)
            all_marps = tools.marp_search(version=rand_version)
            if random:
                marp_rand = choice(all_marps)
                dl_file = marp_rand['download']
                set_name = marp_rand['set_name']
            else:
                marp_list = []
                for i in all_marps:
                    marp_list.append("{}[CR] {}: {} ({}, {})".format(
                        i['gamename'], i['player'], i['rank'], i['percentage'], i['points']))
                ret = self.dialog.select(
                    "Select MARP {} replay:".format(rand_version), marp_list, useDetails=True)
                if ret:
                    dl_file = all_marps[ret]['download']
                    set_name = all_marps[ret]['set_name']
                else:
                    return
        inp_file = tools.marp_download(
            dl_file, os.path.join(self.mame_dir, self.mame_ini['input_directory']))
        opt = ["-playback", inp_file, "-exit_after_playback"]
        self.run_emulator(more_options=opt, machine="mame", setname=set_name)

    def play_random_videos(self):
        """Starts playing random videos

        TODO no video, dont start, see fsaver
        """

        self.Monitor.running = 'video'
        self.VPlayer.doModal()
        self.Monitor.running = 'no'

    def build_sublist_menu(self, select):
        """Build the sublist menu for the listmode."""

        if select in SUBMENU_ORDER:
            position = SUBMENU_ORDER[select]
        else:
            position = 0
            xbmc.log("UMSA build_sublist_menu: select unknown: {}".format(select))

        list_items = []
        list_items.append(xbmcgui.ListItem('Show all', str(M_ALL)))

        # series
        series = self.ggdb.check_series(self.last[self.lastptr])
        if series:
            list_items.append(xbmcgui.ListItem("Series ({})".format(series), str(M_SERIES)))
        else:
            position = position-1

        list_items.append(xbmcgui.ListItem('Maker', str(M_MAKER)))
        list_items.append(xbmcgui.ListItem('Category', str(M_CAT)))

        rec = False
        for i in self.all_dat:
            if 'Rec' in self.all_dat[i]:
                rec = True
                break
        if rec:
            list_items.append(xbmcgui.ListItem("Recommended", str(M_REC)))
        else:
            position = position-1

        list_items.append(xbmcgui.ListItem('Year', str(M_YEAR)))
        list_items.append(xbmcgui.ListItem('Players', str(M_PLAYERS)))

        # source
        if self.actset['swl_name'] == 'mame':
            count_source = self.ggdb.count_source(self.actset['source'])
            if count_source > 1:
                list_items.append(xbmcgui.ListItem(
                    'Source ({}: {})'.format(
                        self.actset['source'][:-4], count_source
                    ), str(M_SOURCE)
                ))
            else:
                xbmc.log("UMSA build_sublist_menu: only 1 source: {}".format(self.actset['source']))
        # swl
        else:
            list_items.append(xbmcgui.ListItem(
                'Softwarelist {}'.format(
                    self.actset['swl_name']
                ), str(M_SWL)
            ))

        list_items.append(xbmcgui.ListItem('Screensaver session', str(M_LSSAVER)))
        list_items.append(xbmcgui.ListItem('Play Status', str(M_PLAYSTAT)))

        self.getControl(LISTMODE_MENU).reset()
        self.getControl(LISTMODE_MENU).addItems(list_items)
        self.getControl(LISTMODE_MENU).selectItem(position)

    def build_main_menu(self, select=None):
        """Shows the context menu."""

        position = 0
        list_items = []
        # check series
        series = self.ggdb.check_series(self.last[self.lastptr])
        # set series indicator
        if series:
            self.getControl(SERIES_LABEL).setVisible(True)
        else:
            self.getControl(SERIES_LABEL).setVisible(False)
        # change list with select parameter
        if select == M_SOURCE:
            list_items.append(xbmcgui.ListItem("Show source", str(M_SOURCE)))
        elif select == M_SWL:
            list_items.append(xbmcgui.ListItem("Show swl", str(M_SWL)))
        elif series:
            list_items.append(xbmcgui.ListItem("Series ({})".format(series), str(M_SERIES)))
        else:
            list_items.append(xbmcgui.ListItem("Show all", str(M_ALL)))
        if select == M_MACHINE:
            position = 2
        # media
        if self.vidman == (0, 0):
            list_items.append(xbmcgui.ListItem("Media", str(M_MEDIA)))
        else:
            list_items.append(xbmcgui.ListItem("Media ({},{})".format(
                self.vidman[0], self.vidman[1]), str(M_MEDIA)))
        # mame machines and different emulators
        count_machines = 0
        if self.actset['swl_name'] != 'mame':
            count_machines = self.ggdb.count_machines_for_swl(self.actset['swl_name'])
        if count_machines > 1:
            list_items.append(
                xbmcgui.ListItem("Emulator (MAME: {})".format(count_machines), str(M_MACHINE)))
        else:
            list_items.append(xbmcgui.ListItem("Emulator (MAME)", str(M_MACHINE)))
        # search
        if self.searchold:
            list_items.append(xbmcgui.ListItem("Search ({})".format(
                self.searchold), str(M_SEARCH_NEW)))
        else:
            list_items.append(xbmcgui.ListItem("Search", str(M_SEARCH_NEW)))
        # filter
        if self.ggdb.use_filter:
            list_items.append(xbmcgui.ListItem(
                "Filter ({})".format(self.act_filter), str(M_FILTER)))
        else:
            list_items.append(xbmcgui.ListItem("Filter (off)", str(M_FILTER)))
        list_items.append(xbmcgui.ListItem("Screensaver", str(M_SSAVER)))
        list_items.append(xbmcgui.ListItem("Update", str(M_UPD)))
        list_items.append(xbmcgui.ListItem("Settings", str(M_ASETTINGS)))
        list_items.append(xbmcgui.ListItem("Exit", str(M_EXIT)))
        self.getControl(MAIN_MENU).reset()
        self.getControl(MAIN_MENU).addItems(list_items)
        self.getControl(MAIN_MENU).selectItem(position)

    def gamelist_move(self):
        """Move in gamelist"""

        # check label if we have games in list
        g_label = self.getControl(GAME_LIST_LABEL).getLabel()
        list_id = self.getControl(GAME_LIST_LABEL_ID).getLabel()
        # TODO use game_list_label_id
        if (g_label in 'Machines for'
                or g_label in 'Choose Media'
                or g_label in 'Emulators'
                or g_label in 'Select'
           ):
            xbmc.log("UMSA gamelist_move: label {} = return".format(g_label))
            return
        # get infos
        gamelist_item = self.getControl(GAME_LIST).getSelectedItem()
        # check if we have an item
        if not gamelist_item:
            xbmc.log("UMSA gamelist_move: no selected item = return")
            return
        #gameinfo = self.getControl(GAME_LIST).getSelectedItem().getLabel()
        gamelist_id = self.getControl(GAME_LIST).getSelectedItem().getLabel2()
        # check if gamelist_id is valid
        if gamelist_id == "0":
            xbmc.log("UMSA gamelist_move: gamelist id invalid = return")
            return
        # check if gamelist kodi obj already has property text
        # return when text already present
        if gamelist_item.getProperty('text'):
            xbmc.log("UMSA gamelist_move: text already there = return")
            return
        # get snap, machines
        xbmc.log("UMSA gamelist_move: db fetch snap, machines for {}".format(gamelist_id))
        snap = self.ggdb.get_artwork_by_software_id(gamelist_id, 'snap')
        # set info to gamelist item
        if snap[0]:
            if snap[1]:
                path = self.progetto
            else:
                path = self.other_artwork
            gamelist_item.setArt(
                {'icon' : os.path.join(path, 'snap', snap[0].replace('mame', 'snap'))}
                )
        gamelist_item.setProperty('text', snap[2])
        xbmc.log("UMSA gamelist_move: properties set = {}".format(
            gamelist_item.getProperty('text')))

    def gamelist_switch_filter(self):
        """Switch filter in gamelist"""

        if self.ggdb.use_filter:
            self.ggdb.use_filter = False
        else:
            self.ggdb.use_filter = True

        content = int(self.getControl(GAME_LIST_LABEL_ID).getLabel())
        self.setFocus(self.getControl(GAME_LIST_OPTIONS))
        self.update_gamelist(content)

    def gamelist_click(self):
        """Reacts on click in gamelist"""

        what = ""
        list_id = self.getControl(GAME_LIST).getSelectedItem().getLabel2()
        if "::" in list_id:
            what, list_id = list_id.split("::")
        if list_id == "0":
            return
        select_label = self.getControl(GAME_LIST).getSelectedItem().getLabel()
        label = self.getControl(GAME_LIST_LABEL).getLabel()

        xbmc.log("UMSA gamelist_click: what {}, list_id {}, label {}, select_label {}". format(
            what, list_id, label, select_label))

        # prev or next
        if list_id in ('prev', 'next'):
            # get prev/next results
            if list_id == 'prev':
                sid = int(self.getControl(GAME_LIST).getListItem(1).getLabel2())
            else:
                size = self.getControl(GAME_LIST).size()
                sid = int(self.getControl(GAME_LIST).getListItem(size-2).getLabel2())
            gamelist, pos, result_count = self.ggdb.execute_statement(
                software_id=sid, prevnext=list_id)
            # create list
            list_items = []
            for i in gamelist:
                list_item = xbmcgui.ListItem(i['name'], str(i['id']))
                list_item.setInfo(
                    'video', {'Writer' : i['year'], 'Studio' : i['maker'],}
                    )
                list_items.append(list_item)
            # show
            self.getControl(GAME_LIST).reset()
            self.getControl(GAME_LIST).addItems(list_items)
            self.getControl(GAME_LIST).selectItem(pos)
            self.setFocus(self.getControl(GAME_LIST))
            return
        if label[:7] == "Select ":
            if list_id == 'source':
                my_list, pos, count = self.ggdb.get_software_for_source(
                    self.actset['id'], select_label)
            elif 'Softwarelist' in label:
                my_list, pos, count = self.ggdb.get_by_swl(list_id, self.actset['id'])
            elif 'Category' in label:
                my_list, pos, count = self.ggdb.get_by_cat(list_id, self.actset['id'])
            elif 'Maker' in label:
                my_list, pos, count = self.ggdb.get_by_maker(list_id, self.actset['id'])
            elif 'Year' in label:
                my_list, pos, count = self.ggdb.get_by_year(list_id, self.actset['id'])
            elif 'Players' in label:
                my_list, pos, count = self.ggdb.get_by_players(list_id, self.actset['id'])
            self.popup_gamelist(my_list, "{} ({})".format(select_label, count), pos)
            return

        # close window
        self.enter = True
        self.setFocus(self.getControl(self.main_focus))

        # choose emulator for source/swl
        if select_label == "Choose a different emulator":
            self.get_diff_emulator()
        # start kodi retroplayer
        elif select_label == "Start with Kodi Retroplayer":
            self.run_emulator({'exe': 'kodi', 'zip': None})
        # emulator run
        elif what == "emu_conn":
            self.run_emulator(self.ggdb.get_emulator(emu_conn_id=list_id))
        # change/delete emulator
        elif what == "emu":
            if (self.dialog.yesno(
                    "Emulator {}".format(select_label), "What shall we do?",
                    nolabel="Reconfigure", yeslabel="Delete")
               ):
                if (self.dialog.yesno(
                        'Delete emulator', 'Really delete {}?'.format(select_label))
                   ):
                    self.ggdb.delete_emulator(list_id)
                    self.update_gamelist(M_ALLEMUS)
            else:
                self.configure_emulator(
                    emu_info=self.ggdb.get_emulator(emu_id=list_id), reconfigure=True)
        # set machine for swl
        elif 'Machines for' in label:
            self.setFocus(self.getControl(self.main_focus))
            self.enter = True
            # get info from db
            machine_name, machine_label = self.ggdb.get_machine_name(list_id)
            # set new image and machine label
            self.getControl(SYSTEM_WRAPLIST).getSelectedItem().setArt(
                {'icon' : os.path.join(self.cab_path, machine_name+'.png')})
            self.getControl(SET_LIST).getSelectedItem().setProperty(
                'Machine', machine_label)
            # save machine for set in self.info
            self.actset['machine_name'] = machine_name
            self.actset['machine_label'] = machine_label
        # play media
        elif label == "Choose Media":
            # TODO: add play soundtrack
            # video
            if list_id[-3:] == 'mp4':
                list_item = xbmcgui.ListItem(select_label)
                self.Player.play(list_id, listitem=list_item, windowed=True)
            # pdf viewer
            elif list_id[-3:] == 'pdf':
                Popen([self.pdfviewer, list_id])
            # marp
            elif list_id[-3:] == 'zip':
                self.marp_replayer(dl_file=list_id, set_name=what)
            # youtube
            elif what == "yt":
                self.Player.play(
                    "plugin://plugin.video.youtube/play/?video_id={}".format(list_id),
                    windowed=True)
                # PY2: youtube plugin does not work within the script
                if PY_VER < (3, 0):
                    self.exit()
            # search marp, youtube
            elif select_label[:9] == "- Youtube":
                search_yt = tools.youtube_search(
                    tools.split_gamename(self.actset['gamename'])[0],
                    self.actset['machine_name'])
                self.ggdb.save_further_media(self.actset['id'], youtube=dumps(search_yt))
                self.update_gamelist(M_MEDIA)
            elif select_label[:8] == "- Replay":
                # TODO check complete game info for a mame swl
                if self.actset['swl_name'] == "mame":
                    self.ggdb.save_further_media(
                        self.actset['id'], marp=dumps(
                            tools.marp_search(short_name=self.actset['name'])))
                self.update_gamelist(M_MEDIA)
        # select new software
        else:
            xbmc.log("UMSA gamelist_click: software id ={}".format(list_id))

            software_id = int(list_id)
            # if self.lastptr == 9:
            #     del self.last[0]
            #     self.last.append(software_id)
            #     self.select_software(self.last[-1])
            # else:
            #     self.last.insert(
            #         self.lastptr+1,
            #         software_id
            #     )
            #     del self.last[0]
            #     self.select_software(self.last[self.lastptr])
            self.lastptr += 1
            self.last.insert(self.lastptr, software_id)
            self.select_software(self.last[self.lastptr])

    def gamelist_context(self):
        """Reacts on context in gamelist"""

        what = ""
        list_id = self.getControl(GAME_LIST).getSelectedItem().getLabel2()
        if "::" in list_id:
            what, list_id = list_id.split("::")
        label = self.getControl(GAME_LIST).getSelectedItem().getLabel()

        xbmc.log("UMSA gamelist_context: what {}, list_id {}, label {}". format(
            what, list_id, label))

        # reconfigure/remove connection
        if what == "emu_conn":
            if (self.dialog.yesno(
                    "Emulator {}".format(label), "What shall we do?",
                    nolabel="Reconfigure", yeslabel="Remove")):
                last_emu_id = self.ggdb.delete_emulator_connection(list_id)
                if last_emu_id:
                    if (self.dialog.yesno(
                            'Delete emulator',
                            'No other connection for {}, delete?'.format(label))):
                        self.ggdb.delete_emulator(last_emu_id)
                self.update_gamelist(M_MACHINE)
            else:
                xbmc.log("!!!RECONFIGURE")
                xbmc.log(list_id)
                xbmc.log('{}'.format(dict(self.ggdb.get_emulator(emu_conn_id=list_id))))
                self.configure_emulator(
                    emu_info=self.ggdb.get_emulator(emu_conn_id=list_id), reconfigure=True)
        # switch filter
        else:
            self.gamelist_switch_filter()

    def show_fulllist(self, what, label):
        """Show full list of maker, cat, year..."""

        if what == M_MAKER:
            my_list = self.ggdb.get_maker()
        elif what == M_SWL:
            my_list = self.ggdb.get_swl()
        elif what == M_SOURCE:
            my_list = []
            for i in self.ggdb.get_source():
                my_list.append({'id': "source", 'name': i['source']})
        elif what == M_YEAR:
            my_list = self.ggdb.get_year()
        elif what == M_PLAYERS:
            my_list = self.ggdb.get_players()
        elif what == M_CAT:
            my_list = self.ggdb.get_categories()
        self.popup_gamelist(my_list, "Select {}".format(label))

    def filter_category(self):
        """Open filter category, load and save filters"""

        # get filter category and set filter content list
        cat = self.getControl(FILTER_CATEGORY_LIST).getSelectedItem().getLabel()

        # save/load filter
        if cat in ("Load Filter", "Save Filter"):
            files = []
            for i in os.listdir(SETTINGS_FOLDER):
                if i[:7] == 'filter_':
                    files.append(i[7:-4])

            if cat == "Load Filter":
                ret = self.dialog.select('Load Filter', files)
                if ret == -1:
                    return
                self.filter_lists = utilmod.load_filter(
                    SETTINGS_FOLDER, 'filter_' + files[ret] + '.txt'
                )
                #c = self.ggdb.define_filter(self.filter_lists)
                self.getControl(LABEL_STATUS).setLabel(
                    "%s filtered items" % (self.ggdb.define_filter(self.filter_lists),)
                )
                self.act_filter = files[ret]
                self.getControl(FILTER_CONTENT_LIST_ACTIVE).reset()
                self.getControl(FILTER_CONTENT_LIST_INACTIVE).reset()
                self.getControl(FILTER_LABEL).setLabel("Select category")
                self.getControl(FILTER_LABEL2).setLabel('Filter: {}'.format(self.act_filter))
                self.setFocus(self.getControl(FILTER_CATEGORY_LIST))
                # TODO show last open category

            else:
                files.append(' or create a new filter')
                ret = self.dialog.select('Save Filter', files)
                if ret == -1:
                    return
                if files[ret] == ' or create a new filter':
                    keyboard = xbmc.Keyboard('', "Name for Filter", 0)
                    keyboard.doModal()
                    if keyboard.isConfirmed():
                        filter_filename = keyboard.getText()
                    else:
                        return
                else:
                    filter_filename = files[ret]

                # save filters
                utilmod.save_filter(
                    SETTINGS_FOLDER,
                    'filter_' + filter_filename + '.txt',
                    self.filter_lists
                )
                self.act_filter = filter_filename
                self.getControl(FILTER_LABEL2).setLabel('Filter: {}'.format(self.act_filter))
                #self.getControl(FILTER_LABEL).setLabel(
                #    'saved ' + filter_filename
                #)

        # or set choosen category
        else:
            self.set_filter_content(cat)

    def filter_content(self, which_content):
        """filter content

        Gets called with action on filter list
        """

        if which_content == 'active':
            contentlist = FILTER_CONTENT_LIST_ACTIVE
        else:
            contentlist = FILTER_CONTENT_LIST_INACTIVE

        # get actual category
        filter_category_name = self.getControl(FILTER_LABEL).getLabel()
        # get db id for actual content entry
        filter_content_id = self.getControl(contentlist).getSelectedItem().getLabel2()

        # update internal list
        if which_content == 'active':
            xbmc.log("UMSA filter_content: remove: {0}".format(filter_content_id))
            self.filter_lists[filter_category_name].remove(filter_content_id)
        else:
            xbmc.log("UMSA filter_content: append: {0}".format(filter_content_id))
            self.filter_lists[filter_category_name].append(filter_content_id)

        # update gui
        self.set_filter_content(filter_category_name, update=which_content)

    def read_settings(self):
        """Read settings for UMSA from Kodi

        - read settings
        - checks if chdman is in mame directory if empty
        - set playvideo
        - set cab_path
        """

        # TODO: put all into settings dict
        # read in settings
        self.mame_exe = __addon__.getSetting('mame')
        self.mameini = __addon__.getSetting('mameini')
        self.mame_dir = __addon__.getSetting('mamedir')
        self.pref_country = __addon__.getSetting('pref_country')
        self.temp_dir = __addon__.getSetting('temp_path')
        self.progetto = __addon__.getSetting('progetto')
        self.aratio = __addon__.getSetting('aspectratio')
        self.datdir = __addon__.getSetting('datdir')
        self.pdfviewer = __addon__.getSetting('pdfviewer')
        self.chdman_exe = __addon__.getSetting('chdman')
        self.other_artwork = __addon__.getSetting('otherart')
        self.ssaver_type = __addon__.getSetting('ssaver_type')
        es_dict = {'Normal': 0, 'Watch': 1, 'Fallback': 2}
        self.emulation_start = es_dict[__addon__.getSetting('emulation_start')]

        # check chdman
        if self.chdman_exe == "":
            # split self.mame_exe
            mame_path = os.path.split(self.mame_exe)[0]
            # check if chdman is in same dir as mame
            if 'linux' in PLATFORM:
                chdman_file = os.path.join(mame_path, 'chdman')
            else:
                chdman_file = os.path.join(mame_path, 'chdman.exe')
            if os.path.isfile(chdman_file):
                self.chdman_exe = chdman_file

        # auto play videos
        if __addon__.getSetting('play_video') == 'true':
            self.playvideo = True
        # needed as settings can be changed and reread
        else:
            self.playvideo = None

        self.cab_path = os.path.join(self.progetto, 'cabinets/cabinets')

    def close_filterlist(self, no_update=None):
        """Close filter list window"""

        xbmc.log("UMSA close_filterlist")
        # update filter
        if not no_update:
            #c = self.ggdb.define_filter(self.filter_lists)
            self.getControl(LABEL_STATUS).setLabel(
                "%s filtered items" % (self.ggdb.define_filter(self.filter_lists),)
            )
        self.setFocus(self.getControl(self.main_focus))

    def get_diff_emulator(self):
        """Get different emulator"""

        emus = self.ggdb.get_emulators()
        if emus:
            emu_names = ['Configure new emulator']
            for i in emus:
                emu_names.append(i['name'])
            ret = self.dialog.select('Emulators', emu_names)
            if ret == -1:
                return
            if ret == 0:
                self.configure_emulator()
            else:
                if self.actset['swl_name'] == "mame":
                    self.ggdb.connect_emulator(
                        emus[ret-1]['id'], source=self.actset['source'])
                else:
                    self.ggdb.connect_emulator(
                        emus[ret-1]['id'], swl_name=self.actset['swl_name'])
                self.run_emulator(emus[ret-1])
        else:
            self.configure_emulator()

    def configure_emulator(self, emu_info=None, reconfigure=False):
        """Dialog to configure emulators

        - configure new emulator
        - save in database
        - run emulator
        """

        if not emu_info:
            emu_info = {'name': '', 'exe': '', 'dir': '', 'zip': 0, 'mode': self.emulation_start}
        else:
            emu_info = dict(emu_info)
        # file
        emu_info['exe'] = self.dialog.browse(
            1, 'Emulator executable', 'files', defaultt=emu_info['exe'])
        if not emu_info['exe']:
            xbmc.executebuiltin('XBMC.Notification(no executable selected,,2500)')
            return
        # dir
        default = emu_info['dir']
        if not default:
            default, emu_file = os.path.split(emu_info['exe'])
            emu_name = os.path.splitext(emu_file)[0]
        emu_info['dir'] = self.dialog.browse(0, 'Working directory', 'files', defaultt=default)
        if not emu_info['dir']:
            xbmc.executebuiltin('XBMC.Notification(no working dir selected,,2500)')
            return
        # zip/chd
        emu_info['zip'] = self.dialog.select(
            'Extract?', ['Extract zip/chd', 'Start with zip/chd'], preselect=emu_info['zip'])
        # mode
        emu_info['mode'] = self.dialog.select(
            'Emulator start', ["Normal", "Watch", "Fallback"], preselect=emu_info['mode'])
        # name
        default = emu_info['name']
        if not default:
            default = emu_name
        emu_info['name'] = self.dialog.input('Name of emulator', default)
        if not emu_info['name']:
            xbmc.executebuiltin('XBMC.Notification(no name entered,,2500)')
            return
        # save to db
        if self.actset['swl_name'] == "mame":
            self.ggdb.save_emulator(emu_info, reconfigure, source=self.actset['source'])
        else:
            self.ggdb.save_emulator(emu_info, reconfigure, swl_name=self.actset['swl_name'])
        # run
        if not reconfigure:
            self.run_emulator(emu_info)

    def update_all(self):
        """Update artwork and support files database

        Threaded call from onInit
        """

        # ds = Thread(target=self.update, args=('dat',) )
        # ds.start()
        # while ds.isAlive():
        #     xbmc.sleep(1000)
        # Thread(target=self.update, args=('art',) ).start()
        self.update('dat')
        self.update('art')

    def update(self, what):
        """Update UMSA database, artwork or support files"""

        # update umsa.db
        if what == 'db':

            progress_dialog = xbmcgui.DialogProgress()
            progress_dialog.create('Updating UMSA database', 'downloading zip...')
            # close db before update
            if self.ggdb:
                self.ggdb.close_db()
            # sanity
            if not os.path.exists(SETTINGS_FOLDER):
                os.mkdir(SETTINGS_FOLDER)
            # TODO: backup
            #try:
                # download
            db_zip = bytearray()
            url = urlopen("http://umsa.info/umsa_db.zip", timeout=20)
            # float with *1.0 for percentage
            db_zip_size = int(url.info()['Content-Length'])*1.0
            while len(db_zip) < db_zip_size:
                db_zip.extend(url.read(102400))
                progress_dialog.update(int((len(db_zip)/db_zip_size)*80))
            # extract
            progress_dialog.update(80, 'unzip file...')
            zipfile.ZipFile(BytesIO(db_zip)).extractall(SETTINGS_FOLDER)
            #except:
            #    xbmc.executebuiltin(
            #        'XBMC.Notification(Updating UMSA database,\
            #         problem during download/unzip,5000)'
            #    )
            #    # TODO: restore backup

            # re-connect to db
            if self.ggdb:
                progress_dialog.update(90, 'copy artwork and dats back to new database...')
                self.ggdb.open_db(SETTINGS_FOLDER)
            # first run
            else:
                self.ggdb = DBMod(
                    SETTINGS_FOLDER,
                    self.filter_lists,
                    self.pref_country,
                )

            progress_dialog.close()

        # update dats database
        elif what == 'dat':
            self.setFocus(self.getControl(self.main_focus))
            self.progress_dialog.create('Scan support files', 'warm up')

            # create thread
            scan_dat_thread = Thread(
                target=self.ggdb.scan_dats,
                args=(self.datdir, SETTINGS_FOLDER)
                )
            scan_dat_thread.start()
            self.ggdb.scan_perc = 0
            self.ggdb.scan_what = ''
            while self.ggdb.scan_perc < 100:
            #TODO while scan_dat_thread.isAlive:
                xbmc.sleep(1000)
                self.progress_dialog.update(
                    self.ggdb.scan_perc,
                    'Scan support files',
                    'scanning {}'.format(self.ggdb.scan_what),
                )
            self.progress_dialog.update(100, 'Scan support files', 'saving')
            self.ggdb.add_dat_to_db(SETTINGS_FOLDER)
            self.progress_dialog.close()

        # update art database
        elif what == 'art':
            self.setFocus(self.getControl(self.main_focus))
            self.progress_dialog.create('Scan artwork folders', 'warm up')

            scan_art_thread = Thread(
                target=self.ggdb.scan_artwork,
                args=((self.progetto, self.other_artwork), SETTINGS_FOLDER)
                )
            scan_art_thread.start()
            self.ggdb.scan_perc = 0
            self.ggdb.scan_what = ''
            while self.ggdb.scan_what != "done":
            #while scan_art_thread.isAlive():
                xbmc.sleep(1000)
                self.progress_dialog.update(
                    self.ggdb.scan_perc,
                    'Scan artwork folders',
                    'scanning {}'.format(self.ggdb.scan_what),
                )
            self.progress_dialog.update(100, 'Scan artwork folders', 'saving')
            self.ggdb.add_art_to_db(SETTINGS_FOLDER)
            self.progress_dialog.close()

    def choose_media(self):
        """Dialog to choose media for playing.

        TODO
        - progettosnap soundtracks
        - vgm_play.xml, needs umsa.info work
        """

        # labels in list
        media_list = []
        video = [{'name':'- Videos -', 'id':'0', 'year':'', 'maker':''}]
        manual = [{'name':'- Manuals -', 'id':'0', 'year':'', 'maker':''}]
        # TODO add soundtracks and vgms

        # get media
        for j in self.info:
            for i in j:
                if 'video' in i:
                    video.append(
                        {'name':'%s (%s)' % (i['gamename'], i['swl_name']),
                         'id':i['video'],
                         'year':'',
                         'maker':''
                         }
                    )
                if 'manual' in i:
                    manual.append(
                        {'name':'%s (%s)' % (i['gamename'], i['swl_name']),
                         'id':i['manual'],
                         'year':'',
                         'maker':''
                         }
                    )
        # get youtube videos
        media = self.ggdb.get_further_media(self.actset['id'])
        if media and media['youtube']:
            yt_list = [{'name': '- Youtube -', 'id':'nan', 'year': '', 'maker': ''}]
            for i in loads(media['youtube']):
                yt_list.append(
                    {'name': i[1], 'id': "yt::{}".format(i[0]), 'year': '', 'maker': ''})
        else:
            yt_list = [{'name': '- Youtube (click for online search) -',
                        'id':'nan', 'year': '', 'maker': ''}]
        if media and media['marp']:
            marp_list = [{'name': '- Replays -', 'id':'nan', 'year': '', 'maker': ''}]
            for i in loads(media['marp']):
                marp_list.append({
                    'name': "{} ({} - {})".format(i['player'], i['percentage'], i['points']),
                    'id': "{}::{}".format(i['set_name'], i['download']),
                    'year': i['rank'], 'maker': i['version']})
        else:
            marp_list = [{'name': '- Replays (click for MARP search) -', 'id':'nan',
                          'year': '', 'maker': ''}]

        pos = 0
        if len(video) > 1:
            media_list.extend(video)
            pos = 1
        if len(manual) > 1:
            media_list.extend(manual)
            pos = 1
        media_list.extend(yt_list)
        media_list.extend(marp_list)

        self.popup_gamelist(media_list, 'Choose Media', pos=pos)

    def show_rec(self):
        """Shows recommended section from mameinfo.dat in gamelist"""

        if (self.actset['id'] in self.all_dat
                and 'Rec' in self.all_dat[self.actset['id']]):
            text = self.all_dat[self.actset['id']]['Rec']
        else:
            for i in self.all_dat:
                if 'Rec' in self.all_dat[i]:
                    text = self.all_dat[i]['Rec']
                    break
        rec_list = []
        pos = 0
        for rec_gamename in text.split('[CR]'):
            if rec_gamename == '':
                continue
            if rec_gamename[0] == '-':
                rec_item = {'name': rec_gamename, 'id': 0, 'year': '', 'maker': '',}
                pos += 1
            else:
                rec_item = self.ggdb.search_single(rec_gamename)
            rec_list.append(rec_item)
        self.popup_gamelist(rec_list, 'Recommended', pos=pos)

    def update_gamelist(self, item):
        """Update gamelist"""

        results, pos = [], 0

        xbmc.log("UMSA update_gamelist: item = {}".format(item))
        self.getControl(GAME_LIST_LABEL_ID).setLabel(str(item))
        self.getControl(GAME_LIST).reset()

        # without list popup
        if item == M_MEDIA:
            self.choose_media()
            return

        # show loading status
        self.getControl(GAME_LIST_LABEL).setLabel('loading...')
        time1 = time.time()

        if item == M_ALL:
            xbmc.log("UMSA update_gamelist: get_by_software")
            results, pos, count = self.ggdb.get_by_software(self.actset['id'])
            gl_label = "Complete list (%d)" % (count,)
            gl_options = ('name', 'year', 'publisher')

        elif item == M_SWL:
            xbmc.log("UMSA update_gamelist: get_by_swl")
            results, pos, count = self.ggdb.get_by_swl(
                self.actset['swl_name'],
                self.actset['id'],
            )
            gl_label = "swl: %s (%d)" % (
                self.actset['swl_name'], count
            )
            gl_options = ("all swls", "get connected swls")

        elif item == M_CAT:
            results, pos, count = self.ggdb.get_by_cat(
                self.actset['category'], self.actset['id']
            )
            gl_label = "Category: %s (%d)" % (
                self.actset['category'], count
            )
            gl_options = ('name', 'year', 'publisher')

        elif item == M_YEAR:
            results, pos, count = self.ggdb.get_by_year(
                self.actset['year'],
                self.actset['id']
            )
            gl_label = "Year: %s (%d)" % (self.actset['year'], count)
            gl_options = ('±0', '±1', '±2')

        elif item == M_PLAYERS:
            results, pos, count = self.ggdb.get_by_players(
                self.actset['nplayers'],
                self.actset['id']
            )
            gl_label = "Players: {} ({})".format(self.actset['nplayers'], count)
            gl_options = ('name', 'year', 'publisher')

        elif item == M_MAKER:
            results, pos, count = self.ggdb.get_by_maker(
                self.actset['publisher'],
                self.actset['id']
            )
            gl_label = "Publisher: %s (%d)" % (self.actset['publisher'], count)
            gl_options = ('name', 'year', 'publisher')

        elif item == M_PLAYSTAT:
            results, pos = self.ggdb.get_last_played("time_played")
            gl_label = ("play status")
            gl_options = ('time_played', 'last_played', 'play_count')

        elif item == M_MACHINE:
            if self.actset['swl_name'] == "mame":
                emus = self.ggdb.get_emulators(source=self.actset['source'])
                gl_label = 'Emulators for source {} ({})'.format(
                    self.actset['source'][:-4], len(results))
            else:
                emus = self.ggdb.get_emulators(swl_name=self.actset['swl_name'])
                temp_results, pos = self.ggdb.get_machines(
                    self.actset['swl_name'], self.actset['machine_name']
                )
                results.extend(temp_results)
                results.append({'id': 0, 'name': "----------", 'year': '', 'maker': ''})
                gl_label = 'Machines for {} ({})'.format(self.actset['swl_name'], len(results))
            for i in emus:
                results.append({'id': "emu_conn::{}".format(i['emu_conn_id']),
                                'name': i['name'], 'year': '', 'maker': ''})
            results.append({'id': 1,
                            'name': "Start with Kodi Retroplayer",
                            'year': ">>>", 'maker': "<<<"})
            results.append({'id': 1,
                            'name': "Choose a different emulator",
                            'year': ">>>", 'maker': "<<<"})
            gl_options = ('name', 'year', 'publisher')

        elif item == M_ALLEMUS:
            for i in self.ggdb.get_emulators():
                results.append(
                    {'id': "emu::{}".format(i['id']),
                     'name': i['name'],
                     'year': '', 'maker': "{} / {}".format(i['mode'], i['zip'])})
            gl_label = "Emulators"
            gl_options = ""

        elif item == M_SOURCE:
            results, pos, result_count = self.ggdb.get_software_for_source(
                self.actset['id'], self.actset['source']
            )
            gl_label = "source: %s (%d)" % (self.actset['source'], result_count)
            gl_options = ('name', 'year', 'publisher')

        elif item == M_LSSAVER:
            results = []
            for i in utilmod.load_lastsaver(SETTINGS_FOLDER):
                saver_list = self.ggdb.get_info_by_set_and_swl(i[0], i[1])
                results.append(
                    {'name': saver_list['name'],
                     'id': str(saver_list['software_id']),
                     'year': saver_list['year'],
                     'maker': saver_list['maker'],
                    }
                )
            gl_label = 'last screensaver session'
            gl_options = ('name', 'year', 'publisher')
            pos = 0

        elif item == M_SERIES:

            results = self.ggdb.get_series(self.last[self.lastptr])
            if results:
                self.popup_gamelist(results, 'Series')
            #self.getControl(GAME_LIST_TEXT).setText('')
            return

        elif item == M_REC:

            self.show_rec()
            #self.getControl(GAME_LIST_TEXT).setText('')
            return

        # TODO rethink normal and context call
        elif item == M_SEARCH_NEW:
            keyboard = xbmc.Keyboard('', "Search for", 0)
            keyboard.doModal()
            if keyboard.isConfirmed():
                self.searchold = keyboard.getText()
            else:
                return
            results, pos, result_count = self.ggdb.get_searchresults(self.searchold)
            gl_label = '%d results for %s' % (result_count, self.searchold)
            gl_options = ('new search',)

        elif item == M_SEARCH:
            if not self.searchold:
                keyboard = xbmc.Keyboard('', "Search for", 0)
                keyboard.doModal()
                if keyboard.isConfirmed():
                    self.searchold = keyboard.getText()
                else:
                    return
            results, pos, result_count = self.ggdb.get_searchresults(self.searchold)
            gl_label = '%d results for %s' % (result_count, self.searchold)
            gl_options = ('new search',)

        # no results = close list
        if len(results) == 0:
            if item == M_SEARCH:
                self.searchold = None
            xbmc.executebuiltin('XBMC.Notification(found nothing,,3000)')
            return

        # one software result = select
        if len(results) == 1 and item not in (M_MACHINE, M_ALLEMUS):
            if item == M_SEARCH:
                self.searchold = None
            xbmc.executebuiltin('XBMC.Notification(only one hit,,3000)')
            # TODO: check if this id is the one already shown
            self.lastptr += 1
            self.last.insert(self.lastptr, results[0]['id'])
            self.select_software(self.last[self.lastptr])
            self.setFocus(self.getControl(SOFTWARE_BUTTON))
            return

        if self.ggdb.use_filter:
            use_filter = ['filter: on', 'filter: off']
        else:
            use_filter = ['filter: off', 'filter: on']
        # TODO: also set sort method: name, year, maker

        time2 = time.time()
        self.getControl(LABEL_STATUS).setLabel(
            'took {:.0f}ms'.format((time2-time1)*1000)
        )

        # now show gamelist with gathered info from above
        self.popup_gamelist(results, gl_label, pos=pos, sort=use_filter, options=gl_options)
        # build submenu with lists in it
        self.build_sublist_menu(item)

        time3 = time.time()
        xbmc.log('UMSA update_gamelist: popup in gui: {:.0f}ms'.format((time3-time2)*1000))
        xbmc.log('UMSA update_gamelist: time overall: {:.0f}ms'.format((time3-time1)*1000))

    def popup_gamelist(self, gamelist, label, pos=0, sort=None, options=None):
        """Pop up gamelist

        TODO
         3 pic modes in skin 4:3 3:4 normal like left pic
        """

        list_items = []
        for i in gamelist:
            if not i:
                # TODO should not happen, check recommended list
                xbmc.log("UMSA popup_gamelist: item in gamelist {} broken: {}".format(
                    label, i))
                continue
            listitem = xbmcgui.ListItem(i['name'], str(i['id']))
            if 'year' in i.keys():
                listitem.setInfo('video', {'Writer': i['year'], 'Studio': i['maker']})
            list_items.append(listitem)

        self.getControl(GAME_LIST_LABEL).setLabel(label)
        self.getControl(GAME_LIST_OPTIONS).reset()
        if options:
            self.getControl(GAME_LIST_OPTIONS).addItems(options)
        self.getControl(GAME_LIST_SORT).reset()
        if sort:
            self.getControl(GAME_LIST_SORT).addItems(sort)
        self.getControl(GAME_LIST).reset()
        self.getControl(GAME_LIST).addItems(list_items)
        self.getControl(GAME_LIST).selectItem(pos)

        self.setFocus(self.getControl(GAME_LIST))
        # load snap, all_machines for selectedItem in GAMELIST
        self.gamelist_move()

    def machine_move(self):
        """Update set list and artwork, set new actual set after machine move"""

        pos_m = self.getControl(SYSTEM_WRAPLIST).getSelectedPosition()
        self.fill_set_list(pos_m)

        # TODO IMPORTANT !!!
        #xbmc.sleep(WAIT_GUI)
        pos_s = self.getControl(SET_LIST).getSelectedPosition()
        self.actset = self.info[pos_m][pos_s]

        self.show_artwork('machine')

    def software_move(self, direction):
        """Get next random software or move one back in history"""

        if direction == 'left' and self.lastptr >= 1:
            self.lastptr -= 1
            self.select_software(self.last[self.lastptr])
            return
        if direction == 'right':
            self.lastptr += 1
            if self.lastptr >= len(self.last):
                self.last.append(self.ggdb.get_random_id())
            self.select_software(self.last[self.lastptr])

    def set_filter_content(self, cat, update=None):
        """Set filter content"""

        active = []
        inactive = []
        filter_content_id = 0
        f_select = 0
        f_element = 0
        count = 0

        # only for action in list, not for inital fill
        if update == 'active':
            f_element = self.getControl(FILTER_CONTENT_LIST_ACTIVE).getSelectedPosition()
            filter_content_id = int(
                self.getControl(FILTER_CONTENT_LIST_ACTIVE).getSelectedItem().getLabel2()
            )
        elif update == 'inactive':
            f_element = self.getControl(FILTER_CONTENT_LIST_INACTIVE).getSelectedPosition()
            filter_content_id = int(
                self.getControl(FILTER_CONTENT_LIST_INACTIVE).getSelectedItem().getLabel2()
            )

        # fill lists
        for entry in self.ggdb.get_all_dbentries(cat):

            # label: swl (count), id
            list_item = xbmcgui.ListItem("{0} ({1})".format(entry[1], entry[2]), str(entry[0]))

            if str(entry[0]) in self.filter_lists[cat]:
                active.append(list_item)
                # check for selected item id, so we can select this in the other list
                if update == 'inactive':
                    if entry[0] == filter_content_id:
                        f_select = count
                    count += 1
            else:
                inactive.append(list_item)
                # check for selected item id, so we can select this in the other list
                if update == 'active':
                    if entry[0] == filter_content_id:
                        f_select = count
                    count += 1

        # reset lists and refill
        self.setFocus(self.getControl(FILTER_CATEGORY_LIST))
        self.getControl(FILTER_CONTENT_LIST_ACTIVE).reset()
        self.getControl(FILTER_CONTENT_LIST_INACTIVE).reset()
        self.getControl(FILTER_CONTENT_LIST_ACTIVE).addItems(active)
        self.getControl(FILTER_CONTENT_LIST_INACTIVE).addItems(inactive)
        self.getControl(FILTER_LABEL).setLabel(cat)

        # set selected items and focus
        if update == 'active':
            if f_element == len(active):
                f_element -= 1
            self.getControl(FILTER_CONTENT_LIST_ACTIVE).selectItem(f_element)
            self.getControl(FILTER_CONTENT_LIST_INACTIVE).selectItem(f_select)
            if len(active) > 0:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_ACTIVE))
            else:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_INACTIVE))
        elif update:
            if f_element == len(inactive):
                f_element -= 1
            self.getControl(FILTER_CONTENT_LIST_INACTIVE).selectItem(f_element)
            self.getControl(FILTER_CONTENT_LIST_ACTIVE).selectItem(f_select)
            if len(inactive) > 0:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_INACTIVE))
            else:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_ACTIVE))
        else:
            # switch to inactive when active is empty
            if len(active) > 0:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_ACTIVE))
            else:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_INACTIVE))

    def get_machine_pic(self, use_set):
        """Return full path for a machine picture based on set

        Uses internal picture for pinballs, reels and arcade
        """

        pic = None
        # TOOD bad solution, needs grouping of categories like Handheld.*
        categories = (
            'Handheld / Electronic Game', "Handheld / Plug n' Play TV Game",
            'Electromechanical / Reels', 'Casino / Reels',
            'Slot Machine / Reels', 'Slot Machine / Video Slot'
        )
        # set machine pic for mame
        if use_set['machine_name'] == 'mame':
            if use_set['is_machine']:
                pic = os.path.join(self.cab_path, use_set['name']+'.png')
            elif use_set['category'] == 'Electromechanical / Pinball':
                pic = os.path.join(MEDIA_FOLDER, "pinball.png")
            elif use_set['category'] in categories and use_set['id'] in self.all_art:
                # TODO remove loop when get_art gives dict[type]
                for art in self.all_art[use_set['id']]:
                    if art['type'] == 'cabinets':
                        pic = os.path.join(self.cab_path, "{}.{}".format(
                            use_set['name'], art['extension']))
                        break
                # fallback
                if not pic:
                    if 'Reels' in use_set['category']:
                        pic = os.path.join(MEDIA_FOLDER, "reels.png")
                    else:
                        # try artpreview TODO remove loop, see above
                        for art in self.all_art[use_set['id']]:
                            if art['type'] == 'artpreview':
                                pic = os.path.join(
                                    self.progetto, 'artpreview/artpreview', "{}.{}".format(
                                        use_set['name'], art['extension']))
                                break
                    if not pic:
                        pic = os.path.join(MEDIA_FOLDER, "arcade.png")
            else:
                if not pic:
                    pic = os.path.join(MEDIA_FOLDER, "arcade.png")
        # set machine pic for swl
        else:
            # TODO do with use_set['machine_name']... needs id
            # for swl_machine_art in self.ggdb.get_artwork_for_set(use_set['machine_id']):
            #    if swl_machine_art['type'] == 'cabinets':
            #        pic = os.path.join(
            #            self.cab_path, use_set['name']+swl_machine_art['extension'])
            if not pic:
                # TODO fallback media pic for missing swl machine cab
                pic = os.path.join(self.cab_path, use_set['machine_name']+'.png')
        return pic

    def fill_set_list(self, pos):
        """Fill the set list"""

        self.getControl(SET_LIST).reset()
        length = len(self.info[pos])
        count = 0

        # shadow pointer
        # if length == 1:
        #     self.getControl(SHADOW_SET).setVisible(False)
        # else:
        #     self.getControl(SHADOW_SET).setVisible(True)

        set_list_items = []
        for i in self.info[pos]:
            gamename, gamedetail = tools.split_gamename(i['gamename'])

            count += 1
            label = ""
            list_item = xbmcgui.ListItem()

            # set label
            if i['category'] != 'Not Classified' or i['nplayers'] != '???':
                if gamedetail:
                    label = "{} - {}, {}".format(
                        gamedetail, i['category'], i['nplayers']
                    )
                else:
                    label = "{}, {}".format(
                        i['category'], i['nplayers']
                    )
            elif gamedetail:
                label = '{}'.format(gamedetail)

            # add swl when not mame
            if i['swl_name'] != 'mame':
                label = '%s (%s)' % (label, i['swl_name'])

            # add * as a sign for a clone
            clone = ''
            if i['clone']:
                clone = '*'

            # add count to label
            if length > 1:
                label = '%s (%s%d/%d)' % (
                    label,
                    clone,
                    count,
                    length
                )

            list_item.setLabel(label)

            # set other labels in skin over setlist
            list_item.setProperty('Titel', gamename)
            list_item.setProperty('Year', i['year'])
            list_item.setProperty('Maker', i['publisher'])
            list_item.setProperty('Machine', i['machine_label'])

            set_list_items.append(list_item)

        self.getControl(SET_LIST).addItems(set_list_items)

    def select_software(self, software_id):
        """Get all machines and sets for a software and fill skin"""

        time1 = time.time()
        xbmc.log("UMSA select_software: id = {}".format(software_id))

        # stop video
        if self.playvideo and self.Player.isPlayingVideo():
            self.Player.stop()
            #xbmc.sleep(100)

        self.getControl(LABEL_STATUS).setLabel('loading software...')

        # get infos
        (self.info,
         pos_machine,
         pos_set,
         self.all_dat,
         self.all_art) = self.ggdb.get_all_for_software(software_id)

        # TODO should never happen
        if len(self.info) == 0:
            xbmc.log(
                "UMSA select_software: ERROR: software id = {}".format(software_id)
            )
            xbmc.executebuiltin(
                "XBMC.Notification(id-{} feels funny),2500".format(software_id)
            )
            self.getControl(LABEL_STATUS).setLabel('loading software...')
            return

        no_machines = len(self.info)
        #no_sets = len(self.info[pos_machine])
        self.actset = self.info[pos_machine][pos_set]

        # shadow pointers
        # if no_machines == 1:
        #     self.getControl(SHADOW_MACHINE).setVisible(False)
        # else:
        #     self.getControl(SHADOW_MACHINE).setVisible(True)

        # fill SET_LIST
        self.getControl(SYSTEM_WRAPLIST).reset()
        self.fill_set_list(pos_machine)
        self.getControl(SET_LIST).selectItem(pos_set)

        # fill MACHINE_WRAPLIST
        count = 0
        list_items = []
        for i in self.info:

            # check if we are at selected machine
            # to use the correct selected set
            set_no = 0
            if pos_machine == count:
                set_no = pos_set
            count += 1

            # set picture
            list_item = xbmcgui.ListItem()
            list_item.setArt({'icon': self.get_machine_pic(use_set=i[set_no])})
            list_items.append(list_item)

        self.getControl(SYSTEM_WRAPLIST).addItems(list_items)
        self.getControl(SYSTEM_WRAPLIST).selectItem(pos_machine)

        # set border for machines
        if no_machines == 1:
            self.getControl(SYSTEM_BORDER).setWidth(124)
            self.getControl(SYSTEM_BORDER).setImage("border1.png")
            self.getControl(MACHINE_SEP1).setVisible(False)
            self.getControl(MACHINE_SEP2).setVisible(False)
            self.getControl(MACHINE_SEP3).setVisible(False)
            self.getControl(MACHINE_PLUS).setVisible(False)
        elif no_machines == 2:
            self.getControl(SYSTEM_BORDER).setWidth(246)
            self.getControl(SYSTEM_BORDER).setImage("border2.png")
            self.getControl(MACHINE_SEP1).setVisible(True)
            self.getControl(MACHINE_SEP2).setVisible(False)
            self.getControl(MACHINE_SEP3).setVisible(False)
            self.getControl(MACHINE_PLUS).setVisible(False)
        elif no_machines == 3:
            self.getControl(SYSTEM_BORDER).setWidth(368)
            self.getControl(SYSTEM_BORDER).setImage("border3.png")
            self.getControl(MACHINE_SEP1).setVisible(True)
            self.getControl(MACHINE_SEP2).setVisible(True)
            self.getControl(MACHINE_SEP3).setVisible(False)
            self.getControl(MACHINE_PLUS).setVisible(False)
        else:
            self.getControl(SYSTEM_BORDER).setWidth(490)
            self.getControl(SYSTEM_BORDER).setImage("border4.png")
            self.getControl(MACHINE_SEP1).setVisible(True)
            self.getControl(MACHINE_SEP2).setVisible(True)
            self.getControl(MACHINE_SEP3).setVisible(True)

        # set width for wraplist
        if no_machines > 4:
            self.getControl(SYSTEM_WRAPLIST).setWidth(480)
            self.getControl(MACHINE_PLUS).setVisible(True)
        else:
            self.getControl(SYSTEM_WRAPLIST).setWidth(no_machines*120)

        self.getControl(TEXTLIST).reset()
        # search local snaps
        self.create_artworklist()
        # play video
        if self.playvideo and not self.Player.isPlayingAudio():
            video = []
            for j in self.info:
                for i in j:
                    if 'video' in i:
                        video.append(
                            {'label': '%s (%s)' % (i['gamename'], i['swl_name']),
                             'id': i['video']
                             }
                        )
            if video:
                video_rand = choice(video)
                video_file = video_rand['id']
                if (not self.Player.isPlayingVideo() or
                        (self.Player.isPlayingVideo() and
                         video_file != self.Player.getPlayingFile())):

                    list_item = xbmcgui.ListItem(video_rand['label'])
                    self.Player.play(
                        video_file,
                        listitem=list_item,
                        windowed=True
                    )

        # show artwork and dat info
        self.show_artwork()

        # set indicators
        if self.vidman == (0, 0):
            self.getControl(MEDIA_LABEL).setVisible(False)
        else:
            self.getControl(MEDIA_LABEL).setVisible(True)
        is_compilation = self.ggdb.check_compilation(self.last[self.lastptr])
        if is_compilation == 2: # on a compilation
            self.getControl(COMPILATION_LABEL).setVisible(True)
        elif is_compilation == 1: # is a compilation
            self.getControl(COMPILATION_LABEL).setVisible(True)
        else:
            self.getControl(COMPILATION_LABEL).setVisible(False)

        xbmc.log("UMSA select_software: set number of machines")
        # set number of machines
        if no_machines > 4:
            self.getControl(LABEL_STATUS).setLabel(
                "{} machines".format(str(len(self.info)))
            )
        else:
            self.getControl(LABEL_STATUS).setLabel('')

        time2 = time.time()
        #xbmc.sleep(WAIT_GUI)
        xbmc.log("UMSA select_software: complete  %0.3f ms" % ((time2-time1)*1000.0))

    def search_snaps(self, set_info):
        """Search files in MAME snapshot directory

        Returns list with full path

        TODO move to screensaver
        """

        imagelist = []
        if set_info['swl_name'] == 'mame':
            snap_dir = os.path.join(
                self.mame_ini['snapshot_directory'],
                set_info['name']
            )
        else:
            snap_dir = os.path.join(
                self.mame_ini['snapshot_directory'],
                set_info['swl_name'], set_info['name']
            )
        if os.path.isdir(snap_dir):
            for snap_file in os.listdir(snap_dir):
                imagelist.append(
                    create_gui_element_from_snap(set_info, os.path.join(snap_dir, snap_file))
                )
        return imagelist

    def create_artworklist(self):
        """Create left and right artwork list, side product is play count and time played"""

        self.played = {
            'count'  : 0,
            'played' : 0
        }
        vid = 0
        man = 0

        for machine in self.info:
            for set_info in machine:

                set_info['right_pics'] = []
                set_info['left_pics'] = []

                # sum up lp
                if set_info['last_played']:
                    self.played['count'] += set_info['last_played']['play_count']
                    self.played['played'] += set_info['last_played']['time_played2']

                # mame snaps
                set_info['localsnaps'] = self.search_snaps(set_info)

                # progettosnaps
                if set_info['id'] not in self.all_art:
                    continue
                for art in self.all_art[set_info['id']]:

                    if art['path']:
                        path = self.progetto
                    else:
                        path = self.other_artwork

                    # create complete filename
                    if set_info['swl_name'] == 'mame':
                        filename = os.path.join(
                            path, art['type'], art['type'], set_info['name']+'.'+art['extension']
                        )
                    else:
                        filename = os.path.join(
                            path, art['type'], set_info['swl_name'],
                            "{}.{}".format(set_info['name'], art['extension'])
                        )

                    if art['type'] in RIGHT_IMAGELIST:
                        list_item = xbmcgui.ListItem()
                        list_item.setLabel("{}: {} ({})".format(
                            art['type'], set_info['detail'], set_info['swl_name']))
                        list_item.setProperty('detail', "{}: {} {}".format(
                            art['type'], set_info['swl_name'], set_info['detail']))
                        list_item.setArt({'icon': filename})
                        set_info['right_pics'].append(list_item)
                    elif art['type'] in LEFT_IMAGELIST:
                        set_info['left_pics'].append(
                            create_gui_element_from_snap(set_info, filename, art)
                        )
                    elif art['type'] == 'videosnaps':
                        set_info['video'] = filename[:-4]+'.'+art['extension']
                        vid += 1
                    elif art['type'] == 'manuals':
                        set_info['manual'] = filename[:-4]+'.'+art['extension']
                        man += 1
                    else:
                        xbmc.log(
                            "UMSA create_artworklist: cant identify artwork type = {}".format(art)
                        )

        self.vidman = (vid, man)
        minutes = divmod(self.played['played'], 60)[0]
        hours, minutes = divmod(minutes, 60)
        self.played['played'] = "%d:%02d" % (hours, minutes)

    def show_artwork(self, howmuch='all'):
        """Show artwork

        TODO
         - no update when set does not change
         - only left side update for after emu run
        """

        rlist = []
        llist = []

        if howmuch == 'set':
            rlist = self.actset['right_pics']
            llist = self.actset['left_pics'] + self.actset['localsnaps']
        elif howmuch == 'machine':
            for i in self.info[self.getControl(SYSTEM_WRAPLIST).getSelectedPosition()]:
                rlist += i['right_pics']
                llist += i['left_pics'] + i['localsnaps']
        else: # all
            for j in self.info:
                for i in j:
                    rlist += i['right_pics']
                    llist += i['left_pics'] + i['localsnaps']

        if len(rlist) > 0:

            # set count/sets
            count = 1
            list_items = []
            for i in rlist:
                # get detail from setlist property and set label new
                i.setLabel("{} ({}/{})".format(
                    i.getProperty('detail'), count, len(rlist)))
                list_items.append(i)
                count += 1
            self.getControl(IMAGE_BIG_LIST).reset()
            self.getControl(IMAGE_BIG_LIST).addItems(list_items)

        else:
            list_item = xbmcgui.ListItem()
            list_item.setProperty('NotEnabled', '1')
            #list_item.setArt({'icon' : 'blank.png'})
            self.getControl(IMAGE_BIG_LIST).reset()
            self.getControl(IMAGE_BIG_LIST).addItem(list_item)

        # fill pic left
        if len(llist) > 0:

            # set count/sets
            count = 1
            list_items = []
            for i in llist:
                # get detail from setlist property and set label new
                # TODO: check if i.getProperty works when used in i.setLabel
                # TODO: before we used to assign property to var
                # TODO: same problem above
                i.setLabel(
                    "{} ({}/{})".format(
                        i.getProperty('detail'),
                        count,
                        len(llist)
                    )
                )
                list_items.append(i)
                count += 1
            self.getControl(IMAGE_LIST).reset()
            self.getControl(IMAGE_LIST).addItems(list_items)

        else:
            list_item = xbmcgui.ListItem()
            list_item.setProperty('NotEnabled', '1')
            #list_item.setArt({'icon' : 'blank.png'})
            self.getControl(IMAGE_LIST).reset()
            self.getControl(IMAGE_LIST).addItem(list_item)

        # show infos from datfiles only when changed
        if self.oldset == (self.actset['swl_name'], self.actset['name']):
            return

        # check play status
        # TODO check if all, system or set
        # TODO also show series and compilation status
        stattext = ''
        if self.played['count'] > 0:
            if self.actset['last_played']:
                played_text = self.actset['last_played']['last_nice']+' ago'
            else:
                played_text = "never"
            stattext = "%s, %sh, %sx[CR]" % (
                played_text,
                self.played['played'],
                self.played['count']
            )

        list_items = []
        count = 0
        if self.actset['id'] in self.all_dat:
            # TODO put history first, so have a sorted list of headings
            for k in sorted(self.all_dat[self.actset['id']]):
                moretext = ''
                if k in ('Contribute', 'Rec'):
                    continue
                if k == 'History':
                    moretext = stattext

                list_item = xbmcgui.ListItem()
                list_item.setLabel(k)
                list_item.setProperty(
                    'text',
                    moretext + self.all_dat[self.actset['id']][k]
                )
                list_items.append(list_item)
                count += 1

        if len(list_items) == 0:
            list_item = xbmcgui.ListItem()
            list_item.setLabel("no information...")
            list_item.setProperty('text', stattext)
            list_items.append(list_item)

        self.getControl(TEXTLIST).reset()
        self.getControl(TEXTLIST).addItems(list_items)

        # shadow pointer
        if count > 1:
            self.getControl(SHADOW_DAT).setVisible(True)
        else:
            self.getControl(SHADOW_DAT).setVisible(False)

        # remember actual swl and set
        self.oldset = (self.actset['swl_name'], self.actset['name'])
        # refresh main menu
        self.build_main_menu()

        xbmc.log("UMSA show_artwork: pics, dats done")

        # TODO
        # - indicate manuals, videos, series, rec, more?
        # with simpel buttons under year - publ: v m s
        # and avail as first under context menu

    def find_roms(self, swl_name, set_name, set_clone):
        """Return found rom/chd from MAME rompath

        TODO
        - move to tools, needs disks and rompath
        """

        # build filename
        is_chd = None
        # TODO can also be a chd
        if swl_name == 'mame':
            zip_name = set_name + '.zip'
        else:
            zip_name = swl_name + '/' + set_name + '.zip'
            # get all disks, means chd here
            # TODO: actually using 1st disk, what if more disks avail?
            disks = self.ggdb.get_disks(swl_name, set_name)
            if disks and 'disk' in disks[0].keys() and disks[0]['disk']:
                # also check parent for merged sets
                if set_clone:
                    is_chd = (
                        os.path.join(swl_name, set_name, '{}.chd'.format(disks[0]['disk'])),
                        os.path.join(swl_name, set_clone, '{}.chd'.format(disks[0]['disk']))
                    )
                else:
                    is_chd = (
                        os.path.join(swl_name, set_name, '{}.chd'.format(disks[0]['disk'])),
                    )
        # search filename
        for rom_path in self.mame_ini['rompath']:
            # check for chd
            if is_chd:
                for i in is_chd:
                    chd_file = os.path.join(rom_path, i)
                    if os.path.isfile(chd_file):
                        return chd_file
            # check for zip
            else:
                zip_file = os.path.join(rom_path, zip_name)
                if os.path.isfile(zip_file):
                    return zip_file
        return None

    def extract_rom(self, rom_file, swl_name, set_name):
        """Extract chd or zip file"""

        folder = os.path.join(self.temp_dir, swl_name + '_' + set_name)

        # TODO needs own def extract_chd ???
        # also rom_file should be a list with all chds if
        # there are more than one!

        # check for chd and extract
        if rom_file[-4:] == '.chd':
            chd_name = os.path.basename(rom_file)
            # dc needs gdi extension
            if swl_name == 'dc':
                file_ext = '.gdi'
            else:
                file_ext = '.cue'
            if os.path.exists(folder):
                # TODO also check the files
                return folder, [chd_name+file_ext]
            os.mkdir(folder)
            progress_dialog = xbmcgui.DialogProgress()
            progress_dialog.create('Extract CHD...', chd_name)
            params = [self.chdman_exe,
                      'extractcd',
                      '-i', rom_file,
                      '-o', os.path.join(folder, chd_name+file_ext)
                     ]
            self.emurunning = True
            proc = Popen(params, stdout=PIPE, stderr=PIPE)
            # routine to show progress in kodi
            perc = 0
            while proc.returncode is None:
                progress_dialog.update(perc)
                chdman_progress = proc.stderr.read(34)
                rpos = chdman_progress[::-1].find('%') # reversed str
                if rpos > -1:
                    pos = len(chdman_progress)-rpos-1
                    str_perc = chdman_progress[pos-4:pos]
                    xbmc.log("UMSA extract_rom: chd extract progress = {}".format(str_perc))
                    try:
                        perc = int(float(chdman_progress[pos-4:pos]))
                    except ValueError:
                        pass
                proc.poll()
                xbmc.sleep(100)
            progress_dialog.update(100)
            progress_dialog.close()
            self.emurunning = False
            xbmc.log(
                "UMSA extract_rom: chd extract: proc.returncode = {0}".format(proc.returncode)
            )
            if proc.returncode == 0:
                return folder, [chd_name+'.cue']
            xbmc.executebuiltin('XBMC.Notification(error extracting chd,,1500)')
            os.rmdir(folder)
            # TODO: show stdout and stderr
            return None, None

        # only extract when folder does not exists
        if os.path.exists(folder):
            zfiles = os.listdir(folder)
        else:
            # for renaming of filename extension
            # (needed by most emulators)
            extension_table = {
                'snes'    : '.sfc',
                'gameboy' : '.gb',
                'gbcolor' : '.gbc',
                'n64'     : '.n64',
                'nes'     : '.nes',
            }

            # extract zipfile
            progress_dialog = xbmcgui.DialogProgressBG()
            progress_dialog.create('Extracting ZIP', 'extracting ZIP')

            os.mkdir(folder)
            try:
                zfile = zipfile.ZipFile(rom_file)
                zfile.extractall(folder)
                zfile.close()
            except:
                xbmc.executebuiltin('XBMC.Notification(error extracting zip,,2500)')
                os.rmdir(folder)
                return None, None

            zfiles = os.listdir(folder)
            # TODO create single rom for cartridges
            # complicated as we don't have the complete xml output with
            # the rom info and it's actually not possible to do
            # './mame64 nes -cart skatedi2 -listxml' to get this info

            # simple hack to concatenate files so other emulators can read them
            if len(zfiles) == 2 and swl_name in extension_table.keys():

                # hack swl nes: prg before chr
                if zfiles[0][-3:] == 'chr' and zfiles[1][-3:] == 'prg':
                    xbmc.log("UMSA extract_rom: NES: 2. is prg... {}".format(zfiles))
                    with open(os.path.join(folder, zfiles[1]), "ab") as prg_file, open(os.path.join(folder, zfiles[0]), "rb") as chr_file:
                        prg_file.write(chr_file.read())
                    prg_file.close()
                    chr_file.close()
                    os.remove(os.path.join(folder, zfiles[0]))
                elif zfiles[0][-3:] == 'prg' and zfiles[1][-3:] == 'chr':
                    xbmc.log("UMSA extract_rom: NES: 1. is prg... {}".format(zfiles))
                    with open(os.path.join(folder, zfiles[0]), "ab") as prg_file, open(os.path.join(folder, zfiles[1]), "rb") as chr_file:
                        prg_file.write(chr_file.read())
                    prg_file.close()
                    chr_file.close()
                    os.remove(os.path.join(folder, zfiles[1]))

                # rest is sorted by name
                else:
                    xbmc.log("UMSA extract_rom: joining rom files: {}".format(zfiles))
                    zfiles_sort = sorted(zfiles)
                    xbmc.log("UMSA extract_rom: sorted: {}".format(zfiles_sort))
                    with open(os.path.join(folder, zfiles_sort[0]), "ab") as file1, open(os.path.join(folder, zfiles_sort[1]), "rb") as file2:
                        file1.write(file2.read())
                    file1.close()
                    os.remove(os.path.join(folder, zfiles_sort[1]))
                zfiles = os.listdir(folder)

            # rename
            if swl_name in extension_table.keys():
                if os.path.splitext(zfiles[0])[1] != extension_table[swl_name]:
                    os.rename(
                        os.path.join(folder, zfiles[0]),
                        os.path.join(folder, "{}.{}".format(
                            zfiles[0], extension_table[swl_name]
                        ))
                    )
                zfiles = os.listdir(folder)

            progress_dialog.update(100)
            progress_dialog.close()

        # dialog when we have still more than one file,
        # like home computer software with many discs
        if len(zfiles) > 1:
            which_file = self.dialog.select('Select file: ', zfiles)
            this_file = zfiles[which_file]
            zfiles[which_file] = zfiles[0]
            zfiles[0] = this_file

        return folder, zfiles

    def run_emulator(self, diff_emu=None, more_options='', machine='', setname=''):
        """Start the emulator...

        Shows a dialog during emulator run.
        """

        # local vars
        path = None # working directory
        params = [] # parameter list, first is emulator executable
        out, err = '', '' # stdour/err for watch emurun
        emulation_start = None

        # different emulator than mame
        if diff_emu:

            xbmc.log("UMSA run_emulator: diff emu: {}".format(dict(diff_emu)))

            if 'mode' in diff_emu:
                emulation_start = diff_emu['mode']

            # demul -run=[dc,naomi,awave,...] -rom=
            if 'demul' in diff_emu['exe']:
                path = diff_emu['dir']
                params.append(diff_emu['exe'])

                # dreamcast
                if self.actset['swl_name'] == 'dc':
                    # TODO: split chd search from find_roms
                    chd = self.find_roms(
                        self.actset['swl_name'], self.actset['name'], self.actset['clone'])
                    # make symlink in tmp as spaces and brackets are ...
                    if 'linux' in PLATFORM:
                        image = os.path.join(self.temp_dir, self.actset['name'])
                        os.symlink(chd, image)
                    else:
                        image = chd
                    params.extend(['-run=dc', '-image={}'.format(image)])
                # arcade
                else:
                    # call -listroms to find parameter for -run=
                    section = ''
                    try:
                        listroms = check_output([diff_emu['exe'], '-listroms'])
                    except:
                        listroms = ''
                    for i in listroms.splitlines():
                        if len(i) > 0 and i[0] != ' ':
                            section = i.rstrip()
                            xbmc.log("UMSA run_emulator: demul - section {}".format(section))
                        elif self.actset['name'] in i:
                            xbmc.log("UMSA run_emulator: demul - found {}".format(i))
                            break
                    if section == "Atomiswave":
                        section = "Awave"
                    params.extend([
                        '-run={0}'.format(section.lower()),
                        '-rom={0}'.format(self.actset['name'])
                    ])
            # standard way with search rom file
            else:
                # find file by the name of the set
                rom_file = self.find_roms(
                    self.actset['swl_name'], self.actset['name'],
                    self.ggdb.get_set_name(self.actset['clone'])
                )
                if not rom_file:
                    xbmc.executebuiltin('XBMC.Notification(rom/chd not found,,3500)')
                    return
                # set emulator and path
                params.append(diff_emu['exe'])
                path = diff_emu['dir']
                # extract rom_file if needed
                unzip_file = ""
                if not diff_emu['zip']:
                    folder, files = self.extract_rom(
                        rom_file, self.actset['swl_name'], self.actset['name']
                    )
                    # when None is returned there was a problem while extracting
                    if not folder:
                        return
                    params.append(os.path.join(folder, files[0]))
                    unzip_file = os.path.join(folder, files[0])
                else:
                    params.append(rom_file)

                # Kodi Retroplayer (looked up from IARL Addon)
                # TODO test
                if diff_emu['exe'] == 'kodi':
                    game_item = xbmcgui.ListItem(unzip_file, "0", "", "")
                    if self.Player.isPlaying():
                        self.Player.stop()
                        xbmc.sleep(100)
                    xbmc.sleep(500)
                    self.Player.play(unzip_file, game_item)
                    self.exit()

                # fs-uae --floppies_dir=/tmp/amiga_game/ --floppy_drive_0=disk1
                #  --floppy_image_0=disk1 --floppy_image_1=disk2
                # TODO: CD32/CDTV but needs chd search instead of floppies
                if 'fs-uae' in diff_emu['exe']:
                    if self.actset['swl_name'] == 'amigaaga_flop':
                        params[1] = '--amiga_model=A1200'
                    else:
                        params[1] = '--amiga_model=A500'
                    params.append('--floppies_dir={}'.format(folder))
                    params.append('--floppy_drive_0={}'.format(files[0]))
                    fcount = 0
                    for i in files:
                        params.append('--floppy_image_{}={}'.format(fcount, i))
                        fcount += 1

        # marp: play given machine, set
        elif machine:
            path = self.mame_dir
            params.extend([self.mame_exe, setname]+more_options)
        # swl is mame
        elif self.actset['swl_name'] == 'mame':
            path = self.mame_dir
            params.extend([self.mame_exe, self.actset['name']])
        # start a swl item
        else:
            path = self.mame_dir
            # get cmd options
            cmd_line = self.ggdb.get_cmd_line_options(
                self.actset['id'],
                self.actset['name'],
                self.actset['machine_name'],
                self.actset['swl_name'],
            )
            params.extend([self.mame_exe]+cmd_line)

        # set emu start if not set yet
        if not emulation_start:
            emulation_start = self.emulation_start
        # stop playing video or pause audio
        if self.playvideo and self.Player.isPlayingVideo():
            self.Player.stop()
        # TODO: Player should set and unset a var with
        # onPlayBackPaused and onPlayBackResumed
        # otherwise paused audio will be started
        elif self.Player.isPlayingAudio():
            self.Player.pause()

        xbmc.log("UMSA run_emulator: parameters = {}".format(params))
        # open a notification with possibility to cancel emulation
        # TODO better desc than emulator run
        self.emu_dialog.create('emulator run', ' '.join(params))
        # TODO: switch to normal dialog without progress as emulator is slow
        self.emu_dialog.update(0) # TODO: does not remove progress bar
        # set flag for monitor
        self.emurunning = True
        # remember start time
        start = time.time()

        # start emulator:
        if emulation_start == 1: # Watch
            proc = Popen(params, bufsize=-1, stdout=PIPE, stderr=PIPE, cwd=path)
        elif emulation_start == 0: # Normal
            proc = Popen(params, cwd=path)
        elif emulation_start == 2: # Fallback
            # TODO make os.system a daemon thread so it does not stop the script?
            # TODO use subprocess.run?
            proc = None
            # Supermodel needs to be started in it's directory
            run = "cd {} && ".format(path)
            # escape parameters with double quotes
            for i in params:
                run += '"{}" '.format(i)
            os.system(run)

        # wait for emulator process to stop or cancel press to kill
        if proc:
            wait_cancel = True
            while wait_cancel:
                xbmc.sleep(500)
                proc.poll()
                if not proc.returncode is None:
                    wait_cancel = False
                if self.emu_dialog.iscanceled():
                    # terminate gives no returncode?
                    # and proc.wait() might hang...
                    proc.terminate()
                    proc.poll()
                    # sleep does nothing?
                    xbmc.sleep(2500)
                    proc.poll()
                    if not proc.returncode:
                        xbmc.log("UMSA run_emulator: process does not terminate, sending SIGKILL")
                        proc.kill()
                    wait_cancel = False
            if self.emulation_start == 1:
                out = proc.stdout.read().decode('utf-8', errors='ignore')
                err = proc.stderr.read().decode('utf-8', errors='ignore')

        # remember end time
        end = time.time()
        self.emurunning = False

        # TODO check if works when video runs
        # unpause audio again
        if self.Player.isPlayingAudio():
            self.Player.pause()

        # pretty output from mame
        if "Average speed:" in out:
            notif = out[out.find('Average speed:')+15:]
        else:
            notif = None

        # show emulator output if we have an error as tab in TEXTLIST
        if proc and proc.returncode != 0:

            xbmc.log("UMSA run_emulator: returncode = {}".format(proc.returncode))
            no_emu_out = True

            # check if item already exists
            for i in range(0, self.getControl(TEXTLIST).size()):
                if self.getControl(TEXTLIST).getListItem(i).getLabel() == 'Emulator output':
                    no_emu_out = False
                    break
            # not: then create
            if no_emu_out and (out or err):
                emu_out_item = xbmcgui.ListItem()
                emu_out_item.setLabel('Emulator output')
                self.getControl(TEXTLIST).addItem(emu_out_item)

            # when we have output
            if out or err:
                emu_out_item.setProperty(
                    'text', 'cmd: {0}\nerr {1}: {2}\nout: {3}'.format(
                        ' '.join(params), proc.returncode, err, out
                    )
                )
                self.getControl(TEXTLIST).selectItem(
                    self.getControl(TEXTLIST).size() - 1
                )
                if not notif:
                    notif = "see bottom left"
            else:
                notif = None

        # not a marp run: check time played and snapshots made
        if not machine:
            # write time, date to status db
            if int(end-start) > 60:
                self.ggdb.write_status_after_play(self.actset['id'], int(end-start))
            # update local snapshots
            if not diff_emu:
                xbmc.sleep(100)
                self.actset['localsnaps'] = self.search_snaps(self.actset)
                self.show_artwork('set')

        # show notification
        xbmc.log("UMSA run_emulator: stopped, monitor = {}".format(self.Monitor.running))
        if self.Monitor.running != 'no':
            self.emu_dialog.update(
                90, "{}\nScreensaver active. Press a button to escape!".format(notif))
        else:
            self.emu_dialog.close()
            if notif:
                xbmc.executebuiltin('XBMC.Notification(output:,{},3000)'.format(notif))

    def exit(self):
        """Exit add-on

        Save last ten, stop video, close database
        TODO: check for threads and close?
        """

        utilmod.save_software_list(SETTINGS_FOLDER, 'lastgames.txt', self.last[-10:])
        # TODO stop video if playing
        # if self.Player.isPlayingVideo() and self.playvideo:
        #     self.Player.stop()
        # close db
        try:
            self.ggdb.close_db()
        except AttributeError:
            pass
        # close script
        self.close()

def main():
    """Main"""

    skin = "Default"
    #path = ''
    path = xbmcaddon.Addon(id='script.umsa.mame.surfer').getAddonInfo('path')
    # check Kodi skin
    if 'transparency' in xbmc.getSkinDir():
        gui = UMSA("umsa_transparency.xml", path, skin, "720p")
    else:
        gui = UMSA("umsa_estuary.xml", path, skin, "720p")
    gui.doModal()
    del gui
main()
