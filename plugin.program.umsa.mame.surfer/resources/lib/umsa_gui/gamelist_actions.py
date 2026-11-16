"""Activation of a gamelist entry.

The module reacts on a click or a context action in the game list: it starts
emulators, plays media, changes the machine of a set or selects a new software.
"""

import os
import traceback
import zipfile
from dataclasses import dataclass
from json import dumps

import xbmc
import xbmcgui
from umsa_core import ProcessRunner, calculate_playback_plan, log, parse_vgm_header
from umsa_core.emulation import format_vgm_title
from umsa_core.game_labels import split_gamename
from umsa_core.support import marp_search

from . import (
    artwork_presenter,
    emulator_setup,
    error_notify,
    optional_plugins,
    software_selector,
)
from . import gamelist as gamelist_workflows
from . import strings as S
from .constants import (
    ACTION_CHOOSE_EMULATOR,
    ACTION_START_EXODOS,
    ACTION_START_EXODOS_ALT,
    ACTION_START_KODI,
    ACTION_START_MAME,
    ENTRY_ACTION,
    ENTRY_SEARCH,
    ENTRY_SERIES,
    GAME_LIST,
    KIND_MACHINES,
    KIND_MEDIA,
    KIND_SELECT,
    M_ALLEMUS,
    M_CAT,
    M_MACHINE,
    M_MAKER,
    M_MEDIA,
    M_PLAYERS,
    M_SWL,
    M_YEAR,
    SEARCH_MARP,
    SEARCH_YOUTUBE,
    SET_LIST,
    SYSTEM_WRAPLIST,
)
from .strings import tr

# emulators started by the action rows of the machine list
ACTION_EMULATORS = {
    ACTION_START_MAME: {'name': "MAME", 'exe': "mame"},
    ACTION_START_KODI: {'name': "Retroplayer", 'exe': "kodi"},
    ACTION_START_EXODOS: {'name': "eXoDOS", 'exe': "exodos"},
    ACTION_START_EXODOS_ALT: {'name': "exoDOS Alternate", 'exe': "exodos_alt"},
}

# Gamelist query (``DBMod.gamelist``) behind an entry of a "Select ..." list, by menu code
SELECT_QUERIES = {
    M_SWL: 'get_by_swl',
    M_CAT: 'get_by_cat',
    M_MAKER: 'get_by_maker',
    M_YEAR: 'get_by_year',
    M_PLAYERS: 'get_by_players',
}


@dataclass
class GamelistActionsCtx:
    """What a click or a context action on a game list entry needs."""

    view: object = None
    services: object = None
    software: object = None
    listing: object = None
    settings: object = None
    # window callbacks: start the emulator, close the add-on
    run_emulator: object = None
    exit: object = None
    # contexts of the modules an entry leads to
    emulator: object = None
    gamelist: object = None
    artwork: object = None
    selector: object = None


