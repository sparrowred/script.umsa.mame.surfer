"""UI Module for UMSA Kodi Add-on.

This module is the Kodi adapter of the frontend: it owns the ``UMSA`` window
class, the Kodi event dispatch and the public names of the add-on. The
workflows themselves live in the ``umsa_gui`` package, one module per topic;
they receive the ``UMSA`` instance as an argument so that the Kodi dialog
stays the single owner of the skin controls.
"""

import os
import sys
from dataclasses import dataclass
from random import choice, randint
from threading import Thread

import xbmc
import xbmcgui
from emulator_launcher import LaunchCtx, launch_emulator
from retroplayer_cache import run_retroplayer
from settings_adapter import load_all_settings
from umsa_core import FILTER_CATEGORIES, set_log
from umsa_core.database import DBMod, split_gamename
from umsa_core.emulation import Emulation
from umsa_core.support import youtube_search
from umsa_core_kodi import (
    VGM_SENDER,
    clear_vgm_info,
    get_core_data_paths,
    get_core_settings,
    get_core_vgmplay_script,
    is_emulator_running,
    parse_software_open_method,
    parse_vgm_action_method,
    set_emulator_running,
)
from umsa_gui import (
    artwork_presenter,
    emulator_setup,
    filter_ui,
    gamelist_actions,
    media_list,
    menu,
    scan_orchestrator,
    screensaver_vgm,
    software_selector,
    startup_import,
)
from umsa_gui import (
    gamelist as gamelist_workflows,
)
from umsa_gui.artwork_presenter import create_gui_element_from_snap
from umsa_gui.constants import (
    ACTION_CANCEL_DIALOG,
    ACTION_CONTEXT,
    ACTION_ENTER,
    ACTION_INFO,
    ACTION_MOVEMENT,
    ACTION_MOVEMENT_DOWN,
    ACTION_MOVEMENT_LEFT,
    ACTION_MOVEMENT_RIGHT,
    ACTION_MOVEMENT_UP,
    ACTION_PLAY_NEXTITEM,
    ACTION_PLAYFULLSCREEN,
    ACTION_SOUND_VOLUME,
    COMPILATION_LABEL,
    EMULATOR_RUNNING_PROPERTY,
    FILTER_CATEGORY_KEYS,
    FILTER_CATEGORY_LIST,
    FILTER_CONTENT_LIST_ACTIVE,
    FILTER_CONTENT_LIST_INACTIVE,
    FILTER_LABEL,
    FILTER_LABEL2,
    FILTER_LIST_BG,
    FILTER_OPTIONS,
    GAME_LIST,
    GAME_LIST_BG,
    GAME_LIST_IMAGE,
    GAME_LIST_LABEL,
    GAME_LIST_LABEL_ID,
    GAME_LIST_OPTIONS,
    GAME_LIST_SORT,
    GAME_LIST_TEXT,
    GROUP_FILTER,
    GROUP_GAME_LIST,
    IMAGE_BIG_LIST,
    IMAGE_LIST,
    IMAGE_RIGHT,
    LABEL_STATUS,
    LEFT_IMAGE_HORI,
    LEFT_IMAGE_VERT,
    LISTMODE_MENU,
    M_ALL,
    M_ALLEMUS,
    M_ASETTINGS,
    M_CAT,
    M_EXIT,
    M_FILTER,
    M_LSSAVER,
    M_MACHINE,
    M_MAKER,
    M_MEDIA,
    M_PLAYERS,
    M_PLAYSTAT,
    M_REC,
    M_SEARCH,
    M_SEARCH_NEW,
    M_SERIES,
    M_SOURCE,
    M_SSAVER,
    M_SWL,
    M_UPD,
    M_YEAR,
    MACHINE_PLUS,
    MACHINE_SEP1,
    MACHINE_SEP2,
    MACHINE_SEP3,
    MAIN_MENU,
    MEDIA_LABEL,
    MUSIC_INFO,
    SERIES_LABEL,
    SET_LIST,
    SHADOW_DAT,
    SHADOW_MACHINE,
    SHADOW_SET,
    SOFTWARE_BUTTON,
    SUBMENU_ORDER,
    SYSTEM_BORDER,
    SYSTEM_WRAPLIST,
    TEXTLIST,
    VIDEO_LABEL,
    WAIT_GUI,
    WAIT_PLAYER,
)
from umsa_gui.filter_ui import empty_filter_lists
from umsa_gui.gamelist import GamelistCtx
from umsa_gui.optional_plugins import KODIPDF, KODIYT, play_pdf
from umsa_gui.paths import ADDON, ADDON_PATH, RESOURCE_LIB

