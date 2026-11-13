"""Software, set and machine selection of the UMSA frontend.

``select_software`` is the central display routine: it loads the sets of a
software, fills the skin controls and starts the optional intro video or VGM.
"""

import time
from random import choice

import xbmc
import xbmcgui
from umsa_core.artwork import machine_set_name
from umsa_core.game_labels import split_gamename

from . import strings as S
from .constants import (
    COMPILATION_LABEL,
    LABEL_STATUS,
    MACHINE_COUNT,
    MACHINE_PLUS,
    MACHINE_SEP1,
    MACHINE_SEP2,
    MACHINE_SEP3,
    MEDIA_LABEL,
    SET_LIST,
    SYSTEM_BORDER,
    SYSTEM_WRAPLIST,
    TEXTLIST,
)
from .strings import tr


def fill_set_list(gui, pos):
    """Fill the set list"""

    gui.getControl(SET_LIST).reset()
    length = len(gui.info[pos])
    set_list_items = []
    for count, i in enumerate(gui.info[pos], start=1):
        gamename, gamedetail = split_gamename(i['gamename'])

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
            label = f'{gamedetail}'

        # add swl when not mame
        if i['swl_name'] != 'mame':
            label = f'{label} ({i["swl_name"]})'

        # add * as a sign for a clone
        clone = ''
        if i['clone']:
            clone = '*'

        # add count to label
        if length > 1:
            label = f'{label} ({clone}{count:d}/{length:d})'

        list_item.setLabel(label)

        # set other labels in skin over setlist
        list_item.setProperty('Titel', gamename)
        list_item.setProperty('Year', i['year'])
        list_item.setProperty('Maker', i['publisher'])
        list_item.setProperty('Machine', i['machine_label'])

        set_list_items.append(list_item)

    gui.getControl(SET_LIST).addItems(set_list_items)


def _vgm_title(gui, vgm_name):
    """Title of a vgmplay set; the set name when umsa.db does not know it."""

    try:
        return gui.ggdb.games.get_info_by_set_and_swl(vgm_name, 'vgmplay')['name']
    except TypeError:  # no such set in umsa.db
        return vgm_name


