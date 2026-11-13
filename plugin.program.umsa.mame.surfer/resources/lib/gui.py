#!/usr/bin/env python3
"""UI Module for UMSA Kodi Add-on.

This module is the Kodi adapter of the frontend: it owns the ``UMSA`` window
class, the Kodi event dispatch and the public names of the add-on. The
workflows themselves live in the ``umsa_gui`` package, one module per topic;
they receive the ``UMSA`` instance as an argument so that the Kodi dialog
stays the single owner of the skin controls.
"""

import functools
import os
import sys
from dataclasses import dataclass
from random import choice, randint
from threading import Lock, Thread

import xbmc
import xbmcgui
from emulator_launcher import LaunchCtx, launch_emulator
from retroplayer_cache import run_retroplayer
from settings_adapter import load_all_settings
from umsa_core import set_log
from umsa_core.database import DBMod
from umsa_core.default_filter import DEFAULT_FILTER_NAME
from umsa_core.emulation import Emulation
from umsa_core.game_labels import split_gamename
from umsa_core.rom_cache import CacheLayout
from umsa_core.support import youtube_search
from umsa_core_kodi import (
    VGM_SENDER,
    clear_stale_screensaver_state,
    clear_vgm_info,
    get_core_data_paths,
    get_core_settings,
    get_core_vgmplay_script,
    is_emulator_running,
    is_frontend_close_method,
    make_abort_wait,
    open_core_settings,
    parse_software_open_method,
    parse_vgm_action_method,
    set_emulator_running,
    set_frontend_running,
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
from umsa_gui import strings as S
from umsa_gui.action_backlog import ActionBacklog
from umsa_gui.artwork_presenter import create_gui_element_from_snap
from umsa_gui.constants import (
    ACTION_BACKLOG_THRESHOLD,
    ACTION_CANCEL_DIALOG,
    ACTION_CHOOSE_EMULATOR,
    ACTION_CONTEXT,
    ACTION_ENTER,
    ACTION_INFO,
    ACTION_LIST_SCROLL,
    ACTION_MOVEMENT,
    ACTION_MOVEMENT_DOWN,
    ACTION_MOVEMENT_LEFT,
    ACTION_MOVEMENT_RIGHT,
    ACTION_MOVEMENT_UP,
    ACTION_NOOP,
    ACTION_PLAY_NEXTITEM,
    ACTION_PLAYFULLSCREEN,
    ACTION_SOUND_VOLUME,
    ACTION_START_EXODOS,
    ACTION_START_EXODOS_ALT,
    ACTION_START_KODI,
    ACTION_START_MAME,
    COMPILATION_LABEL,
    EMULATOR_RUNNING_PROPERTY,
    ENTRY_ACTION,
    ENTRY_SEARCH,
    FILTER_CATEGORY_KEYS,
    FILTER_CATEGORY_LIST,
    FILTER_CONTENT_LIST_ACTIVE,
    FILTER_CONTENT_LIST_INACTIVE,
    FILTER_KEY_LOAD,
    FILTER_KEY_SAVE,
    FILTER_LABEL,
    FILTER_LABEL2,
    FILTER_LIST_BG,
    FILTER_OPTION_ALL,
    FILTER_OPTION_INVERT,
    FILTER_OPTION_NONE,
    FILTER_OPTIONS,
    GAME_LIST,
    GAME_LIST_BG,
    GAME_LIST_IMAGE,
    GAME_LIST_LABEL,
    GAME_LIST_LABEL_ID,
    GAME_LIST_OPTIONS,
    GAME_LIST_SORT,
    GAME_LIST_TEXT,
    GAMELIST_SETTLE_DELAY,
    GROUP_FILTER,
    GROUP_GAME_LIST,
    IMAGE_BIG_LIST,
    IMAGE_LIST,
    IMAGE_RIGHT,
    KIND_EMULATORS,
    KIND_MACHINES,
    KIND_MEDIA,
    KIND_SELECT,
    KIND_SOFTWARE,
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
    MACHINE_COUNT,
    MACHINE_PLUS,
    MACHINE_SEP1,
    MACHINE_SEP2,
    MACHINE_SEP3,
    MAIN_MENU,
    MEDIA_LABEL,
    MUSIC_INFO,
    OPTION_NEW_SEARCH,
    OPTIONS_ORDER,
    OPTIONS_PLAY_STATUS,
    SEARCH_MARP,
    SEARCH_YOUTUBE,
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
    TEXTLIST_HIDDEN,
    TEXTLIST_KEY_EMU_OUTPUT,
    TEXTLIST_KEY_NO_INFO,
    TEXTLIST_KEY_PROPERTY,
    TEXTLIST_ORDER,
    TEXTLIST_OTHER_CATEGORIES,
    VIDEO_LABEL,
    WAIT_GUI,
    WAIT_PLAYER,
)
from umsa_gui.filter_ui import empty_filter_lists
from umsa_gui.gamelist import GamelistCtx, GamelistSettle
from umsa_gui.optional_plugins import KODIPDF, KODIYT, play_pdf
from umsa_gui.paths import ADDON, ADDON_PATH, RESOURCE_LIB
from umsa_gui.request_queue import (
    REQUEST_CLOSE,
    REQUEST_OPEN_SOFTWARE,
    RequestQueue,
)
from umsa_gui.strings import tr

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
    "ACTION_BACKLOG_THRESHOLD",
    "ACTION_CANCEL_DIALOG",
    "ACTION_CHOOSE_EMULATOR",
    "ACTION_CONTEXT",
    "ACTION_ENTER",
    "ACTION_INFO",
    "ACTION_LIST_SCROLL",
    "ACTION_MOVEMENT",
    "ACTION_MOVEMENT_DOWN",
    "ACTION_MOVEMENT_LEFT",
    "ACTION_MOVEMENT_RIGHT",
    "ACTION_MOVEMENT_UP",
    "ACTION_NOOP",
    "ACTION_PLAYFULLSCREEN",
    "ACTION_PLAY_NEXTITEM",
    "ACTION_SOUND_VOLUME",
    "ACTION_START_EXODOS",
    "ACTION_START_EXODOS_ALT",
    "ACTION_START_KODI",
    "ACTION_START_MAME",
    "COMPILATION_LABEL",
    "CORE_DATA_PATHS",
    "EMULATOR_RUNNING_PROPERTY",
    "ENTRY_ACTION",
    "ENTRY_SEARCH",
    "FILTER_CATEGORY_KEYS",
    "FILTER_CATEGORY_LIST",
    "FILTER_CONTENT_LIST_ACTIVE",
    "FILTER_CONTENT_LIST_INACTIVE",
    "FILTER_KEY_LOAD",
    "FILTER_KEY_SAVE",
    "FILTER_LABEL",
    "FILTER_LABEL2",
    "FILTER_LIST_BG",
    "FILTER_OPTIONS",
    "FILTER_OPTION_ALL",
    "FILTER_OPTION_INVERT",
    "FILTER_OPTION_NONE",
    "GAMELIST_SETTLE_DELAY",
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
    "KIND_EMULATORS",
    "KIND_MACHINES",
    "KIND_MEDIA",
    "KIND_SELECT",
    "KIND_SOFTWARE",
    "KODIPDF",
    "KODIYT",
    "LABEL_STATUS",
    "LEFT_IMAGE_HORI",
    "LEFT_IMAGE_VERT",
    "LISTMODE_MENU",
    "MACHINE_COUNT",
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
    "OPTIONS_ORDER",
    "OPTIONS_PLAY_STATUS",
    "OPTION_NEW_SEARCH",
    "PLATFORM",
    "SEARCH_MARP",
    "SEARCH_YOUTUBE",
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
    "TEXTLIST_HIDDEN",
    "TEXTLIST_KEY_EMU_OUTPUT",
    "TEXTLIST_KEY_NO_INFO",
    "TEXTLIST_KEY_PROPERTY",
    "TEXTLIST_ORDER",
    "TEXTLIST_OTHER_CATEGORIES",
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

    Kodi delivers the callback also in the middle of a running window
    handler. Closing the window and opening a software are therefore only
    queued (``UMSA.requests``) and run once no handler is active; the VGM
    actions only write to the VGM socket and run at once. After
    ``release_resources()`` the monitor ignores everything.
    """

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def onNotification(self, sender, method, data):
        if sender != VGM_SENDER:
            return
        if getattr(self.owner, '_resources_released', False):
            return
        if is_frontend_close_method(method):
            # the maintenance script deletes databases: release them first
            xbmc.log("UMSA gui: close requested by maintenance")
            self.owner.requests.post(REQUEST_CLOSE)
            return
        software_id = parse_software_open_method(method)
        if software_id is not None:
            self.owner.requests.post(REQUEST_OPEN_SOFTWARE, software_id)
            return
        action = parse_vgm_action_method(method)
        if action in ('volume_up', 'volume_down', 'next', 'stop', 'start_random'):
            self.owner._handle_vgm_action(action)


# guards the hand-over of the database close to a still running scan thread
_SCAN_LOCK = Lock()

# screen aspect -> divisor for the width of the left images (skin is 16:9)
_LEFT_IMAGE_ASPECTS = {"16:10": 1.6, "5:4": 1.25, "4:3": 1.33}


def _window_handler(method):
    """Mark a Kodi window callback as running for ``UMSA.requests``.

    Requests of the monitor that arrive meanwhile run after the outermost
    handler returned.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        requests = getattr(self, 'requests', None)
        if not isinstance(requests, RequestQueue):
            return method(self, *args, **kwargs)
        with requests.busy():
            return method(self, *args, **kwargs)

    return wrapper


def _close_database(window):
    """Close the databases, then tell the maintenance script they are free."""

    try:
        window.ggdb.close()
    except Exception as exc:
        xbmc.log(f"UMSA gui: exit: could not close database: {exc}", xbmc.LOGERROR)
    set_frontend_running(False)


class UMSA(xbmcgui.WindowXMLDialog):
    """Main UMSA class"""

    # one-time part of onInit done (Kodi runs onInit on every window init)
    _initialized = False
    # skin widths of the left images, read on the first onInit
    _left_image_widths = None
    # the running scan thread closes the databases when it ends
    _close_db_after_scan = False
    # the scan thread left update() (set under _SCAN_LOCK)
    _scan_ended = False
    # ROM cache settings, set by _read_settings()
    rom_cache = False
    cache_layout = None
    # setting vgm_port (None: Core default)
    vgm_port = None

    def __init__(self, strXMLname, strFallbackPath, strDefaultName, forceFallback):

        # initialize
        self.quit = False
        # close / open-software requests of the monitor, run while idle
        self.requests = RequestQueue(self._handle_request)
        # set once release_resources() ran (exit() or Kodi shutdown)
        self._resources_released = False
        self.selected_control_id = SOFTWARE_BUTTON # holds the old control id from skin
        self.main_focus = SOFTWARE_BUTTON # remember main select when in gamelist
        self.info = None # contains all sets for actual software
        self.emulation = None

        self.dummy = None # needed to prevent a software jump
                          # when popup is quit by left or right
        self.enter = None # set when a gamelist select happens
        # scanned machine cabinets of the shown software (machine wraplist)
        self.machine_cabinets = {}
        # deferred reload of the gamelist entry once scrolling stopped
        self.gamelist_settle = GamelistSettle()
        # drops software moves queued while a held left/right key is processed
        self.software_backlog = ActionBacklog()
        self.oldset = () # needed for show_info to see if set has changed
        # to assure only one thread is running
        self.scan_thread = None
        # list for last selected games, only saves the software id
        self.last = []
        # pointer for last selected games list
        self.lastptr = 0
        # old search
        self.searchold = None
        # what the game list shows (KIND_*) and, for a "Select ..." list,
        # the menu code it was opened for
        self.gamelist_kind = KIND_SOFTWARE
        self.gamelist_select = None
        # filter category shown in the filter content lists
        self.act_filter_category = None
        # diff emu toggle
        self.diff_emu = False
        # set for vgms for software
        self.vgms = None
        self.vgm_titles = {}
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
        self.pdfviewer = ''
        # ProcessRunner of the external PDF viewer (gamelist_actions.open_manual)
        self.manual_viewer = None
        self.initial_software_id = None

        # Clear stale emulator running state from any previous crashed instance
        self.set_emulator_running(False)
        # tell the maintenance script that the frontend (and its databases) is open
        set_frontend_running(True)

        # no settings yet = open the UMSA (Core) settings first
        if not os.path.exists(SETTINGS_FOLDER):
            open_core_settings()
        self.read_settings()

        xbmc.log("UMSA gui: __init__ done")

    @_window_handler
    def onInit(self):
        """Kodi onInit.

        Kodi runs it again whenever the window is initialised anew, so only
        the controls are set up every time; objects, databases and the
        history are created once (``_init_once``).
        """

        self._init_controls()
        first_run = not self._initialized
        if first_run:
            if not self._init_once():
                return
            self._initialized = True
        self.getControl(FILTER_LABEL2).setLabel(tr(S.FILTER_NAME, self.act_filter))

        # select software
        if first_run and self.initial_software_id is not None:
            self._remember_and_select(self.initial_software_id)
        else:
            # a later run only fills the controls again, no history entry
            self.select_software(self.last[self.lastptr])

        xbmc.log("UMSA gui: onInit: done")
        xbmc.log(f"UMSA gui: PDF Reader import: {KODIPDF}")
        xbmc.log(f"UMSA gui: Youtube import: {KODIYT}")

        if self.quit:
            self.close()
            return

    def _init_controls(self):
        """Set the skin controls up; safe to repeat on every onInit."""

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

        # set aspectratio for left images depending on screen aspect; always
        # from the widths of the skin, so a repeated run does not scale twice
        if self._left_image_widths is None:
            self._left_image_widths = (
                self.getControl(LEFT_IMAGE_HORI).getWidth(),
                self.getControl(LEFT_IMAGE_VERT).getWidth())
        aspect = _LEFT_IMAGE_ASPECTS.get(self.aratio)
        if aspect is not None:
            _4to3, _3to4 = self._left_image_widths
            self.getControl(LEFT_IMAGE_HORI).setWidth(int(_4to3 / aspect * 1.77)) # 4:3
            self.getControl(LEFT_IMAGE_VERT).setWidth(int(_3to4 * 1.77 / aspect)) # 3:4

        # fill filter lists
        self.getControl(FILTER_CATEGORY_LIST).reset()
        self.getControl(FILTER_CATEGORY_LIST).addItems(
            filter_ui.category_list_items())
        self.getControl(FILTER_OPTIONS).reset()
        self.getControl(FILTER_OPTIONS).addItems([
            xbmcgui.ListItem(tr(string_id), key)
            for key, string_id in (
                (FILTER_OPTION_ALL, S.FILTER_OPTION_ALL),
                (FILTER_OPTION_NONE, S.FILTER_OPTION_NONE),
                (FILTER_OPTION_INVERT, S.FILTER_OPTION_INVERT))])

    def _init_once(self):
        """Create player, dialogs, emulation, monitor, database and history.

        Returns False when the window was closed (first start without a
        database download).
        """

        self.player = xbmc.Player()

        # for kodi dialogs
        self.dialog = xbmcgui.Dialog()
        self.emu_dialog = xbmcgui.DialogProgress()

        # bg progress bar
        self.progress_dialog = xbmcgui.DialogProgressBG()

        # no videos when something is already running
        if self.player.isPlayingVideo():
            self.already_playing = True

        # initalize Emulation class
        self.emulation = Emulation(
            self.temp_dir, self.mameini, self.mame_dir, self.mame_exe, self.chdman_exe,
            get_core_vgmplay_script(), self._show_vgm_info, self.nonmame, terminal=self.terminal,
            vgmplay_exe=self.vgmplay_exe, vgm_stopped_callback=self._hide_vgm_info,
            vgm_max_duration=self.vgm_max_duration, rom_cache=self.rom_cache,
            cache_layout=self.cache_layout, vgm_port=self.vgm_port)

        # receive VGM control commands from the screensaver add-on
        self.vgm_monitor = VgmCommandMonitor(self)
        # abort-aware wait for long Core loops (emulator run, CHD, scans)
        self.abort_wait = make_abort_wait(self.vgm_monitor)

        # filters are loaded from status.db after the database is open and the
        # one-time legacy import has run (the migration runs at DBMod open)
        self.filter_lists = empty_filter_lists()
        self.act_filter = DEFAULT_FILTER_NAME

        # database connection
        if CORE_DATA_PATHS.umsa_db.is_file():
            self.ggdb = DBMod(SETTINGS_FOLDER, self.nonmame, self.filter_lists, self.pref_country)
        else:
            # DB download in foreground, dat+art scan in background
            if not self.update('db'):
                xbmc.log("UMSA gui: onInit: no umsa.db after download, closing",
                         xbmc.LOGERROR)
                self.close()
                return False
            self._start_scan('dat')

        # one-time legacy import + load persisted filter selections and history
        self.run_startup_import()
        # first start: create the default filter (status.db has none yet)
        self.ggdb.ensure_default_filter()
        self.filter_lists = self.ggdb.history.load_filter_selections(self.act_filter)
        self.ggdb.gamelist.define_filter(self.filter_lists)

        # load last internal software list
        self.last = self.ggdb.history.load_lastgames()
        # fill with random software if not 10
        while len(self.last) < 10:
            self.last.append(self.ggdb.gamelist.get_random_id())
        # initialize pointer to the newest entry
        self.lastptr = len(self.last) - 1
        return True

    # sequence: onFocus, onClick, onAction

    @_window_handler
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

    @_window_handler
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

        selected = self.getControl(control_id).getSelectedItem()
        # option lists carry their key in label2
        item = selected.getLabel2()
        if control_id == TEXTLIST:
            # placeholder without DAT text: nothing to show
            if selected.getProperty(TEXTLIST_KEY_PROPERTY) == TEXTLIST_KEY_NO_INFO:
                return
            # text viewer: show the text of the entry itself, entries like
            # 'Emulator output' exist only in the list, not in all_dat
            else:
                self.dialog.textviewer(
                    selected.getLabel(), selected.getProperty('text'))

        elif control_id == GAME_LIST_OPTIONS:
            if item == OPTION_NEW_SEARCH:
                keyboard = xbmc.Keyboard('', tr(S.SEARCH_FOR), 0)
                keyboard.doModal()
                if keyboard.isConfirmed():
                    self.searchold = keyboard.getText()
                else:
                    return
                gamelist, pos, result_count = self.ggdb.games.get_searchresults(self.searchold)
                gl_label = tr(S.LIST_SEARCH_RESULTS, result_count, self.searchold)
                gl_options = (OPTION_NEW_SEARCH,)

                # check how many results
                if len(gamelist) == 0:
                    self.dialog.notification(tr(S.SEARCH), tr(S.SEARCH_NO_RESULTS),
                        xbmcgui.NOTIFICATION_ERROR, 5000, False)
                    return
                if len(gamelist) == 1:
                    self.searchold = None
                    self._remember_and_select(gamelist[0]['id'])
                    return

                # TODO no popup, but refill
                self.popup_gamelist(gamelist, gl_label, pos=pos, options=gl_options)

            # options from play status
            elif item in OPTIONS_PLAY_STATUS:
                gamelist, pos = self.ggdb.software.get_last_played(item)
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

            elif item in OPTIONS_ORDER:
                self.ggdb.gamelist.set_order(item)
                content = int(self.getControl(GAME_LIST_LABEL_ID).getLabel())
                self.update_gamelist(content)

        elif control_id == GAME_LIST_SORT:
            self.gamelist_switch_filter()

        # FILTER: select all, none or invert lists
        elif control_id == FILTER_OPTIONS:
            filter_category_name = self.act_filter_category
            if item == FILTER_OPTION_NONE:
                self.filter_lists[filter_category_name] = []
            elif item == FILTER_OPTION_ALL:
                self.filter_lists[filter_category_name] = []
                for i in self.ggdb.games.get_all_dbentries(filter_category_name):
                    self.filter_lists[filter_category_name].append(str(i['id']))
            elif item == FILTER_OPTION_INVERT:
                templist = []
                for i in self.ggdb.games.get_all_dbentries(filter_category_name):
                    if str(i['id']) not in self.filter_lists[filter_category_name]:
                        templist.append(str(i['id']))
                self.filter_lists[filter_category_name] = templist
            self.set_filter_content(filter_category_name)

            # set focus to active, when empty deactive
            if len(self.filter_lists[filter_category_name]) == 0:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_INACTIVE))
            else:
                self.setFocus(self.getControl(FILTER_CONTENT_LIST_ACTIVE))

    @_window_handler
    def onAction(self, action):
        """Kodi onAction"""

        xbmc.log(f"UMSA gui: onAction: id = {action.getId()}")

        if action.getId() == 0:
            return

        # deferred gamelist reload (GamelistSettle): touch nothing else, so
        # neither the screensaver nor the popup dummy logic reacts on it
        if action.getId() in ACTION_NOOP:
            if self.selected_control_id == GAME_LIST:
                self.gamelist_move(force=True)
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
        # random playback sits between two tracks with playvgm off: a stop
        # must still end it
        if (action.getId() == 13 and self.emulation.playrandomvgm
                and not self.emulation.playvgm):
            self.emulation.stop_vgm(timeout=0)
        if self.emulation.playvgm:
            # x = stop
            if action.getId() == 13:
                # no waiting inside a window handler
                self.emulation.stop_vgm(timeout=0)
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
            return

        # ACTION SOFTWARE_BUTTON
        if self.selected_control_id == SOFTWARE_BUTTON:
            self.main_focus = SOFTWARE_BUTTON
            if action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_MOVEMENT_LEFT:
                direction = 'right' if action.getId() in ACTION_MOVEMENT_RIGHT else 'left'
                if self.software_backlog.is_backlog():
                    xbmc.log("UMSA gui: onAction: software move skipped (backlog)", xbmc.LOGDEBUG)
                else:
                    self.software_move(direction)
                self.software_backlog.done()
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
                    # show the lists of the selected category right away
                    self.show_filter_category_content(force=True)

                elif menu_item == M_EXIT:
                    self.exit()

                elif menu_item == M_UPD:
                    self.setFocus(self.getControl(self.main_focus))
                    if self._refuse_while_scanning():
                        return

                    ret = self.dialog.select(
                        tr(S.UPDATE_WHAT), [
                            tr(S.UPDATE_DATABASE),
                            tr(S.UPDATE_SCAN_DATS),
                            tr(S.UPDATE_SCAN_ARTWORK),
                            tr(S.UPDATE_SCAN_EXODOS),
                            tr(S.UPDATE_SCAN_GB64),
                        ]
                    )
                    if ret == 0:
                        self.update('db')
                    elif ret == 1:
                        self._start_scan('dat')
                    elif ret == 2:
                        self._start_scan('art')
                    elif ret == 3:
                        self._start_scan('exo')
                    elif ret == 4:
                        self._start_scan('gb64')

                elif menu_item == M_SSAVER:
                    self.setFocus(self.getControl(self.main_focus))
                    ret = self.dialog.select(
                        tr(S.SAVER_WHICH_SHOW), [
                            tr(S.SAVER_SHOW_VIDEOS),
                            tr(S.SAVER_SHOW_CROSS),
                            tr(S.SAVER_SHOW_SLIDE),
                            tr(S.SAVER_SHOW_WALL),
                            tr(S.SAVER_SHOW_MARP),
                            tr(S.SAVER_SHOW_VGM),
                        ]
                    )
                    if ret == 0:
                        self.start_screensaver('videos')
                    elif (ret == 1 or ret == 2) and self.ensure_screensaver_available():
                        art_types = self.ggdb.artwork.get_art_types()
                        ret2 = self.dialog.multiselect(
                            tr(S.SAVER_WHICH_ARTWORK), art_types
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
                        screensaver_vgm.start_random_vgm(self)
                elif menu_item == M_ASETTINGS:
                    self.setFocus(self.getControl(self.main_focus))
                    open_core_settings()
                    self.read_settings()
                else:
                    # close the menu; 'loading...' shows in LABEL_STATUS until the list pops up
                    self.setFocus(self.getControl(self.main_focus))
                    self.update_gamelist(menu_item)

            elif action.getId() in ACTION_CONTEXT:

                menu_item = int(self.getControl(MAIN_MENU).getSelectedItem().getLabel2())
                # listmode menu
                if menu_item in (M_ALL, M_SOURCE, M_SWL, M_SERIES):
                    self.update_gamelist(menu_item)
                    self.setFocus(self.getControl(LISTMODE_MENU))
                # switch filter
                elif menu_item == M_FILTER:
                    if self.ggdb.gamelist.use_filter:
                        self.ggdb.gamelist.set_filter_enabled(False)
                        self.getControl(MAIN_MENU).getSelectedItem().setLabel(
                            tr(S.MENU_FILTER_OFF))
                    else:
                        self.ggdb.gamelist.set_filter_enabled(True)
                        self.getControl(MAIN_MENU).getSelectedItem().setLabel(
                            tr(S.MENU_FILTER_NAME, self.act_filter))
                # update umsa db
                elif menu_item == M_UPD:
                    self.setFocus(self.getControl(self.main_focus))
                    # umsa.db is closed for the update: not under a scan
                    if self._refuse_while_scanning():
                        return
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
            elif action.getId() in ACTION_LIST_SCROLL:
                self.gamelist_move()
                self.schedule_gamelist_settle()

        # ACTION FILTER_CATEGORY_LIST
        elif self.selected_control_id == FILTER_CATEGORY_LIST:
            xbmc.log("UMSA gui: onAction: FILTER_CATEGORY_LIST")

            if action.getId() in ACTION_ENTER:
                self.filter_category()
            elif action.getId() in ACTION_LIST_SCROLL:
                self.show_filter_category_content()

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

        # all UMSA settings are owned by the Core add-on
        core_settings = get_core_settings()
        # effective MAME paths (optional settings resolved) and computed values
        emu_settings = load_all_settings(
            core_settings, __resource__, PLATFORM, home=os.path.expanduser('~')
        )

        self.mame_exe = core_settings.mame_exe
        self.mameini = emu_settings.mame_ini
        self.mame_dir = emu_settings.mame_working_dir
        self.chdman_exe = emu_settings.chdman_exe
        self.progettosnaps = core_settings.progettosnaps_dir
        self.own_artwork = core_settings.own_artwork_dir
        self.aratio = core_settings.aspect_ratio
        self.datdir = core_settings.support_files_dir
        self.vgmplay_exe = core_settings.vgmplay_exe
        self.musicinfo = core_settings.show_music_info
        self.vgm_show_machine_list = core_settings.vgm_show_machine_list
        self.vgm_max_duration = core_settings.vgm_max_duration
        self.vgm_port = core_settings.vgm_port
        self.vgm_intro_duration = core_settings.vgm_intro_duration

        self.pref_country = core_settings.pref_country
        self.temp_dir = core_settings.rom_temp_dir
        self.pdfviewer = core_settings.pdf_viewer
        self.terminal = core_settings.terminal
        self.emulation_start = core_settings.emulation_start
        self.playvideo = True if core_settings.auto_play_videos else None

        self.nonmame = emu_settings.nonmame
        self.cab_path = emu_settings.cab_path
        self.batomame = emu_settings.batomame
        # ROM cache: one layout for extracted sets and copies of all starts
        self.rom_cache = core_settings.rom_cache
        self.cache_layout = CacheLayout(
            self.temp_dir, core_settings.batocera_layout, self.batomame)

        self._apply_settings_to_services()

    def _apply_settings_to_services(self):
        """Hand re-read settings to the objects that copied them in onInit.

        On the first call (from onInit) neither object exists yet; after the
        settings dialog the changes take effect without a restart. The
        aspect ratio is the exception: onInit scales the left image controls
        once, so it still needs a restart.
        """

        emulation = getattr(self, 'emulation', None)
        if emulation is not None:
            emulation.apply_settings(
                self.temp_dir, self.mameini, self.mame_dir, self.mame_exe,
                self.chdman_exe, self.nonmame, self.terminal, self.vgmplay_exe,
                self.vgm_max_duration, rom_cache=self.rom_cache,
                cache_layout=self.cache_layout, vgm_port=self.vgm_port)
        ggdb = getattr(self, 'ggdb', None)
        if ggdb is not None:
            ggdb.nonmame = self.nonmame
            ggdb.pref_country = self.pref_country

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

    def ensure_screensaver_available(self):
        """Return True if the screensaver add-on can be started, else notify."""
        return screensaver_vgm.ensure_screensaver_available(self)

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

    def gamelist_move(self, pos=None, force=False):
        """Move in gamelist"""
        return gamelist_workflows.gamelist_move(self, pos=pos, force=force)

    def schedule_gamelist_settle(self):
        """Reload the selected gamelist entry once the list stopped moving."""
        self.gamelist_settle.schedule()

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
        return gamelist_workflows.update_gamelist(self, item)

    def popup_gamelist(self, gamelist, label, pos=0, sort=None, options=None,
                       kind=KIND_SOFTWARE, select_what=None):
        """Pop up gamelist."""
        return gamelist_workflows.popup_gamelist(
            self, gamelist, label, pos, sort, options, kind, select_what)

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

    def set_filter_content(self, cat, update=None, focus_lists=True):
        """Set filter content"""
        return filter_ui.set_filter_content(self, cat, update, focus_lists)

    def show_filter_category_content(self, force=False):
        """Fill the filter content lists for the selected category."""
        return filter_ui.show_category_content(self, force)

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
                emulation=self.emulation,
                ggdb=self.ggdb,
                emu_dialog=self.emu_dialog,
                dialog=self.dialog,
                player=self.player,
                rom_cache=self.rom_cache,
                cache_layout=self.cache_layout,
                wait=self.abort_wait,
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
            wait=self.abort_wait,
            on_shutdown=self.exit,
        )
        launch_emulator(ctx)

    # --- scans ----------------------------------------------------------

    def update(self, what):
        """Update UMSA database, artwork or support files"""
        return scan_orchestrator.update(self, what, CORE_DATA_PATHS)

    def _scan_running(self):
        """Return whether a scan thread is alive; forget a finished one."""

        if self.scan_thread and not self.scan_thread.is_alive():
            self.scan_thread = None
        return bool(self.scan_thread)

    def _refuse_while_scanning(self):
        """Tell the user that a scan runs; True when the caller must stop."""

        if not self._scan_running():
            return False
        self.dialog.notification(
            tr(S.SCAN_STATUS), tr(S.SCAN_ALREADY_RUNNING),
            xbmcgui.NOTIFICATION_ERROR, 4000)
        return True

    def _start_scan(self, what):
        """Run ``update(what)`` in the scan thread."""

        self._scan_ended = False
        self.scan_thread = Thread(target=self._run_scan, args=(what,))
        self.scan_thread.start()

    def _run_scan(self, what):
        """Body of the scan thread.

        A scan that outlived ``release_resources()`` closes the databases
        itself: they are never closed under a running scan.
        """

        try:
            self.update(what)
        finally:
            with _SCAN_LOCK:
                self._scan_ended = True
                if self._close_db_after_scan:
                    xbmc.log("UMSA gui: scan ended after exit, closing database")
                    _close_database(self)

    def _handle_request(self, kind, value):
        """Run a queued request of the monitor (``self.requests``)."""

        if self._resources_released:
            return
        if kind == REQUEST_CLOSE:
            self.exit()
        elif kind == REQUEST_OPEN_SOFTWARE:
            self.open_software(value)

    def exit(self):
        """Exit add-on: stop video, close database."""

        self.release_resources()
        self.close()

    def release_resources(self):
        """Stop VGM and scans, close the databases; repeated calls are safe.

        ``exit()`` calls it before closing the window; ``main()`` calls it
        when Kodi closed the window without ``exit()`` (shutdown), so a
        playing VGM or a running scan does not keep the script alive.

        A scan that does not stop in time keeps the databases: its thread
        closes them when it ends (``_run_scan``).
        """

        if getattr(self, '_resources_released', False):
            return
        self._resources_released = True

        requests = getattr(self, 'requests', None)
        if isinstance(requests, RequestQueue):
            requests.close()

        settle = getattr(self, 'gamelist_settle', None)
        if settle is not None:
            settle.cancel()

        # random playback sits between two tracks with playvgm off; a window
        # that closed before its first init has no emulation yet
        emulation = getattr(self, 'emulation', None)
        if emulation is not None and (emulation.playvgm or emulation.playrandomvgm):
            try:
                emulation.stop_vgm()
            except Exception as exc:
                xbmc.log(f"UMSA gui: exit: could not stop VGM playback: {exc}", xbmc.LOGERROR)
            try:
                clear_vgm_info()
            except Exception as exc:
                xbmc.log(f"UMSA gui: exit: could not clear VGM info: {exc}", xbmc.LOGERROR)

        try:
            if hasattr(self, 'ggdb') and self.ggdb and hasattr(self.ggdb, 'scan_status'):
                self.ggdb.scan_status = False
                xbmc.log('UMSA gui: exit: requested scan stop', xbmc.LOGDEBUG)
        except Exception as exc:
            xbmc.log(f"UMSA gui: exit: could not request scan stop: {exc}", xbmc.LOGERROR)

        scan_alive = False
        try:
            scan_thread = getattr(self, 'scan_thread', None)
            if scan_thread and scan_thread.is_alive():
                try:
                    scan_thread.join(timeout=5)
                except Exception as exc:
                    xbmc.log(f"UMSA gui: exit: could not join scan thread: {exc}", xbmc.LOGERROR)
                scan_alive = scan_thread.is_alive()
        except Exception as exc:
            xbmc.log(f"UMSA gui: exit: could not inspect scan thread: {exc}", xbmc.LOGERROR)

        with _SCAN_LOCK:
            if scan_alive and not getattr(self, '_scan_ended', False):
                # never close the databases under a running scan
                self._close_db_after_scan = True
                xbmc.log(
                    "UMSA gui: exit: scan still running, its thread closes "
                    "the database", xbmc.LOGWARNING)
                return

        # databases are closed: the maintenance script may go on
        _close_database(self)