__addon__ = ADDON
__cwd__ = ADDON_PATH
__resource__ = RESOURCE_LIB

PLATFORM = sys.platform

# shared application data
CORE_DATA_PATHS = get_core_data_paths(create=False)
SETTINGS_FOLDER = CORE_DATA_PATHS.filters_dir

# Public API of this module. These names existed before the workflows were
# split into the ``umsa_gui`` package and are re-exported unchanged.
__all__ = [
    "ACTION_CANCEL_DIALOG",
    "ACTION_CONTEXT",
    "ACTION_ENTER",
    "ACTION_INFO",
    "ACTION_MOVEMENT",
    "ACTION_MOVEMENT_DOWN",
    "ACTION_MOVEMENT_LEFT",
    "ACTION_MOVEMENT_RIGHT",
    "ACTION_MOVEMENT_UP",
    "ACTION_PLAYFULLSCREEN",
    "ACTION_PLAY_NEXTITEM",
    "ACTION_SOUND_VOLUME",
    "COMPILATION_LABEL",
    "CORE_DATA_PATHS",
    "EMULATOR_RUNNING_PROPERTY",
    "FILTER_CATEGORY_KEYS",
    "FILTER_CATEGORY_LIST",
    "FILTER_CONTENT_LIST_ACTIVE",
    "FILTER_CONTENT_LIST_INACTIVE",
    "FILTER_LABEL",
    "FILTER_LABEL2",
    "FILTER_LIST_BG",
    "FILTER_OPTIONS",
    "GAME_LIST",
    "GAME_LIST_BG",
    "GAME_LIST_IMAGE",
    "GAME_LIST_LABEL",
    "GAME_LIST_LABEL_ID",
    "GAME_LIST_OPTIONS",
    "GAME_LIST_SORT",
    "GAME_LIST_TEXT",
    "GROUP_FILTER",
    "GROUP_GAME_LIST",
    "IMAGE_BIG_LIST",
    "IMAGE_LIST",
    "IMAGE_RIGHT",
    "KODIPDF",
    "KODIYT",
    "LABEL_STATUS",
    "LEFT_IMAGE_HORI",
    "LEFT_IMAGE_VERT",
    "LISTMODE_MENU",
    "MACHINE_PLUS",
    "MACHINE_SEP1",
    "MACHINE_SEP2",
    "MACHINE_SEP3",
    "MAIN_MENU",
    "MEDIA_LABEL",
    "MUSIC_INFO",
    "M_ALL",
    "M_ALLEMUS",
    "M_ASETTINGS",
    "M_CAT",
    "M_EXIT",
    "M_FILTER",
    "M_LSSAVER",
    "M_MACHINE",
    "M_MAKER",
    "M_MEDIA",
    "M_PLAYERS",
    "M_PLAYSTAT",
    "M_REC",
    "M_SEARCH",
    "M_SEARCH_NEW",
    "M_SERIES",
    "M_SOURCE",
    "M_SSAVER",
    "M_SWL",
    "M_UPD",
    "M_YEAR",
    "PLATFORM",
    "SERIES_LABEL",
    "SETTINGS_FOLDER",
    "SET_LIST",
    "SHADOW_DAT",
    "SHADOW_MACHINE",
    "SHADOW_SET",
    "SOFTWARE_BUTTON",
    "SUBMENU_ORDER",
    "SYSTEM_BORDER",
    "SYSTEM_WRAPLIST",
    "TEXTLIST",
    "UMSA",
    "VIDEO_LABEL",
    "WAIT_GUI",
    "WAIT_PLAYER",
    "GamelistCtx",
    "RetroplayerCtx",
    "VgmCommandMonitor",
    "create_gui_element_from_snap",
    "empty_filter_lists",
    "main",
    "play_pdf",
]


