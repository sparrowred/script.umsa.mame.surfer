# -*- coding: utf-8 -*-
"""UI Module for UMSA Kodi Add-on.

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
from random import choice, randint
from urllib.request import urlopen
import xbmc
import xbmcgui
import xbmcvfs
from xbmcvfs import translatePath
from xbmcaddon import Addon
# own modules
import support
import utilities
from screensaver import Monitor, create_gui_element_from_snap
from database import DBMod, split_gamename
from emulation import Emulation, NONMAME

try:
    from pdf import play_pdf
    KODIPDF = True
except:
    KODIPDF = False
try:
    import youtube_plugin
    KODIYT = True
except ImportError:
    KODIYT = False

# TODO check what we use
__addon__ = sys.modules['__main__'].__addon__
__cwd__ = __addon__.getAddonInfo('path')

PLATFORM = sys.platform

# folder for settings
SETTINGS_FOLDER = translatePath(__addon__.getAddonInfo('profile'))
__resource__ = translatePath(os.path.join(__cwd__, 'resources', 'lib'))

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
ACTION_PLAY_NEXTITEM = (14,112)
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
MUSIC_INFO = 4100
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
RIGHT_IMAGELIST = ('cabinets', 'cpanel', 'flyers', 'marquees', 'media',
                   'cabdevs', 'pcb', 'artpreview', 'covers', 
                   'projectmess_covers')

class UMSA(xbmcgui.WindowXMLDialog):
    """Main UMSA class"""

    def __init__(self, strXMLname, strFallbackPath, strDefaultName, forceFallback):

        # initialize
        self.quit = False
        self.selected_control_id = SOFTWARE_BUTTON # holds the old control id from skin
        self.main_focus = SOFTWARE_BUTTON # remember main select when in gamelist
        self.info = None # contains all sets for actual software
        self.emulation = None

        self.dummy = None # needed to prevent a software jump
                          # when popup is quit by left or right
        self.enter = None # set when a gamelist select happens
        self.oldset = () # needed for show_info to see if set has changed
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
        # set for vgms for software
        self.vgms = None
        # batocera mapping
        self.batomame: dict[str, str] = {}

        self.monitor = None
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

        # no settings = open settings
        if not os.path.exists(SETTINGS_FOLDER):
            __addon__.openSettings()
        self.read_settings()

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
        self.monitor = Monitor(itself=self, __addon__=__addon__)

        # for kodi dialogs
        self.dialog = xbmcgui.Dialog()
        self.emu_dialog = xbmcgui.DialogProgress()

        # bg progress bar
        self.progress_dialog = xbmcgui.DialogProgressBG()

        # no videos when something is already running
        if self.monitor.player.isPlayingVideo():
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

        # initalize Emulation class
        self.emulation = Emulation(
            self.temp_dir, self.mameini, self.mame_dir, self.mame_exe, self.chdman_exe,
            None, None, self.nonmame, terminal=self.terminal, vgmplay_exe=self.vgmplay_exe )

        # load filters
        self.filter_lists = utilities.load_filter(SETTINGS_FOLDER, 'filter_default.txt')
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
            self.ggdb = DBMod(SETTINGS_FOLDER, self.nonmame, self.filter_lists, self.pref_country)
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
        self.last = utilities.load_software_list(
            SETTINGS_FOLDER, 'lastgames.txt'
        )
        # fill with random software if not 10
        while len(self.last) < 10:
            self.last.append(self.ggdb.get_random_id())
        # select software
        self.select_software(self.last[self.lastptr])

        xbmc.log("UMSA onInit: done")
        xbmc.log(f"UMSA PDF Reader import: {KODIPDF}")
        xbmc.log(f"UMSA Youtube import: {KODIYT}")
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
        #if (control_id == TEXTLIST and self.getControl(TEXTLIST).size() < 2):
        #    if self.selected_control_id == SET_LIST:
        #        xbmc.log("UMSA onFocus: from SET to SOFTWARE")
        #        self.setFocus(self.getControl(SOFTWARE_BUTTON))
        #    else:
        #        # TODO will not happen as we go from SOFTWARE TO BOTTOM CPANEL?
        #        xbmc.log("UMSA onFocus: from SOFTWARE to SET")
        #        self.setFocus(self.getControl(SET_LIST))

        # update control_id
        self.enter = None
        self.selected_control_id = control_id

    def onClick(self, control_id):
        """Kodi onClick"""
        xbmc.log("UMSA onClick")

        # screensaver check
        if self.monitor.saver.running != 'no':
            xbmc.log("UMSA onClick: Monitor runs, return")
            if self.monitor.saver.running in ('wall', 'cross', 'slide'):
                self.monitor.saver.running = 'no'
                xbmc.log("UMSA onClick: Monitor in picture mode, turned off")
            return

        # start emulator
        if control_id in (SOFTWARE_BUTTON, SET_LIST, SYSTEM_WRAPLIST):
            # !!! SUPER TODO !!! make this a setting!
            #self.run_emulator({'exe': "kodi", 'name': "Retroplayer"})
            self.run_emulator({'exe': "mame", 'name': "MAME"})
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
                    self.dialog.notification('Search', 'found no results',
                        xbmcgui.NOTIFICATION_ERROR, 5000, False)
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
        if self.monitor.saver.running in ('wall', 'cross', 'slide'):
            self.monitor.saver.running = 'no'
            return
        if self.monitor.saver.running != "no":
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
            self.monitor.player.play(windowed=False)
        # vgm action stuff
        if self.monitor.emulation.playvgm:
            # x = stop
            if action.getId() == 13:
                if self.monitor.emulation.playrandomvgm:
                    self.monitor.emulation.playrandomvgm = False
                self.monitor.emulation.send_vgmaction(b'exit')
                self.getControl(MUSIC_INFO).setVisibleCondition('Player.HasAudio')
                self.getControl(MUSIC_INFO).setLabel(
                    "$INFO[MusicPlayer.Artist] - $INFO[MusicPlayer.Title] (-$INFO[MusicPlayer.TimeRemaining])"
                )
            # media key next/right shoulder button to stop current vgm but not stop playing
            elif action.getId() in ACTION_PLAY_NEXTITEM:
                self.monitor.emulation.send_vgmaction(b'exit')
            # + for volume up
            elif action.getId() == 88:
                self.monitor.emulation.send_vgmaction(b'volume_up')
            # - for volume down
            elif action.getId() == 89:
                self.monitor.emulation.send_vgmaction(b'volume_down')

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
            if self.monitor.player.isPlayingVideo() and not self.already_playing:
                self.monitor.player.stop()
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
                    if self.scan_thread and not self.scan_thread.is_alive():
                        self.scan_thread = None
                    if self.scan_thread:
                        self.dialog.notification('Scan Status', 'scan already running...',
                            xbmcgui.NOTIFICATION_ERROR, 4000)
                        return

                    ret = self.dialog.select(
                        'What should we do?',
                        ('Update database', 'Scan dat files', 'Scan artwork', 'Scan eXoDOS', 'Scan GB64')
                    )
                    if ret == 0:
                        self.update('db')
                    elif ret == 1:
                        self.scan_thread = Thread(target=self.update, args=('dat',))
                        self.scan_thread.start()
                    elif ret == 2:
                        self.scan_thread = Thread(target=self.update, args=('art',))
                        self.scan_thread.start()
                    elif ret == 3:
                        self.scan_thread = Thread(target=self.update, args=('exo',))
                        self.scan_thread.start()
                    elif ret == 4:
                        self.scan_thread = Thread(target=self.update, args=('gb64',))
                        self.scan_thread.start()

                elif menu_item == M_SSAVER:
                    self.setFocus(self.getControl(self.main_focus))
                    ret = self.dialog.select(
                        'Which show would please you?', (
                            'I wanna see random videos',
                            'Make me the artwork crossover',
                            'Just slide one after another',
                            'Gimme da wall, now',
                            'Astonish me with a MARP replay',
                            'Play random Video Game Music'
                        )
                    )
                    if ret == 0:
                        self.monitor.play_saver('videos')
                    elif ret == 1 or ret == 2:
                        art_types = self.ggdb.get_art_types()
                        ret2 = self.dialog.multiselect(
                            "What do you want to see?", art_types
                        )
                        if ret2:
                            selected_art_types = []
                            for i in ret2:
                                selected_art_types.append(art_types[i])
                            if ret == 1:
                                self.monitor.play_saver('cross', selected_art_types)
                            else:
                                self.monitor.play_saver('slide', selected_art_types)
                    elif ret == 3:
                        # TODO create wall 1st if empty?
                        self.monitor.play_saver('wall')
                    elif ret == 4:
                        self.marp_replayer()
                    elif ret == 5:
                        self.getControl(MUSIC_INFO).setLabel('Starting random VGM...')
                        self.getControl(MUSIC_INFO).setVisibleCondition('True')
                        self.monitor.emulation.play_random_vgm(
                            self.ggdb, self.getControl(MUSIC_INFO), SETTINGS_FOLDER, xbmc.sleep)
                elif menu_item == M_ASETTINGS:
                    self.setFocus(self.getControl(self.main_focus))
                    __addon__.openSettings()
                    self.read_settings()
                else:
                    self.setFocus(self.getControl(GAME_LIST_LABEL))
                    self.update_gamelist(menu_item)

            elif action.getId() in ACTION_CONTEXT:

                menu_item = int(self.getControl(MAIN_MENU).getSelectedItem().getLabel2())
                # listmode menu
                if menu_item in (M_ALL, M_SOURCE, M_SWL, M_SERIES):
                    # TODO empty gamelist popup
                    self.update_gamelist(menu_item)
                    self.setFocus(self.getControl(LISTMODE_MENU))
                # switch filter
                elif menu_item == M_FILTER:
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
                    yt_list = support.youtube_search(
                        split_gamename(self.actset['gamename'])[0],
                        self.actset['machine_name'])
                    playurl = "plugin://plugin.video.youtube/play/?video_id={}".format(
                        choice(yt_list)[0])
                    self.monitor.player.play(playurl, windowed=True)
                    # close menu
                    self.setFocus(self.getControl(self.main_focus))
                # start random screensaver
                elif menu_item == M_SSAVER:
                    rand_saver = randint(1, 3)
                    # close menu
                    self.setFocus(self.getControl(self.main_focus))
                    if rand_saver == 1:
                        self.monitor.play_saver('videos')
                    elif rand_saver == 2:
                        self.marp_replayer(random=True)
                    else:
                        self.monitor.play_saver('cross', ['snap'])

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
                    {'icon': self.monitor.saver.get_machine_pic(self.actset)}
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
            all_marps = support.marp_search(version=rand_version)
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
        #inp_file = support.marp_download(
        #    dl_file, os.path.join(self.mame_dir, self.emulation.mame_ini['input_directory']))
        #opt = ["-playback", inp_file, "-exit_after_playback"]
        self.run_emulator({
            'name': "MARP Replay", 'exe': "marp", 'set_name': set_name, 'marp_dl': dl_file})

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
        # start with mame exe
        elif select_label == "Start with M.A.M.E.":
            self.run_emulator({'name': "MAME", 'exe': "mame"})
        # start kodi retroplayer
        elif select_label == "Start with Kodi Retroplayer":
            self.run_emulator({'name': "Retroplayer", 'exe': "kodi"})
        # start exodos shell
        elif select_label == "Start eXoDOS Shell launcher":
            self.run_emulator({'name': "eXoDOS", 'exe': "exodos"})
        elif select_label == "Start eXoDOS Alternate Shell launcher":
            self.run_emulator({'name': "exoDOS Alternate", 'exe': "exodos_alt"})
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
            # video
            if list_id[-3:] == 'mp4':
                list_item = xbmcgui.ListItem(select_label)
                self.monitor.player.play(list_id, listitem=list_item, windowed=True)
            # pdf viewer
            elif list_id[-3:] == 'pdf':
                self.exit()
                play_pdf(list_id, compress=True, is_image_plugin=False)
                #Popen([self.pdfviewer, list_id])
            # marp
            elif list_id[-3:] == 'zip':
                self.marp_replayer(dl_file=list_id, set_name=what)
            # vgm
            elif what == "vgm":
                select = []
                vgm_zipfile = self.emulation.find_roms('vgmplay', list_id)
                xbmc.log(f"UMSA: get vgmfile - {vgm_zipfile}")
                vgm_tracklist = zipfile.ZipFile(vgm_zipfile).namelist()
                for vgm in vgm_tracklist:
                    select.append(vgm)
                if select:
                    which_track = self.dialog.select('Select VGM track:', select)
                    if which_track > -1:
                        self.monitor.emulation.play_vgm(
                            f'{list_id}:{which_track+1:03d}', sleep=xbmc.sleep)
            # youtube
            elif what == "yt":
                self.monitor.player.play(
                    "plugin://plugin.video.youtube/play/?video_id={}".format(list_id),
                    windowed=True)
            # search marp, youtube
            # TODO show online search in gamelist during search!!!
            elif select_label[:9] == "- Youtube":
                # TODO check api requests
                yt_search_url = "plugin://plugin.video.youtube/kodion/search/query/?category_label=REPLACE&incognito=True&q=REPLACE&type=video"
                yt_search_str = f"{split_gamename(self.actset['gamename'])[0]} {self.actset['machine_name']}".replace(' ','%20')
                self.exit()
                xbmc.executebuiltin(f"ActivateWindow(Videos,{yt_search_url.replace('REPLACE',yt_search_str)},return)")

                #self.ggdb.save_further_media(self.actset['id'], youtube=dumps(
                #    support.youtube_search(
                #        split_gamename(self.actset['gamename'])[0], self.actset['machine_name'])))
                #self.update_gamelist(M_MEDIA)
            elif select_label[:8] == "- Replay":
                # TODO check complete game info for a mame swl
                if self.actset['swl_name'] == "mame":
                    self.ggdb.save_further_media(
                        self.actset['id'], marp=dumps(
                            support.marp_search(short_name=self.actset['name'])))
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
                self.filter_lists = utilities.load_filter(
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
                utilities.save_filter(
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
        - create batocera mapping for caching roms
        """

        # TODO: put all into settings dict
        # read in settings
        self.mame_exe = __addon__.getSetting('mame')
        self.mameini = __addon__.getSetting('mameini')
        self.mame_dir = __addon__.getSetting('mamedir')
        self.pref_country = __addon__.getSetting('pref_country')
        self.temp_dir = __addon__.getSetting('temp_path')
        self.progetto = __addon__.getSetting('progetto')
        self.other_artwork = __addon__.getSetting('otherart')
        self.aratio = __addon__.getSetting('aspectratio')
        self.datdir = __addon__.getSetting('datdir')
        self.pdfviewer = __addon__.getSetting('pdfviewer')
        self.chdman_exe = __addon__.getSetting('chdman')
        self.terminal = __addon__.getSetting('terminal')
        self.vgmplay_exe = __addon__.getSetting('vgmplay')
        es_dict = {'Normal': 0, 'Watch': 1, 'Fallback': 2}
        self.emulation_start = es_dict[__addon__.getSetting('emulation_start')]
        self.nonmame = {
            'exodos': __addon__.getSetting('exodos'),
            'gb64': __addon__.getSetting('gb64'),
            'whdload': __addon__.getSetting('whdload'),
        }

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

        # batocera mapping
        with open(os.path.join(__resource__, 'batocera-dir-struct-map.txt')) as f:
            for content in f:
                content = content.rstrip()
                if content[0] != '#':
                    bato, fmame = content.split(':')
                    for i in fmame.split(','):
                        if i and i not in self.batomame.keys():
                            self.batomame[i] = bato

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
            self.dialog.notification('Configure Emulator', 'no executable selected',
                xbmcgui.NOTIFICATION_ERROR, 3000, False)
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

        self.update('dat')
        self.update('art')

    def update(self, what):
        """Update UMSA database, artwork or support files"""

        # TODO move to support? could remove import urllib
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
                    self.nonmame,
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
            self.ggdb.scan_status = True
            while self.ggdb.scan_status:
            #TODO while scan_dat_thread.is_alive:
                xbmc.sleep(1000)
                self.progress_dialog.update(
                    self.ggdb.scan_perc,
                    'Scan support files',
                    'scanning {}'.format(self.ggdb.scan_what),
                )
            self.progress_dialog.update(100, 'Scan support files', 'saving')
            self.ggdb.add_dat_to_db(SETTINGS_FOLDER)
            self.progress_dialog.close()

        # update exodos database
        elif what == 'exo':
            self.setFocus(self.getControl(self.main_focus))
            self.progress_dialog.create('Scan eXoDOS files', 'warm up')

            # create thread
            scan_dat_thread = Thread(
                target=self.ggdb.scan_exodos_to_db,
                args=('', SETTINGS_FOLDER)
                )
            scan_dat_thread.start()
            self.ggdb.scan_perc = 0
            self.ggdb.scan_what = ''
            self.ggdb.scan_status = True
            #TODO while scan_dat_thread.is_alive:
            while self.ggdb.scan_status:
                xbmc.sleep(1000)
                self.progress_dialog.update(
                    self.ggdb.scan_perc,
                    'Scan eXoDOS files',
                    'scanning {}'.format(self.ggdb.scan_what),
                )
            self.progress_dialog.update(100, 'Scan eXoDOS files', 'saving')
            self.ggdb.add_dat_to_db(SETTINGS_FOLDER)
            self.ggdb.add_art_to_db(SETTINGS_FOLDER)
            self.progress_dialog.close()

        # update gb64 database
        elif what == 'gb64':
            self.setFocus(self.getControl(self.main_focus))
            self.progress_dialog.create('Scan GameBase64 files', 'warm up')

            # create thread
            scan_dat_thread = Thread(
                target=self.ggdb.scan_gb64_to_db,
                args=('', SETTINGS_FOLDER)
                )
            scan_dat_thread.start()
            self.ggdb.scan_perc = 0
            self.ggdb.scan_what = ''
            self.ggdb.scan_status = True
            #TODO while scan_dat_thread.is_alive:
            while self.ggdb.scan_status:
                xbmc.sleep(1000)
                self.progress_dialog.update(
                    self.ggdb.scan_perc,
                    'Scan GameBase64 files',
                    'scanning {}'.format(self.ggdb.scan_what),
                )
            self.progress_dialog.update(100, 'Scan GameBase64 files', 'saving')
            self.ggdb.add_dat_to_db(SETTINGS_FOLDER)
            self.ggdb.add_art_to_db(SETTINGS_FOLDER)
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
            self.ggdb.scan_status = True
            # TODO while scan_art_thread.is_alive():
            while self.ggdb.scan_status:
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
        """Dialog to choose media for playing."""

        # labels in list
        media_list = []
        video = [{'name':'- Videos -', 'id':'0', 'year':'', 'maker':''}]
        manual = [{'name':'- Manuals -', 'id':'0', 'year':'', 'maker':''}]
        vgm = [{'name':'- Music -', 'id':'0', 'year':'', 'maker':''}]

        xbmc.log("UMSA: choose media - %s" % (self.vgms), xbmc.LOGDEBUG)
        if self.vgms:
            for vgmitem in self.vgms:
                vgm.append({'name':vgmitem, 'id':"vgm::"+vgmitem, 'year':'', 'maker':''})
        xbmc.log("UMSA: choose media - vgmlist %s" % (vgm), xbmc.LOGDEBUG)
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
        if len(vgm) > 1:
            media_list.extend(vgm)
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
            if self.actset['swl_name'] == 'exodos':
                results.append({'id': 1,
                            'name': "Start eXoDOS Shell launcher",
                            'year': ">>>", 'maker': "<<<"})
                results.append({'id': 1,
                            'name': "Start eXoDOS Alternate Shell launcher",
                            'year': ">>>", 'maker': "<<<"})
            results.append({'id': 1,
                            'name': "Start with M.A.M.E.",
                            'year': ">>>", 'maker': "<<<"})
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
            for i in utilities.load_lastsaver(SETTINGS_FOLDER):
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
            self.dialog.notification('Search', 'found nothing...',
                xbmcgui.NOTIFICATION_ERROR, 3000, False)
            return

        # one software result = select
        if len(results) == 1 and item not in (M_MACHINE, M_ALLEMUS):
            if item == M_SEARCH:
                self.searchold = None
            self.dialog.notification('Search', 'only one hit...',
                xbmcgui.NOTIFICATION_INFO, 2000, False)
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
            gamename, gamedetail = split_gamename(i['gamename'])

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
        if self.playvideo and self.monitor.player.isPlayingVideo() and not self.already_playing:
            self.monitor.player.stop()
            #xbmc.sleep(100)
        elif self.monitor.emulation.playintrovgm:
            self.monitor.emulation.playintrovgm = False
            self.monitor.emulation.send_vgmaction(b'exit')

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
                "UMSA select_software: ERROR: software id = {}".format(software_id))
            self.dialog.notification('Select Software', f'id-{software_id} feels funny?!?',
                xbmcgui.NOTIFICATION_ERROR, 4000)
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
            list_item.setArt({'icon': self.monitor.saver.get_machine_pic(use_set=i[set_no])})
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
        # TODO create vgm list from new table
        # create vgm list from history.xml
        self.vgms = None
        for dat_set in self.all_dat.values():
            if 'others' in dat_set and 'vgmplay' in dat_set['others']:
                xbmc.log("UMSA: VGMs found!", xbmc.LOGINFO)
                if not self.vgms:
                    self.vgms = set()
                for splitentry in dat_set['others'].split(','):
                    if 'vgmplay' in splitentry:
                        self.vgms.add(splitentry.split('=')[1])
                xbmc.log("UMSA: %s" % (self.vgms), xbmc.LOGDEBUG)

        # play video
        if (self.playvideo
            and not self.monitor.player.isPlayingAudio()
            and not self.monitor.emulation.playvgm
            ):
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
                if (not self.monitor.player.isPlayingVideo() or
                        (self.monitor.player.isPlayingVideo() and
                         video_file != self.monitor.player.getPlayingFile())):

                    list_item = xbmcgui.ListItem(video_rand['label'])
                    self.monitor.player.play(
                        video_file,
                        listitem=list_item,
                        windowed=True
                    )
            else:
                # play random vgm
                if self.vgms:
                    play_vgm = choice(tuple(self.vgms))
                    xbmc.log(f'UMSA: play intro vgm {play_vgm}')
                    self.dialog.notification('VGM Intro', f'Playing {play_vgm}',
                        xbmcgui.NOTIFICATION_INFO, 3000, False)
                    self.monitor.emulation.play_vgm(
                        play_vgm, 10, xbmc.sleep, intro=True)

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
                self.emulation.mame_ini['snapshot_directory'],
                set_info['name']
            )
        else:
            snap_dir = os.path.join(
                self.emulation.mame_ini['snapshot_directory'],
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
                    elif (set_info['swl_name'] == 'exodos') or (set_info['swl_name'][:5] == 'gb64_'):
                        filename = art['filename']
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

    def run_emulator(self, emu_infos):
        """Prepare commandline options for emulator and start emulator."""

        # stop playing mame vgm
        if self.monitor.emulation.playvgm:
            xbmc.log("UMSA runemu stop VGM", xbmc.LOGINFO)
            self.monitor.emulation.send_vgmaction(b'exit')
            if self.monitor.emulation.playrandomvgm:
                self.monitor.emulation.playrandomvgm = None
            xbmc.sleep(500)

        # TODO: switch to normal dialog without progress as emulator is slow?
        self.emu_dialog.create("Emulator: {}".format(emu_infos['name']), 'warm up...')
        # set flag for monitor
        self.monitor.saver.running = 'emu'
        self.emulation.emurun = {
            'emulation_start': self.emulation_start,
            'working_dir': self.mame_dir,
            'swl_name': self.actset['swl_name'],
            'set_name': self.actset['name'],
            'description': self.actset['gamename'],
            'publisher': self.actset['publisher'],
            'set_clone': self.ggdb.get_set_name(self.actset['clone']),
            'disks': self.ggdb.get_disks(self.actset['swl_name'], self.actset['name'])
        }
        # check if more than 1 disk, then selection
        if self.emulation.emurun['disks'] and len(self.emulation.emurun['disks']) > 1:
            select = []
            for i in self.emulation.emurun['disks']:
                # TODO remove when export is fixed
                xbmc.log("-----{}-----".format(dict(i)), xbmc.LOGDEBUG)
                if i['disk']:
                    select.append(i['disk'])
            if select:
                which_disk = self.dialog.select('Select CHD:', select)
                if which_disk > -1:
                    this_disk = self.emulation.emurun['disks'][which_disk]
                    self.emulation.emurun['disks'][which_disk] = self.emulation.emurun['disks'][0]
                    self.emulation.emurun['disks'][0] = this_disk
        # Kodi Retroplayer
        #
        # Copy needed files over to Batocera directory structure
        # and try to start in Kodi Retroplayer
        #
        # - mame
        # build cache path (check if roms source is in batocera map for naomi etc dir)
        # check if file already exists > start!
        # search zip file in rom dirs
        # check for chd: if yes, copy over to cache
        # copy zip file over to cache path > start!
        #
        # - swl (implemented)
        # build cache path (if no hit for batocera, then write to mame and start with mame)
        # check if folder already exists > get file and start!
        # search zip file in rom dirs
        # check for chd: if yes, copy over to cache
        # extract zip file over to cache path > get file and start!
        #
        # - other emulators
        # build cache path from batocera > error if no hit
        # check if file (c64: folder) already exists > start!
        # search file in special rom dir
        # copy over to cache / c64: extract to folder
        # start
        #
        if emu_infos['exe'] == 'kodi':
            self.emu_dialog.update(10, 'searching roms...')
            playfile = None

            # set cache folder
            if self.actset['swl_name'] == 'mame':
                if self.actset['source'] in self.batomame:
                    self.emulation.emurun['folder'] = os.path.join(
                        self.temp_dir, self.batomame[self.actset['source']] )
                else:
                    self.emulation.emurun['folder'] = os.path.join(
                        self.temp_dir, 'mame', 'roms')
            elif self.actset['swl_name'] in NONMAME:
                if self.actset['swl_name']+'.xml' in self.batomame:
                    self.emulation.emurun['folder'] = os.path.join( 
                        self.temp_dir, self.batomame[self.actset['swl_name']+'.xml'])
                else:
                    self.dialog.notification(heading='error',
                        message=f"{self.actset['swl_name']}: not found in Batocera map",
                        icon=xbmcgui.NOTIFICATION_ERROR, time=7500)
                    self.monitor.saver.running = 'no'
                    self.emu_dialog.close()
                    return
                if 'gb64' in self.actset['swl_name']:
                   self.emulation.emurun['folder'] = os.path.join(
                       self.emulation.emurun['folder'],
                       os.path.basename(self.actset['name']) )
            elif self.actset['swl_name']+'.xml' in self.batomame:
                self.emulation.emurun['folder'] = os.path.join(
                    self.temp_dir, self.batomame[self.actset['swl_name']+'.xml'],
                    f"{self.actset['swl_name']}_{self.actset['name']}")
            else:
                self.emulation.emurun['folder'] = os.path.join(
                    self.temp_dir, 'mame', 'roms', self.actset['swl_name'])
            xbmc.log(f"cache folder: {self.emulation.emurun['folder']}", xbmc.LOGDEBUG)

            # check if rom already in cache folder and set playfile
            xbmc.log("check if rom in cache", xbmc.LOGDEBUG)
            if self.actset['swl_name'] in NONMAME:
                if os.path.exists(self.emulation.emurun['folder']):
                    if 'gb64' in self.actset['swl_name']:
                        dfiles = os.listdir(self.emulation.emurun['folder'])
                        for dfile in dfiles:
                            if dfile != 'VERSION.NFO':
                                playfile = os.path.join(
                                    self.emulation.emurun['folder'], dfile)
                                break
                    else:
                        playfile = os.path.join(
                            self.emulation.emurun['folder'],self.actset['name']+'.zip')
            elif self.actset['swl_name'] == 'mame':
                # TODO we always assume zip, not 7z, rar or what else does mame support?
                playfile = os.path.join(
                    self.emulation.emurun['folder'], self.actset['name']+'.zip')
            elif self.actset['swl_name']+'.xml' in self.batomame:
                if os.path.exists(self.emulation.emurun['folder']):
                    dfiles = os.listdir(self.emulation.emurun['folder'])
                    if dfiles:
                        playfile = os.path.join(
                            self.emulation.emurun['folder'], dfiles[0])
            else:
                self.dialog.notification(heading='error',
                                         message='check rom in cache deadend?',
                                         icon=xbmcgui.NOTIFICATION_ERROR, time=10000)
            xbmc.log(f"cache build rom file: {playfile}", xbmc.LOGDEBUG)

            # we need to search for the rom in known rom paths if not in cache
            check_file = None
            if playfile:
                check_file = os.path.isfile(playfile)
            if not check_file:
                xbmc.log(f"searching {self.actset['swl_name']} roms:", xbmc.LOGDEBUG)
                if self.actset['swl_name'] in NONMAME:
                    self.emulation.find_nonmame_roms()
                else:
                    # TODO: for mame use parent!
                    self.emulation.find_roms()
                xbmc.log(f"zips: {self.emulation.emurun['zips']}", xbmc.LOGDEBUG)
                xbmc.log(f"chds: {self.emulation.emurun['chds']}", xbmc.LOGDEBUG)
                xbmc.log(f"disks: {self.emulation.emurun['disks']}", xbmc.LOGDEBUG)
                # TODO check result of find_roms here
                if self.actset['swl_name'] == 'mame':
                    if self.emulation.emurun['zips']:
                        playfile = os.path.join(
                            self.emulation.emurun['folder'],
                            self.actset['name']+'.zip')
                        xbmc.log("copy rom file", xbmc.LOGDEBUG)
                        if xbmcvfs.copy(
                            self.emulation.emurun['zips'][0], playfile):
                            xbmc.log("copy successful", xbmc.LOGINFO)
                        else:
                            xbmc.log("copy error!!!", xbmc.LOGWARNING)
                    # TODO also copy chds = self.emulation.emurun['disks']
                elif self.actset['swl_name'] in NONMAME:
                    if 'gb64' in self.actset['swl_name']:
                        self.emulation.extract_rom()
                        if 'extract_files' in self.emulation.emurun:
                            for pfile in self.emulation.emurun['extract_files']:
                                if pfile != 'VERSION.NFO':
                                    playfile = os.path.join(
                                        self.emulation.emurun['folder'],
                                        self.emulation.emurun['extract_files'][0])
                    else:
                        if self.emulation.emurun['zips']:
                            playfile = os.path.join(
                                self.emulation.emurun['folder'],
                                #self.actset['name']+'.zip'
                                os.path.basename(self.emulation.emurun['zips'][0])
                            )
                            xbmcvfs.copy(
                                self.emulation.emurun['zips'][0], playfile)
                elif self.emulation.emurun['zips']:
                    self.emulation.extract_rom()
                    if 'extract_files' in self.emulation.emurun:
                        playfile = os.path.join(
                            self.emulation.emurun['folder'],
                            self.emulation.emurun['extract_files'][0])
                elif self.emulation.emurun['chds']:
                    # TODO loop and copy all chds
                    playfile = os.path.join(
                        self.emulation.emurun['folder'],
                        self.emulation.emurun['disks'][0]['disk']+'.chd')
                    xbmcvfs.copy(self.emulation.emurun['chds'][0],playfile)
                else:
                    self.monitor.saver.running = 'no'
                    self.emu_dialog.close()
                    self.dialog.notification(
                        heading='error', message='seems we can not find the rom?',
                        icon=xbmcgui.NOTIFICATION_ERROR, time=7500)
                    return

            # stop if nothing found to play
            if not playfile:
                self.monitor.saver.running = 'no'
                self.emu_dialog.close()
                self.dialog.notification(heading='error', message='rom not found',
                    icon=xbmcgui.NOTIFICATION_ERROR, time=7500)
                return
            xbmc.log(f"playfile = {playfile}", xbmc.LOGDEBUG)

            # start retroplayer
            xbmc.log("UMSA actset: {}".format(self.actset), xbmc.LOGDEBUG)
            game_item = xbmcgui.ListItem(playfile)
            game_item.setInfo(type='game', infoLabels={ 'title': self.actset['gamename']})
            game_tag = game_item.getGameInfoTag()
            game_tag.setTitle(     self.actset['name'] )
            game_tag.setPlatform(  self.actset['machine_label'] )
            game_tag.setGenres( [  self.actset['category'], ] )
            game_tag.setPublisher( self.actset['publisher'] )
            game_tag.setDeveloper( self.actset['publisher'] ) # get dev from game entry
            game_tag.setOverview(  'set info from history' ) # TODO
            if self.actset['year'].isdigit():
                game_tag.setYear(  int(self.actset['year']) )
            else:
                game_tag.setYear(0)
            # TODO depends on swl, add-id is name? check log or addon
            # Sets the add-on ID of the game client executing the game.
            #game_tag.setGameClient()
            if self.monitor.player.isPlaying():
                self.monitor.player.stop()
                xbmc.sleep(500)
            self.monitor.player.play(playfile, game_item)
            self.monitor.saver.running = 'no'
            self.emu_dialog.close()
            # TODO need to exit or found out how to deinit window and init after play session
            # but when is play over? !!! check self.monitor.player.isPlaying()
            # as longs is its playing the game runs!
            self.exit()

            # TODO update status, but how to measure playtime?
            # start thread, wait for kodi signal that retroplayer stops?
            return

        # exodos
        if 'exodos' in emu_infos['exe']:
            alt = "shell"
            if 'alt' in emu_infos['exe']:
                alt = "alt"
            self.emu_dialog.update(10, 'searching shellscript...')
            self.emulation.find_nonmame_roms(alt)
            self.emulation.emurun['args'] = []
            self.emulation.emurun['emulation_start'] = 2
        # marp
        elif emu_infos['exe'] == "marp":
            self.emulation.emurun['emu_exe'] = self.mame_exe
            self.emu_dialog.update(20, 'download replay...')
            # TODO error handling, percentage?
            inp_file = support.marp_download(
                emu_infos['marp_dl'],
                os.path.join(self.mame_dir, self.emulation.mame_ini['input_directory']))
            self.emulation.emurun['args'] = [
                emu_infos['set_name'], "-playback", inp_file, "-exit_after_playback"]
        # mame
        elif emu_infos['exe'] == "mame":
            self.emulation.emurun['emu_exe'] = self.mame_exe
            if self.actset['swl_name'] == 'mame':
                self.emulation.emurun['args'] = self.actset['name']
            # check for Gamebase64 files
            elif self.actset['swl_name'].startswith('gb64_'):
                filename = self.nonmame['gb64']+'Games/'+self.actset['name']+'.zip'
                self.emulation.emurun['args'] = [
                    'c64p', f"-{self.actset['swl_name'][-4:]}", filename]
            # start a swl item
            else:
                self.emu_dialog.update(20, 'create swl options...')
                # get cmd options
                self.emulation.emurun['args'] = self.ggdb.get_cmd_line_options(
                    self.actset['id'], self.actset['name'],
                    self.actset['machine_name'], self.actset['swl_name'])
        # other emulator
        else:
            xbmc.log("UMSA run_emulator: diff emu: {}".format(dict(emu_infos)))
            error = self.emulation.other_emulator(
                # TODO add exodos longname from 1st line of dat?
                emu_infos, sleep=xbmc.sleep, dialog=self.emu_dialog)
            if not error:
                self.monitor.saver.running = 'no'
                self.emu_dialog.close()
                self.dialog.notification(f'{emu_infos["name"]} error', f'rom not found',
                    xbmcgui.NOTIFICATION_ERROR, 3500)
            # dialog when more than 1 extracted file in zip
            # TODO don't overwrite emurun[args] when emu FS-UAE !!!
            if ('extract_files' in self.emulation.emurun and
                    len(self.emulation.emurun['extract_files']) > 1):
                which_file = self.dialog.select(
                    'Select file: ', self.emulation.emurun['extract_files'])
                if which_file > -1:
                    self.emulation.emurun['args'] = os.path.join(
                        self.emulation.emurun['folder'],
                        self.emulation.emurun['extract_files'][which_file]
                    )

        # stop playing video or pause audio
        if self.playvideo and self.monitor.player.isPlayingVideo():
            self.monitor.player.stop()
        # TODO: Player should set and unset a var with
        # onPlayBackPaused and onPlayBackResumed
        # otherwise paused audio will be started
        elif self.monitor.player.isPlayingAudio():
            self.monitor.player.pause()

        xbmc.log("UMSA run_emulator: parameters = {}".format(self.emulation.emurun))
        #xbmc.log("UMSA run_emulator: parameters = {}".format(self.emulation.emurun['args']))
        self.emu_dialog.update(50, 'emulator running...')
        # todo: how to exit fullscreen?
        #xbmc.executebuiltin("Action(Fullscreen)")
        #xbmc.executebuiltin("Minimize")
        xbmc.sleep(100)
        self.emulation.run()

        start = time.time()
        out, err = '', ''
        # wait for emulator process to stop or cancel press to kill
        wait_cancel = True
        while wait_cancel:
            xbmc.sleep(1000)
            if self.emulation.process:
                self.emulation.process.poll()
                if self.emulation.process.returncode is not None:
                    wait_cancel = False
            else:
                wait_cancel = False
            if self.emu_dialog.iscanceled():
                self.emu_dialog.update(60, 'emulator stopping...')
                wait_cancel = False
                xbmc.log("UMSA run_emulator: cancel pressed, sending SIGTERM")
                self.emulation.terminate()
                xbmc.sleep(3000)
                if self.emulation.process and self.emulation.process.poll() is None:
                    xbmc.log(
                        "UMSA run_emulator: process does not terminate, sending SIGKILL")
                    self.emulation.kill()
        if self.emulation.emurun['emulation_start'] == 1:
            out = self.emulation.process.stdout.read().decode('utf-8', errors='ignore')
            err = self.emulation.process.stderr.read().decode('utf-8', errors='ignore')

        #xbmc.executebuiltin("Maximize")
        #xbmc.executebuiltin("Action(Fullscreen)")
        end = time.time()
        self.emu_dialog.update(75, 'emulator stopped...')
        notif = "Played: {}".format(self.ggdb.make_time_nice(end-start))
        self.monitor.saver.running = 'no'
        # TODO check if works when video runs
        # unpause audio again
        if self.monitor.player.isPlayingAudio():
            self.monitor.player.pause()

        # pretty output from mame
        if "Average speed:" in out:
            # find last percentage from "Average speed: 100.00% (1 seconds)"
            # reverse string, search 'speed:' and '% (' reversed and reverse again
            percent = out[::-1][out[::-1].find('( %')+2:out[::-1].find(' :deeps')][::-1]
            if percent != "100.00%":
                notif += " - {}".format(percent)

        # show emulator output if we have an error as tab in TEXTLIST
        if self.emulation.process and self.emulation.process.returncode != 0:
            no_emu_out = True
            # check if item already exists
            for i in range(0, self.getControl(TEXTLIST).size()):
                if self.getControl(TEXTLIST).getListItem(i).getLabel() == 'Emulator output':
                    no_emu_out = False
                    emu_out_item = self.getControl(TEXTLIST).getListItem(i)
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
                        ' '.join(self.emulation.emurun['args']),
                        self.emulation.process.returncode, err, out))
                self.getControl(TEXTLIST).selectItem(self.getControl(TEXTLIST).size()-1)
                notif += "\nerror: see bottom left"

        # write time, date to status db whe not marp
        if emu_infos['exe'] != "marp":
            if int(end-start) > 60:
                self.ggdb.write_status_after_play(self.actset['id'], int(end-start))
            # update local snapshots when mame
            if emu_infos['exe'] == "mame":
                xbmc.sleep(100)
                self.actset['localsnaps'] = self.search_snaps(self.actset)
                self.show_artwork('set')

        # show notification
        xbmc.log("UMSA run_emulator: stopped, monitor = {}".format(self.monitor.saver.running))
        if self.monitor.saver.running != 'no':
            self.emu_dialog.update(
                90, "{}\nScreensaver active. Press a button to escape!".format(notif))
        else:
            self.emu_dialog.close()
            self.dialog.notification(f'{emu_infos["name"]} stopped', f'{notif}',
                xbmcgui.NOTIFICATION_INFO, 3000, False)

    def exit(self):
        """Exit add-on

        Save last ten, stop video, close database
        TODO: check for threads and close?
        """

        utilities.save_software_list(SETTINGS_FOLDER, 'lastgames.txt', self.last[-10:])
        if self.monitor.emulation.playvgm:
            self.monitor.emulation.playrandomvgm = None
            self.monitor.emulation.send_vgmaction(b'exit')
        # TODO stop video if playing
        # if self.monitor.player.isPlayingVideo() and self.playvideo:
        #     self.monitor.player.stop()
        # close db
        try:
            self.ggdb.close_db()
        except AttributeError:
            pass
        # close script
        self.close()

def main():
    """Start Kodi UI."""

    utilities.set_log(lambda *args, level='debug': xbmc.log(' '.join(map(str, args)),
        {'debug': xbmc.LOGDEBUG, 'info': xbmc.LOGINFO, 'warning': xbmc.LOGWARNING}
        .get(level, xbmc.LOGDEBUG)))
    path = Addon(id='script.umsa.mame.surfer').getAddonInfo('path')
    if 'transparency' in xbmc.getSkinDir():
        gui = UMSA("umsa_transparency.xml", path, "default", "720p")
    elif 'rapier' in xbmc.getSkinDir():
        gui = UMSA("umsa_rapier.xml", path, "default", "720p")
    else:
        gui = UMSA("umsa_estuary.xml", path, "default", "720p")
    gui.doModal()
    del gui

main()