def gamelist_click(ctx):
    """Reacts on click in gamelist"""

    what = ""
    selected = ctx.view.getControl(GAME_LIST).getSelectedItem()
    list_id = selected.getLabel2()
    if "::" in list_id:
        what, list_id = list_id.split("::")
    if list_id == "0":
        return
    select_label = selected.getLabel()
    # the set a click selects (search results); read before the list changes
    set_id = selected.getProperty('set_id')
    kind = ctx.listing.gamelist_kind

    xbmc.log(f"UMSA gui: gamelist_click: what {what}, list_id {list_id}, kind {kind}, select_label {select_label}")

    # prev or next
    if list_id in ('prev', 'next'):
        # get prev/next results
        if list_id == 'prev':
            sid = int(ctx.view.getControl(GAME_LIST).getListItem(1).getLabel2())
        else:
            size = ctx.view.getControl(GAME_LIST).size()
            sid = int(ctx.view.getControl(GAME_LIST).getListItem(size - 2).getLabel2())
        gamelist, pos, _result_count = ctx.services.ggdb.gamelist.execute_statement(
            software_id=sid, prevnext=list_id)
        # create list
        list_items = gamelist_workflows.list_items(gamelist)
        # show
        ctx.view.getControl(GAME_LIST).reset()
        ctx.view.getControl(GAME_LIST).addItems(list_items)
        ctx.view.getControl(GAME_LIST).selectItem(pos)
        ctx.view.setFocus(ctx.view.getControl(GAME_LIST))
        return
    if kind == KIND_SELECT:
        if list_id == 'source':
            my_list, pos, count = ctx.services.ggdb.gamelist.get_software_for_source(
                ctx.software.actset['id'], select_label)
        else:
            query = getattr(
                ctx.services.ggdb.gamelist, SELECT_QUERIES[ctx.listing.gamelist_select])
            my_list, pos, count = query(list_id, ctx.software.actset['id'])
        gamelist_workflows.popup_gamelist(ctx.gamelist, my_list, f"{select_label} ({count})", pos)
        return
    # series row of the search list: the series list replaces it
    if what == ENTRY_SERIES:
        entries = ctx.services.ggdb.games.get_series_entries(int(list_id))
        if entries:
            gamelist_workflows.popup_gamelist(ctx.gamelist, entries, tr(S.LIST_SERIES))
        return

    # close window
    ctx.listing.enter = True
    ctx.view.setFocus(ctx.view.getControl(ctx.listing.main_focus))

    # action rows of the machine list: choose emulator for source/swl or
    # start with MAME, Kodi RetroPlayer or an eXoDOS shell launcher
    if kind == KIND_MACHINES and what == ENTRY_ACTION:
        if list_id == ACTION_CHOOSE_EMULATOR:
            emulator_setup.get_diff_emulator(ctx.emulator)
        else:
            ctx.run_emulator(dict(ACTION_EMULATORS[list_id]))
    # emulator run
    elif what == "emu_conn":
        ctx.run_emulator(ctx.services.ggdb.emulators.get_emulator(emu_conn_id=list_id))
    # change/delete emulator
    elif what == "emu":
        if (ctx.services.dialog.yesno(
                tr(S.EMU_TITLE, select_label), tr(S.EMU_WHAT_TO_DO),
                nolabel=tr(S.EMU_RECONFIGURE), yeslabel=tr(S.EMU_DELETE))
           ):
            if (ctx.services.dialog.yesno(
                    tr(S.EMU_DELETE_TITLE), tr(S.EMU_DELETE_CONFIRM, select_label))
               ):
                ctx.services.ggdb.emulators.delete_emulator(list_id)
                gamelist_workflows.update_gamelist(ctx.gamelist, M_ALLEMUS)
        else:
            emulator_setup.configure_emulator(ctx.emulator,
                emu_info=ctx.services.ggdb.emulators.get_emulator(emu_id=list_id), reconfigure=True)
    # set machine for swl
    elif kind == KIND_MACHINES:
        ctx.view.setFocus(ctx.view.getControl(ctx.listing.main_focus))
        ctx.listing.enter = True
        # get info from db
        machine_name, machine_label = ctx.services.ggdb.games.get_machine_name(list_id)
        # save machine for set in self.info
        ctx.software.actset['machine_name'] = machine_name
        ctx.software.actset['machine_label'] = machine_label
        # scanned cabinet of the new machine (own artwork first)
        ctx.software.machine_cabinets.update(ctx.services.ggdb.art_queries.get_machine_cabinets([machine_name]))
        # set new image and machine label
        ctx.view.getControl(SYSTEM_WRAPLIST).getSelectedItem().setArt(
            {'icon': artwork_presenter.get_machine_pic(ctx.artwork, ctx.software.actset)})
        ctx.view.getControl(SET_LIST).getSelectedItem().setProperty(
            'Machine', machine_label)
    # play media
    elif kind == KIND_MEDIA:
        # video
        if list_id[-3:] == 'mp4':
            try:
                list_item = xbmcgui.ListItem(select_label)
                ctx.services.player.play(list_id, listitem=list_item, windowed=True)
            except Exception as error:  # noqa: BLE001 - reported to the user
                _report(ctx, S.MEDIA_VIDEO_FAILED, f'video {list_id!r}', error)
        # pdf viewer
        elif list_id[-3:] == 'pdf':
            open_manual(ctx, list_id)
        # marp
        elif list_id[-3:] == 'zip':
            emulator_setup.marp_replayer(ctx.emulator, dl_file=list_id, set_name=what)
        # vgm
        elif what == "vgm":
            try:
                _play_vgm(ctx, list_id)
            except Exception as error:  # noqa: BLE001 - reported to the user
                _report(ctx, S.VGM_FAILED, f'VGM {list_id!r}', error)
        # youtube
        elif what == "yt":
            try:
                ctx.services.player.play(
                    f"plugin://plugin.video.youtube/play/?video_id={list_id}",
                    windowed=True)
            except Exception as error:  # noqa: BLE001 - reported to the user
                _report(ctx, S.MEDIA_YOUTUBE_FAILED, f'youtube video {list_id!r}', error)
        # search marp, youtube
        elif what == ENTRY_SEARCH and list_id == SEARCH_YOUTUBE:
            yt_search_url = "plugin://plugin.video.youtube/kodion/search/query/?category_label=REPLACE&incognito=True&q=REPLACE&type=video"
            try:
                yt_search_str = f"{split_gamename(ctx.software.actset['gamename'])[0]} {ctx.software.actset['machine_name']}".replace(' ', '%20')
                ctx.exit()
                xbmc.executebuiltin(f"ActivateWindow(Videos,{yt_search_url.replace('REPLACE',yt_search_str)},return)")
            except Exception as error:  # noqa: BLE001 - reported to the user
                _report(ctx, S.MEDIA_YOUTUBE_FAILED, 'youtube search', error)

        elif what == ENTRY_SEARCH and list_id == SEARCH_MARP:
            if ctx.software.actset['swl_name'] == "mame":
                try:
                    ctx.services.ggdb.status.save_further_media(
                        ctx.software.actset['id'], marp=dumps(
                            marp_search(short_name=ctx.software.actset['name'])))
                except Exception as error:  # noqa: BLE001 - reported to the user
                    _report(ctx, S.MARP_FAILED, 'MARP search', error)
                    return
            gamelist_workflows.update_gamelist(ctx.gamelist, M_MEDIA)
    # select new software
    else:
        xbmc.log(f"UMSA gui: gamelist_click: software id={list_id}")
        software_id = int(list_id)
        if set_id:
            software_selector.remember_and_select(
                ctx.selector, software_id, set_id=int(set_id))
        else:
            software_selector.remember_and_select(ctx.selector, software_id)


