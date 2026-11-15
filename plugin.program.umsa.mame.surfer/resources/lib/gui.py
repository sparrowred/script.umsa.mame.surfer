#!/usr/bin/env python3
"""UI Module for UMSA Kodi Add-on.

This module is the Kodi adapter of the frontend: it owns the ``UMSA`` window
class and the Kodi event dispatch. The
workflows themselves live in the ``umsa_gui`` package, one module per topic;
they receive a context of their own (``umsa_gui.wiring``) built from the shared
state of the window (``umsa_gui.state``) and call each other directly; the
Kodi dialog stays the single owner of the skin controls.
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
from settings_adapter import FrontendSettings, load_all_settings
from umsa_core import set_log
from umsa_core.database import DBMod
from umsa_core.default_filter import DEFAULT_FILTER_NAME
from umsa_core.emulation import Emulation
from umsa_core.game_labels import split_gamename
from umsa_core.scans import Scans
from umsa_core.support import youtube_search
from umsa_core_kodi import (
    VGM_SENDER,
    clear_stale_screensaver_state,
    clear_vgm_info,
    get_core_data_paths,
    get_core_settings,
    get_core_vgmplay_script,
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
from umsa_gui.constants import (
    ACTION_CANCEL_DIALOG,
    ACTION_CONTEXT,
    ACTION_ENTER,
    ACTION_LIST_SCROLL,
    ACTION_MOVEMENT_DOWN,
    ACTION_MOVEMENT_LEFT,
    ACTION_MOVEMENT_RIGHT,
    ACTION_MOVEMENT_UP,
    ACTION_NOOP,
    ACTION_PLAY_NEXTITEM,
    COMPILATION_LABEL,
    FILTER_CATEGORY_LIST,
    FILTER_CONTENT_LIST_ACTIVE,
    FILTER_CONTENT_LIST_INACTIVE,
    FILTER_LABEL2,
    FILTER_OPTION_ALL,
    FILTER_OPTION_INVERT,
    FILTER_OPTION_NONE,
    FILTER_OPTIONS,
    GAME_LIST,
    GAME_LIST_LABEL_ID,
    GAME_LIST_OPTIONS,
    GAME_LIST_SORT,
    LEFT_IMAGE_HORI,
    LEFT_IMAGE_VERT,
    LISTMODE_MENU,
    M_ALL,
    M_ALLEMUS,
    M_ASETTINGS,
    M_EXIT,
    M_FILTER,
    M_LSSAVER,
    M_MACHINE,
    M_MEDIA,
    M_PLAYSTAT,
    M_SEARCH,
    M_SEARCH_NEW,
    M_SERIES,
    M_SOURCE,
    M_SSAVER,
    M_SWL,
    M_UPD,
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
    SERIES_LABEL,
    SET_LIST,
    SHADOW_DAT,
    SOFTWARE_BUTTON,
    SYSTEM_WRAPLIST,
    TEXTLIST,
    TEXTLIST_KEY_NO_INFO,
    TEXTLIST_KEY_PROPERTY,
)
from umsa_gui.filter_ui import empty_filter_lists
from umsa_gui.gamelist import GamelistSettle
from umsa_gui.optional_plugins import KODIPDF, KODIYT
from umsa_gui.paths import ADDON_PATH, RESOURCE_LIB
from umsa_gui.request_queue import (
    REQUEST_CLOSE,
    REQUEST_OPEN_SOFTWARE,
    RequestQueue,
)
from umsa_gui.state import (
    FilterState,
    History,
    ListState,
    Services,
    SoftwareState,
    View,
)
from umsa_gui.strings import tr
from umsa_gui.wiring import build_contexts

PLATFORM = sys.platform

# shared application data
CORE_DATA_PATHS = get_core_data_paths(create=False)
SETTINGS_FOLDER = CORE_DATA_PATHS.filters_dir


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
        if self.owner._resources_released:
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
            screensaver_vgm.handle_vgm_action(
                self.owner.ctx.screensaver_vgm, action)


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
        with self.requests.busy():
            return method(self, *args, **kwargs)

    return wrapper


def _close_database(window):
    """Close the databases, then tell the maintenance script they are free."""

    try:
        window.services.ggdb.close()
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
    # set once release_resources() ran (exit() or Kodi shutdown)
    _resources_released = False

    def __init__(self, strXMLname, strFallbackPath, strDefaultName, forceFallback):

        # initialize
        self._init_state()
        self.initial_software_id = None

        # Clear stale emulator running state from any previous crashed instance
        set_emulator_running(False)
        # tell the maintenance script that the frontend (and its databases) is open
        set_frontend_running(True)

        # no settings yet = open the UMSA (Core) settings first
        if not os.path.exists(SETTINGS_FOLDER):
            open_core_settings()
        self.read_settings()

        xbmc.log("UMSA gui: __init__ done")

    def _init_state(self):
        """Create the state of the window and the contexts of the workflows.

        The shared blocks (``umsa_gui.state``) are created once and never
        replaced: the workflow contexts (``self.ctx``) keep references to them.
        """

        # close / open-software requests of the monitor, run while idle
        self.requests = RequestQueue(self._handle_request)
        self._resources_released = False
        self.selected_control_id = SOFTWARE_BUTTON # holds the old control id from skin
        self.dummy = None # needed to prevent a software jump
                          # when popup is quit by left or right
        # deferred reload of the gamelist entry once scrolling stopped
        self.gamelist_settle = GamelistSettle()
        # drops software moves queued while a held left/right key is processed
        self.software_backlog = ActionBacklog()
        # to assure only one thread is running
        self.scan_thread = None

        # skin controls, as the workflows see them
        self.view = View(self)
        # player, dialogs, emulation, database and scans (created in onInit)
        self.services = Services()
        # last selected software and the pointer into it
        self.history = History()
        # the shown software: sets, selected set, artwork, DAT texts, VGMs
        self.software = SoftwareState()
        # filter lists and the name of the loaded filter
        self.filters = FilterState()
        # what the game list shows, old search, focus to return to
        self.listing = ListState()
        # UMSA settings, filled by read_settings()
        self.settings = FrontendSettings(settings_folder=SETTINGS_FOLDER)

        self.ctx = build_contexts(
            view=self.view, services=self.services, history=self.history,
            software=self.software, filters=self.filters, listing=self.listing,
            settings=self.settings, settle=self.gamelist_settle,
            run_emulator=self.run_emulator, exit=self.exit)

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
        self.getControl(FILTER_LABEL2).setLabel(tr(S.FILTER_NAME, self.filters.act_filter))

        # select software
        if first_run and self.initial_software_id is not None:
            software_selector.remember_and_select(
                self.ctx.software_selector, self.initial_software_id)
        else:
            # a later run only fills the controls again, no history entry
            software_selector.select_software(
                self.ctx.software_selector,
                self.history.last[self.history.lastptr])

        xbmc.log("UMSA gui: onInit: done")
        xbmc.log(f"UMSA gui: PDF Reader import: {KODIPDF}")
        xbmc.log(f"UMSA gui: Youtube import: {KODIYT}")

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
        aspect = _LEFT_IMAGE_ASPECTS.get(self.settings.aratio)
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

        self.services.player = xbmc.Player()

        # for kodi dialogs
        self.services.dialog = xbmcgui.Dialog()
        self.services.emu_dialog = xbmcgui.DialogProgress()

        # bg progress bar
        self.services.progress_dialog = xbmcgui.DialogProgressBG()

        # no videos when something is already running
        if self.services.player.isPlayingVideo():
            self.software.already_playing = True

        # initalize Emulation class
        self.services.emulation = Emulation(
            self.settings.temp_dir, self.settings.mameini, self.settings.mame_dir,
            self.settings.mame_exe, self.settings.chdman_exe,
            get_core_vgmplay_script(),
            functools.partial(screensaver_vgm.show_vgm_info, self.ctx.screensaver_vgm),
            self.settings.nonmame, terminal=self.settings.terminal,
            vgmplay_exe=self.settings.vgmplay_exe,
            vgm_stopped_callback=functools.partial(
                screensaver_vgm.hide_vgm_info, self.ctx.screensaver_vgm),
            vgm_max_duration=self.settings.vgm_max_duration, rom_cache=self.settings.rom_cache,
            cache_layout=self.settings.cache_layout, vgm_port=self.settings.vgm_port)

        # receive VGM control commands from the screensaver add-on
        self.vgm_monitor = VgmCommandMonitor(self)
        # abort-aware wait for long Core loops (emulator run, CHD, scans)
        self.services.abort_wait = make_abort_wait(self.vgm_monitor)

        # filters are loaded from status.db after the database is open and the
        # one-time legacy import has run (the migration runs at DBMod open)
        self.filters.filter_lists = empty_filter_lists()
        self.filters.act_filter = DEFAULT_FILTER_NAME

        # scans write through their own connections; created before the
        # first start's DAT scan and kept when update('db') replaces ggdb
        self.services.scans = Scans(CORE_DATA_PATHS, lambda: self.settings.nonmame)

        # database connection
        if CORE_DATA_PATHS.umsa_db.is_file():
            self.services.ggdb = DBMod(
                SETTINGS_FOLDER, self.settings.nonmame,
                self.filters.filter_lists, self.settings.pref_country)
            # a umsa.db without software (broken download) is fetched again,
            # once, before the default filter is created from it
            if not self.services.ggdb.games.has_software():
                xbmc.log("UMSA gui: onInit: umsa.db holds no software, "
                         "downloading it again", xbmc.LOGWARNING)
                if not scan_orchestrator.update(self.ctx.scan_orchestrator, 'db', CORE_DATA_PATHS):
                    xbmc.log("UMSA gui: onInit: download failed, closing",
                             xbmc.LOGERROR)
                    self.close()
                    return False
                if not self.services.ggdb.games.has_software():
                    xbmc.log("UMSA gui: onInit: umsa.db still holds no software, "
                             "closing", xbmc.LOGERROR)
                    self.services.dialog.notification(
                        tr(S.DB_TITLE), tr(S.DB_EMPTY),
                        xbmcgui.NOTIFICATION_ERROR, 5000)
                    self.close()
                    return False
        else:
            # DB download in foreground, dat+art scan in background
            if not scan_orchestrator.update(self.ctx.scan_orchestrator, 'db', CORE_DATA_PATHS):
                xbmc.log("UMSA gui: onInit: no umsa.db after download, closing",
                         xbmc.LOGERROR)
                self.close()
                return False
            self._start_scan('dat')

        # one-time legacy import + load persisted filter selections and history
        startup_import.run_startup_import(self.ctx.startup_import)
        # first start: create the default filter (status.db has none yet)
        self.services.ggdb.ensure_default_filter()
        self.filters.filter_lists = self.services.ggdb.history.load_filter_selections(
            self.filters.act_filter)
        self.services.ggdb.gamelist.define_filter(self.filters.filter_lists)

        # load last internal software list
        self.history.last = self.services.ggdb.history.load_lastgames()
        # fill with random software if not 10
        while len(self.history.last) < 10:
            software_id = self.services.ggdb.gamelist.get_random_id()
            if software_id is None:
                # empty database: nothing to fill in
                break
            self.history.last.append(software_id)
        # initialize pointer to the newest entry
        self.history.lastptr = len(self.history.last) - 1
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
                if self.listing.enter:
                    self.listing.enter = None
                else:
                    self.dummy = True

            elif self.selected_control_id in (
                    FILTER_CATEGORY_LIST,
                    FILTER_CONTENT_LIST_ACTIVE,
                    FILTER_CONTENT_LIST_INACTIVE,
                ):

                filter_ui.close_filterlist(self.ctx.filter_ui)
                if self.listing.enter:
                    self.listing.enter = None
                else:
                    self.dummy = True

            elif self.selected_control_id == MAIN_MENU:
                self.dummy = True

        # update control_id
        self.listing.enter = None
        self.selected_control_id = control_id

    @_window_handler
    def onClick(self, control_id):
        """Kodi onClick"""
        xbmc.log("UMSA gui: onClick")

        # screensaver check
        screensaver_mode = screensaver_vgm.get_screensaver_mode()
        if screensaver_mode != 'no':
            xbmc.log("UMSA gui: onClick: Monitor runs, return")
            if screensaver_mode in ('wall', 'cross', 'slide'):
                screensaver_vgm.stop_screensaver()
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
                self.services.dialog.textviewer(
                    selected.getLabel(), selected.getProperty('text'))

        elif control_id == GAME_LIST_OPTIONS:
            if item == OPTION_NEW_SEARCH:
                keyboard = xbmc.Keyboard('', tr(S.SEARCH_FOR), 0)
                keyboard.doModal()
                if keyboard.isConfirmed():
                    self.listing.searchold = keyboard.getText()
                else:
                    return
                gamelist, pos, result_count = self.services.ggdb.games.get_searchresults(
                    self.listing.searchold)
                gl_label = tr(S.LIST_SEARCH_RESULTS, result_count, self.listing.searchold)
                gl_options = (OPTION_NEW_SEARCH,)

                # check how many results
                if len(gamelist) == 0:
                    self.services.dialog.notification(tr(S.SEARCH), tr(S.SEARCH_NO_RESULTS),
                        xbmcgui.NOTIFICATION_ERROR, 5000, False)
                    return
                if len(gamelist) == 1:
                    self.listing.searchold = None
                    software_selector.remember_and_select(self.ctx.software_selector, gamelist[0]['id'])
                    return

                # TODO no popup, but refill
                gamelist_workflows.popup_gamelist(
                    self.ctx.gamelist, gamelist, gl_label, pos=pos, options=gl_options)

            # options from play status
            elif item in OPTIONS_PLAY_STATUS:
                gamelist, pos = self.services.ggdb.software.get_last_played(item)
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
                self.services.ggdb.gamelist.set_order(item)
                content = int(self.getControl(GAME_LIST_LABEL_ID).getLabel())
                gamelist_workflows.update_gamelist(self.ctx.gamelist, content)

        elif control_id == GAME_LIST_SORT:
            gamelist_workflows.gamelist_switch_filter(self.ctx.gamelist)

        # FILTER: select all, none or invert lists
        elif control_id == FILTER_OPTIONS:
            filter_category_name = self.filters.act_filter_category
            if item == FILTER_OPTION_NONE:
                self.filters.filter_lists[filter_category_name] = []
            elif item == FILTER_OPTION_ALL:
                self.filters.filter_lists[filter_category_name] = []
                for i in self.services.ggdb.games.get_all_dbentries(filter_category_name):
                    self.filters.filter_lists[filter_category_name].append(str(i['id']))
            elif item == FILTER_OPTION_INVERT:
                templist = []
                for i in self.services.ggdb.games.get_all_dbentries(filter_category_name):
                    if str(i['id']) not in self.filters.filter_lists[filter_category_name]:
                        templist.append(str(i['id']))
                self.filters.filter_lists[filter_category_name] = templist
            filter_ui.set_filter_content(self.ctx.filter_ui, filter_category_name)

            # set focus to active, when empty deactive
            if len(self.filters.filter_lists[filter_category_name]) == 0:
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
                gamelist_workflows.gamelist_move(self.ctx.gamelist, force=True)
            return

        # check if monitor runs
        screensaver_mode = screensaver_vgm.get_screensaver_mode()
        if screensaver_mode in ('wall', 'cross', 'slide'):
            screensaver_vgm.stop_screensaver()
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
            self.services.player.play(windowed=False)

        # vgm action stuff
        # random playback sits between two tracks with playvgm off: a stop
        # must still end it
        if (action.getId() == 13 and self.services.emulation.playrandomvgm
                and not self.services.emulation.playvgm):
            self.services.emulation.stop_vgm(timeout=0)
        if self.services.emulation.playvgm:
            # x = stop
            if action.getId() == 13:
                # no waiting inside a window handler
                self.services.emulation.stop_vgm(timeout=0)
                self.getControl(MUSIC_INFO).setVisibleCondition('Player.HasAudio')
                self.getControl(MUSIC_INFO).setLabel(
                    "$INFO[MusicPlayer.Artist] - $INFO[MusicPlayer.Title] (-$INFO[MusicPlayer.TimeRemaining])"
                )
            # media key next/right shoulder button to stop current vgm but not stop playing
            elif action.getId() in ACTION_PLAY_NEXTITEM:
                self.services.emulation.send_vgmaction(b'exit')
            # + for volume up
            elif action.getId() == 88:
                self.services.emulation.send_vgmaction(b'volume_up')
            # - for volume down
            elif action.getId() == 89:
                self.services.emulation.send_vgmaction(b'volume_down')

        # exit only in main screen, otherwise close popup or stop video
        if action.getId() in ACTION_CANCEL_DIALOG:

            actual_control = self.selected_control_id
            if actual_control in (
                    GAME_LIST, GAME_LIST_OPTIONS, GAME_LIST_SORT, LISTMODE_MENU, MAIN_MENU
            ):
                self.setFocus(self.getControl(self.listing.main_focus))
                self.listing.enter = True
                return
            if actual_control in (
                    FILTER_CATEGORY_LIST, FILTER_CONTENT_LIST_ACTIVE,
                    FILTER_CONTENT_LIST_INACTIVE, FILTER_OPTIONS,
            ):
                filter_ui.close_filterlist(self.ctx.filter_ui)
                self.listing.enter = True
                return
            # stop video and return
            if self.services.player.isPlayingVideo() and not self.software.already_playing:
                self.services.player.stop()
                return
            # exit add-on
            self.exit()
            return

        # ACTION SOFTWARE_BUTTON
        if self.selected_control_id == SOFTWARE_BUTTON:
            self.listing.main_focus = SOFTWARE_BUTTON
            if action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_MOVEMENT_LEFT:
                direction = 'right' if action.getId() in ACTION_MOVEMENT_RIGHT else 'left'
                if self.software_backlog.is_backlog():
                    xbmc.log("UMSA gui: onAction: software move skipped (backlog)", xbmc.LOGDEBUG)
                else:
                    software_selector.software_move(self.ctx.software_selector, direction)
                self.software_backlog.done()
            elif action.getId() in ACTION_MOVEMENT_DOWN+ACTION_MOVEMENT_UP:
                artwork_presenter.show_artwork(self.ctx.artwork_presenter)
            elif action.getId() in ACTION_CONTEXT:
                menu.build_main_menu(self.ctx.menu, select=M_ALL)
                self.setFocus(self.getControl(MAIN_MENU))

        # MAIN MENU
        elif self.selected_control_id == MAIN_MENU:

            if action.getId() in ACTION_MOVEMENT_LEFT:
                self.setFocus(self.getControl(self.listing.main_focus))
            elif action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_ENTER:

                # get menu item
                menu_item = int(self.getControl(MAIN_MENU).getSelectedItem().getLabel2())
                xbmc.log(f"UMSA gui: onAction: menu = {menu_item}")

                if menu_item == M_FILTER:
                    self.setFocus(self.getControl(FILTER_CATEGORY_LIST))
                    # show the lists of the selected category right away
                    filter_ui.show_category_content(self.ctx.filter_ui, force=True)

                elif menu_item == M_EXIT:
                    self.exit()

                elif menu_item == M_UPD:
                    self.setFocus(self.getControl(self.listing.main_focus))
                    if self._refuse_while_scanning():
                        return

                    ret = self.services.dialog.select(
                        tr(S.UPDATE_WHAT), [
                            tr(S.UPDATE_DATABASE),
                            tr(S.UPDATE_SCAN_DATS),
                            tr(S.UPDATE_SCAN_ARTWORK),
                            tr(S.UPDATE_SCAN_EXODOS),
                            tr(S.UPDATE_SCAN_GB64),
                        ]
                    )
                    if ret == 0:
                        scan_orchestrator.update(self.ctx.scan_orchestrator, 'db', CORE_DATA_PATHS)
                    elif ret == 1:
                        self._start_scan('dat')
                    elif ret == 2:
                        self._start_scan('art')
                    elif ret == 3:
                        self._start_scan('exo')
                    elif ret == 4:
                        self._start_scan('gb64')

                elif menu_item == M_SSAVER:
                    self.setFocus(self.getControl(self.listing.main_focus))
                    ret = self.services.dialog.select(
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
                        screensaver_vgm.start_screensaver(self.ctx.screensaver_vgm, 'videos')
                    elif (ret == 1 or ret == 2) and (
                            screensaver_vgm.ensure_screensaver_available(
                                self.ctx.screensaver_vgm)):
                        art_types = self.services.ggdb.artwork.get_art_types()
                        ret2 = self.services.dialog.multiselect(
                            tr(S.SAVER_WHICH_ARTWORK), art_types
                        )
                        if ret2:
                            selected_art_types = []
                            for i in ret2:
                                selected_art_types.append(art_types[i])
                            if ret == 1:
                                screensaver_vgm.start_screensaver(
                                    self.ctx.screensaver_vgm, 'cross', selected_art_types)
                            else:
                                screensaver_vgm.start_screensaver(
                                    self.ctx.screensaver_vgm, 'slide', selected_art_types)
                    elif ret == 3:
                        screensaver_vgm.start_screensaver(self.ctx.screensaver_vgm, 'wall')
                    elif ret == 4:
                        emulator_setup.marp_replayer(self.ctx.emulator_setup)
                    elif ret == 5:
                        screensaver_vgm.start_random_vgm(self.ctx.screensaver_vgm)
                elif menu_item == M_ASETTINGS:
                    self.setFocus(self.getControl(self.listing.main_focus))
                    open_core_settings()
                    self.read_settings()
                else:
                    # close the menu; 'loading...' shows in LABEL_STATUS until the list pops up
                    self.setFocus(self.getControl(self.listing.main_focus))
                    gamelist_workflows.update_gamelist(self.ctx.gamelist, menu_item)

            elif action.getId() in ACTION_CONTEXT:

                menu_item = int(self.getControl(MAIN_MENU).getSelectedItem().getLabel2())
                # listmode menu
                if menu_item in (M_ALL, M_SOURCE, M_SWL, M_SERIES):
                    gamelist_workflows.update_gamelist(self.ctx.gamelist, menu_item)
                    self.setFocus(self.getControl(LISTMODE_MENU))
                # switch filter
                elif menu_item == M_FILTER:
                    if self.services.ggdb.gamelist.use_filter:
                        self.services.ggdb.gamelist.set_filter_enabled(False)
                        self.getControl(MAIN_MENU).getSelectedItem().setLabel(
                            tr(S.MENU_FILTER_OFF))
                    else:
                        self.services.ggdb.gamelist.set_filter_enabled(True)
                        self.getControl(MAIN_MENU).getSelectedItem().setLabel(
                            tr(S.MENU_FILTER_NAME, self.filters.act_filter))
                # update umsa db
                elif menu_item == M_UPD:
                    self.setFocus(self.getControl(self.listing.main_focus))
                    # umsa.db is closed for the update: not under a scan
                    if self._refuse_while_scanning():
                        return
                    scan_orchestrator.update(self.ctx.scan_orchestrator, 'db', CORE_DATA_PATHS)
                # shortcut to play status
                elif menu_item == M_EXIT:
                    gamelist_workflows.update_gamelist(self.ctx.gamelist, M_PLAYSTAT)
                # shortcut to last screensaver list
                elif menu_item == M_ASETTINGS:
                    gamelist_workflows.update_gamelist(self.ctx.gamelist, M_LSSAVER)
                # show all emulators
                elif menu_item == M_MACHINE:
                    gamelist_workflows.update_gamelist(self.ctx.gamelist, M_ALLEMUS)
                # call old search
                elif menu_item == M_SEARCH_NEW:
                    if self.listing.searchold:
                        gamelist_workflows.update_gamelist(self.ctx.gamelist, M_SEARCH)
                # directly play a youtube video
                elif menu_item == M_MEDIA:
                    yt_list = youtube_search(
                        split_gamename(self.software.actset['gamename'])[0],
                        self.software.actset['machine_name'])
                    playurl = f"plugin://plugin.video.youtube/play/?video_id={choice(yt_list)[0]}"
                    self.services.player.play(playurl, windowed=True)
                    # close menu
                    self.setFocus(self.getControl(self.listing.main_focus))
                # start random screensaver
                elif menu_item == M_SSAVER:
                    rand_saver = randint(1, 3)
                    # close menu
                    self.setFocus(self.getControl(self.listing.main_focus))
                    if rand_saver == 1:
                        screensaver_vgm.start_screensaver(self.ctx.screensaver_vgm, 'videos')
                    elif rand_saver == 2:
                        emulator_setup.marp_replayer(self.ctx.emulator_setup, random=True)
                    else:
                        screensaver_vgm.start_screensaver(self.ctx.screensaver_vgm, 'cross', ['snap'])

        # ACTION listmode submenu
        elif self.selected_control_id == LISTMODE_MENU:
            if action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_ENTER:
                gamelist_workflows.update_gamelist(self.ctx.gamelist,
                    int(self.getControl(LISTMODE_MENU).getSelectedItem().getLabel2())
                )
            elif action.getId() in ACTION_MOVEMENT_LEFT:
                self.setFocus(self.getControl(self.listing.main_focus))
            # load the list of the entry right away (like the filter categories)
            elif action.getId() in ACTION_LIST_SCROLL:
                gamelist_workflows.preview_listmode_gamelist(self.ctx.gamelist)
            # show all maker, swl, year
            elif action.getId() in ACTION_CONTEXT:
                gamelist_workflows.show_fulllist(self.ctx.gamelist,
                    int(self.getControl(LISTMODE_MENU).getSelectedItem().getLabel2()),
                    self.getControl(LISTMODE_MENU).getSelectedItem().getLabel())

        # ACTION SYSTEM_WRAPLIST
        elif self.selected_control_id == SYSTEM_WRAPLIST:
            xbmc.log("UMSA gui: onAction: MACHINE_LIST")
            self.listing.main_focus = SYSTEM_WRAPLIST
            if action.getId() in ACTION_MOVEMENT_RIGHT+ACTION_MOVEMENT_LEFT:
                software_selector.machine_move(self.ctx.software_selector)
            elif action.getId() in ACTION_MOVEMENT_DOWN+ACTION_MOVEMENT_UP:
                artwork_presenter.show_artwork(self.ctx.artwork_presenter, 'machine')
            elif action.getId() in ACTION_CONTEXT:
                if self.software.actset['swl_name'] == 'mame':
                    menu.build_main_menu(self.ctx.menu, M_SOURCE)
                else:
                    menu.build_main_menu(self.ctx.menu, M_SWL)
                self.setFocus(self.getControl(MAIN_MENU))

        # ACTION TEXTLIST
        elif self.selected_control_id == TEXTLIST:
            self.listing.main_focus = TEXTLIST
            if action.getId() in ACTION_CONTEXT:
                self.setFocus(self.getControl(MAIN_MENU))

        # ACTION GAME_LIST
        elif self.selected_control_id == GAME_LIST:
            if action.getId() in ACTION_ENTER:
                gamelist_actions.gamelist_click(self.ctx.gamelist_actions)
            elif action.getId() in ACTION_MOVEMENT_LEFT:
                self.setFocus(self.getControl(LISTMODE_MENU))
            elif action.getId() in ACTION_CONTEXT:
                gamelist_actions.gamelist_context(self.ctx.gamelist_actions)
            elif action.getId() in ACTION_LIST_SCROLL:
                gamelist_workflows.gamelist_move(self.ctx.gamelist)
                self.gamelist_settle.schedule()

        # ACTION FILTER_CATEGORY_LIST
        elif self.selected_control_id == FILTER_CATEGORY_LIST:
            xbmc.log("UMSA gui: onAction: FILTER_CATEGORY_LIST")

            if action.getId() in ACTION_ENTER:
                filter_ui.filter_category(self.ctx.filter_ui)
            elif action.getId() in ACTION_LIST_SCROLL:
                filter_ui.show_category_content(self.ctx.filter_ui)

        # ACTION FILTER_CONTENT_LIST_ACTIVE
        elif self.selected_control_id == FILTER_CONTENT_LIST_ACTIVE:
            xbmc.log("UMSA gui: onAction: FILTER_CONTENT_LIST_ACTIVE")

            if action.getId() in ACTION_ENTER:
                filter_ui.filter_content(self.ctx.filter_ui, 'active')

        # ACTION FILTER_CONTENT_LIST_INACTIVE
        elif self.selected_control_id == FILTER_CONTENT_LIST_INACTIVE:
            xbmc.log("UMSA gui: onAction: FILTER_CONTENT_LIST_INACTIVE")

            if action.getId() in ACTION_ENTER:
                filter_ui.filter_content(self.ctx.filter_ui, 'inactive')

        # ACTION SET_LIST
        elif self.selected_control_id == SET_LIST:
            self.listing.main_focus = SET_LIST
            # update actual set
            if action.getId() in ACTION_MOVEMENT_LEFT+ACTION_MOVEMENT_RIGHT:
                pos_m = self.getControl(SYSTEM_WRAPLIST).getSelectedPosition()
                pos_s = self.getControl(SET_LIST).getSelectedPosition()
                self.software.actset = self.software.info[pos_m][pos_s]
                # update SYSTEM_WRAPLIST image when different MAME driver is selected
                self.getControl(SYSTEM_WRAPLIST).getSelectedItem().setArt(
                    {'icon': artwork_presenter.get_machine_pic(
                        self.ctx.artwork_presenter, self.software.actset)}
                    )
                # update pics
                artwork_presenter.show_artwork(self.ctx.artwork_presenter, 'set')
            # update artwork
            elif action.getId() in ACTION_MOVEMENT_DOWN+ACTION_MOVEMENT_UP:
                artwork_presenter.show_artwork(self.ctx.artwork_presenter, 'set')
            # popup mainmenu
            elif action.getId() in ACTION_CONTEXT:
                menu.build_main_menu(self.ctx.menu, select=M_MACHINE)
                self.setFocus(self.getControl(MAIN_MENU))

    # --- settings -------------------------------------------------------

    def read_settings(self):
        """Read settings for UMSA from Kodi and initialize."""

        # all UMSA settings are owned by the Core add-on
        core_settings = get_core_settings()
        # effective MAME paths (optional settings resolved) and computed values
        emu_settings = load_all_settings(
            core_settings, RESOURCE_LIB, PLATFORM, home=os.path.expanduser('~')
        )

        self.settings.apply(core_settings, emu_settings)
        self._apply_settings_to_services()

    def _apply_settings_to_services(self):
        """Hand re-read settings to the objects that copied them in onInit.

        On the first call (from onInit) neither object exists yet; after the
        settings dialog the changes take effect without a restart. The
        aspect ratio is the exception: onInit scales the left image controls
        once, so it still needs a restart.
        """

        settings = self.settings
        emulation = self.services.emulation
        if emulation is not None:
            emulation.apply_settings(
                settings.temp_dir, settings.mameini, settings.mame_dir, settings.mame_exe,
                settings.chdman_exe, settings.nonmame, settings.terminal, settings.vgmplay_exe,
                settings.vgm_max_duration, rom_cache=settings.rom_cache,
                cache_layout=settings.cache_layout, vgm_port=settings.vgm_port)
        ggdb = self.services.ggdb
        if ggdb is not None:
            ggdb.nonmame = settings.nonmame
            ggdb.pref_country = settings.pref_country

    # --- emulators ------------------------------------------------------

    def run_emulator(self, emu_infos):
        """Prepare commandline options for emulator and start emulator."""

        if emu_infos.get('exe') == 'kodi':
            rp_ctx = RetroplayerCtx(
                actset=self.software.actset,
                emulation=self.services.emulation,
                ggdb=self.services.ggdb,
                emu_dialog=self.services.emu_dialog,
                dialog=self.services.dialog,
                player=self.services.player,
                rom_cache=self.settings.rom_cache,
                cache_layout=self.settings.cache_layout,
                wait=self.services.abort_wait,
            )
            rp_ctx.stop_screensaver = screensaver_vgm.stop_screensaver
            rp_ctx.exit = self.exit
            run_retroplayer(rp_ctx)
            return

        ctx = LaunchCtx(
            actset=self.software.actset,
            emu_infos=emu_infos,
            emulation=self.services.emulation,
            ggdb=self.services.ggdb,
            emu_dialog=self.services.emu_dialog,
            dialog=self.services.dialog,
            player=self.services.player,
            mame_dir=self.settings.mame_dir,
            emulation_start=self.settings.emulation_start,
            playvideo=self.settings.playvideo,
            stop_screensaver=screensaver_vgm.stop_screensaver,
            get_screensaver_mode=screensaver_vgm.get_screensaver_mode,
            set_emulator_running=set_emulator_running,
            search_snaps=functools.partial(
                artwork_presenter.search_snaps, self.ctx.artwork_presenter),
            show_artwork=functools.partial(
                artwork_presenter.show_artwork, self.ctx.artwork_presenter),
            add_or_update_emu_output=functools.partial(
                emulator_setup.add_or_update_emu_output, self.ctx.emulator_setup),
            notify_final=functools.partial(
                emulator_setup.notify_final_launch, self.ctx.emulator_setup),
            sleep=xbmc.sleep,
            wait=self.services.abort_wait,
            on_shutdown=self.exit,
        )
        launch_emulator(ctx)

    # --- scans ----------------------------------------------------------

    def _scan_running(self):
        """Return whether a scan thread is alive; forget a finished one."""

        if self.scan_thread and not self.scan_thread.is_alive():
            self.scan_thread = None
        return bool(self.scan_thread)

    def _refuse_while_scanning(self):
        """Tell the user that a scan runs; True when the caller must stop."""

        if not self._scan_running():
            return False
        self.services.dialog.notification(
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
            scan_orchestrator.update(self.ctx.scan_orchestrator, what, CORE_DATA_PATHS)
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
            software_selector.open_software(self.ctx.software_selector, value)

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

        if self._resources_released:
            return
        self._resources_released = True

        self.requests.close()
        self.gamelist_settle.cancel()

        # random playback sits between two tracks with playvgm off; a window
        # that closed before its first init has no emulation yet
        emulation = self.services.emulation
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
            if self.services.scans is not None:
                self.services.scans.state.request_stop()
                xbmc.log('UMSA gui: exit: requested scan stop', xbmc.LOGDEBUG)
        except Exception as exc:
            xbmc.log(f"UMSA gui: exit: could not request scan stop: {exc}", xbmc.LOGERROR)

        scan_alive = False
        try:
            scan_thread = self.scan_thread
            if scan_thread and scan_thread.is_alive():
                try:
                    scan_thread.join(timeout=5)
                except Exception as exc:
                    xbmc.log(f"UMSA gui: exit: could not join scan thread: {exc}", xbmc.LOGERROR)
                scan_alive = scan_thread.is_alive()
        except Exception as exc:
            xbmc.log(f"UMSA gui: exit: could not inspect scan thread: {exc}", xbmc.LOGERROR)

        with _SCAN_LOCK:
            if scan_alive and not self._scan_ended:
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
    gui = UMSA("umsa_estuary.xml", ADDON_PATH, "default", "1080i")
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
        if not gui._close_db_after_scan:
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
