"""Software, set and machine selection of the UMSA frontend.

``select_software`` is the central display routine: it loads the sets of a
software, fills the skin controls and starts the optional intro video or VGM.
``remember_and_select`` adds the software to the history, which lives in
memory and is persisted in ``status.db``.
"""

import time
from dataclasses import dataclass
from random import choice

import xbmc
import xbmcgui
from umsa_core.artwork import machine_set_name
from umsa_core.game_labels import split_gamename

from . import artwork_presenter
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


@dataclass
class SoftwareCtx:
    """Selection of a software: its sets, the history and the intro media."""

    view: object = None
    services: object = None
    software: object = None
    history: object = None
    settings: object = None
    # context of the artwork lists
    artwork: object = None


def fill_set_list(ctx, pos):
    """Fill the set list"""

    ctx.view.getControl(SET_LIST).reset()
    length = len(ctx.software.info[pos])
    set_list_items = []
    for count, i in enumerate(ctx.software.info[pos], start=1):
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

    ctx.view.getControl(SET_LIST).addItems(set_list_items)


def _vgm_title(ctx, vgm_name):
    """Title of a vgmplay set; the set name when umsa.db does not know it."""

    try:
        return ctx.services.ggdb.games.get_info_by_set_and_swl(vgm_name, 'vgmplay')['name']
    except TypeError:  # no such set in umsa.db
        return vgm_name