def select_software(gui, software_id):
    """Get all machines and sets for a software and fill skin.

    Returns ``True`` when the software was displayed and ``False`` when
    the display failed, so history-adding callers can avoid phantom
    entries.
    """

    time1 = time.time()
    xbmc.log(f"UMSA gui: select_software: id = {software_id}")

    # stop video
    if gui.playvideo and gui.player.isPlayingVideo() and not gui.already_playing:
        gui.player.stop()
    elif gui.emulation.playintrovgm:
        gui.emulation.playintrovgm = False
        gui.emulation.send_vgmaction(b'exit')

    gui.getControl(LABEL_STATUS).setLabel(tr(S.LOADING_SOFTWARE))

    # get infos
    (all_info,
     pos_machine,
     pos_set,
     gui.all_dat,
     gui.all_art) = gui.ggdb.software.get_all_for_software(software_id)

    # error if no info
    if len(all_info) == 0:
        xbmc.log(f"UMSA gui: select_software: ERROR: software id={software_id}", xbmc.LOGERROR)
        gui.dialog.notification(
            tr(S.SELECT_SOFTWARE), tr(S.SOFTWARE_BROKEN, software_id),
            xbmcgui.NOTIFICATION_ERROR, 4000)
        gui.getControl(LABEL_STATUS).setLabel(tr(S.LOADING_SOFTWARE))
        return False

    gui.info = all_info
    if not getattr(gui, 'vgm_show_machine_list', False):
        selected_set = gui.info[pos_machine][pos_set]
        visible_info = []
        visible_selection = None
        for machine in gui.info:
            visible_sets = [
                set_info for set_info in machine
                if set_info['swl_name'] != 'vgmplay'
            ]
            if visible_sets:
                if selected_set in visible_sets:
                    visible_selection = (len(visible_info), visible_sets.index(selected_set))
                visible_info.append(visible_sets)
        # Fallback: a software with only vgmplay sets keeps showing them
        # (gui.info and the selected position stay untouched).
        if visible_info:
            gui.info = visible_info
            if visible_selection is None:
                pos_machine, pos_set = 0, 0
            else:
                pos_machine, pos_set = visible_selection

    no_machines = len(gui.info)
    gui.actset = gui.info[pos_machine][pos_set]

    # scanned cabinets for the machine wraplist (own artwork before progettosnaps)
    gui.machine_cabinets = gui.ggdb.art_queries.get_machine_cabinets(
        {machine_set_name(set_info) for machine in gui.info for set_info in machine})

    # fill SET_LIST
    gui.getControl(SYSTEM_WRAPLIST).reset()
    gui.fill_set_list(pos_machine)
    gui.getControl(SET_LIST).selectItem(pos_set)

    # fill MACHINE_WRAPLIST
    list_items = []
    for count, i in enumerate(gui.info):

        # check if we are at selected machine, to use the correct selected set
        set_no = 0
        if pos_machine == count:
            set_no = pos_set

        # set picture
        list_item = xbmcgui.ListItem()
        list_item.setArt({'icon': gui.get_machine_pic(use_set=i[set_no])})
        list_items.append(list_item)

    gui.getControl(SYSTEM_WRAPLIST).addItems(list_items)
    gui.getControl(SYSTEM_WRAPLIST).selectItem(pos_machine)

    # set border for machines
    if no_machines == 1:
        gui.getControl(SYSTEM_BORDER).setWidth(186)
        gui.getControl(SYSTEM_BORDER).setImage("border1.png")
        gui.getControl(MACHINE_SEP1).setVisible(False)
        gui.getControl(MACHINE_SEP2).setVisible(False)
        gui.getControl(MACHINE_SEP3).setVisible(False)
    elif no_machines == 2:
        gui.getControl(SYSTEM_BORDER).setWidth(369)
        gui.getControl(SYSTEM_BORDER).setImage("border2.png")
        gui.getControl(MACHINE_SEP1).setVisible(True)
        gui.getControl(MACHINE_SEP2).setVisible(False)
        gui.getControl(MACHINE_SEP3).setVisible(False)
    elif no_machines == 3:
        gui.getControl(SYSTEM_BORDER).setWidth(552)
        gui.getControl(SYSTEM_BORDER).setImage("border3.png")
        gui.getControl(MACHINE_SEP1).setVisible(True)
        gui.getControl(MACHINE_SEP2).setVisible(True)
        gui.getControl(MACHINE_SEP3).setVisible(False)
    else:
        gui.getControl(SYSTEM_BORDER).setWidth(735)
        gui.getControl(SYSTEM_BORDER).setImage("border4.png")
        gui.getControl(MACHINE_SEP1).setVisible(True)
        gui.getControl(MACHINE_SEP2).setVisible(True)
        gui.getControl(MACHINE_SEP3).setVisible(True)

    # set width for wraplist; the "more" marker only beyond 4 machines
    # (set for every software: history navigation reuses the controls)
    gui.getControl(MACHINE_PLUS).setVisible(no_machines > 4)
    if no_machines > 4:
        gui.getControl(SYSTEM_WRAPLIST).setWidth(720)
    else:
        gui.getControl(SYSTEM_WRAPLIST).setWidth(no_machines * 180)

    gui.getControl(TEXTLIST).reset()
    # search local snaps
    gui.create_artworklist()

    # Keep database-linked VGM sets available even when hidden from the machine list.
    # gui.vgm_titles maps the short set name to the title shown in the media list.
    vgm_titles = {
        set_info['name']: set_info['gamename']
        for machine in all_info
        for set_info in machine
        if set_info['swl_name'] == 'vgmplay'
    }
    for dat_set in gui.all_dat.values():
        if 'others' in dat_set and 'vgmplay' in dat_set['others']:
            xbmc.log("UMSA gui: VGMs found!", xbmc.LOGINFO)
            for splitentry in dat_set['others'].split(','):
                if 'vgmplay' in splitentry:
                    vgm_name = splitentry.split('=')[1]
                    if vgm_name not in vgm_titles:
                        vgm_titles[vgm_name] = _vgm_title(gui, vgm_name)
    gui.vgms = set(vgm_titles) or None
    gui.vgm_titles = vgm_titles
    xbmc.log(f"UMSA gui: {gui.vgms}", xbmc.LOGDEBUG)

    # Auto-play a video first; the intro VGM is only the fallback.
    can_start_media = (
        not gui.player.isPlayingAudio()
        and not gui.emulation.playvgm
    )
    video_selected = False
    if gui.playvideo and can_start_media:
        video = []
        for j in gui.info:
            for i in j:
                if 'video' in i:
                    video.append(
                        {'label': f"{i['gamename']} ({i['swl_name']})",
                         'id': i['video']
                         }
                        )
        if video:
            video_rand = choice(video)
            video_file = video_rand['id']
            video_selected = True
            if (not gui.player.isPlayingVideo()
                    or video_file != gui.player.getPlayingFile()):
                list_item = xbmcgui.ListItem(video_rand['label'])
                gui.player.play(
                    video_file,
                    listitem=list_item,
                    windowed=True
                )

    intro_duration = getattr(gui, 'vgm_intro_duration', 0)
    if (can_start_media and not video_selected
            and not gui.player.isPlayingVideo()
            and gui.vgms and intro_duration > 0):
        play_vgm = choice(tuple(gui.vgms))
        xbmc.log(f'UMSA gui: play intro vgm {play_vgm}')
        # Emulation refuses the start while an earlier playback still ends
        if gui.emulation.play_vgm(play_vgm, intro_duration, intro=True):
            gui.dialog.notification(tr(S.VGM_INTRO), tr(S.VGM_PLAYING, play_vgm),
                xbmcgui.NOTIFICATION_INFO, 3000, False)

    # show artwork and dat info
    gui.show_artwork()

    # set indicators
    if gui.vidman == (0, 0):
        gui.getControl(MEDIA_LABEL).setVisible(False)
    else:
        gui.getControl(MEDIA_LABEL).setVisible(True)
    is_compilation = gui.ggdb.games.check_compilation(gui.last[gui.lastptr])
    if is_compilation == 2 or is_compilation == 1:  # on a compilation
        gui.getControl(COMPILATION_LABEL).setVisible(True)
    else:
        gui.getControl(COMPILATION_LABEL).setVisible(False)

    xbmc.log("UMSA gui: select_software: set number of machines")
    # number of machines next to the "more" marker, from 6 machines on
    if no_machines >= 6:
        gui.getControl(MACHINE_COUNT).setLabel(str(no_machines))
    else:
        gui.getControl(MACHINE_COUNT).setLabel('')
    # loading done: clear 'loading software...'
    gui.getControl(LABEL_STATUS).setLabel('')

    time2 = time.time()
    xbmc.log("UMSA gui: select_software: complete  %0.3f ms" % ((time2 - time1) * 1000.0))
    return True


