"""Software, set and machine selection of the UMSA frontend.

``select_software`` is the central display routine: it loads the sets of a
software, fills the skin controls and starts the optional intro video or VGM.
"""

import time
from random import choice

import xbmc
import xbmcgui
from umsa_core.database import split_gamename

from .constants import (
    COMPILATION_LABEL,
    LABEL_STATUS,
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


def fill_set_list(gui, pos):
    """Fill the set list"""

    gui.getControl(SET_LIST).reset()
    length = len(gui.info[pos])
    count = 0

    set_list_items = []
    for i in gui.info[pos]:
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
            label = f'{gamedetail}'

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

    gui.getControl(SET_LIST).addItems(set_list_items)


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

    gui.getControl(LABEL_STATUS).setLabel('loading software...')

    # get infos
    (gui.info,
     pos_machine,
     pos_set,
     gui.all_dat,
     gui.all_art) = gui.ggdb.get_all_for_software(software_id)

    # error if no info
    if len(gui.info) == 0:
        xbmc.log(f"UMSA gui: select_software: ERROR: software id={software_id}", xbmc.LOGERROR)
        gui.dialog.notification('Select Software', f'id-{software_id} feels funny?!?',
            xbmcgui.NOTIFICATION_ERROR, 4000)
        gui.getControl(LABEL_STATUS).setLabel('loading software...')
        return False

    no_machines = len(gui.info)
    gui.actset = gui.info[pos_machine][pos_set]

    # fill SET_LIST
    gui.getControl(SYSTEM_WRAPLIST).reset()
    gui.fill_set_list(pos_machine)
    gui.getControl(SET_LIST).selectItem(pos_set)

    # fill MACHINE_WRAPLIST
    count = 0
    list_items = []
    for i in gui.info:

        # check if we are at selected machine, to use the correct selected set
        set_no = 0
        if pos_machine == count:
            set_no = pos_set
        count += 1

        # set picture
        list_item = xbmcgui.ListItem()
        list_item.setArt({'icon': gui.get_machine_pic(use_set=i[set_no])})
        list_items.append(list_item)

    gui.getControl(SYSTEM_WRAPLIST).addItems(list_items)
    gui.getControl(SYSTEM_WRAPLIST).selectItem(pos_machine)

    # set border for machines
    if no_machines == 1:
        gui.getControl(SYSTEM_BORDER).setWidth(124)
        gui.getControl(SYSTEM_BORDER).setImage("border1.png")
        gui.getControl(MACHINE_SEP1).setVisible(False)
        gui.getControl(MACHINE_SEP2).setVisible(False)
        gui.getControl(MACHINE_SEP3).setVisible(False)
        gui.getControl(MACHINE_PLUS).setVisible(False)
    elif no_machines == 2:
        gui.getControl(SYSTEM_BORDER).setWidth(246)
        gui.getControl(SYSTEM_BORDER).setImage("border2.png")
        gui.getControl(MACHINE_SEP1).setVisible(True)
        gui.getControl(MACHINE_SEP2).setVisible(False)
        gui.getControl(MACHINE_SEP3).setVisible(False)
        gui.getControl(MACHINE_PLUS).setVisible(False)
    elif no_machines == 3:
        gui.getControl(SYSTEM_BORDER).setWidth(368)
        gui.getControl(SYSTEM_BORDER).setImage("border3.png")
        gui.getControl(MACHINE_SEP1).setVisible(True)
        gui.getControl(MACHINE_SEP2).setVisible(True)
        gui.getControl(MACHINE_SEP3).setVisible(False)
        gui.getControl(MACHINE_PLUS).setVisible(False)
    else:
        gui.getControl(SYSTEM_BORDER).setWidth(490)
        gui.getControl(SYSTEM_BORDER).setImage("border4.png")
        gui.getControl(MACHINE_SEP1).setVisible(True)
        gui.getControl(MACHINE_SEP2).setVisible(True)
        gui.getControl(MACHINE_SEP3).setVisible(True)

    # set width for wraplist
    if no_machines > 4:
        gui.getControl(SYSTEM_WRAPLIST).setWidth(480)
        gui.getControl(MACHINE_PLUS).setVisible(True)
    else:
        gui.getControl(SYSTEM_WRAPLIST).setWidth(no_machines * 120)

    gui.getControl(TEXTLIST).reset()
    # search local snaps
    gui.create_artworklist()

    # TODO create vgm list from new table
    # OUTDATED create vgm list from history.xml
    gui.vgms = None
    for dat_set in gui.all_dat.values():
        if 'others' in dat_set and 'vgmplay' in dat_set['others']:
            xbmc.log("UMSA gui: VGMs found!", xbmc.LOGINFO)
            if not gui.vgms:
                gui.vgms = set()
            for splitentry in dat_set['others'].split(','):
                if 'vgmplay' in splitentry:
                    gui.vgms.add(splitentry.split('=')[1])
            xbmc.log(f"UMSA gui: {gui.vgms}", xbmc.LOGDEBUG)

    # play video
    if (gui.playvideo
        and not gui.player.isPlayingAudio()
        and not gui.emulation.playvgm
        ):
        video = []
        for j in gui.info:
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
            if (not gui.player.isPlayingVideo() or
                    (gui.player.isPlayingVideo() and
                     video_file != gui.player.getPlayingFile())):

                list_item = xbmcgui.ListItem(video_rand['label'])
                gui.player.play(
                    video_file,
                    listitem=list_item,
                    windowed=True
                )
        else:
            # play random vgm
            if gui.vgms:
                play_vgm = choice(tuple(gui.vgms))
                xbmc.log(f'UMSA gui: play intro vgm {play_vgm}')
                gui.dialog.notification('VGM Intro', f'Playing {play_vgm}',
                    xbmcgui.NOTIFICATION_INFO, 3000, False)
                gui.emulation.play_vgm(
                    play_vgm, 10, xbmc.sleep, intro=True)

    # show artwork and dat info
    gui.show_artwork()

    # set indicators
    if gui.vidman == (0, 0):
        gui.getControl(MEDIA_LABEL).setVisible(False)
    else:
        gui.getControl(MEDIA_LABEL).setVisible(True)
    is_compilation = gui.ggdb.check_compilation(gui.last[gui.lastptr])
    if is_compilation == 2 or is_compilation == 1:  # on a compilation
        gui.getControl(COMPILATION_LABEL).setVisible(True)
    else:
        gui.getControl(COMPILATION_LABEL).setVisible(False)

    xbmc.log("UMSA gui: select_software: set number of machines")
    # set number of machines
    if no_machines > 4:
        gui.getControl(LABEL_STATUS).setLabel(
            f"{len(gui.info)!s} machines"
        )
    else:
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
            gui._remember_and_select(gui.ggdb.get_random_id())
        else:
            gui.lastptr += 1
            gui.select_software(gui.last[gui.lastptr])


def open_software(gui, software_id):
    """Select software requested by the screensaver, keeping history."""

    xbmc.log(f"UMSA gui: open software from handoff: id = {software_id}")
    gui._remember_and_select(software_id)