class VgmCommandMonitor(xbmc.Monitor):
    """Receive control commands sent by the screensaver add-on.

    The VGM process and the software selection belong to this script, so
    the screensaver (a separate add-on) asks for volume/next/stop and for
    opening a displayed software over Kodi notifications.
    """

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def onNotification(self, sender, method, data):
        if sender != VGM_SENDER:
            return
        software_id = parse_software_open_method(method)
        if software_id is not None:
            self.owner.open_software(software_id)
            return
        action = parse_vgm_action_method(method)
        if action in ('volume_up', 'volume_down', 'next', 'stop'):
            self.owner._handle_vgm_action(action)


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
        self.lastptr = 0
        # old search
        self.searchold = None
        # diff emu toggle
        self.diff_emu = False
        # set for vgms for software
        self.vgms = None
        # batocera mapping
        self.batomame: dict[str, str] = {}

        self.player = None
        self.dialog = None
        self.emu_dialog = None
        self.progress_dialog = None
        self.already_playing = None
        self.playvideo = None
        self.filter_lists = None
        self.act_filter = None
        self.ggdb = None
        self.settings_folder = SETTINGS_FOLDER
        self.actset = None
        self.all_art = None
        self.all_dat = None
        self.played = None
        self.vidman = None
        self.emulation_start = 0
        self.initial_software_id = None

        # Clear stale emulator running state from any previous crashed instance
        self.set_emulator_running(False)

        # no settings = open settings
        if not os.path.exists(SETTINGS_FOLDER):
            __addon__.openSettings()
        self.read_settings()

        xbmc.log("UMSA gui: __init__ done")

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

        self.player = xbmc.Player()

        # for kodi dialogs
        self.dialog = xbmcgui.Dialog()
        self.emu_dialog = xbmcgui.DialogProgress()

        # bg progress bar
        self.progress_dialog = xbmcgui.DialogProgressBG()

        # no videos when something is already running
        if self.player.isPlayingVideo():
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
            get_core_vgmplay_script(), self._show_vgm_info, self.nonmame, terminal=self.terminal,
            vgmplay_exe=self.vgmplay_exe, vgm_stopped_callback=self._hide_vgm_info)

        # receive VGM control commands from the screensaver add-on
        if not hasattr(self, 'vgm_monitor'):
            self.vgm_monitor = VgmCommandMonitor(self)

        # filters are loaded from status.db after the database is open and the
        # one-time legacy import has run (the migration runs at DBMod open)
        self.filter_lists = empty_filter_lists()
        self.act_filter = 'default'

        # fill filter lists
        list_items = []
        for i in FILTER_CATEGORIES:
            list_items.append(xbmcgui.ListItem(i))
        self.getControl(FILTER_CATEGORY_LIST).addItems(list_items)
        self.getControl(FILTER_OPTIONS).addItems(('all', 'none', 'invert'))

        # database connection
        if CORE_DATA_PATHS.umsa_db.is_file():
            self.ggdb = DBMod(SETTINGS_FOLDER, self.nonmame, self.filter_lists, self.pref_country)
        else:
            # DB download in foreground, dat+art scan in background
            self.update('db')
            self.scan_thread = Thread(target=self.update, args=('dat',))
            self.scan_thread.start()

        # one-time legacy import + load persisted filter selections and history
        self.run_startup_import()
        self.filter_lists = self.ggdb.load_filter_selections(self.act_filter)
        self.ggdb.define_filter(self.filter_lists)
        self.getControl(FILTER_LABEL2).setLabel(f'Filter: {self.act_filter}')

        # load last internal software list
        self.last = self.ggdb.load_lastgames()
        # fill with random software if not 10
        while len(self.last) < 10:
            self.last.append(self.ggdb.get_random_id())
        # initialize pointer to the newest entry
        self.lastptr = len(self.last) - 1
        # select software
        if self.initial_software_id is None:
            self.select_software(self.last[self.lastptr])
        else:
            self._remember_and_select(self.initial_software_id)

        xbmc.log("UMSA gui: onInit: done")
        xbmc.log(f"UMSA gui: PDF Reader import: {KODIPDF}")
        xbmc.log(f"UMSA gui: Youtube import: {KODIYT}")

        if self.quit:
            self.close()
            return

    # sequence: onFocus, onClick, onAction

    def onFocus(self, control_id):
        """Kodi onFocus"""

        xbmc.log(f"UMSA gui: onFocus: old: {self.selected_control_id}")
        xbmc.log(f"UMSA gui: onFocus: new: {control_id}")

        # TODO: get rid off dummy with a list instead of the software button?
        # list item label would then be actual software button input from skin
        self.dummy = None

        # close popups
        if control_id in (SOFTWARE_BUTTON, SYSTEM_WRAPLIST, SET_LIST, TEXTLIST):

            if self.selected_control_id in (
                    GAME_LIST, GAME_LIST_OPTIONS, GAME_LIST_SORT, LISTMODE_MENU
                ):
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

        # update control_id
        self.enter = None
        self.selected_control_id = control_id

    def onClick(self, control_id):
        """Kodi onClick"""
        xbmc.log("UMSA gui: onClick")

        # screensaver check
        screensaver_mode = self.get_screensaver_mode()
        if screensaver_mode != 'no':
            xbmc.log("UMSA gui: onClick: Monitor runs, return")
            if screensaver_mode in ('wall', 'cross', 'slide'):
                self.stop_screensaver()
                xbmc.log("UMSA gui: onClick: Monitor in picture mode, turned off")
            return

        # start emulator
        if control_id in (SOFTWARE_BUTTON, SET_LIST, SYSTEM_WRAPLIST):
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
                    self._remember_and_select(gamelist[0]['id'])
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
                self.ggdb.set_order(item)
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
                    self.filter_lists[filter_category_name].append(str(i['id']))
            elif item == 'invert':
                templist = []
                for i in self.ggdb.get_all_dbentries(filter_category_name):
                    if str(i['id']) not in self.filter_lists[filter_category_name]:
                        templist.append(str(i['id']))
                self.filter_lists[filter_category_name] = templist
            self.set_filter_content(filter_category_name)

            # set focus to active, when empty deactive
            if len(self.filter_lists[filter_category_name]) == 0:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_INACTIVE))
            else:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_ACTIVE))

    def onAction(self, action):
        """Kodi onAction"""

        xbmc.log(f"UMSA gui: onAction: id = {action.getId()}")

        if action.getId() == 0:
            return

        # check if monitor runs
        screensaver_mode = self.get_screensaver_mode()
        if screensaver_mode in ('wall', 'cross', 'slide'):
            self.stop_screensaver()
            return
        if screensaver_mode != "no":
            xbmc.log("UMSA gui: onAction: Monitor running ? doing nothing")

        # needed for left/right exit from popup
        if self.dummy:
            xbmc.log("UMSA gui: onAction: dummy action after exit from popup")
            self.dummy = None
            if (action.getId() in ACTION_MOVEMENT_LEFT
                    or action.getId() in ACTION_MOVEMENT_RIGHT):
                return

        # TODO check if fullscreen works
        if action.getId() == 18:
            self.player.play(windowed=False)

        # vgm action stuff
        if self.emulation.playvgm:
            # x = stop
            if action.getId() == 13:
                if self.emulation.playrandomvgm:
                    self.emulation.playrandomvgm = False
                self.emulation.send_vgmaction(b'exit')
                self.getControl(MUSIC_INFO).setVisibleCondition('Player.HasAudio')
                self.getControl(MUSIC_INFO).setLabel(
                    "$INFO[MusicPlayer.Artist] - $INFO[MusicPlayer.Title] (-$INFO[MusicPlayer.TimeRemaining])"
                )
            # media key next/right shoulder button to stop current vgm but not stop playing
            elif action.getId() in ACTION_PLAY_NEXTITEM:
                self.emulation.send_vgmaction(b'exit')
            # + for volume up
            elif action.getId() == 88:
                self.emulation.send_vgmaction(b'volume_up')
            # - for volume down
            elif action.getId() == 89:
                self.emulation.send_vgmaction(b'volume_down')

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
            if self.player.isPlayingVideo() and not self.already_playing:
                self.player.stop()
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

            if action.getId() in ACTION_MOVEMENT_LEFT:
                self.setFocus(self.getControl(self.main_focus))
            elif action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_ENTER:

                # get menu item
                menu_item = int(self.getControl(MAIN_MENU).getSelectedItem().getLabel2())
                xbmc.log(f"UMSA gui: onAction: menu = {menu_item}")

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
                        self.start_screensaver('videos')
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
                                self.start_screensaver('cross', selected_art_types)
                            else:
                                self.start_screensaver('slide', selected_art_types)
                    elif ret == 3:
                        self.start_screensaver('wall')
                    elif ret == 4:
                        self.marp_replayer()
                    elif ret == 5:
                        self._show_vgm_info('Starting random VGM...')
                        self.emulation.play_random_vgm(
                            self.ggdb, None, SETTINGS_FOLDER, xbmc.sleep)
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
                    self.update_gamelist(menu_item)
                    self.setFocus(self.getControl(LISTMODE_MENU))
                # switch filter
                elif menu_item == M_FILTER:
                    if self.ggdb.use_filter:
                        self.ggdb.set_filter_enabled(False)
                        self.getControl(MAIN_MENU).getSelectedItem().setLabel("Filter (off)")
                    else:
                        self.ggdb.set_filter_enabled(True)
                        self.getControl(MAIN_MENU).getSelectedItem().setLabel(
                            f"Filter ({self.act_filter})")
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
                # directly play a youtube video
                elif menu_item == M_MEDIA:
                    yt_list = youtube_search(
                        split_gamename(self.actset['gamename'])[0],
                        self.actset['machine_name'])
                    playurl = f"plugin://plugin.video.youtube/play/?video_id={choice(yt_list)[0]}"
                    self.player.play(playurl, windowed=True)
                    # close menu
                    self.setFocus(self.getControl(self.main_focus))
                # start random screensaver
                elif menu_item == M_SSAVER:
                    rand_saver = randint(1, 3)
                    # close menu
                    self.setFocus(self.getControl(self.main_focus))
                    if rand_saver == 1:
                        self.start_screensaver('videos')
                    elif rand_saver == 2:
                        self.marp_replayer(random=True)
                    else:
                        self.start_screensaver('cross', ['snap'])

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
            xbmc.log("UMSA gui: onAction: MACHINE_LIST")
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
            xbmc.log("UMSA gui: onAction: FILTER_CATEGORY_LIST")

            if action.getId() in ACTION_ENTER:
                self.filter_category()

        # ACTION FILTER_CONTENT_LIST_ACTIVE
        elif self.selected_control_id == FILTER_CONTENT_LIST_ACTIVE:
            xbmc.log("UMSA gui: onAction: FILTER_CONTENT_LIST_ACTIVE")

            if action.getId() in ACTION_ENTER:
                self.filter_content('active')

        # ACTION FILTER_CONTENT_LIST_INACTIVE
        elif self.selected_control_id == FILTER_CONTENT_LIST_INACTIVE:
            xbmc.log("UMSA gui: onAction: FILTER_CONTENT_LIST_INACTIVE")

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
                # update SYSTEM_WRAPLIST image when different MAME driver is selected
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

    # --- startup, history and settings ---------------------------------

    def run_startup_import(self):
        """Run the one-time legacy import and report its outcome."""
        return startup_import.run_startup_import(self)

    def _save_lastgames(self):
        """Persist the current in-memory history without trimming it."""
        return startup_import.save_lastgames(self)

    def _remember_and_select(self, software_id):
        """Insert a display event, select it, and persist only on success."""
        return startup_import.remember_and_select(self, software_id)

    def read_settings(self):
        """Read settings for UMSA from Kodi and initialize."""

        # read in shared settings from the Core module
        core_settings = get_core_settings()
        # read in settings specific to this add-on
        gui_settings, emu_settings = load_all_settings(
            core_settings, __addon__, __resource__, PLATFORM
        )

        self.mame_exe = core_settings.mame
        self.mameini = core_settings.mameini
        self.mame_dir = core_settings.mamedir
        self.progettosnaps = core_settings.progettosnaps
        self.own_artwork = core_settings.own_artwork
        self.aratio = core_settings.aspectratio
        self.datdir = core_settings.datdir
        self.vgmplay_exe = core_settings.vgmplay
        self.musicinfo = core_settings.musicinfo_enabled

        self.pref_country = gui_settings.pref_country
        self.temp_dir = gui_settings.temp_dir
        self.pdfviewer = gui_settings.pdfviewer
        self.chdman_exe = gui_settings.chdman_exe
        self.terminal = gui_settings.terminal
        self.emulation_start = gui_settings.emulation_start
        self.playvideo = gui_settings.playvideo

        self.nonmame = emu_settings.nonmame
        self.cab_path = emu_settings.cab_path
        self.batomame = emu_settings.batomame

    def artwork_source_roots(self):
        """Map artwork sources to their configured root directories."""

        return {
            "progettosnaps": self.progettosnaps,
            "own_artwork": self.own_artwork,
            "exodos": self.nonmame.get("exodos", ""),
            "gb64": self.nonmame.get("gb64", ""),
        }

    # --- screensaver and VGM -------------------------------------------

    def set_emulator_running(self, running: bool):
        """Set/clear the property indicating an external emulator is running.

        This property is shared with screensaver.umsa.mame.surfer; both add-ons
        must use the identical property name. Also recomputes global
        screensaver inhibition state.
        """
        set_emulator_running(running)

    def is_emulator_running(self):
        """Return True if an external emulator is currently running."""
        return is_emulator_running()

    def get_screensaver_mode(self):
        """Return the active standalone screensaver mode, if any."""
        return screensaver_vgm.get_screensaver_mode(self)

    def start_screensaver(self, mode, art_types=None):
        """Launch the standalone screensaver with a validated request token."""
        return screensaver_vgm.start_screensaver(self, mode, art_types)

    def stop_screensaver(self):
        """Close an active standalone screensaver dialog."""
        return screensaver_vgm.stop_screensaver(self)

    def _show_vgm_info(self, message):
        """Publish VGM info to the shared window and to this window's label."""
        return screensaver_vgm.show_vgm_info(self, message)

    def _hide_vgm_info(self):
        """Clear the shared VGM info and restore this window's music label."""
        return screensaver_vgm.hide_vgm_info(self)

    def _handle_vgm_action(self, action):
        """Run a VGM control action requested by another add-on."""
        return screensaver_vgm.handle_vgm_action(self, action)

    def open_software(self, software_id):
        """Select software requested by the screensaver, keeping history."""
        return software_selector.open_software(self, software_id)

    # --- menu, gamelist and media --------------------------------------

    def build_sublist_menu(self, select):
        """Build the sublist menu for the listmode."""
        return menu.build_sublist_menu(self, select)

    def build_main_menu(self, select=None):
        """Shows the context menu."""
        return menu.build_main_menu(self, select)

    def gamelist_move(self):
        """Move in gamelist"""
        return gamelist_workflows.gamelist_move(self)

    def gamelist_switch_filter(self):
        """Switch filter in gamelist"""
        return gamelist_workflows.gamelist_switch_filter(self)

    def gamelist_click(self):
        """Reacts on click in gamelist"""
        return gamelist_actions.gamelist_click(self)

    def gamelist_context(self):
        """Reacts on context in gamelist"""
        return gamelist_actions.gamelist_context(self)

    def show_fulllist(self, what, label):
        """Show full list of maker, cat, year..."""
        return gamelist_workflows.show_fulllist(self, what, label)

    def update_gamelist(self, item):
        """Update gamelist"""
        return gamelist_workflows.update_gamelist(
            self, item, CORE_DATA_PATHS.lastsaver_file)

    def popup_gamelist(self, gamelist, label, pos=0, sort=None, options=None):
        """Pop up gamelist."""
        return gamelist_workflows.popup_gamelist(
            self, gamelist, label, pos, sort, options)

    def choose_media(self):
        """Dialog to choose media for playing."""
        return media_list.choose_media(self)

    def show_rec(self):
        """Shows recommended section from mameinfo.dat in gamelist"""
        return media_list.show_rec(self)

    # --- filter ---------------------------------------------------------

    def filter_category(self):
        """Open filter category, load and save filters"""
        return filter_ui.filter_category(self)

    def filter_content(self, which_content):
        """Move an entry between the active and the inactive filter list."""
        return filter_ui.filter_content(self, which_content)

    def set_filter_content(self, cat, update=None):
        """Set filter content"""
        return filter_ui.set_filter_content(self, cat, update)

    def close_filterlist(self, no_update=None):
        """Close filter list window"""
        return filter_ui.close_filterlist(self, no_update)

    # --- software and artwork -------------------------------------------

    def select_software(self, software_id):
        """Get all machines and sets for a software and fill skin."""
        return software_selector.select_software(self, software_id)

    def fill_set_list(self, pos):
        """Fill the set list"""
        return software_selector.fill_set_list(self, pos)

    def machine_move(self):
        """Update set list and artwork, set new actual set after machine move"""
        return software_selector.machine_move(self)

    def software_move(self, direction):
        """Get next random software or move one back in history"""
        return software_selector.software_move(self, direction)

    def get_machine_pic(self, use_set):
        """Return the machine artwork path for the current game set."""
        return artwork_presenter.get_machine_pic(self, use_set)

    def search_snaps(self, set_info):
        """Search files in MAME snapshot directory"""
        return artwork_presenter.search_snaps(self, set_info)

    def create_artworklist(self):
        """Create left and right artwork list, side product is play count and time played"""
        return artwork_presenter.create_artworklist(self)

    def show_artwork(self, howmuch='all'):
        """Show artwork"""
        return artwork_presenter.show_artwork(self, howmuch)

    # --- emulators ------------------------------------------------------

    def get_diff_emulator(self):
        """Get different emulator"""
        return emulator_setup.get_diff_emulator(self)

    def configure_emulator(self, emu_info=None, reconfigure=False):
        """Dialog to configure emulators."""
        return emulator_setup.configure_emulator(self, emu_info, reconfigure)

    def marp_replayer(self, dl_file=None, set_name=None, random=None):
        """Start MAME with a MARP Replay input file"""
        return emulator_setup.marp_replayer(self, dl_file, set_name, random)

    def _add_or_update_emu_output(self, out, err, exit_code, cmd_args):
        """Show the emulator output in the text list of the skin."""
        return emulator_setup.add_or_update_emu_output(
            self, out, err, exit_code, cmd_args)

    def _notify_final_launch(self, notif_text, emu_name, mode):
        """Tell the user that the emulator stopped."""
        return emulator_setup.notify_final_launch(self, notif_text, emu_name, mode)

    def run_emulator(self, emu_infos):
        """Prepare commandline options for emulator and start emulator."""

        if emu_infos.get('exe') == 'kodi':
            rp_ctx = RetroplayerCtx(
                actset=self.actset,
                batomame=self.batomame,
                temp_dir=self.temp_dir,
                emulation=self.emulation,
                emu_dialog=self.emu_dialog,
                dialog=self.dialog,
                player=self.player,
            )
            rp_ctx.stop_screensaver = self.stop_screensaver
            rp_ctx.exit = self.exit
            run_retroplayer(rp_ctx)
            return

        ctx = LaunchCtx(
            actset=self.actset,
            emu_infos=emu_infos,
            emulation=self.emulation,
            ggdb=self.ggdb,
            emu_dialog=self.emu_dialog,
            dialog=self.dialog,
            player=self.player,
            mame_dir=self.mame_dir,
            emulation_start=self.emulation_start,
            playvideo=self.playvideo,
            stop_screensaver=self.stop_screensaver,
            get_screensaver_mode=self.get_screensaver_mode,
            set_emulator_running=self.set_emulator_running,
            search_snaps=self.search_snaps,
            show_artwork=self.show_artwork,
            add_or_update_emu_output=self._add_or_update_emu_output,
            notify_final=self._notify_final_launch,
            sleep=xbmc.sleep,
        )
        launch_emulator(ctx)

    # --- scans ----------------------------------------------------------

    def update(self, what):
        """Update UMSA database, artwork or support files"""
        return scan_orchestrator.update(self, what, CORE_DATA_PATHS)

    def exit(self):
        """Exit add-on

        Save last ten, stop video, close database
        """

        self._save_lastgames()
        if self.emulation.playvgm:
            self.emulation.playrandomvgm = None
            self.emulation.send_vgmaction(b'exit')
            try:
                clear_vgm_info()
            except Exception:
                pass
        try:
            if hasattr(self, 'ggdb') and self.ggdb and hasattr(self.ggdb, 'scan_status'):
                self.ggdb.scan_status = False
                xbmc.log('UMSA gui: exit: requested scan stop', xbmc.LOGDEBUG)
        except Exception:
            pass
        try:
            if hasattr(self, 'scan_thread') and self.scan_thread and self.scan_thread.is_alive():
                try:
                    self.scan_thread.join(timeout=5)
                except Exception:
                    pass
        except Exception:
            # TODO output error to log
            pass
        try:
            self.ggdb.close()
        except Exception:
            pass
        self.close()


def main():
    """Start Kodi UI."""

    set_log(lambda *args, level='debug': xbmc.log(' '.join(map(str, args)),
        {'debug': xbmc.LOGDEBUG, 'info': xbmc.LOGINFO, 'warning': xbmc.LOGWARNING,
         'error': xbmc.LOGERROR}
        .get(level, xbmc.LOGDEBUG)))
    path = __cwd__
    gui = UMSA("umsa_estuary.xml", path, "default", "1080i")
    if len(sys.argv) > 2 and sys.argv[1] == "select_software":
        try:
            gui.initial_software_id = int(sys.argv[2])
        except ValueError:
            xbmc.log("UMSA gui: invalid software selection argument", xbmc.LOGERROR)
    gui.doModal()
    del gui


@dataclass
class RetroplayerCtx:
    actset: object = None
    batomame: object = None
    temp_dir: object = None
    emulation: object = None
    emu_dialog: object = None
    dialog: object = None
    player: object = None

    def stop_screensaver(self):
        pass

    def exit(self):
        pass