def machine_move(gui):
    """Update set list and artwork, set new actual set after machine move"""

    pos_m = gui.getControl(SYSTEM_WRAPLIST).getSelectedPosition()
    gui.fill_set_list(pos_m)

    pos_s = gui.getControl(SET_LIST).getSelectedPosition()
    gui.actset = gui.info[pos_m][pos_s]

    gui.show_artwork('machine')


def software_move(gui, direction):
    """Get next random software or move one back in history"""

    # The navigable window is the latest 10 entries (or fewer if history is smaller)
    nav_start = max(0, len(gui.last) - 10)

    if direction == 'left' and gui.lastptr > nav_start:
        gui.lastptr -= 1
        gui.select_software(gui.last[gui.lastptr])
        return
    if direction == 'right':
        if gui.lastptr + 1 >= len(gui.last):
            # moving past the newest entry appends a new random one
            software_id = gui.ggdb.gamelist.get_random_id()
            # do not draw the software that is already shown
            for _retry in range(3):
                if str(software_id) != str(gui.last[gui.lastptr]):
                    break
                software_id = gui.ggdb.gamelist.get_random_id()
            if software_id is None:
                xbmc.log("UMSA gui: no random software, database is empty")
                return
            gui._remember_and_select(software_id)
        else:
            gui.lastptr += 1
            gui.select_software(gui.last[gui.lastptr])


def open_software(gui, software_id):
    """Select software requested by the screensaver, keeping history."""

    xbmc.log(f"UMSA gui: open software from handoff: id = {software_id}")
    gui._remember_and_select(software_id)
