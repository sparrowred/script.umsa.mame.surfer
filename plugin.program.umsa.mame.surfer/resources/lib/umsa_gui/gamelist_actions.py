"""Activation of a gamelist entry.

The module reacts on a click or a context action in the game list: it starts
emulators, plays media, changes the machine of a set or selects a new software.
"""

import os
import zipfile
from json import dumps

import xbmc
import xbmcgui
from umsa_core import ProcessRunner, calculate_playback_plan, log, parse_vgm_header
from umsa_core.database import split_gamename
from umsa_core.emulation import format_vgm_title
from umsa_core.support import marp_search
from umsa_core.vgm_header import MAX_PLAYBACK_SECONDS

from . import optional_plugins
from . import strings as S
from .constants import (
    ACTION_CHOOSE_EMULATOR,
    ACTION_START_EXODOS,
    ACTION_START_EXODOS_ALT,
    ACTION_START_KODI,
    ACTION_START_MAME,
    ENTRY_ACTION,
    ENTRY_SEARCH,
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

# DBMod query behind an entry of a "Select ..." list, by menu code
SELECT_QUERIES = {
    M_SWL: 'get_by_swl',
    M_CAT: 'get_by_cat',
    M_MAKER: 'get_by_maker',
    M_YEAR: 'get_by_year',
    M_PLAYERS: 'get_by_players',
}


def gamelist_click(gui):
    """Reacts on click in gamelist"""

    what = ""
    list_id = gui.getControl(GAME_LIST).getSelectedItem().getLabel2()
    if "::" in list_id:
        what, list_id = list_id.split("::")
    if list_id == "0":
        return
    select_label = gui.getControl(GAME_LIST).getSelectedItem().getLabel()
    kind = gui.gamelist_kind

    xbmc.log(f"UMSA gui: gamelist_click: what {what}, list_id {list_id}, kind {kind}, select_label {select_label}")

    # prev or next
    if list_id in ('prev', 'next'):
        # get prev/next results
        if list_id == 'prev':
            sid = int(gui.getControl(GAME_LIST).getListItem(1).getLabel2())
        else:
            size = gui.getControl(GAME_LIST).size()
            sid = int(gui.getControl(GAME_LIST).getListItem(size - 2).getLabel2())
        gamelist, pos, _result_count = gui.ggdb.execute_statement(
            software_id=sid, prevnext=list_id)
        # create list
        list_items = []
        for i in gamelist:
            list_item = xbmcgui.ListItem(i['name'], str(i['id']))
            list_item.setInfo(
                'video', {'Writer': i['year'], 'Studio': i['maker'],}
                )
            list_items.append(list_item)
        # show
        gui.getControl(GAME_LIST).reset()
        gui.getControl(GAME_LIST).addItems(list_items)
        gui.getControl(GAME_LIST).selectItem(pos)
        gui.setFocus(gui.getControl(GAME_LIST))
        return
    if kind == KIND_SELECT:
        if list_id == 'source':
            my_list, pos, count = gui.ggdb.get_software_for_source(
                gui.actset['id'], select_label)
        else:
            query = getattr(gui.ggdb, SELECT_QUERIES[gui.gamelist_select])
            my_list, pos, count = query(list_id, gui.actset['id'])
        gui.popup_gamelist(my_list, f"{select_label} ({count})", pos)
        return

    # close window
    gui.enter = True
    gui.setFocus(gui.getControl(gui.main_focus))

    # action rows of the machine list: choose emulator for source/swl or
    # start with MAME, Kodi RetroPlayer or an eXoDOS shell launcher
    if kind == KIND_MACHINES and what == ENTRY_ACTION:
        if list_id == ACTION_CHOOSE_EMULATOR:
            gui.get_diff_emulator()
        else:
            gui.run_emulator(dict(ACTION_EMULATORS[list_id]))
    # emulator run
    elif what == "emu_conn":
        gui.run_emulator(gui.ggdb.get_emulator(emu_conn_id=list_id))
    # change/delete emulator
    elif what == "emu":
        if (gui.dialog.yesno(
                tr(S.EMU_TITLE, select_label), tr(S.EMU_WHAT_TO_DO),
                nolabel=tr(S.EMU_RECONFIGURE), yeslabel=tr(S.EMU_DELETE))
           ):
            if (gui.dialog.yesno(
                    tr(S.EMU_DELETE_TITLE), tr(S.EMU_DELETE_CONFIRM, select_label))
               ):
                gui.ggdb.delete_emulator(list_id)
                gui.update_gamelist(M_ALLEMUS)
        else:
            gui.configure_emulator(
                emu_info=gui.ggdb.get_emulator(emu_id=list_id), reconfigure=True)
    # set machine for swl
    elif kind == KIND_MACHINES:
        gui.setFocus(gui.getControl(gui.main_focus))
        gui.enter = True
        # get info from db
        machine_name, machine_label = gui.ggdb.get_machine_name(list_id)
        # save machine for set in self.info
        gui.actset['machine_name'] = machine_name
        gui.actset['machine_label'] = machine_label
        # scanned cabinet of the new machine (own artwork first)
        gui.machine_cabinets.update(gui.ggdb.get_machine_cabinets([machine_name]))
        # set new image and machine label
        gui.getControl(SYSTEM_WRAPLIST).getSelectedItem().setArt(
            {'icon': gui.get_machine_pic(gui.actset)})
        gui.getControl(SET_LIST).getSelectedItem().setProperty(
            'Machine', machine_label)
    # play media
    elif kind == KIND_MEDIA:
        # video
        if list_id[-3:] == 'mp4':
            list_item = xbmcgui.ListItem(select_label)
            gui.player.play(list_id, listitem=list_item, windowed=True)
        # pdf viewer
        elif list_id[-3:] == 'pdf':
            open_manual(gui, list_id)
        # marp
        elif list_id[-3:] == 'zip':
            gui.marp_replayer(dl_file=list_id, set_name=what)
        # vgm
        elif what == "vgm":
            vgm_zipfile = gui.emulation.find_roms('vgmplay', list_id)
            xbmc.log(f"UMSA gui: get vgmfile - {vgm_zipfile}")
            vgm_tracklist = zipfile.ZipFile(vgm_zipfile).namelist()
            select = vgm_tracklist.copy()
            if select:
                which_track = gui.dialog.select(tr(S.SELECT_VGM_TRACK), select)
                if which_track > -1:
                    track = vgm_tracklist[which_track]
                    header = parse_vgm_header(vgm_zipfile, track, logger=log)
                    plan = calculate_playback_plan(
                        header,
                        max_seconds=getattr(gui, 'vgm_max_duration', MAX_PLAYBACK_SECONDS))
                    # Core turns the title into "<title> -MM:ss (<dB> dB)"
                    title = format_vgm_title(track, gui.actset['gamename'])
                    gui.emulation.play_vgm(
                        f'{list_id}:{which_track+1:03d}', sleep=xbmc.sleep,
                        info=title, plan=plan)
        # youtube
        elif what == "yt":
            gui.player.play(
                f"plugin://plugin.video.youtube/play/?video_id={list_id}",
                windowed=True)
        # search marp, youtube
        elif what == ENTRY_SEARCH and list_id == SEARCH_YOUTUBE:
            yt_search_url = "plugin://plugin.video.youtube/kodion/search/query/?category_label=REPLACE&incognito=True&q=REPLACE&type=video"
            yt_search_str = f"{split_gamename(gui.actset['gamename'])[0]} {gui.actset['machine_name']}".replace(' ', '%20')
            gui.exit()
            xbmc.executebuiltin(f"ActivateWindow(Videos,{yt_search_url.replace('REPLACE',yt_search_str)},return)")

        elif what == ENTRY_SEARCH and list_id == SEARCH_MARP:
            if gui.actset['swl_name'] == "mame":
                gui.ggdb.save_further_media(
                    gui.actset['id'], marp=dumps(
                        marp_search(short_name=gui.actset['name'])))
            gui.update_gamelist(M_MEDIA)
    # select new software
    else:
        xbmc.log(f"UMSA gui: gamelist_click: software id={list_id}")
        software_id = int(list_id)
        gui._remember_and_select(software_id)


def open_manual(gui, path):
    """Open a PDF manual.

    The Kodi PDF reader add-on is used when it is installed, else the
    external viewer of the settings; without both the user is told so and
    the window stays open.
    """

    if optional_plugins.KODIPDF:
        # the reader takes over the display
        gui.exit()
        optional_plugins.play_pdf(path, compress=True, is_image_plugin=False)
        return
    viewer = getattr(gui, 'pdfviewer', '')
    if not viewer:
        gui.dialog.notification(
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
        gui.dialog.notification(
            tr(S.MANUAL_TITLE), tr(S.MANUAL_VIEWER_FAILED, viewer),
            xbmcgui.NOTIFICATION_ERROR, 5000)
        return
    # keeps the process owned; a second manual replaces it
    gui.manual_viewer = runner


def gamelist_context(gui):
    """Reacts on context in gamelist"""

    what = ""
    list_id = gui.getControl(GAME_LIST).getSelectedItem().getLabel2()
    if "::" in list_id:
        what, list_id = list_id.split("::")
    label = gui.getControl(GAME_LIST).getSelectedItem().getLabel()

    xbmc.log(f"UMSA gui: gamelist_context: what {what}, list_id {list_id}, label {label}")

    # reconfigure/remove connection
    if what == "emu_conn":
        if gui.dialog.yesno(
                tr(S.EMU_TITLE, label), tr(S.EMU_WHAT_TO_DO),
                nolabel=tr(S.EMU_RECONFIGURE), yeslabel=tr(S.EMU_REMOVE)):
            last_emu_id = gui.ggdb.delete_emulator_connection(list_id)
            if last_emu_id and gui.dialog.yesno(
                    tr(S.EMU_DELETE_TITLE),
                    tr(S.EMU_DELETE_LAST_CONNECTION, label)):
                gui.ggdb.delete_emulator(last_emu_id)
            gui.update_gamelist(M_MACHINE)
        else:
            xbmc.log("UMSA gui: reconfigure emulator")
            xbmc.log(f"UMSA gui: {list_id}")
            xbmc.log(f'UMSA gui: {dict(gui.ggdb.get_emulator(emu_conn_id=list_id))}')
            gui.configure_emulator(
                emu_info=gui.ggdb.get_emulator(emu_conn_id=list_id), reconfigure=True)
    # switch filter
    else:
        gui.gamelist_switch_filter()
