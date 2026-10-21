"""Activation of a gamelist entry.

The module reacts on a click or a context action in the game list: it starts
emulators, plays media, changes the machine of a set or selects a new software.
"""

import os
import zipfile
from json import dumps

import xbmc
import xbmcgui
from umsa_core import calculate_playback_plan, log, parse_vgm_header
from umsa_core.database import split_gamename
from umsa_core.emulation import format_vgm_info
from umsa_core.support import marp_search

from .constants import (
    GAME_LIST,
    GAME_LIST_LABEL,
    M_ALLEMUS,
    M_MACHINE,
    M_MEDIA,
    SET_LIST,
    SYSTEM_WRAPLIST,
)
from .optional_plugins import play_pdf


def gamelist_click(gui):
    """Reacts on click in gamelist"""

    what = ""
    list_id = gui.getControl(GAME_LIST).getSelectedItem().getLabel2()
    if "::" in list_id:
        what, list_id = list_id.split("::")
    if list_id == "0":
        return
    select_label = gui.getControl(GAME_LIST).getSelectedItem().getLabel()
    label = gui.getControl(GAME_LIST_LABEL).getLabel()

    xbmc.log(f"UMSA gui: gamelist_click: what {what}, list_id {list_id}, label {label}, select_label {select_label}")

    # prev or next
    if list_id in ('prev', 'next'):
        # get prev/next results
        if list_id == 'prev':
            sid = int(gui.getControl(GAME_LIST).getListItem(1).getLabel2())
        else:
            size = gui.getControl(GAME_LIST).size()
            sid = int(gui.getControl(GAME_LIST).getListItem(size - 2).getLabel2())
        gamelist, pos, result_count = gui.ggdb.execute_statement(
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
    if label[:7] == "Select ":
        if list_id == 'source':
            my_list, pos, count = gui.ggdb.get_software_for_source(
                gui.actset['id'], select_label)
        elif 'Softwarelist' in label:
            my_list, pos, count = gui.ggdb.get_by_swl(list_id, gui.actset['id'])
        elif 'Category' in label:
            my_list, pos, count = gui.ggdb.get_by_cat(list_id, gui.actset['id'])
        elif 'Maker' in label:
            my_list, pos, count = gui.ggdb.get_by_maker(list_id, gui.actset['id'])
        elif 'Year' in label:
            my_list, pos, count = gui.ggdb.get_by_year(list_id, gui.actset['id'])
        elif 'Players' in label:
            my_list, pos, count = gui.ggdb.get_by_players(list_id, gui.actset['id'])
        gui.popup_gamelist(my_list, f"{select_label} ({count})", pos)
        return

    # close window
    gui.enter = True
    gui.setFocus(gui.getControl(gui.main_focus))

    # choose emulator for source/swl
    if select_label == "Choose a different emulator":
        gui.get_diff_emulator()
    # start with mame exe
    elif select_label == "Start with M.A.M.E.":
        gui.run_emulator({'name': "MAME", 'exe': "mame"})
    # start kodi retroplayer
    elif select_label == "Start with Kodi Retroplayer":
        gui.run_emulator({'name': "Retroplayer", 'exe': "kodi"})
    # start exodos shell
    elif select_label == "Start eXoDOS Shell launcher":
        gui.run_emulator({'name': "eXoDOS", 'exe': "exodos"})
    elif select_label == "Start eXoDOS Alternate Shell launcher":
        gui.run_emulator({'name': "exoDOS Alternate", 'exe': "exodos_alt"})
    # emulator run
    elif what == "emu_conn":
        gui.run_emulator(gui.ggdb.get_emulator(emu_conn_id=list_id))
    # change/delete emulator
    elif what == "emu":
        if (gui.dialog.yesno(
                f"Emulator {select_label}", "What shall we do?",
                nolabel="Reconfigure", yeslabel="Delete")
           ):
            if (gui.dialog.yesno(
                    'Delete emulator', f'Really delete {select_label}?')
               ):
                gui.ggdb.delete_emulator(list_id)
                gui.update_gamelist(M_ALLEMUS)
        else:
            gui.configure_emulator(
                emu_info=gui.ggdb.get_emulator(emu_id=list_id), reconfigure=True)
    # set machine for swl
    elif 'Machines for' in label:
        gui.setFocus(gui.getControl(gui.main_focus))
        gui.enter = True
        # get info from db
        machine_name, machine_label = gui.ggdb.get_machine_name(list_id)
        # set new image and machine label
        gui.getControl(SYSTEM_WRAPLIST).getSelectedItem().setArt(
            {'icon': os.path.join(gui.cab_path, machine_name + '.png')})
        gui.getControl(SET_LIST).getSelectedItem().setProperty(
            'Machine', machine_label)
        # save machine for set in self.info
        gui.actset['machine_name'] = machine_name
        gui.actset['machine_label'] = machine_label
    # play media
    elif label == "Choose Media":
        # video
        if list_id[-3:] == 'mp4':
            list_item = xbmcgui.ListItem(select_label)
            gui.player.play(list_id, listitem=list_item, windowed=True)
        # pdf viewer
        elif list_id[-3:] == 'pdf':
            gui.exit()
            play_pdf(list_id, compress=True, is_image_plugin=False)
            #Popen([gui.pdfviewer, list_id])
        # marp
        elif list_id[-3:] == 'zip':
            gui.marp_replayer(dl_file=list_id, set_name=what)
        # vgm
        elif what == "vgm":
            select = []
            vgm_zipfile = gui.emulation.find_roms('vgmplay', list_id)
            xbmc.log(f"UMSA gui: get vgmfile - {vgm_zipfile}")
            vgm_tracklist = zipfile.ZipFile(vgm_zipfile).namelist()
            for vgm in vgm_tracklist:
                select.append(vgm)
            if select:
                which_track = gui.dialog.select('Select VGM track:', select)
                if which_track > -1:
                    track = vgm_tracklist[which_track]
                    header = parse_vgm_header(vgm_zipfile, track, logger=log)
                    plan = calculate_playback_plan(header)
                    nice = format_vgm_info(
                        track, gui.actset['gamename'], header, plan)
                    gui.emulation.play_vgm(
                        f'{list_id}:{which_track+1:03d}', sleep=xbmc.sleep,
                        info=nice, plan=plan)
        # youtube
        elif what == "yt":
            gui.player.play(
                f"plugin://plugin.video.youtube/play/?video_id={list_id}",
                windowed=True)
        # search marp, youtube
        elif select_label[:9] == "- Youtube":
            yt_search_url = "plugin://plugin.video.youtube/kodion/search/query/?category_label=REPLACE&incognito=True&q=REPLACE&type=video"
            yt_search_str = f"{split_gamename(gui.actset['gamename'])[0]} {gui.actset['machine_name']}".replace(' ', '%20')
            gui.exit()
            xbmc.executebuiltin(f"ActivateWindow(Videos,{yt_search_url.replace('REPLACE',yt_search_str)},return)")

        elif select_label[:8] == "- Replay":
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
        if (gui.dialog.yesno(
                f"Emulator {label}", "What shall we do?",
                nolabel="Reconfigure", yeslabel="Remove")):
            last_emu_id = gui.ggdb.delete_emulator_connection(list_id)
            if last_emu_id:
                if (gui.dialog.yesno(
                        'Delete emulator',
                        f'No other connection for {label}, delete?')):
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
