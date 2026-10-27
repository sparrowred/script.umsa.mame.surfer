"""Artwork collection and presentation for the UMSA frontend.

The module resolves the artwork of the selected software (Core helpers do the
path resolution) and fills the skin controls that show it.
"""

import os

import xbmc
import xbmcgui
from umsa_core import (
    categorize_art_type,
    check_image_aspect,
    find_local_snapshots,
    get_machine_artwork_path,
    resolve_artwork_path,
)

from .constants import (
    IMAGE_BIG_LIST,
    IMAGE_LIST,
    SHADOW_DAT,
    SYSTEM_WRAPLIST,
    TEXTLIST,
)
from .paths import SKIN_MEDIA_FOLDER


def create_gui_element_from_snap(set_info, image, art_type='unset'):
    """Return a Kodi list item for a snapshot."""

    if image:
        dir_split = os.path.dirname(image).split('/')
        if len(dir_split) < 2:
            art = art_type
        else:
            art = dir_split[-2]
            if art == set_info['swl_name']:
                art = os.path.basename(image)[:-4]
    else:
        art = art_type

    list_item = xbmcgui.ListItem()
    list_item.setLabel("{}: {} ({})".format(
        art, set_info['detail'], set_info['swl_name']))
    list_item.setArt({'icon': image})
    list_item.setProperty('detail', "{}: {} {}".format(
        art, set_info['swl_name'], set_info['detail']))
    aspect = check_image_aspect(set_info)
    for name in ('Vertical', 'Horizontal', 'NotScaled'):
        list_item.setProperty(name, '1' if aspect == name else '')
    return list_item


def get_machine_pic(gui, use_set):
    """Return the machine artwork path for the current game set."""

    return get_machine_artwork_path(use_set, gui.cab_path, SKIN_MEDIA_FOLDER)


def search_snaps(gui, set_info):
    """Search files in MAME snapshot directory

    Returns list of Kodi ListItems
    """

    return [
        create_gui_element_from_snap(set_info, snap_path)
        for snap_path in find_local_snapshots(
            gui.emulation.snapshot_directory, set_info)
    ]


def create_artworklist(gui):
    """Create left and right artwork list, side product is play count and time played"""

    gui.played = {
        'count': 0,
        'played': 0
    }
    vid = 0
    man = 0

    for machine in gui.info:
        for set_info in machine:

            set_info['right_pics'] = []
            set_info['left_pics'] = []

            # sum up lp
            if set_info['last_played']:
                gui.played['count'] += set_info['last_played']['play_count']
                gui.played['played'] += set_info['last_played']['time_played2']

            # mame snaps
            set_info['localsnaps'] = gui.search_snaps(set_info)

            # progettosnaps
            if set_info['id'] not in gui.all_art:
                continue
            for art in gui.all_art[set_info['id']]:

                source_roots = gui.artwork_source_roots()
                filename = resolve_artwork_path(art, set_info, source_roots)

                art_category = categorize_art_type(art['type'])
                if art_category == 'right':
                    list_item = xbmcgui.ListItem()
                    list_item.setLabel("{}: {} ({})".format(
                        art['type'], set_info['detail'], set_info['swl_name']))
                    list_item.setProperty('detail', "{}: {} {}".format(
                        art['type'], set_info['swl_name'], set_info['detail']))
                    list_item.setArt({'icon': filename})
                    set_info['right_pics'].append(list_item)
                elif art_category == 'left':
                    set_info['left_pics'].append(
                        create_gui_element_from_snap(set_info, filename, art)
                    )
                elif art_category == 'video':
                    set_info['video'] = filename[:-4] + '.' + art['extension']
                    vid += 1
                elif art_category == 'manual':
                    set_info['manual'] = filename[:-4] + '.' + art['extension']
                    man += 1
                else:
                    xbmc.log("UMSA gui: create_artworklist: cant identify artwork type = {art}")

    gui.vidman = (vid, man)
    minutes = divmod(gui.played['played'], 60)[0]
    hours, minutes = divmod(minutes, 60)
    gui.played['played'] = f'{hours}:{minutes:02d}'


def show_artwork(gui, howmuch='all'):
    """Show artwork

    TODO
     - no update when set does not change
     - only left side update for after emu run
    """

    rlist = []
    llist = []

    if howmuch == 'set':
        rlist = gui.actset['right_pics']
        llist = gui.actset['left_pics'] + gui.actset['localsnaps']
    elif howmuch == 'machine':
        for i in gui.info[gui.getControl(SYSTEM_WRAPLIST).getSelectedPosition()]:
            rlist += i['right_pics']
            llist += i['left_pics'] + i['localsnaps']
    else:  # all
        for j in gui.info:
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
        gui.getControl(IMAGE_BIG_LIST).reset()
        gui.getControl(IMAGE_BIG_LIST).addItems(list_items)

    else:
        list_item = xbmcgui.ListItem()
        list_item.setProperty('NotEnabled', '1')
        gui.getControl(IMAGE_BIG_LIST).reset()
        gui.getControl(IMAGE_BIG_LIST).addItem(list_item)

    # fill pic left
    if len(llist) > 0:

        # set count/sets
        count = 1
        list_items = []
        for i in llist:
            # get detail from setlist property and set label new
            i.setLabel(
                "{} ({}/{})".format(
                    i.getProperty('detail'),
                    count,
                    len(llist)
                )
            )
            list_items.append(i)
            count += 1
        gui.getControl(IMAGE_LIST).reset()
        gui.getControl(IMAGE_LIST).addItems(list_items)

    else:
        list_item = xbmcgui.ListItem()
        list_item.setProperty('NotEnabled', '1')
        gui.getControl(IMAGE_LIST).reset()
        gui.getControl(IMAGE_LIST).addItem(list_item)

    # show infos from datfiles only when changed
    if gui.oldset == (gui.actset['swl_name'], gui.actset['name']):
        return

    # check play status
    # TODO check if all, system or set
    # TODO also show series and compilation status
    stattext = ''
    if gui.played['count'] > 0:
        if gui.actset['last_played']:
            played_text = gui.actset['last_played']['last_nice'] + ' ago'
        else:
            played_text = "never"
        stattext = (
            f"{played_text}, {gui.played['played']}h, "
            f"{gui.played['count']}x[CR]"
        )

    list_items = []
    count = 0
    if gui.actset['id'] in gui.all_dat:
        # TODO put history first, so have a sorted list of headings
        for k in sorted(gui.all_dat[gui.actset['id']]):
            moretext = ''
            if k in ('Contribute', 'Rec'):
                continue
            if k == 'History':
                moretext = stattext

            list_item = xbmcgui.ListItem()
            list_item.setLabel(k)
            list_item.setProperty(
                'text',
                moretext + gui.all_dat[gui.actset['id']][k]
            )
            list_items.append(list_item)
            count += 1

    if len(list_items) == 0:
        list_item = xbmcgui.ListItem()
        list_item.setLabel("no information...")
        list_item.setProperty('text', stattext)
        list_items.append(list_item)

    gui.getControl(TEXTLIST).reset()
    gui.getControl(TEXTLIST).addItems(list_items)

    # shadow pointer
    if count > 1:
        gui.getControl(SHADOW_DAT).setVisible(True)
    else:
        gui.getControl(SHADOW_DAT).setVisible(False)

    # remember actual swl and set
    gui.oldset = (gui.actset['swl_name'], gui.actset['name'])
    # refresh main menu
    gui.build_main_menu()
    xbmc.log("UMSA gui: show_artwork: pics, dats done")
