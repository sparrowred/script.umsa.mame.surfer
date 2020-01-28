# -*- coding: utf-8 -*-
""" Main Gui for Kodi Addon """

import os
import sys
import subprocess
import time
import zipfile
import random
import re
from io import BytesIO
from threading import Thread
# PY2: remove except part for py3 only
try:
    from urllib.request import urlopen
    from urllib.parse import urlencode
except ImportError:
    from urllib2 import urlopen
    from urllib import urlencode

import xbmc
import xbmcgui
import xbmcaddon
# own modules
import marp # marp functionality
import utilmod # utility functions
from utilmod2 import Check # check_snapshot
from utilmod2 import check_image_aspect
from dbmod import DBMod # database module

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
VIDEO_LABEL = 2005
SOFTWARE_BUTTON = 4000
MAIN_MENU = 4901
SUBMAIN_MENU = 4902
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
M_FAVS = 1
M_EMU = 2
M_MACHINE = 21
M_SERIES = 3
M_VMS = 4
M_SEARCH = 5
M_LISTS = 6
M_ALL = 61
M_MAKER = 62
M_CAT = 63
M_YEAR = 64
M_SOURCE = 65
M_SWL = 66
M_REC = 67
M_FILTER = 7
M_MORE = 8
M_UPD = 81
M_SSAVER = 82
M_PLAYSTAT = 83
M_LSSAVER = 84
M_SETTINGS = 85
M_ASETTINGS = 86
M_YTVID = 87
M_EXIT = 9
M_BACK = 10

# xbmc.sleep times in ms
WAIT_PLAYER = 500
WAIT_GUI = 100

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
            xbmc.log("UMSA FSVideoSaver: did not find any videos")
            self.parent.Player.stop()
            self.parent.Monitor.running = 'no'
            self.close()
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
            tt = int(self.parent.Player.getTotalTime())
            # wait until video starts
            #while not self.parent.Player.isPlayingVideo():
            while tt == 0:
                xbmc.sleep(100)
                tt = int(self.parent.Player.getTotalTime())
            # calc show times
            if tt > 28:
                tc1 = 10
                tc2 = tt-10
            elif tt > 16:
                tc1 = 8
                tc2 = tt-2
            else:
                tc1 = 4
                tc2 = tt-1
            self.runp = True
            c = 0
            xbmc.log("UMSA Player: time: {}, start {}, end {}".format(tt, tc1, tc2))
            while self.runp:
                if self.parent.Player.isPlayingVideo():
                    if c == tc1:
                        # set video label
                        self.parent.VPlayer.getControl(VIDEO_LABEL).setLabel(
                            self.parent.Player.getVideoInfoTag().getTitle()
                        )
                    elif c == tc2:
                        self.parent.VPlayer.getControl(VIDEO_LABEL).setLabel('')
                        self.runp = False
                        continue
                else:
                    self.runp = False
                    continue
                xbmc.sleep(1000)
                c += 1
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
            x = random.randint(0, 1280)
            y = random.randint(0, 720)
            if aspect == 'Vertical':
                # TODO look up aspect calc from ssaver
                piclist.append(
                    xbmcgui.ControlImage(x-120, y-160, 240, 320, filename)
                )
            elif aspect == 'NotScaled':
                piclist.append(
                    xbmcgui.ControlImage(x-180, y-180, 360, 360, filename, 2)
                )
            else:
                piclist.append(
                    xbmcgui.ControlImage(x-180, y-135, 360, 270, filename)
                )
            # show pic
            self.parent.addControl(piclist[-1])
            if len(piclist) > 60:
                self.parent.removeControl(piclist[0])
                del piclist[0]
            xbmc.sleep(2000)
        # clean up
        piclist.reverse()
        for o in piclist:
            self.parent.removeControl(o)

    def onScreensaverActivated(self):
        """onScreensaverActivated

        TODO
         check addon settings what is allowed
        """

        xbmc.log("UMSA Monitor: screensaver activated")
        # only when not already running and no emulator running
        if self.parent.emurunning:
            self.running = "emu"
        elif self.running == "no":
            # no videos when audio is running
            if self.parent.Player.isPlayingAudio():
                # TODO: make configurable through settings
                self.snapshot_crossover(['covers', 'flyers'])
            elif random.randint(0, 1):
                self.snapshot_crossover(['covers', 'flyers'])
            else:
                xbmc.log("UMSA Monitor: play videos")
                self.parent.play_random_videos()
        xbmc.log("UMSA Monitor: running = {}".format(self.running))

    def onScreensaverDeactivated(self):
        """onScreensaverDeactivated"""

        xbmc.log("UMSA Monitor: screensaver deactivated")
        if self.running != 'video':
            if self.running == 'emu':
                self.running = "no"
                self.parent.emu_dialog.close()
            self.running = "no"
        else:
            xbmc.log("UMSA Monitor: internal video screensaver stays active")