def select_software(ctx, software_id, set_id=None):
    """Get all machines and sets for a software and fill skin.

    ``set_id`` (search result) selects that set instead of the latest played
    one; a requested ``vgmplay`` set that ``vgm_show_machine_list`` hides
    falls back to the first visible set.

    Returns ``True`` when the software was displayed and ``False`` when
    the display failed, so history-adding callers can avoid phantom
    entries.
    """

    time1 = time.time()
    xbmc.log(f"UMSA gui: select_software: id = {software_id}")

    # stop video
    if ctx.settings.playvideo and ctx.services.player.isPlayingVideo() and not ctx.software.already_playing:
        ctx.services.player.stop()
    elif ctx.services.emulation.playintrovgm:
        ctx.services.emulation.playintrovgm = False
        ctx.services.emulation.send_vgmaction(b'exit')

    ctx.view.getControl(LABEL_STATUS).setLabel(tr(S.LOADING_SOFTWARE))

    # get infos (without a set the call keeps its historical shape)
    if set_id is None:
        details = ctx.services.ggdb.software.get_all_for_software(software_id)
    else:
        details = ctx.services.ggdb.software.get_all_for_software(
            software_id, set_id=set_id)
    (all_info,
     pos_machine,
     pos_set,
     ctx.software.all_dat,
     ctx.software.all_art) = details

    # error if no info
    if len(all_info) == 0:
        xbmc.log(f"UMSA gui: select_software: ERROR: software id={software_id}", xbmc.LOGERROR)
        ctx.services.dialog.notification(
            tr(S.SELECT_SOFTWARE), tr(S.SOFTWARE_BROKEN, software_id),
            xbmcgui.NOTIFICATION_ERROR, 4000)
        ctx.view.getControl(LABEL_STATUS).setLabel(tr(S.LOADING_SOFTWARE))
        return False

    ctx.software.info = all_info
    if not ctx.settings.vgm_show_machine_list:
        selected_set = ctx.software.info[pos_machine][pos_set]
        visible_info = []
        visible_selection = None
        for machine in ctx.software.info:
            visible_sets = [
                set_info for set_info in machine
                if set_info['swl_name'] != 'vgmplay'
            ]
            if visible_sets:
                if selected_set in visible_sets:
                    visible_selection = (len(visible_info), visible_sets.index(selected_set))
                visible_info.append(visible_sets)
        # Fallback: a software with only vgmplay sets keeps showing them
        # (ctx.software.info and the selected position stay untouched).
        if visible_info:
            ctx.software.info = visible_info
            if visible_selection is None:
                pos_machine, pos_set = 0, 0
            else:
                pos_machine, pos_set = visible_selection

    no_machines = len(ctx.software.info)
    ctx.software.actset = ctx.software.info[pos_machine][pos_set]

    # scanned cabinets for the machine wraplist (own artwork before progettosnaps)
    ctx.software.machine_cabinets = ctx.services.ggdb.art_queries.get_machine_cabinets(
        {machine_set_name(set_info) for machine in ctx.software.info for set_info in machine})

    # fill SET_LIST
    ctx.view.getControl(SYSTEM_WRAPLIST).reset()
    fill_set_list(ctx, pos_machine)
    ctx.view.getControl(SET_LIST).selectItem(pos_set)

    # fill MACHINE_WRAPLIST
    list_items = []
    for count, i in enumerate(ctx.software.info):

        # check if we are at selected machine, to use the correct selected set
        set_no = 0
        if pos_machine == count:
            set_no = pos_set

        # set picture
        list_item = xbmcgui.ListItem()
        list_item.setArt({'icon': artwork_presenter.get_machine_pic(ctx.artwork, use_set=i[set_no])})
        list_items.append(list_item)

    ctx.view.getControl(SYSTEM_WRAPLIST).addItems(list_items)
    ctx.view.getControl(SYSTEM_WRAPLIST).selectItem(pos_machine)

    # set border for machines
    if no_machines == 1:
        ctx.view.getControl(SYSTEM_BORDER).setWidth(186)
        ctx.view.getControl(SYSTEM_BORDER).setImage("border1.png")
        ctx.view.getControl(MACHINE_SEP1).setVisible(False)
        ctx.view.getControl(MACHINE_SEP2).setVisible(False)
        ctx.view.getControl(MACHINE_SEP3).setVisible(False)
    elif no_machines == 2:
        ctx.view.getControl(SYSTEM_BORDER).setWidth(369)
        ctx.view.getControl(SYSTEM_BORDER).setImage("border2.png")
        ctx.view.getControl(MACHINE_SEP1).setVisible(True)
        ctx.view.getControl(MACHINE_SEP2).setVisible(False)
        ctx.view.getControl(MACHINE_SEP3).setVisible(False)
    elif no_machines == 3:
        ctx.view.getControl(SYSTEM_BORDER).setWidth(552)
        ctx.view.getControl(SYSTEM_BORDER).setImage("border3.png")
        ctx.view.getControl(MACHINE_SEP1).setVisible(True)
        ctx.view.getControl(MACHINE_SEP2).setVisible(True)
        ctx.view.getControl(MACHINE_SEP3).setVisible(False)
    else:
        ctx.view.getControl(SYSTEM_BORDER).setWidth(735)
        ctx.view.getControl(SYSTEM_BORDER).setImage("border4.png")
        ctx.view.getControl(MACHINE_SEP1).setVisible(True)
        ctx.view.getControl(MACHINE_SEP2).setVisible(True)
        ctx.view.getControl(MACHINE_SEP3).setVisible(True)

    # set width for wraplist; the "more" marker only beyond 4 machines
    # (set for every software: history navigation reuses the controls)
    ctx.view.getControl(MACHINE_PLUS).setVisible(no_machines > 4)
    if no_machines > 4:
        ctx.view.getControl(SYSTEM_WRAPLIST).setWidth(720)
    else:
        ctx.view.getControl(SYSTEM_WRAPLIST).setWidth(no_machines * 180)

    ctx.view.getControl(TEXTLIST).reset()
    # search local snaps
    artwork_presenter.create_artworklist(ctx.artwork)

    # Keep database-linked VGM sets available even when hidden from the machine list.
    # vgm_titles maps the short set name to the title shown in the media list.
    vgm_titles = {
        set_info['name']: set_info['gamename']
        for machine in all_info
        for set_info in machine
        if set_info['swl_name'] == 'vgmplay'
    }
    for dat_set in ctx.software.all_dat.values():
        if 'others' in dat_set and 'vgmplay' in dat_set['others']:
            xbmc.log("UMSA gui: VGMs found!", xbmc.LOGINFO)
            for splitentry in dat_set['others'].split(','):
                if 'vgmplay' in splitentry:
                    vgm_name = splitentry.split('=')[1]
                    if vgm_name not in vgm_titles:
                        vgm_titles[vgm_name] = _vgm_title(ctx, vgm_name)
    ctx.software.vgms = set(vgm_titles) or None
    ctx.software.vgm_titles = vgm_titles
    xbmc.log(f"UMSA gui: {ctx.software.vgms}", xbmc.LOGDEBUG)

    # Auto-play a video first; the intro VGM is only the fallback.
    can_start_media = (
        not ctx.services.player.isPlayingAudio()
        and not ctx.services.emulation.playvgm
    )
    video_selected = False
    if ctx.settings.playvideo and can_start_media:
        video = []
        for j in ctx.software.info:
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
            if (not ctx.services.player.isPlayingVideo()
                    or video_file != ctx.services.player.getPlayingFile()):
                list_item = xbmcgui.ListItem(video_rand['label'])
                ctx.services.player.play(
                    video_file,
                    listitem=list_item,
                    windowed=True
                )

    intro_duration = ctx.settings.vgm_intro_duration
    if (can_start_media and not video_selected
            and not ctx.services.player.isPlayingVideo()
            and ctx.software.vgms and intro_duration > 0):
        play_vgm = choice(tuple(ctx.software.vgms))
        xbmc.log(f'UMSA gui: play intro vgm {play_vgm}')
        # Emulation refuses the start while an earlier playback still ends
        if ctx.services.emulation.play_vgm(play_vgm, intro_duration, intro=True):
            ctx.services.dialog.notification(tr(S.VGM_INTRO), tr(S.VGM_PLAYING, play_vgm),
                xbmcgui.NOTIFICATION_INFO, 3000, False)

    # show artwork and dat info
    artwork_presenter.show_artwork(ctx.artwork)

    # set indicators
    if ctx.software.vidman == (0, 0):
        ctx.view.getControl(MEDIA_LABEL).setVisible(False)
    else:
        ctx.view.getControl(MEDIA_LABEL).setVisible(True)
    is_compilation = ctx.services.ggdb.games.check_compilation(ctx.history.last[ctx.history.lastptr])
    if is_compilation == 2 or is_compilation == 1:  # on a compilation
        ctx.view.getControl(COMPILATION_LABEL).setVisible(True)
    else:
        ctx.view.getControl(COMPILATION_LABEL).setVisible(False)

    xbmc.log("UMSA gui: select_software: set number of machines")
    # number of machines next to the "more" marker, from 6 machines on
    if no_machines >= 6:
        ctx.view.getControl(MACHINE_COUNT).setLabel(str(no_machines))
    else:
        ctx.view.getControl(MACHINE_COUNT).setLabel('')
    # loading done: clear 'loading software...'
    ctx.view.getControl(LABEL_STATUS).setLabel('')

    time2 = time.time()
    xbmc.log("UMSA gui: select_software: complete  %0.3f ms" % ((time2 - time1) * 1000.0))
    return True