def _report(ctx, title_id, what, error):
    """Log a failed media action with its traceback and tell the user (E-1)."""

    log(f'UMSA gui: {what} failed: {error}\n{traceback.format_exc()}', level='error')
    error_notify.notify_error(ctx.services.dialog, title_id, error=error)


def _play_vgm(ctx, list_id):
    """Let the user pick a track of the VGM set ``list_id`` and play it.

    A refused start (``play_vgm`` returns False: a playback runs) stays
    silent (C-M9).
    """

    vgm_zipfile = ctx.services.emulation.find_roms('vgmplay', list_id)
    xbmc.log(f"UMSA gui: get vgmfile - {vgm_zipfile}")
    vgm_tracklist = zipfile.ZipFile(vgm_zipfile).namelist()
    select = vgm_tracklist.copy()
    if select:
        which_track = ctx.services.dialog.select(tr(S.SELECT_VGM_TRACK), select)
        if which_track > -1:
            track = vgm_tracklist[which_track]
            header = parse_vgm_header(vgm_zipfile, track, logger=log)
            plan = calculate_playback_plan(
                header,
                max_seconds=ctx.settings.vgm_max_duration)
            # Core turns the title into "<title> -MM:ss (<dB> dB)"
            title = format_vgm_title(track, ctx.software.actset['gamename'])
            ctx.services.emulation.play_vgm(
                f'{list_id}:{which_track+1:03d}',
                info=title, plan=plan)


def open_manual(ctx, path):
    """Open a PDF manual.

    The Kodi PDF reader add-on is used when it is installed, else the
    external viewer of the settings; without both the user is told so and
    the window stays open.
    """

    if optional_plugins.KODIPDF:
        # the reader takes over the display
        ctx.exit()
        try:
            optional_plugins.play_pdf(path, compress=True, is_image_plugin=False)
        except Exception as error:  # noqa: BLE001 - reported to the user
            # the window is closed already, the notification shows anyway
            _report(ctx, S.MEDIA_MANUAL_FAILED, f'manual {path!r}', error)
        return
    viewer = ctx.settings.pdfviewer
    if not viewer:
        ctx.services.dialog.notification(
            tr(S.MANUAL_TITLE), tr(S.MANUAL_NO_VIEWER),
            xbmcgui.NOTIFICATION_ERROR, 5000)
        return
    # the viewer is a program of its own: the window stays open, nothing waits
    try:
        runner = ProcessRunner()
        runner.start([viewer, path], cwd=os.path.dirname(viewer) or '.')
    except OSError as error:
        log(
            f'UMSA gui: could not start PDF viewer {viewer!r}: {error}',
            level='error')
        ctx.services.dialog.notification(
            tr(S.MANUAL_TITLE), tr(S.MANUAL_VIEWER_FAILED, viewer),
            xbmcgui.NOTIFICATION_ERROR, 5000)
        return
    # keeps the process owned; a second manual replaces it
    ctx.services.manual_viewer = runner


def gamelist_context(ctx):
    """Reacts on context in gamelist"""

    what = ""
    list_id = ctx.view.getControl(GAME_LIST).getSelectedItem().getLabel2()
    if "::" in list_id:
        what, list_id = list_id.split("::")
    label = ctx.view.getControl(GAME_LIST).getSelectedItem().getLabel()

    xbmc.log(f"UMSA gui: gamelist_context: what {what}, list_id {list_id}, label {label}")

    # reconfigure/remove connection
    if what == "emu_conn":
        if ctx.services.dialog.yesno(
                tr(S.EMU_TITLE, label), tr(S.EMU_WHAT_TO_DO),
                nolabel=tr(S.EMU_RECONFIGURE), yeslabel=tr(S.EMU_REMOVE)):
            last_emu_id = ctx.services.ggdb.emulators.delete_emulator_connection(list_id)
            if last_emu_id and ctx.services.dialog.yesno(
                    tr(S.EMU_DELETE_TITLE),
                    tr(S.EMU_DELETE_LAST_CONNECTION, label)):
                ctx.services.ggdb.emulators.delete_emulator(last_emu_id)
            gamelist_workflows.update_gamelist(ctx.gamelist, M_MACHINE)
        else:
            xbmc.log("UMSA gui: reconfigure emulator")
            xbmc.log(f"UMSA gui: {list_id}")
            xbmc.log(f'UMSA gui: {dict(ctx.services.ggdb.emulators.get_emulator(emu_conn_id=list_id))}')
            emulator_setup.configure_emulator(ctx.emulator,
                emu_info=ctx.services.ggdb.emulators.get_emulator(emu_conn_id=list_id), reconfigure=True)
    # switch filter
    else:
        gamelist_workflows.gamelist_switch_filter(ctx.gamelist)
