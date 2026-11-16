"""Artwork collection and presentation for the UMSA frontend.

The module resolves the artwork of the selected software (Core helpers do the
path resolution) and fills the skin controls that show it.
"""

import os
from dataclasses import dataclass

import xbmc
import xbmcgui
from umsa_core import (
    categorize_art_type,
    check_image_aspect,
    find_local_snapshots,
    get_machine_artwork_path,
    resolve_artwork_path,
)
from umsa_core.dat_parser import DAT_HISTORY

from . import menu
from . import strings as S
from .constants import (
    IMAGE_BIG_LIST,
    IMAGE_LIST,
    SHADOW_DAT,
    SYSTEM_WRAPLIST,
    TEXTLIST,
    TEXTLIST_HIDDEN,
    TEXTLIST_KEY_NO_INFO,
    TEXTLIST_KEY_PROPERTY,
    TEXTLIST_ORDER,
    TEXTLIST_OTHER_CATEGORIES,
)
from .paths import SKIN_MEDIA_FOLDER
from .strings import tr

_TEXTLIST_RANK = {name: rank for rank, name in enumerate(TEXTLIST_ORDER)}


@dataclass
class ArtworkCtx:
    """Artwork and DAT texts of the shown software."""

    view: object = None
    services: object = None
    software: object = None
    settings: object = None
    # context of the main menu (rebuilt after the artwork changed)
    menu: object = None


def textlist_sort_key(category):
    """Sort key of a DAT category in TEXTLIST: fixed rank, then name.

    Categories missing from ``TEXTLIST_ORDER`` take the rank of the
    ``TEXTLIST_OTHER_CATEGORIES`` placeholder and sort alphabetically there.
    """

    rank = _TEXTLIST_RANK.get(
        category, _TEXTLIST_RANK[TEXTLIST_OTHER_CATEGORIES])
    return rank, category


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


def get_machine_pic(ctx, use_set):
    """Return the machine artwork path for the current game set.

    Scanned cabinets (``ctx.software.machine_cabinets``) win; without an artwork
    scan the fixed progettosnaps path (``ctx.settings.cab_path``) is used.
    """

    return get_machine_artwork_path(
        use_set, ctx.settings.cab_path, SKIN_MEDIA_FOLDER,
        cabinets=ctx.software.machine_cabinets,
        source_roots=ctx.settings.artwork_source_roots())


def search_snaps(ctx, set_info):
    """Search files in MAME snapshot directory

    Returns list of Kodi ListItems
    """

    return [
        create_gui_element_from_snap(set_info, snap_path)
        for snap_path in find_local_snapshots(
            ctx.services.emulation.snapshot_directory, set_info)
    ]


def create_artworklist(ctx):
    """Create left and right artwork list, side product is play count and time played"""

    ctx.software.played = {
        'count': 0,
        'played': 0
    }
    vid = 0
    man = 0

    for machine in ctx.software.info:
        for set_info in machine:

            set_info['right_pics'] = []
            set_info['left_pics'] = []

            # sum up lp
            if set_info['last_played']:
                ctx.software.played['count'] += set_info['last_played']['play_count']
                ctx.software.played['played'] += set_info['last_played']['time_played2']

            # mame snaps
            set_info['localsnaps'] = search_snaps(ctx, set_info)

            # progettosnaps
            if set_info['id'] not in ctx.software.all_art:
                continue
            for art in ctx.software.all_art[set_info['id']]:

                source_roots = ctx.settings.artwork_source_roots()
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
                    xbmc.log(f"UMSA gui: create_artworklist: cant identify artwork type = {art}")

    ctx.software.vidman = (vid, man)
    minutes = divmod(ctx.software.played['played'], 60)[0]
    hours, minutes = divmod(minutes, 60)
    ctx.software.played['played'] = f'{hours}:{minutes:02d}'


def show_artwork(ctx, howmuch='all'):
    """Show artwork

    TODO
     - no update when set does not change
     - only left side update for after emu run
    """

    rlist = []
    llist = []

    if howmuch == 'set':
        rlist = ctx.software.actset['right_pics']
        llist = ctx.software.actset['left_pics'] + ctx.software.actset['localsnaps']
    elif howmuch == 'machine':
        for i in ctx.software.info[ctx.view.getControl(SYSTEM_WRAPLIST).getSelectedPosition()]:
            rlist += i['right_pics']
            llist += i['left_pics'] + i['localsnaps']
    else:  # all
        for j in ctx.software.info:
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
        ctx.view.getControl(IMAGE_BIG_LIST).reset()
        ctx.view.getControl(IMAGE_BIG_LIST).addItems(list_items)

    else:
        list_item = xbmcgui.ListItem()
        list_item.setProperty('NotEnabled', '1')
        ctx.view.getControl(IMAGE_BIG_LIST).reset()
        ctx.view.getControl(IMAGE_BIG_LIST).addItem(list_item)

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
        ctx.view.getControl(IMAGE_LIST).reset()
        ctx.view.getControl(IMAGE_LIST).addItems(list_items)

    else:
        list_item = xbmcgui.ListItem()
        list_item.setProperty('NotEnabled', '1')
        ctx.view.getControl(IMAGE_LIST).reset()
        ctx.view.getControl(IMAGE_LIST).addItem(list_item)

    # show infos from datfiles only when changed
    if ctx.software.oldset == (ctx.software.actset['swl_name'], ctx.software.actset['name']):
        return

    # check play status
    # TODO check if all, system or set
    # TODO also show series and compilation status
    stattext = ''
    if ctx.software.played['count'] > 0:
        if ctx.software.actset['last_played']:
            played_text = tr(S.PLAYED_AGO, ctx.software.actset['last_played']['last_nice'])
        else:
            played_text = tr(S.PLAYED_NEVER)
        stattext = (
            f"{played_text}, {ctx.software.played['played']}h, "
            f"{ctx.software.played['count']}x[CR]"
        )

    list_items = []
    count = 0
    if ctx.software.actset['id'] in ctx.software.all_dat:
        set_dat = ctx.software.all_dat[ctx.software.actset['id']]
        for k in sorted(set_dat, key=textlist_sort_key):
            moretext = ''
            if k in TEXTLIST_HIDDEN:
                continue
            if k == DAT_HISTORY:
                moretext = stattext

            list_item = xbmcgui.ListItem()
            list_item.setLabel(k)
            list_item.setProperty('text', moretext + set_dat[k])
            list_items.append(list_item)
            count += 1

    if len(list_items) == 0:
        list_item = xbmcgui.ListItem()
        list_item.setLabel(tr(S.NO_INFO))
        list_item.setProperty(TEXTLIST_KEY_PROPERTY, TEXTLIST_KEY_NO_INFO)
        list_item.setProperty('text', stattext)
        list_items.append(list_item)

    ctx.view.getControl(TEXTLIST).reset()
    ctx.view.getControl(TEXTLIST).addItems(list_items)

    # shadow pointer
    if count > 1:
        ctx.view.getControl(SHADOW_DAT).setVisible(True)
    else:
        ctx.view.getControl(SHADOW_DAT).setVisible(False)

    # remember actual swl and set
    ctx.software.oldset = (ctx.software.actset['swl_name'], ctx.software.actset['name'])
    # refresh main menu
    menu.build_main_menu(ctx.menu)
    xbmc.log("UMSA gui: show_artwork: pics, dats done")