def main():
    """Start Kodi UI."""

    set_log(lambda *args, level='debug': xbmc.log(' '.join(map(str, args)),
        {'debug': xbmc.LOGDEBUG, 'info': xbmc.LOGINFO, 'warning': xbmc.LOGWARNING,
         'error': xbmc.LOGERROR}
        .get(level, xbmc.LOGDEBUG)))
    # flags of a screensaver that was killed would block every later start
    clear_stale_screensaver_state()
    path = __cwd__
    gui = UMSA("umsa_estuary.xml", path, "default", "1080i")
    if len(sys.argv) > 2 and sys.argv[1] == "select_software":
        try:
            gui.initial_software_id = int(sys.argv[2])
        except ValueError:
            xbmc.log("UMSA gui: invalid software selection argument", xbmc.LOGERROR)
    try:
        gui.doModal()
    finally:
        # Kodi closes the window at shutdown without exit() - and before the
        # monitor reports the abort request: always stop VGM and scans here
        # (a no-op after exit()), a non-daemon VGM thread blocks the script
        # end and with it the Kodi shutdown
        try:
            gui.release_resources()
        except Exception as exc:
            xbmc.log(f"UMSA gui: cleanup after the window closed failed: {exc}",
                     xbmc.LOGERROR)
        # also covers windows closed without exit() (e.g. failed first start);
        # a scan that still runs clears the flag when it closed the databases
        if not getattr(gui, '_close_db_after_scan', False):
            set_frontend_running(False)
    del gui


@dataclass
class RetroplayerCtx:
    actset: object = None
    emulation: object = None
    ggdb: object = None
    emu_dialog: object = None
    dialog: object = None
    player: object = None
    # setting rom_cache and the cache folders (umsa_core.rom_cache)
    rom_cache: bool = False
    cache_layout: object = None
    # abort-aware wait (umsa_core.abort.Wait)
    wait: object = None

    def stop_screensaver(self):
        pass

    def exit(self):
        pass