def machine_move(ctx):
    """Update set list and artwork, set new actual set after machine move"""

    pos_m = ctx.view.getControl(SYSTEM_WRAPLIST).getSelectedPosition()
    fill_set_list(ctx, pos_m)

    pos_s = ctx.view.getControl(SET_LIST).getSelectedPosition()
    ctx.software.actset = ctx.software.info[pos_m][pos_s]

    artwork_presenter.show_artwork(ctx.artwork, 'machine')


def software_move(ctx, direction):
    """Get next random software or move one back in history"""

    # The navigable window is the latest 10 entries (or fewer if history is smaller)
    nav_start = max(0, len(ctx.history.last) - 10)

    if direction == 'left' and ctx.history.lastptr > nav_start:
        ctx.history.lastptr -= 1
        select_software(ctx, ctx.history.last[ctx.history.lastptr])
        return
    if direction == 'right':
        if ctx.history.lastptr + 1 >= len(ctx.history.last):
            # moving past the newest entry appends a new random one
            software_id = ctx.services.ggdb.gamelist.get_random_id()
            # do not draw the software that is already shown
            for _retry in range(3):
                if str(software_id) != str(ctx.history.last[ctx.history.lastptr]):
                    break
                software_id = ctx.services.ggdb.gamelist.get_random_id()
            if software_id is None:
                xbmc.log("UMSA gui: no random software, database is empty")
                return
            remember_and_select(ctx, software_id)
        else:
            ctx.history.lastptr += 1
            select_software(ctx, ctx.history.last[ctx.history.lastptr])


def open_software(ctx, software_id):
    """Select software requested by the screensaver, keeping history."""

    xbmc.log(f"UMSA gui: open software from handoff: id = {software_id}")
    remember_and_select(ctx, software_id)


def save_lastgames(ctx):
    """Persist the current in-memory history without trimming it."""

    if ctx.services.ggdb is not None:
        ctx.services.ggdb.history.save_lastgames(ctx.history.last)


def _select(ctx, software_id, set_id):
    """``select_software`` with the set only when one is requested."""

    if set_id is None:
        return select_software(ctx, software_id)
    return select_software(ctx, software_id, set_id)


def remember_and_select(ctx, software_id, set_id=None):
    """Insert a display event, select it, and persist only on success.

    A failed display (empty `select_software`) must not leave a phantom
    entry: the in-memory insert is rolled back and nothing is persisted.
    Pointer semantics match the previous insert-and-advance callers.

    ``set_id`` (search result) selects that set. A software that is shown
    already is reloaded only for another set; the history stays as it is.
    """

    # no identical entries next to each other in the history
    if ctx.history.last and 0 <= ctx.history.lastptr < len(ctx.history.last):
        if str(ctx.history.last[ctx.history.lastptr]) == str(software_id):
            actset = ctx.software.actset
            if set_id is not None and (not actset or actset.get('id') != set_id):
                xbmc.log(f"UMSA gui: remember_and_select: {software_id} shown, "
                         f"moving to set {set_id}")
                return select_software(ctx, software_id, set_id)
            xbmc.log(f"UMSA gui: remember_and_select: {software_id} already shown")
            return True
        if (ctx.history.lastptr + 1 < len(ctx.history.last)
                and str(ctx.history.last[ctx.history.lastptr + 1]) == str(software_id)):
            ctx.history.lastptr += 1
            if not _select(ctx, ctx.history.last[ctx.history.lastptr], set_id):
                ctx.history.lastptr -= 1
                return False
            return True

    ctx.history.lastptr += 1
    ctx.history.last.insert(ctx.history.lastptr, software_id)
    if not _select(ctx, software_id, set_id):
        del ctx.history.last[ctx.history.lastptr]
        ctx.history.lastptr -= 1
        return False
    # Cap in-memory history at 100 entries to match persistent storage limit.
    # Only applied after successful selection; failed selection fully rolls back.
    if len(ctx.history.last) > 100:
        del ctx.history.last[0]
        ctx.history.lastptr -= 1
    save_lastgames(ctx)
    return True
