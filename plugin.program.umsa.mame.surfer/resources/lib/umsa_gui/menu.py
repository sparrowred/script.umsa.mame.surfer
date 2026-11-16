"""Main menu and list-mode submenu of the UMSA frontend.

Both menus are pure Kodi list construction: they read the current selection
state from their context and fill the skin controls.
"""

from dataclasses import dataclass

import xbmc
import xbmcgui
from umsa_core.dat_parser import DAT_REC

from . import strings as S
from .constants import (
    LISTMODE_MENU,
    M_ALL,
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
    M_SEARCH_NEW,
    M_SERIES,
    M_SOURCE,
    M_SSAVER,
    M_SWL,
    M_UPD,
    M_YEAR,
    MAIN_MENU,
    SERIES_LABEL,
    SUBMENU_ORDER,
)
from .strings import tr


@dataclass
class MenuCtx:
    """What the menus read: selection, history, search and filter name."""

    view: object = None
    services: object = None
    software: object = None
    history: object = None
    listing: object = None
    filters: object = None


def build_sublist_menu(ctx, select):
    """Build the sublist menu for the listmode."""

    if select in SUBMENU_ORDER:
        position = SUBMENU_ORDER[select]
    else:
        position = 0
        xbmc.log(f"UMSA gui: build_sublist_menu: select unknown: {select}")

    list_items = []
    list_items.append(xbmcgui.ListItem(tr(S.MENU_SHOW_ALL), str(M_ALL)))

    # series
    last_val = ctx.history.last[ctx.history.lastptr] if ctx.history.last else None
    xbmc.log(f"UMSA gui: build_sublist_menu: last={ctx.history.last}, lastptr={ctx.history.lastptr}, last_val={last_val}")
    series = ctx.services.ggdb.games.check_series(last_val) if last_val is not None else 0
    xbmc.log(f"UMSA gui: build_sublist_menu: series={series}")
    if series:
        list_items.append(xbmcgui.ListItem(tr(S.MENU_SERIES, series), str(M_SERIES)))
    else:
        position = position - 1

    list_items.append(xbmcgui.ListItem(tr(S.MENU_MAKER), str(M_MAKER)))
    list_items.append(xbmcgui.ListItem(tr(S.MENU_CATEGORY), str(M_CAT)))

    rec = False
    for i in ctx.software.all_dat:
        if DAT_REC in ctx.software.all_dat[i]:
            rec = True
            break
    if rec:
        list_items.append(xbmcgui.ListItem(tr(S.RECOMMENDED), str(M_REC)))
    else:
        position = position - 1

    list_items.append(xbmcgui.ListItem(tr(S.MENU_YEAR), str(M_YEAR)))
    list_items.append(xbmcgui.ListItem(tr(S.MENU_PLAYERS), str(M_PLAYERS)))

    # source
    if ctx.software.actset['swl_name'] == 'mame':
        count_source = ctx.services.ggdb.games.count_source(ctx.software.actset['source'])
        if count_source > 1:
            list_items.append(xbmcgui.ListItem(
                tr(S.MENU_SOURCE, ctx.software.actset['source'][:-4], count_source),
                str(M_SOURCE)))
        else:
            xbmc.log(f"UMSA gui: build_sublist_menu: only 1 source: {ctx.software.actset['source']}")
    # swl
    else:
        list_items.append(xbmcgui.ListItem(
            tr(S.MENU_SOFTWARELIST, ctx.software.actset['swl_name']), str(M_SWL)))

    list_items.append(xbmcgui.ListItem(tr(S.MENU_SAVER_SESSION), str(M_LSSAVER)))
    list_items.append(xbmcgui.ListItem(tr(S.MENU_PLAY_STATUS), str(M_PLAYSTAT)))

    ctx.view.getControl(LISTMODE_MENU).reset()
    ctx.view.getControl(LISTMODE_MENU).addItems(list_items)
    ctx.view.getControl(LISTMODE_MENU).selectItem(position)


def build_main_menu(ctx, select=None):
    """Shows the context menu."""

    position = 0
    list_items = []
    # check series
    series = ctx.services.ggdb.games.check_series(ctx.history.last[ctx.history.lastptr])
    # set series indicator
    if series:
        ctx.view.getControl(SERIES_LABEL).setVisible(True)
    else:
        ctx.view.getControl(SERIES_LABEL).setVisible(False)
    # change list with select parameter
    if select == M_SOURCE:
        list_items.append(xbmcgui.ListItem(tr(S.MENU_SHOW_SOURCE), str(M_SOURCE)))
    elif select == M_SWL:
        list_items.append(xbmcgui.ListItem(tr(S.MENU_SHOW_SWL), str(M_SWL)))
    elif series:
        list_items.append(xbmcgui.ListItem(tr(S.MENU_SERIES, series), str(M_SERIES)))
    else:
        list_items.append(xbmcgui.ListItem(tr(S.MENU_SHOW_ALL), str(M_ALL)))
    if select == M_MACHINE:
        position = 2
    # media
    if ctx.software.vidman == (0, 0):
        list_items.append(xbmcgui.ListItem(tr(S.MENU_MEDIA), str(M_MEDIA)))
    else:
        list_items.append(xbmcgui.ListItem(
            tr(S.MENU_MEDIA_COUNT, ctx.software.vidman[0], ctx.software.vidman[1]), str(M_MEDIA)))
    # mame machines and different emulators
    count_machines = 0
    if ctx.software.actset['swl_name'] != 'mame':
        count_machines = ctx.services.ggdb.games.count_machines_for_swl(ctx.software.actset['swl_name'])
    if count_machines > 1:
        list_items.append(
            xbmcgui.ListItem(tr(S.MENU_EMULATOR_COUNT, count_machines), str(M_MACHINE)))
    else:
        list_items.append(xbmcgui.ListItem(tr(S.MENU_EMULATOR), str(M_MACHINE)))
    # search
    if ctx.listing.searchold:
        list_items.append(xbmcgui.ListItem(
            tr(S.MENU_SEARCH_TERM, ctx.listing.searchold), str(M_SEARCH_NEW)))
    else:
        list_items.append(xbmcgui.ListItem(tr(S.SEARCH), str(M_SEARCH_NEW)))
    # filter
    if ctx.services.ggdb.gamelist.use_filter:
        list_items.append(xbmcgui.ListItem(
            tr(S.MENU_FILTER_NAME, ctx.filters.act_filter), str(M_FILTER)))
    else:
        list_items.append(xbmcgui.ListItem(tr(S.MENU_FILTER_OFF), str(M_FILTER)))
    list_items.append(xbmcgui.ListItem(tr(S.SCREENSAVER), str(M_SSAVER)))
    list_items.append(xbmcgui.ListItem(tr(S.MENU_UPDATE), str(M_UPD)))
    list_items.append(xbmcgui.ListItem(tr(S.MENU_SETTINGS), str(M_ASETTINGS)))
    list_items.append(xbmcgui.ListItem(tr(S.MENU_EXIT), str(M_EXIT)))
    ctx.view.getControl(MAIN_MENU).reset()
    ctx.view.getControl(MAIN_MENU).addItems(list_items)
    ctx.view.getControl(MAIN_MENU).selectItem(position)