class UMSA(xbmcgui.WindowXMLDialog):
    """Main UMSA class"""

    def __init__(self, strXMLname, strFallbackPath, strDefaultName, forceFallback):

        # no settings
        if not os.path.exists(SETTINGS_FOLDER):
            __addon__.openSettings()
        self.read_settings()

        # initialize
        random.seed()
        self.mame_ini = None
        self.quit = False
        self.selectedControlId = SOFTWARE_BUTTON # holds the old control id from skin
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
        self.pd = None
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

        # filter categories
        self.filter_cat = [
            "Softwarelists", "Game Categories", "Machine Categories", "Players",
            "Years", "----------", "Load Filter", "Save Filter"
            ]

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
        self.pd = xbmcgui.DialogProgressBG()

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
        l = []
        for i in self.filter_cat:
            l.append(xbmcgui.ListItem(i))
        self.getControl(FILTER_CATEGORY_LIST).addItems(l)
        self.getControl(FILTER_OPTIONS).addItems(('all', 'none', 'invert'))

        # database connection
        if os.path.isfile(os.path.join(SETTINGS_FOLDER, 'umsa.db')):
            self.ggdb = DBMod(
                SETTINGS_FOLDER,
                self.filter_lists,
                self.pref_country,
            )
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

    def onFocus(self, controlId):
        """Kodi onFocus"""

        xbmc.log("UMSA onFocus: old: %s" % (self.selectedControlId,))
        xbmc.log("UMSA onFocus: new: %s" % (controlId,))

        # TODO: get rid off dummy with a list instead of the software button?
        # list item label would then be actual software button input from skin
        self.dummy = None

        # # close popups
        if controlId in (SOFTWARE_BUTTON, SYSTEM_WRAPLIST, SET_LIST, TEXTLIST):
        #if controlId == SOFTWARE_BUTTON or controlId == SYSTEM_WRAPLIST:

            if self.selectedControlId in (
                    GAME_LIST, GAME_LIST_OPTIONS, GAME_LIST_SORT, SUBMAIN_MENU
                ):
                self.setFocus(self.getControl(SOFTWARE_BUTTON))
                if self.enter:
                    self.enter = None
                else:
                    self.dummy = True

            elif self.selectedControlId in (
                    FILTER_CATEGORY_LIST,
                    FILTER_CONTENT_LIST_ACTIVE,
                    FILTER_CONTENT_LIST_INACTIVE,
                ):

                self.close_filterlist()
                if self.enter:
                    self.enter = None
                else:
                    self.dummy = True

            elif self.selectedControlId == MAIN_MENU:
                self.dummy = True

        # update menu when focused
        elif controlId == MAIN_MENU:
            # TODO sub main
            # self.build_main_menu()
            pass

        # WORKING VERSION
        # close popups
        # if controlId == SOFTWARE_BUTTON or controlId == SYSTEM_WRAPLIST:
        #
        #     if self.selectedControlId in (
        #             GAME_LIST, GAME_LIST_OPTIONS, GAME_LIST_SORT
        #         ):
        #         self.setFocus(self.getControl(SOFTWARE_BUTTON))
        #         if self.enter:
        #             self.enter = None
        #         else:
        #             self.dummy = True
        #
        #     elif self.selectedControlId in (
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
        # if (controlId == SYSTEM_WRAPLIST
        #      and self.getControl(SYSTEM_WRAPLIST).size() == 1
        #    ):
        #     if self.selectedControlId == SET_LIST:
        #         xbmc.log("- from SET to SOFTWARE")
        #         self.setFocus(self.getControl(SOFTWARE_BUTTON))
        #     else:
        #         xbmc.log("- from SOFTWARE to SET")
        #         self.setFocus(self.getControl(SET_LIST))
        # if controlId == SET_LIST and self.getControl(SET_LIST).size() == 1:
        #     if self.selectedControlId == SYSTEM_WRAPLIST:
        #         xbmc.log("- from MACHINE to TEXT")
        #         self.setFocus(self.getControl(TEXTLIST))
        #     else:
        #         xbmc.log("- from TEXT to MACHINE")
        #         self.setFocus(self.getControl(SYSTEM_WRAPLIST))
        if (controlId == TEXTLIST and self.getControl(TEXTLIST).size() < 2):
            if self.selectedControlId == SET_LIST:
                xbmc.log("UMSA onFocus: from SET to SOFTWARE")
                self.setFocus(self.getControl(SOFTWARE_BUTTON))
            else:
                # TODO will not happen as we go from SOFTWARE TO BOTTOM CPANEL?
                xbmc.log("UMSA onFocus: from SOFTWARE to SET")
                self.setFocus(self.getControl(SET_LIST))

        # update controlId
        self.enter = None
        self.selectedControlId = controlId

    def onClick(self, controlID):
        """Kodi onClick"""

        xbmc.log("UMSA onClick")

        if self.Monitor.running != "no":
            if self.Monitor.running == 'pic':
                self.Monitor.running = 'no'
            xbmc.log("UMSA onClick: Monitor runs = return")
            return

        # start emulator
        if controlID in (SOFTWARE_BUTTON, SET_LIST, SYSTEM_WRAPLIST):
            self.run_emulator()

        # TEXTLIST: start emulator or show series
        elif controlID == TEXTLIST:
            if self.getControl(TEXTLIST).getSelectedItem().getLabel() == 'Series':
                x = self.ggdb.get_series(self.last[self.lastptr])
                if x:
                    self.popup_gamelist(x, 0, 'Series', [], [])
                #self.getControl(GAME_LIST_TEXT).setText('')
            else:
                self.run_emulator()

        # pushed GAME_LIST_OPTIONS
        elif controlID == GAME_LIST_OPTIONS:
            item = self.getControl(GAME_LIST_OPTIONS).getSelectedItem().getLabel()

            if item == "new search":
                keyboard = xbmc.Keyboard('', "Search for", 0)
                keyboard.doModal()
                if keyboard.isConfirmed():
                    self.searchold = keyboard.getText()
                else:
                    return
                x, pos, result_count = self.ggdb.get_searchresults(self.searchold)
                gl_label = '%d results for %s' % (result_count, self.searchold)
                gl_options = ('new search',)

                # check how many results
                if len(x) == 0:
                    xbmc.executebuiltin('XBMC.Notification(nothing,,5000)')
                    return
                if len(x) == 1:
                    self.searchold = None
                    self.lastptr += 1
                    self.last.insert(self.lastptr, x[0]['id'])
                    self.select_software(self.last[self.lastptr])
                    return

                # TODO no popup, but refill
                self.popup_gamelist(x, pos, gl_label, [], gl_options)

            # options from play status
            elif item in ('time_played', 'last_played', 'play_count'):
                x, pos = self.ggdb.get_last_played(item)
                self.getControl(GAME_LIST).reset()
                l = []
                for i in x:
                    li = xbmcgui.ListItem(i['name'], str(i['id']))
                    li.setInfo(
                        'video', {'Writer': i['year'], 'Studio': i['maker']}
                        )
                    l.append(li)
                self.getControl(GAME_LIST).addItems(l)
                self.setFocus(self.getControl(GAME_LIST))

            elif item in ('name', 'year', 'publisher'):
                self.ggdb.order = item
                content = int(self.getControl(GAME_LIST_LABEL_ID).getLabel())
                self.update_gamelist(content)

        elif controlID == GAME_LIST_SORT:
            self.gamelist_switch_filter()

        # FILTER: select all, none or invert lists
        elif controlID == FILTER_OPTIONS:

            item = self.getControl(FILTER_OPTIONS).getSelectedItem().getLabel()
            filter_category_name = self.getControl(FILTER_LABEL).getLabel()

            if item == 'none':
                self.filter_lists[filter_category_name] = []
            elif item == 'all':
                self.filter_lists[filter_category_name] = []
                for e in self.ggdb.get_all_dbentries(filter_category_name):
                    self.filter_lists[filter_category_name].append(str(e[0]))
            elif item == 'invert':
                templist = []
                for e in self.ggdb.get_all_dbentries(filter_category_name):
                    if str(e[0]) not in self.filter_lists[filter_category_name]:
                        templist.append(str(e[0]))
                self.filter_lists[filter_category_name] = templist

            self.set_filter_content(filter_category_name)

            # set focus to active, when empty deactive
            if len(self.filter_lists[filter_category_name]) == 0:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_INACTIVE))
            else:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_ACTIVE))

    def onAction(self, action):
        """Kodi onAction"""

        xbmc.log("UMSA onAction: {}".format(action.getId()))

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

        # TODO: does not work
        # check if 18 is correct
        # try play windowed=False
        if action.getId() == 18: # tab for video fullscreen/window switch
            xbmc.log("UMSA onAction: switch video fullscreen/windowed")
            self.Player.play(windowed=True)

        # exit only in main screen, otherwise close popup or stop video
        if action.getId() in ACTION_CANCEL_DIALOG:

            x = self.selectedControlId
            if x in (
                    GAME_LIST, GAME_LIST_OPTIONS, GAME_LIST_SORT, SUBMAIN_MENU
            ):
                self.setFocus(self.getControl(SOFTWARE_BUTTON))
                self.enter = True
                return
            if x in (
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
        if self.selectedControlId == SOFTWARE_BUTTON:
            xbmc.log("UMSA onAction: SOFTWARE_BUTTON")

            if action.getId() in ACTION_MOVEMENT_RIGHT:
                self.software_move('right')

            elif action.getId() in ACTION_MOVEMENT_LEFT:
                self.software_move('left')

            elif action.getId() in ACTION_MOVEMENT_DOWN+ACTION_MOVEMENT_UP:
                self.show_artwork()

            elif action.getId() in ACTION_CONTEXT:
                # STATUS of LIST?
                # if empty fill, ow just open
                self.update_gamelist(M_ALL)
                self.gamelist_move()

        # MAIN MENU
        elif self.selectedControlId == MAIN_MENU:

            if action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_ENTER:

                # get menu item
                m = int(self.getControl(MAIN_MENU).getSelectedItem().getLabel2())
                xbmc.log("UMSA onAction: menu = {}".format(m))

                if m == M_FAVS:
                    pass

                elif m == M_FILTER:
                    self.setFocus(self.getControl(FILTER_CATEGORY_LIST))

                elif m == M_MORE:
                    xl = []
                    for i in (
                            ('Update', M_UPD),
                            ('Artwork Show', M_SSAVER),
                            ('Play Status', M_PLAYSTAT),
                            ('Screensaver List', M_LSSAVER),
                            ('Listmode', M_LISTS),
                            ('Youtube Video', M_YTVID),
                            ('Settings (empty)', M_SETTINGS),
                            ('Addon Settings', M_ASETTINGS),
                            ('< Back', M_BACK)
                    ):
                        xl.append(xbmcgui.ListItem(i[0], str(i[1])))
                    self.getControl(MAIN_MENU).reset()
                    self.getControl(MAIN_MENU).addItems(xl)
                    self.setFocus(self.getControl(MAIN_MENU))

                elif m == M_YTVID:
                    query_string = urlencode(
                        {"search_query" : '{} {}'.format(
                            self.actset['gamename'].replace(self.actset['detail'], '').split(),
                            self.actset['machine_name'] #self.actset['machine_label']
                        )}
                    )
                    html_content = urlopen(
                        "http://www.youtube.com/results?" + query_string
                    )
                    search_results = re.findall(
                        r'href=\"\/watch\?v=(.{11})',
                        html_content.read().decode('utf-8', errors='ignore')
                    )
                    #playurl = "plugin://plugin.video.youtube/?action=play_video&videoid={}".format(
                    playurl = "plugin://plugin.video.youtube/play/?video_id={}".format(
                        search_results[0]
                    )
                    self.Player.play(playurl, windowed=True)
                    # TODO doesnt work, try with new window like fsvidplay
                    # and put playurl into skin? or this we have to call player?

                elif m == M_EXIT:
                    self.exit()

                elif m == M_UPD:
                    self.setFocus(self.getControl(SOFTWARE_BUTTON))
                    # sanity
                    if self.scan_thread and not self.scan_thread.isAlive():
                        self.scan_thread = None
                    if self.scan_thread:
                        xbmc.executebuiltin(
                            'XBMC.Notification(scan status,scan already running...,3000)'
                        )
                        return

                    ret = self.dialog.select(
                        'What wants to get a refresh today?',
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

                elif m == M_SSAVER:
                    self.setFocus(self.getControl(SOFTWARE_BUTTON))
                    ret = self.dialog.select(
                        'Which show would please you?', (
                            'Play random videos',
                            'Make Artwork Crossover',
                            'MARP Replayer',
                        )
                    )
                    if ret != -1:
                        self.setFocus(self.getControl(SOFTWARE_BUTTON))
                    if ret == 0:
                        self.play_random_videos()
                    elif ret == 1:
                        x = self.ggdb.get_art_types()
                        ret2 = self.dialog.multiselect(
                            "What do you want to see?", x
                        )
                        if ret2:
                            y = []
                            for i in ret2:
                                y.append(x[i])
                            xbmc.sleep(500)
                            self.Monitor.snapshot_crossover(y)
                    elif ret == 2:
                        self.marp_replayer()
                elif m == M_ASETTINGS:
                    self.setFocus(self.getControl(SOFTWARE_BUTTON))
                    __addon__.openSettings()
                    self.read_settings()
                elif m == M_BACK:
                    self.build_main_menu()

                elif m == M_LISTS:
                    xbmc.log("UMSA onAction: M_LISTS sub")
                    #self.setFocus(self.getControl(GAME_LIST_LABEL))
                    self.update_gamelist(M_ALL)
                else:
                    self.setFocus(self.getControl(GAME_LIST_LABEL))
                    self.update_gamelist(m)

            elif action.getId() in ACTION_CONTEXT:

                m = int(self.getControl(MAIN_MENU).getSelectedItem().getLabel2())

                if m == M_FILTER:
                    if self.ggdb.use_filter:
                        self.ggdb.use_filter = False
                    else:
                        self.ggdb.use_filter = True
                    self.build_main_menu()

        # TODO: rename, is for gamelist menu now
        elif self.selectedControlId == SUBMAIN_MENU:

            if action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_ENTER:

                sm = int(self.getControl(SUBMAIN_MENU).getSelectedItem().getLabel2())
                self.update_gamelist(sm)

        # ACTION SYSTEM_WRAPLIST
        elif self.selectedControlId == SYSTEM_WRAPLIST:
            xbmc.log("UMSA onAction: MACHINE_LIST")

            if action.getId() in ACTION_MOVEMENT_RIGHT or action.getId() in ACTION_MOVEMENT_LEFT:
                self.machine_move()

            elif action.getId() in ACTION_MOVEMENT_DOWN or action.getId() in ACTION_MOVEMENT_UP:
                self.show_artwork('machine')

            elif action.getId() in ACTION_CONTEXT:
                if self.actset['swl_name'] == 'mame':
                    self.update_gamelist(M_SOURCE)
                else:
                    self.update_gamelist(M_SWL)

        elif self.selectedControlId == TEXTLIST:

            if action.getId() in ACTION_CONTEXT:
                self.update_gamelist(M_ALL)

        # ACTION GAME_LIST
        elif self.selectedControlId == GAME_LIST:
            xbmc.log("UMSA onAction: GAME_LIST")

            if action.getId() in ACTION_ENTER:
                self.gamelist_click()
            elif action.getId() in ACTION_CONTEXT:
                self.gamelist_switch_filter()
            else:
                self.gamelist_move()

        # ACTION FILTER_CATEGORY_LIST
        elif self.selectedControlId == FILTER_CATEGORY_LIST:
            xbmc.log("UMSA onAction: FILTER_CATEGORY_LIST")

            if action.getId() in ACTION_ENTER:
                self.filter_category()

        # ACTION FILTER_CONTENT_LIST_ACTIVE
        elif self.selectedControlId == FILTER_CONTENT_LIST_ACTIVE:
            xbmc.log("UMSA onAction: FILTER_CONTENT_LIST_ACTIVE")

            if action.getId() in ACTION_ENTER:
                self.filter_content('active')

        # ACTION FILTER_CONTENT_LIST_INACTIVE
        elif self.selectedControlId == FILTER_CONTENT_LIST_INACTIVE:
            xbmc.log("UMSA onAction: FILTER_CONTENT_LIST_INACTIVE")

            if action.getId() in ACTION_ENTER:
                self.filter_content('inactive')

        # ACTION SET_LIST
        elif self.selectedControlId == SET_LIST:
            xbmc.log("UMSA onAction: SET_LIST")

            if action.getId() in ACTION_MOVEMENT_LEFT+ACTION_MOVEMENT_RIGHT:

                # update actual set
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

            elif action.getId() in ACTION_MOVEMENT_DOWN or action.getId() in ACTION_MOVEMENT_UP:
                self.show_artwork('set')

            elif action.getId() in ACTION_CONTEXT:
                if self.actset['swl_name'] == 'mame':
                    self.update_gamelist(M_SOURCE)
                else:
                    self.update_gamelist(M_MACHINE)

    def marp_replayer(self):
        """Play a random replay from replay.marpirc.net"""

        # TODO: get version from mame executable
        random_inp_file = random.choice(
            marp.rand(str(random.randint(178, 217)))
        )
        xbmc.log("UMSA marp_replayer: random choice {}".format(random_inp_file))

        inp_file = marp.download(
            random_inp_file[7],
            os.path.join(self.mame_dir, self.mame_ini['input_directory'])
        )

        opt = [
            #"-seconds_to_run", "60",
            "-playback", inp_file,
            "-exit_after_playback",
        ]

        self.run_emulator(
            more_options=opt, machine="mame", setname=random_inp_file[0]
        )

    def play_random_videos(self):
        """Starts playing random videos"""

        self.Monitor.running = 'video'
        self.VPlayer.doModal()
        self.Monitor.running = 'no'

    def build_sublist_menu(self):
        """Builds the sublist menu"""

        xl = []
        xl.append(xbmcgui.ListItem('All', str(M_ALL)))
        xl.append(xbmcgui.ListItem('Publisher', str(M_MAKER)))
        xl.append(xbmcgui.ListItem('Category', str(M_CAT)))
        xl.append(xbmcgui.ListItem('Year', str(M_YEAR)))

        rec = False
        for i in self.all_dat:
            if 'Rec' in self.all_dat[i]:
                rec = True
                break
        if rec:
            xl.append(xbmcgui.ListItem("Recommended", str(M_REC)))

        # source
        if self.actset['swl_name'] == 'mame':
            c = self.ggdb.count_source(self.actset['source'])
            if c > 1:
                xl.append(xbmcgui.ListItem(
                    'Source {} ({})'.format(
                        self.actset['source'], c
                    ), str(M_SOURCE)
                ))
            else:
                xbmc.log("UMSA build_sublist_menu: only 1 source: {}".format(self.actset['source']))
        # swl
        else:
            xl.append(xbmcgui.ListItem(
                'Softwarelist: {}'.format(
                    self.actset['swl_name']
                ), str(M_SWL)
            ))

        # TODO: series, search?

        self.getControl(SUBMAIN_MENU).reset()
        self.getControl(SUBMAIN_MENU).addItems(xl)

    def build_main_menu(self):
        """Builds up the main menu"""

        xl = []
        # TODO build fav support
        xl.append(xbmcgui.ListItem('Add to Favorites', '1'))

        # TODO save diff emu per set and show here
        xl.append(xbmcgui.ListItem('Emulator: MAME', '2'))

        # TODO only when emu = mame
        if self.actset['swl_name'] != 'mame':
            c = self.ggdb.count_machines_for_swl(self.actset['swl_name'])
            if c > 1:
                xl.append(xbmcgui.ListItem('- change machine ({})'.format(c), '21'))

        # series
        series = self.ggdb.check_series(self.last[self.lastptr])
        if series:
            xl.append(
                xbmcgui.ListItem("Show series ({})".format(series), '3')
            )

        # video/manual/TODO sound
        xbmc.log("UMSA  build_main_menu: video, manual status = {}".format(self.vidman))
        if self.vidman != (0, 0):
            t = ''
            if self.vidman[0] == 1 and self.vidman[1] == 0:
                t = "Play Video"
            elif self.vidman[1] == 1 and self.vidman[0] == 0:
                t = "Show Manual"
            else:
                if self.vidman[0] > 0:
                    t += "Videos({}) ".format(self.vidman[0])
                if self.vidman[1] > 0:
                    t += "Manuals({})".format(self.vidman[1])
            xl.append(xbmcgui.ListItem(t, str(M_VMS)))

        # search
        if self.searchold:
            xl.append(
                xbmcgui.ListItem('Last Search: {}'.format(self.searchold), str(M_SEARCH))
                )
        else:
            xl.append(
                xbmcgui.ListItem('New Search', str(M_SEARCH))
                )

        # filter
        if self.ggdb.use_filter:
            xl.append(
                xbmcgui.ListItem('Filter: {}'.format(self.act_filter), '7')
                )
        else:
            xl.append(
                xbmcgui.ListItem('Filter: off', '7')
                )

        xl.append(xbmcgui.ListItem('More', '8'))
        xl.append(xbmcgui.ListItem('Exit UMSA', '9'))
        self.getControl(MAIN_MENU).reset()
        self.getControl(MAIN_MENU).addItems(xl)

    def gamelist_move(self):
        """Move in gamelist"""

        # check label if we have games in list
        g_label = self.getControl(GAME_LIST_LABEL).getLabel()
        if 'Machines for' in g_label or 'Choose Media' in g_label:
            xbmc.log("UMSA gamelist_move: no games = return")
            return
        # get infos
        gi = self.getControl(GAME_LIST).getSelectedItem()
        # check if we have an item
        if not gi:
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
        if gi.getProperty('text'):
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
            gi.setArt(
                {'icon' : os.path.join(path, 'snap', snap[0].replace('mame', 'snap'))}
                )
        gi.setProperty('text', snap[2])
        xbmc.log("UMSA gamelist_move: properties set = {}".format(gi.getProperty('text')))

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

        gamelist_id = self.getControl(GAME_LIST).getSelectedItem().getLabel2()
        if gamelist_id == "0":
            return

        # GAME LIST contains machines for a swl
        if 'Machines for' in self.getControl(GAME_LIST_LABEL).getLabel():

            # get info from db
            machine_name, machine_label = self.ggdb.get_machine_name(
                                gamelist_id
                        )

            # set new image and machine label
            self.getControl(SYSTEM_WRAPLIST).getSelectedItem().setArt(
                {'icon' : os.path.join(self.cab_path, machine_name+'.png')}
                )
            self.getControl(SET_LIST).getSelectedItem().setProperty(
                'Machine', machine_label
            )

            # save machine for set in self.info
            self.actset['machine_name'] = machine_name
            self.actset['machine_label'] = machine_label

            self.enter = True
            self.setFocus(self.getControl(SOFTWARE_BUTTON))

        elif self.getControl(GAME_LIST_LABEL).getLabel() == 'Choose Media':

            # TODO: add play soundtrack
            xbmc.log("UMSA gamelist_click: id = {}".format(gamelist_id))
            if gamelist_id[-3:] == "mp4":

                #if self.Player.isPlayingVideo():
                #    self.Player.stop()
                #    xbmc.sleep(200)
                # TODO video label
                gameinfo = self.getControl(GAME_LIST).getSelectedItem().getLabel()
                li = xbmcgui.ListItem(gameinfo)
                #li.setInfo('video',
                #    {'Writer': i['year'],
                #     'Studio': i['maker']}
                #)
                self.Player.play(
                    gamelist_id,
                    listitem=li,
                    windowed=True
                )

            else:
                self.setFocus(self.getControl(SOFTWARE_BUTTON))
                # start pdf viewer in bg
                subprocess.Popen([self.pdfviewer, gamelist_id])

        # GAME LIST contains software
        else:

            # get prev/next results and show them
            xbmc.log("UMSA gamelist_click: software id ={}".format(gamelist_id))
            if gamelist_id in ('prev', 'next'):
                if gamelist_id == 'prev':
                    sid = int(self.getControl(GAME_LIST).getListItem(1).getLabel2())
                else:
                    size = self.getControl(GAME_LIST).size()
                    sid = int(self.getControl(GAME_LIST).getListItem(size-2).getLabel2())
                x, pos = self.ggdb.get_prevnext_software(sid, gamelist_id)

                l = []
                for i in x:
                    li = xbmcgui.ListItem(i['name'], str(i['id']))
                    li.setInfo(
                        'video', {'Writer' : i['year'], 'Studio' : i['maker'],}
                        )
                    l.append(li)
                self.getControl(GAME_LIST).reset()
                self.getControl(GAME_LIST).addItems(l)
                self.getControl(GAME_LIST).selectItem(pos)
                self.setFocus(self.getControl(GAME_LIST))

            # new software selected
            else:
                software_id = int(gamelist_id)
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

                self.enter = True
                self.setFocus(self.getControl(SYSTEM_WRAPLIST))

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
                c = self.ggdb.define_filter(self.filter_lists)
                self.getControl(LABEL_STATUS).setLabel(
                    "%s filtered items" % (c,)
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
            #otherlist = FILTER_CONTENT_LIST_INACTIVE
        else:
            contentlist = FILTER_CONTENT_LIST_INACTIVE
            #otherlist = FILTER_CONTENT_LIST_ACTIVE

        # get actual category
        filter_category_name = self.getControl(FILTER_LABEL).getLabel()
        # get db id for actual content entry
        filter_content_id = self.getControl(contentlist).getSelectedItem().getLabel2()

        xbmc.log("UMSA filter_content: filter_category_name = {}".format(filter_category_name))
        xbmc.log("UMSA filter_content: list = {}".format(self.filter_lists[filter_category_name]))

        # update internal list
        if which_content == 'active':
            xbmc.log("MSA filter_content: remove: {0}".format(filter_content_id))
            self.filter_lists[filter_category_name].remove(filter_content_id)
        else:
            xbmc.log("MSA filter_content: append: {0}".format(filter_content_id))
            self.filter_lists[filter_category_name].append(filter_content_id)

        # update gui
        self.set_filter_content(filter_category_name, update=which_content)

    def read_settings(self):
        """Read settings for UMSA from Kodi

        - read settings
        - imports check_snapshot
        - checks if chdman is in mame directory
        - set playvideo
        - set cab_path
        """

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
        self.ssaver = __addon__.getSetting('ssaver')

        # import check_snapshot for screensaver
        self.util = Check()
        if self.util.pil:
            xbmc.log("UMSA read_settings: PIL library found")

        # check chdman
        if self.chdman_exe == "":
            # split self.mame_exe
            mame_path, unused = os.path.split(self.mame_exe)
            # check if chdman is in same dir as mame
            if 'linux' in PLATFORM:
                chdman_file = os.path.join(mame_path, 'chdman')
            else:
                chdman_file = os.path.join(mame_path, 'chdman.exe')
            if os.path.isfile(chdman_file):
                self.chdman_exe = chdman_file

        # auto play videos
        if __addon__.getSetting('playvideo') == 'true':
            self.playvideo = True
        else:
            self.playvideo = None

        self.cab_path = os.path.join(self.progetto, 'cabinets/cabinets')

    def close_filterlist(self, no_update=None):
        """Close filter list window"""

        xbmc.log("UMSA close_filterlist")
        # update filter
        if not no_update:
            c = self.ggdb.define_filter(self.filter_lists)
            self.getControl(LABEL_STATUS).setLabel(
                "%s filtered items" % (c,)
            )
        self.setFocus(self.getControl(SOFTWARE_BUTTON))

    def get_diff_emulator(self, source=None, swl_name=None):
        """Get different emulator"""

        if source:
            x = self.ggdb.get_emulator(source=source)
            text = 'source %s' % (source,)
        else:
            x = self.ggdb.get_emulator(swl_name=swl_name)
            text = 'swl %s' % (swl_name, )

        elist = ['Kodi Retroplayer', 'Different emulator']
        for i in x.keys():
            elist.insert(0, i)

        ret = self.dialog.select('Emulator: '+text, elist)
        if ret == -1:
            return

        if elist[ret] == 'Different emulator':

            x = self.ggdb.get_all_emulators()
            if x:
                dlist = ['New emulator'] + x.keys()
                ret2 = self.dialog.select('Emulator: '+text, dlist)
                if dlist[ret2] == 'New emulator':
                    if source:
                        self.get_new_emulator(source=source)
                    else:
                        self.get_new_emulator(swl_name=swl_name)
                else:
                    if source:
                        self.ggdb.connect_emulator(
                            x[dlist[ret2]]['id'], # id of emu entry
                            source=source
                        )
                    else:
                        self.ggdb.connect_emulator(
                            x[dlist[ret2]]['id'], # id of emu entry
                            swl_name=swl_name
                        )
                    self.run_emulator(x[dlist[ret2]])
                    return

            elif source:
                self.get_new_emulator(source=source)
            else:
                self.get_new_emulator(swl_name=swl_name)

        elif elist[ret] == "Kodi Retroplayer":
            self.run_emulator({'exe': 'kodi', 'zip': None})
        else:
            self.run_emulator(x[elist[ret]])

    def get_new_emulator(self, source=None, swl_name=None):
        """Dialog to configure new emulator

        - configure new emulator
        - save in database
        - run emulator
        """

        # get filename
        fn = self.dialog.browse(1, 'Emulator executable', 'files')
        if not fn:
            return

        # get working dir
        wd = self.dialog.browse(0, 'Working directory', 'files')
        if not wd:
            return

        # zip support
        zip_support = self.dialog.yesno('Zip support?', 'means no zip uncompress')
        xbmc.log("UMSA get_new_emulator: zip_support = {}".format(zip_support))

        # name
        name = self.dialog.input('Name of emulator')
        if not name:
            return

        if source:
            self.ggdb.save_emulator(name, fn, wd, zip_support, source=source)
        else:
            self.ggdb.save_emulator(name, fn, wd, zip_support, swl_name=swl_name)

        self.run_emulator(
            {
                'exe' : fn,
                'dir' : wd,
                'zip' : zip_support
            }
        )

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

            pd = xbmcgui.DialogProgress()
            pd.create('Updating UMSA database', 'downloading zip...')
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
                pd.update(int((len(db_zip)/db_zip_size)*80))
            # extract
            pd.update(80, 'unzip file...')
            zipfile.ZipFile(BytesIO(db_zip)).extractall(SETTINGS_FOLDER)
            #except:
            #    xbmc.executebuiltin(
            #        'XBMC.Notification(Updating UMSA database,\
            #         problem during download/unzip,5000)'
            #    )
            #    # TODO: restore backup

            # re-connect to db
            if self.ggdb:
                pd.update(90, 'copy artwork and dats back to new database...')
                self.ggdb.open_db(SETTINGS_FOLDER)
            # first run
            else:
                self.ggdb = DBMod(
                    SETTINGS_FOLDER,
                    self.filter_lists,
                    self.pref_country,
                )

            pd.close()

        # update dats database
        elif what == 'dat':
            self.setFocus(self.getControl(SOFTWARE_BUTTON))
            self.pd.create('Scan DAT files', 'scanning files...')

            xbmc.log("UMSA update: start dat scan thread")
            # create thread
            x = Thread(
                target=self.ggdb.scan_dats,
                args=(self.datdir, SETTINGS_FOLDER)
                )
            x.start()

            self.ggdb.scan_perc = 0
            self.ggdb.scan_what = ''
            while self.ggdb.scan_perc < 100:
            #TODO while x.isAlive:
                xbmc.sleep(1000)
                self.pd.update(
                    self.ggdb.scan_perc,
                    'Scan DAT files',
                    'scanning {0}...'.format(self.ggdb.scan_what),
                )
            self.pd.update(100, 'Scan DAT files', 'copy to umsa.db...')
            self.ggdb.add_dat_to_db(SETTINGS_FOLDER)
            self.pd.close()

        # update art database
        elif what == 'art':
            self.setFocus(self.getControl(SOFTWARE_BUTTON))
            self.pd.create('Scan Artwork folders', 'scanning dirs...')
            x = Thread(
                target=self.ggdb.scan_artwork,
                args=((self.progetto, self.other_artwork), SETTINGS_FOLDER)
                )
            x.start()

            self.ggdb.scan_perc = 0
            self.ggdb.scan_what = ''
            while self.ggdb.scan_what != "done":
            #while x.isAlive():
                xbmc.sleep(1000)
                self.pd.update(
                    self.ggdb.scan_perc,
                    'Scan Artwork folders',
                    'scanning {0}...'.format(self.ggdb.scan_what),
                )
            self.pd.update(100, 'Scan Artwork folders', 'copy to umsa.db...')
            self.ggdb.add_art_to_db(SETTINGS_FOLDER)
            self.pd.close()

    def choose_media(self):
        """Dialog to choose video or manual to show"""

        # labels in list
        video = [{'name':'Videos:', 'id':'0', 'year':'', 'maker':''}]
        manual = [{'name':'Manuals:', 'id':'0', 'year':'', 'maker':''}]
        # TODO add soundtracks

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

        xbmc.log("UMSA choose_media: video {}, man {}".format(len(video), len(manual)))
        # only 1 video
        if len(video) == 2 and len(manual) == 1:
            #if self.Player.isPlayingVideo():
            #    self.Player.stop()
            #    xbmc.sleep(200)
            li = xbmcgui.ListItem(video[1]['id'])
            li.setInfo('video', {'Title': video[1]['name'],})
            self.Player.play(
                video[1]['id'],
                listitem=li,
                windowed=True
            )
        # only 1 manual
        elif len(manual) == 2 and len(video) == 1:
            # start pdf viewer in bg
            subprocess.Popen([self.pdfviewer, manual[1]['id']])
        # more
        else:
            if len(video) == 1:
                x = manual
            elif len(manual) == 1:
                x = video
            else:
                x = video + manual

            self.popup_gamelist(x, 1, 'Choose Media', [], [])

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
        ll = []
        pos = 0
        for i in text.split('[CR]'):
            if i == '':
                continue
            if i[0] == '-':
                x = {'name'    : i,
                     'id'      : 0,
                     'year'    : '',
                     'maker'   : '',
                    }
                pos += 1
            else:
                x = self.ggdb.search_single(i)
            ll.append(x)
        self.popup_gamelist(ll, pos, 'Recommended', [], [])

    def update_gamelist(self, item):
        """Update gamelist"""

        xbmc.log("UMSA update_gamelist: item = {}".format(item))
        self.getControl(GAME_LIST_LABEL_ID).setLabel(str(item))
        self.getControl(GAME_LIST).reset()

        # without list popup
        if item == M_EMU:
            self.setFocus(self.getControl(SOFTWARE_BUTTON))
            if self.actset['swl_name'] == 'mame':
                self.get_diff_emulator(source=self.actset['source'])
            else:
                self.get_diff_emulator(swl_name=self.actset['swl_name'])
            return
        if item == M_VMS:
            self.choose_media()
            return

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
            results, pos = self.ggdb.get_machines(
                self.actset['swl_name'], self.actset['machine_name']
            )
            gl_label = 'Machines for swl %s (%d)' % (
                self.actset['swl_name'], len(results)
            )
            gl_options = ('name', 'year', 'publisher')

        elif item == M_SOURCE:
            results, pos, result_count = self.ggdb.get_software_for_source(
                self.actset['id'], self.actset['source']
            )
            gl_label = "source: %s (%d)" % (self.actset['source'], result_count)
            gl_options = ('name', 'year', 'publisher')

        elif item == M_LSSAVER:
            results = []
            for i in utilmod.load_lastsaver(SETTINGS_FOLDER):
                y = self.ggdb.get_info_by_set_and_swl(i[0], i[1])
                results.append(
                    {'name': y['name'],
                     'id': str(y['software_id']),
                     'year': y['year'],
                     'maker': y['maker'],
                    }
                )
            gl_label = 'last screensaver session'
            gl_options = ('name', 'year', 'publisher')
            pos = 0

        elif item == M_SERIES:

            results = self.ggdb.get_series(self.last[self.lastptr])
            if results:
                self.popup_gamelist(results, 0, 'Series', [], [])
            #self.getControl(GAME_LIST_TEXT).setText('')
            return

        elif item == M_REC:

            self.show_rec()
            #self.getControl(GAME_LIST_TEXT).setText('')
            return

        elif item == M_SEARCH:
            # only when search is empty
            if not self.searchold:
                keyboard = xbmc.Keyboard('', "Search for", 0)
                keyboard.doModal()
                if keyboard.isConfirmed():
                    self.searchold = keyboard.getText()
                else:
                    self.getControl(LABEL_STATUS).setLabel('user canceled')
                    #self.getControl(GAME_LIST_TEXT).setText('')
                    return

            results, pos, result_count = self.ggdb.get_searchresults(self.searchold)
            gl_label = '%d results for %s' % (result_count, self.searchold)
            gl_options = ('new search',)

        # check how many results
        if len(results) == 0:
            if item == M_SEARCH:
                self.searchold = None
            xbmc.executebuiltin('XBMC.Notification(found nothing,,3000)')
            return
        if len(results) == 1:
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
            fl = ['filter: on', 'filter: off']
        else:
            fl = ['filter: off', 'filter: on']
        # TODO: also set sort method: name, year, maker

        time2 = time.time()
        self.getControl(LABEL_STATUS).setLabel(
            'took {:.0f}ms'.format((time2-time1)*1000)
        )

        # now show gamelist with gathered info from above
        self.popup_gamelist(
            results, pos, gl_label, fl, gl_options
        )
        # build submenu with lists in it
        self.build_sublist_menu()

        time3 = time.time()
        xbmc.log('UMSA update_gamelist: popup in gui: {:.0f}ms'.format((time3-time2)*1000))
        xbmc.log('UMSA update_gamelist: time overall: {:.0f}ms'.format((time3-time1)*1000))

    def popup_gamelist(self, gamelist, pos, label, sort, options):
        """Pop up gamelist

        TODO
         3 pic modes in skin 4:3 3:4 normal like left pic
        """

        xl = []
        for i in gamelist:
            listitem = xbmcgui.ListItem(i['name'], str(i['id']))
            listitem.setInfo('video', {'Writer': i['year'], 'Studio': i['maker']})
            xl.append(listitem)

        self.getControl(GAME_LIST_LABEL).setLabel(label)
        self.getControl(GAME_LIST_OPTIONS).reset()
        self.getControl(GAME_LIST_OPTIONS).addItems(options)
        self.getControl(GAME_LIST_SORT).reset()
        self.getControl(GAME_LIST_SORT).addItems(sort)
        self.getControl(GAME_LIST).reset()
        self.getControl(GAME_LIST).addItems(xl)
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
        c = 0

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
        for e in self.ggdb.get_all_dbentries(cat):

            # label: swl (count), id
            x = xbmcgui.ListItem("{0} ({1})".format(e[1], e[2]), str(e[0]))

            if str(e[0]) in self.filter_lists[cat]:
                active.append(x)
                # check for selected item id, so we can select this in the other list
                if update == 'inactive':
                    if e[0] == filter_content_id:
                        f_select = c
                    c += 1
            else:
                inactive.append(x)
                # check for selected item id, so we can select this in the other list
                if update == 'active':
                    if e[0] == filter_content_id:
                        f_select = c
                    c += 1

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
            self.setFocus(self.getControl(FILTER_CONTENT_LIST_ACTIVE))
        elif update:
            if f_element == len(inactive):
                f_element -= 1
            self.getControl(FILTER_CONTENT_LIST_INACTIVE).selectItem(f_element)
            self.getControl(FILTER_CONTENT_LIST_ACTIVE).selectItem(f_select)
            self.setFocus(self.getControl(FILTER_CONTENT_LIST_INACTIVE))
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

        # set machine pic for swl
        # TODO use art_set table from db
        pic = os.path.join(
            self.cab_path,
            use_set['machine_name']+'.png'
        )
        # change when no swl
        if use_set['machine_name'] == 'mame':
            if use_set['is_machine']:
                pic = os.path.join(
                    self.cab_path,
                    use_set['name']+'.png'
                )
            elif use_set['category'] == 'Electromechanical / Pinball':
                pic = os.path.join(
                    MEDIA_FOLDER,
                    "pinball.png"
                )
            elif use_set['category'] in (
                    'Electromechanical / Reels',
                    'Casino / Reels'
                ):
                pic = os.path.join(
                    MEDIA_FOLDER,
                    "reels.png"
                )
            else:
                pic = os.path.join(
                    MEDIA_FOLDER,
                    "arcade.png"
                )
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

        l = []
        for i in self.info[pos]:

            count += 1
            label = ""
            x = xbmcgui.ListItem()

            # set label
            if i['category'] != 'Not Classified' or i['nplayers'] != '???':
                if i['detail']:
                    label = "{} - {}, {}".format(
                        i['detail'], i['category'], i['nplayers']
                    )
                else:
                    label = "{}, {}".format(
                        i['category'], i['nplayers']
                    )
            elif i['detail']:
                label = '%s' % (i['detail'],)

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

            x.setLabel(label)

            # set other labels in skin over setlist
            x.setProperty(
                # strip detail from gamename
                'Titel', i['gamename'][:len(i['gamename'])
                                       - len(i['detail'])].strip()
            )
            x.setProperty('Year', i['year'])
            x.setProperty('Maker', i['publisher'])
            x.setProperty('Machine', i['machine_label'])

            l.append(x)

        self.getControl(SET_LIST).addItems(l)

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
        x = 0
        l = []
        for i in self.info:

            # check if we are at selected machine
            # to use the correct selected set
            set_no = 0
            if pos_machine == x:
                set_no = pos_set
            x += 1

            # set picture
            y = xbmcgui.ListItem()
            y.setArt({'icon': self.get_machine_pic(use_set=i[set_no])})
            l.append(y)

        self.getControl(SYSTEM_WRAPLIST).addItems(l)
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
                video_rand = random.choice(video)
                video_file = video_rand['id']
                if (not self.Player.isPlayingVideo() or
                        (self.Player.isPlayingVideo() and
                         video_file != self.Player.getPlayingFile())):

                    li = xbmcgui.ListItem(video_rand['label'])
                    self.Player.play(
                        video_file,
                        listitem=li,
                        windowed=True
                    )

        # show artwork and dat info
        self.show_artwork()

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
        """

        imagelist = []

        if set_info['swl_name'] == 'mame':
            newpath = os.path.join(
                self.mame_ini['snapshot_directory'],
                set_info['name']
            )
        else:
            newpath = os.path.join(
                self.mame_ini['snapshot_directory'],
                set_info['swl_name'], set_info['name']
            )
        if os.path.isdir(newpath):
            for ni in os.listdir(newpath):
                image = os.path.join(newpath, ni)
                imagelist.append(
                    self.create_gui_element_from_snap(
                        set_info, image=image
                    )
                )

        return imagelist

    def create_gui_element_from_snap(self, set_info, image, typeof=None):
        """Returns Kodi element for a snapshot"""

        if image:
            x = os.path.dirname(image).split('/')
            if len(x) < 2:
                art = typeof
            else:
                art = x[-2]
                # dir is the same as swl, then set filename as art
                if art == set_info['swl_name']:
                    art = os.path.basename(image)[:-4]
        else:
            art = typeof

        x = xbmcgui.ListItem()
        x.setLabel(
            '%s: %s (%s)' % (
                art, set_info['detail'], set_info['swl_name']
            )
        )
        x.setArt({'icon': image})

        # label to later set
        x.setProperty(
            'detail',
            "{}: {} {}".format(art, set_info['swl_name'], set_info['detail'])
        )

        aspect = check_image_aspect(set_info)
        if aspect == 'Vertical':
            x.setProperty('Vertical', '1')
            x.setProperty('Horizontal', '')
            x.setProperty('NotScaled', '')
        elif aspect == 'Horizontal':
            x.setProperty('Vertical', '')
            x.setProperty('Horizontal', '1')
            x.setProperty('NotScaled', '')
        elif aspect == 'NotScaled':
            x.setProperty('Vertical', '')
            x.setProperty('Horizontal', '')
            x.setProperty('NotScaled', '1')

        return x


    def create_artworklist(self):
        """Create left and right artwork list, side product is play count and time played"""

        self.played = {
            'count'  : 0,
            'played' : 0
        }
        vid = 0
        man = 0

        for m in self.info:
            for s in m:

                s['right_pics'] = []
                s['left_pics'] = []

                # sum up lp
                if s['last_played']:
                    self.played['count'] += s['last_played']['play_count']
                    self.played['played'] += s['last_played']['time_played2']

                # mame snaps
                s['localsnaps'] = self.search_snaps(s)

                # progettosnaps
                if  s['id'] not in self.all_art:
                    continue
                for a in self.all_art[s['id']]:

                    if a[2]:
                        path = self.progetto
                    else:
                        path = self.other_artwork

                    # create complete filename
                    if s['swl_name'] == 'mame':
                        filename = os.path.join(
                            path, a[0], a[0], s['name']+'.'+a[1]
                        )
                    else:
                        filename = os.path.join(
                            path, a[0], s['swl_name'], s['name']+'.'+a[1]
                        )

                    if a[0] in RIGHT_IMAGELIST:
                        x = xbmcgui.ListItem()
                        x.setLabel(
                            '%s: %s (%s)' % (
                                a[0], s['detail'], s['swl_name']
                            )
                        )
                        x.setProperty(
                            'detail',
                            "{}: {} {}".format(a[0], s['swl_name'], s['detail'])
                        )
                        x.setArt({'icon': filename})
                        s['right_pics'].append(x)
                    elif a[0] in LEFT_IMAGELIST:
                        s['left_pics'].append(
                            self.create_gui_element_from_snap(
                                s, filename, a
                            )
                        )
                    elif a[0] == 'videosnaps':
                        s['video'] = filename[:-4]+'.'+a[1]
                        vid += 1
                    elif a[0] == 'manuals':
                        s['manual'] = filename[:-4]+'.'+a[1]
                        man += 1
                    else:
                        xbmc.log(
                            "UMSA create_artworklist: cant identify artwork type = {}".format(a)
                        )

        self.vidman = (vid, man)
        m, s = divmod(self.played['played'], 60)
        h, m = divmod(m, 60)
        self.played['played'] = "%d:%02d" % (h, m)

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

            random.shuffle(rlist)

            # set count/sets
            count = 1
            ll = []
            for i in rlist:
                # get detail from setlist property and set label new
                i.setLabel(
                    "{} ({}/{})".format(
                        i.getProperty('detail'),
                        count,
                        len(rlist)
                    )
                )
                ll.append(i)
                count += 1

            self.getControl(IMAGE_BIG_LIST).reset()
            self.getControl(IMAGE_BIG_LIST).addItems(ll)

        else:
            x = xbmcgui.ListItem()
            x.setProperty('NotEnabled', '1')
            #x.setArt({'icon' : 'blank.png'})
            self.getControl(IMAGE_BIG_LIST).reset()
            self.getControl(IMAGE_BIG_LIST).addItem(x)

        # fill pic left
        if len(llist) > 0:

            random.shuffle(llist)

            # set count/sets
            count = 1
            ll = []
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
                ll.append(i)
                count += 1
            self.getControl(IMAGE_LIST).reset()
            self.getControl(IMAGE_LIST).addItems(ll)

        else:
            x = xbmcgui.ListItem()
            x.setProperty('NotEnabled', '1')
            #x.setArt({'icon' : 'blank.png'})
            self.getControl(IMAGE_LIST).reset()
            self.getControl(IMAGE_LIST).addItem(x)

        # show infos from datfiles only when changed
        if self.oldset == (self.actset['swl_name'], self.actset['name']):
            return

        # check play status
        # TODO check if all, system or set
        # TODO also show series and compilation status
        stattext = ''
        if self.played['count'] > 0:
            if self.actset['last_played']:
                bd = self.actset['last_played']['last_nice']+' ago'
            else:
                bd = "never"
            stattext = "%s, %sh, %sx[CR]" % (
                bd,
                self.played['played'],
                self.played['count']
            )

        ll = []
        count = 0
        if self.actset['id'] in self.all_dat:
            for k in sorted(self.all_dat[self.actset['id']]):
                moretext = ''
                if k in ('Contribute', 'Rec'):
                    continue
                if k == 'History':
                    moretext = stattext

                x = xbmcgui.ListItem()
                x.setLabel(k)
                x.setProperty(
                    'text',
                    moretext + self.all_dat[self.actset['id']][k]
                )
                ll.append(x)
                count += 1

        if len(ll) == 0:
            x = xbmcgui.ListItem()
            x.setLabel("no information...")
            x.setProperty('text', stattext)
            ll.append(x)

        self.getControl(TEXTLIST).reset()
        self.getControl(TEXTLIST).addItems(ll)

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

    def find_roms(self, swl_name, set_name):
        """Find roms in MAME rom paths for different emulators"""

        c = False
        if swl_name == 'mame':
            l = set_name + '.zip'
        else:
            l = swl_name + '/' + set_name + '.zip'

            # this is for chds:
            # get disk name from db over parts
            disk = self.ggdb.get_disk(swl_name, set_name)
            if disk:
                c = os.path.join(swl_name, set_name, disk + '.chd')

        for p in self.mame_ini['rompath']:

            # check for chd
            if c:
                chd = os.path.join(p, c)
                if os.path.isfile(chd):
                    return chd
            # check for zip
            else:
                z = os.path.join(p, l)
                if os.path.isfile(z):
                    return z
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
            pd = xbmcgui.DialogProgress()
            pd.create('Extract CHD...', chd_name)
            params = [self.chdman_exe,
                      'extractcd',
                      '-i', rom_file,
                      '-o', os.path.join(folder, chd_name+file_ext)
                     ]
            self.emurunning = True
            proc = subprocess.Popen(
                params,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                )
            # routine to show progress in kodi
            perc = 0
            while proc.returncode is None:
                pd.update(perc)
                x = proc.stderr.read(34)
                rpos = x[::-1].find('%') # reversed str
                if rpos > -1:
                    pos = len(x)-rpos-1
                    str_perc = x[pos-4:pos]
                    xbmc.log("UMSA extract_rom: chd extract progress = {}".format(str_perc))
                    try:
                        perc = int(float(x[pos-4:pos]))
                    except:
                        pass
                proc.poll()
                xbmc.sleep(100)
            pd.update(100)
            pd.close()
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
            pd = xbmcgui.DialogProgressBG()
            pd.create('Extracting ZIP', 'extracting ZIP')

            os.mkdir(folder)
            zfile = zipfile.ZipFile(rom_file)
            try:
                zfile.extractall(folder)
                zfile.close()
            except:
                xbmc.executebuiltin('XBMC.Notification(error extracting zip,,1500)')
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
                    sf = sorted(zfiles)
                    xbmc.log("UMSA extract_rom: sorted: {}".format(sf))
                    with open(os.path.join(folder, sf[0]), "ab") as file1, open(os.path.join(folder, sf[1]), "rb") as file2:
                        file1.write(file2.read())
                    file1.close()
                    os.remove(os.path.join(folder, sf[1]))
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

            pd.update(100)
            pd.close()

        # dialog when we have still more than one file,
        # like home computer software with many discs
        if len(zfiles) > 1:
            wf = self.dialog.select('Select file: ', zfiles)
            nf = zfiles[wf]
            zfiles[wf] = zfiles[0]
            zfiles[0] = nf

        return folder, zfiles

    def run_emulator(self, diff_emu=None, more_options='', machine='', setname=''):
        """Start the emulator

        Show a pop up during emulator run.

        TODO
         - add setting for os.exec instead of Subprocess (at least needed on MacOSX)
        """

        # local vars
        path = None # working directory
        params = [] # parameter list, first is emulator executable

        # different emulator than mame
        if diff_emu:

            xbmc.log("UMSA run_emulator: diff emu: {}".format(diff_emu))

            # demul -run=[dc,naomi,awave,...] -rom=
            if 'demul' in diff_emu['exe']:
                path = diff_emu['dir']
                params.append(diff_emu['exe'])

                # dreamcast
                if self.actset['swl_name'] == 'dc':
                    # TODO: split chd search from find_roms
                    chd = self.find_roms(self.actset['swl_name'], self.actset['name'])
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
                        listroms = subprocess.check_output(
                            [diff_emu['exe'], '-listroms'],
                        )
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

            else: # standard way with search rom file

                # find file by the name of the set
                rom_file = self.find_roms(
                    self.actset['swl_name'], self.actset['name']
                )
                # also check for file with the name of the parent set
                if not rom_file and self.actset['clone']:
                    rom_file = self.find_roms(
                        self.actset['swl_name'],
                        self.ggdb.get_set_name(self.actset['clone'])
                    )
                if not rom_file:
                    xbmc.executebuiltin('XBMC.Notification(rom not found,,2500)')
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
                # TODO exists script and error in player onexits
                # generate own play class?
                if diff_emu['exe'] == 'kodi':

                    game_item = xbmcgui.ListItem(unzip_file, "0", "", "")
                    if self.Player.isPlaying():
                        self.Player.stop()
                        xbmc.sleep(100)
                    xbmc.sleep(500)
                    self.Player.play(unzip_file, game_item)
                    # TODO wait for play to end here?
                    # or must we exit umsa?
                    return

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
            xbmc.log("UMSA run_emulator: command line = {}".format(cmd_line))
            params.extend([self.mame_exe]+cmd_line)

        # stop playing video or pause audio
        # TODO: maybe also set cmd option -window as video is playing
        if self.playvideo and self.Player.isPlayingVideo():
            self.Player.stop()
        # TODO: Player should set and unset a var with
        # onPlayBackPaused and onPlayBackResumed
        # otherwise paused audio will be started
        elif self.Player.isPlayingAudio():
            self.Player.pause()

        # open a notification with possibility to cancel emulation
        xbmc.log("UMSA run_emulator: parameters = {}".format(params))
        self.emu_dialog.create(
            'emulator run', ' '.join(params)
        )
        # TODO: switch to normal dialog without progress as emulator is slow
        self.emu_dialog.update(0) # TODO: does not remove progress bar
        # set flag for monitor
        self.emurunning = True
        # remember start time
        start = time.time()

        # start emulator:

        # TODO give option for no PIPEs and/or os.exec
        # or is id pd.dialog? test
        if 'demul' in params[0] or self.actset['swl_name'] == 'dc':
            # no mem prob due to excessive std* logs
            proc = subprocess.Popen(params, cwd=path)
        else:
            proc = subprocess.Popen(
                params,
                bufsize=-1,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=path
            )

        # wait for emulator process to stop or cancel press to kill
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
                xbmc.sleep(5000)
                proc.poll()
                if not proc.returncode:
                    xbmc.log("UMSA run_emulator: process does not terminate, sending SIGKILL")
                    proc.kill()
                wait_cancel = False

        xbmc.log("UMSA run_emulator: returncode = {}".format(proc.returncode))
        if 'demul' in params[0] or self.actset['swl_name'] == 'dc':
            out = ''
            err = ''
        else:
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

        # show emulator output if we have an error
        if proc.returncode != 0:

            xbmc.log("UMSA run_emulator: returncode not 0, creating error msg")
            # errors go to TEXTLIST
            x = True

            # check if item already exists
            for i in range(0, self.getControl(TEXTLIST).size()):
                y = self.getControl(TEXTLIST).getListItem(i)
                if y.getLabel() == 'Emulator output':
                    x = False
                    break
            # not: then create
            if x and (out or err):
                y = xbmcgui.ListItem()
                y.setLabel('Emulator output')
                self.getControl(TEXTLIST).addItem(y)

            # when we have output
            if out or err:
                y.setProperty(
                    'text',
                    'cmd: {0}\nerr {1}: {2}\nout: {3}'.format(
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

            # move snapshots from machine to swl dir
            if (self.actset['swl_name'] != 'mame'
                    and not diff_emu
                    and self.actset['swl_name'] != self.actset['machine_name']):

                original_dir = os.path.join(
                    self.mame_ini['snapshot_directory'],
                    self.actset['machine_name'],
                    self.actset['name']
                )

                # if new snaps dir exists, then snaps where taken
                if os.path.isdir(original_dir):

                    swl_dir = os.path.join(
                        self.mame_ini['snapshot_directory'],
                        self.actset['swl_name']
                    )
                    set_dir = os.path.join(
                        self.mame_ini['snapshot_directory'],
                        self.actset['swl_name'],
                        self.actset['name']
                    )

                    # check if needed dirs exists or create
                    if not os.path.isdir(swl_dir):
                        # create swl_name dir
                        os.mkdir(swl_dir)
                    if not os.path.isdir(set_dir):
                        # create set_name dir
                        os.mkdir(set_dir)
                        # mv all files

                    # get all files (machine_name), iterate over
                    for snap_file in os.listdir(original_dir):
                        # while file exists in swl_name
                        new_file = snap_file
                        while os.path.isfile(os.path.join(set_dir, new_file)):
                            #  rename (2 random digits in front)
                            new_file = (
                                str(random.randint(0, 9)) + str(random.randint(0, 9)) + snap_file
                            )
                        # mv file to swl_name
                        os.rename(
                            os.path.join(original_dir, snap_file),
                            os.path.join(set_dir, new_file)
                        )

                    # remove original set and machine dir
                    os.rmdir(original_dir)
                    os.rmdir(
                        os.path.join(
                            self.mame_ini['snapshot_directory'], self.actset['machine_name']
                        )
                    )

            # update local snapshots
            xbmc.sleep(100)
            self.actset['localsnaps'] = self.search_snaps(self.actset)
            self.show_artwork('set')

        # show notification
        xbmc.log("UMSA run_emulator: stopped, monitor = {}".format(self.Monitor.running))
        if self.Monitor.running != 'no':
            self.emu_dialog.update(
                90, "{}\nScreensaver active. Press a button to escape!".format(notif)
            )
        else:
            self.emu_dialog.close()
            if notif:
                xbmc.executebuiltin(
                    'XBMC.Notification(output:,{},3000)'.format(notif)
                )

    def exit(self):
        """exit: close video and db conn"""

        utilmod.save_software_list(
            SETTINGS_FOLDER, 'lastgames.txt', self.last[-10:]
        )

        # stop video if playing
        # if self.Player.isPlayingVideo() and self.playvideo:
        #     self.Player.stop()

        # TODO close all threads?

        # close db
        try:
            self.ggdb.close_db()
        except AttributeError:
            pass

        # close script
        self.close()

def main():
    """ main loop """

    skin = "Default"
    path = ''
    path = xbmcaddon.Addon(id='script.umsa.mame.surfer').getAddonInfo('path')

    # check Kodi skin
    if 'transparency' in xbmc.getSkinDir():
        gui = UMSA("umsa_transparency.xml", path, skin, "720p")
    else:
        gui = UMSA("umsa_estuary.xml", path, skin, "720p")

    gui.doModal()
    del gui

main()
