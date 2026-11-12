"""Gamelist construction, presentation and navigation.

``update_gamelist`` dispatches to the strategies in ``gamelist_strategies`` and
``popup_gamelist`` fills the game list control. The activation of a gamelist
entry lives in ``gamelist_actions``.
"""

import threading
import time
from dataclasses import dataclass

import xbmc
import xbmcgui
from gamelist_strategies import EARLY_RETURN, GAMELIST_STRATEGIES

from . import strings as S
from .constants import (
    GAME_LIST,
    GAME_LIST_LABEL,
    GAME_LIST_LABEL_ID,
    GAME_LIST_OPTIONS,
    GAME_LIST_SORT,
    GAMELIST_SETTLE_DELAY,
    KIND_EMULATORS,
    KIND_MACHINES,
    KIND_SELECT,
    KIND_SOFTWARE,
    LABEL_STATUS,
    M_ALLEMUS,
    M_CAT,
    M_MACHINE,
    M_MAKER,
    M_MEDIA,
    M_PLAYERS,
    M_SEARCH,
    M_SOURCE,
    M_SWL,
    M_YEAR,
    OPTION_NEW_SEARCH,
    SOFTWARE_BUTTON,
)
from .strings import tr

# text of the GAME_LIST_OPTIONS entries, by option key; other keys show as is
OPTION_LABELS = {
    OPTION_NEW_SEARCH: S.OPTION_NEW_SEARCH,
    'name': S.OPTION_NAME,
    'year': S.OPTION_YEAR,
    'publisher': S.OPTION_PUBLISHER,
    'time_played': S.OPTION_TIME_PLAYED,
    'last_played': S.OPTION_LAST_PLAYED,
    'play_count': S.OPTION_PLAY_COUNT,
    'all swls': S.OPTION_ALL_SWLS,
    'get connected swls': S.OPTION_CONNECTED_SWLS,
}

# lists that hold no software entries, by menu code
LIST_KINDS = {
    M_MACHINE: KIND_MACHINES,
    M_ALLEMUS: KIND_EMULATORS,
}


def option_label(key):
    """Return the text shown for the option ``key``."""

    string_id = OPTION_LABELS.get(key)
    return tr(string_id) if string_id else key


@dataclass
class GamelistCtx:
    db: object = None
    actset: object = None
    last: object = None
    lastptr: int = 0
    searchold: object = None
    popup_gamelist: object = None
    show_rec: object = None


class GamelistSettle:
    """Deferred reload of the gamelist entry once the list stopped moving.

    While a key is held (or the analog trigger scrolls) the ``onAction``
    callbacks queue up behind the synchronous artwork lookups, and the entry
    the list finally stops on may never be shown. Every movement restarts a
    timer; when it fires, ``Action(noop)`` is sent to the window, and its
    ``onAction`` handler reloads the selected entry on the script thread.

    The timer thread only calls ``executebuiltin``: the database connection
    and the controls stay on the script thread.
    """

    def __init__(self, delay=GAMELIST_SETTLE_DELAY):
        self.delay = delay
        self._timer = None
        self._lock = threading.Lock()

    def schedule(self):
        """(Re)start the timer."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self):
        """Stop a pending timer."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _fire(self):
        with self._lock:
            self._timer = None
        xbmc.executebuiltin('Action(noop)')


def update_gamelist(gui, item):
    """Update gamelist"""

    results, pos = [], 0

    xbmc.log(f"UMSA gui: update_gamelist: item = {item}")
    gui.getControl(GAME_LIST_LABEL_ID).setLabel(str(item))
    gui.getControl(GAME_LIST).reset()

    # without list popup
    if item == M_MEDIA:
        gui.choose_media()
        return

    # show loading status (popup title and status line)
    gui.getControl(GAME_LIST_LABEL).setLabel(tr(S.LOADING))
    gui.getControl(LABEL_STATUS).setLabel(tr(S.LOADING))
    time1 = time.time()

    strategy = GAMELIST_STRATEGIES.get(item)
    if strategy is not None:
        gl_ctx = GamelistCtx(
            db=gui.ggdb,
            actset=gui.actset,
            last=gui.last,
            lastptr=gui.lastptr,
            searchold=gui.searchold,
            popup_gamelist=gui.popup_gamelist,
            show_rec=gui.show_rec,
        )
        outcome = strategy(gl_ctx)
        gui.searchold = gl_ctx.searchold
        if outcome is EARLY_RETURN:
            # Ensure the submenu is populated for strategies that open a gamelist
            # (Series, Recommended) so that left navigation from the gamelist works.
            gui.build_sublist_menu(item)
            gui.getControl(LABEL_STATUS).setLabel('')
            return
        results, pos, gl_label, gl_options = outcome

    # no results = close list
    if len(results) == 0:
        gui.getControl(LABEL_STATUS).setLabel('')
        if item == M_SEARCH:
            gui.searchold = None
        gui.dialog.notification(tr(S.SEARCH), tr(S.SEARCH_NOTHING),
            xbmcgui.NOTIFICATION_ERROR, 3000, False)
        return

    # one software result = select
    if len(results) == 1 and item not in (M_MACHINE, M_ALLEMUS):
        if item == M_SEARCH:
            gui.searchold = None
        gui.dialog.notification(tr(S.SEARCH), tr(S.SEARCH_ONE_HIT),
            xbmcgui.NOTIFICATION_INFO, 2000, False)
        # TODO: check if this id is the one already shown
        gui._remember_and_select(results[0]['id'])
        gui.setFocus(gui.getControl(SOFTWARE_BUTTON))
        return

    if gui.ggdb.use_filter:
        use_filter = [tr(S.LIST_FILTER_ON), tr(S.LIST_FILTER_OFF)]
    else:
        use_filter = [tr(S.LIST_FILTER_OFF), tr(S.LIST_FILTER_ON)]

    time2 = time.time()
    gui.getControl(LABEL_STATUS).setLabel(
        tr(S.QUERY_TOOK, f'{(time2-time1)*1000:.0f}')
    )

    # now show gamelist with gathered info from above
    gui.popup_gamelist(
        results, gl_label, pos=pos, sort=use_filter, options=gl_options,
        kind=LIST_KINDS.get(item, KIND_SOFTWARE))
    # build submenu with lists in it
    gui.build_sublist_menu(item)

    time3 = time.time()
    xbmc.log(f'UMSA gui: update_gamelist: popup in gui: {(time3-time2)*1000:.0f}ms')
    xbmc.log(f'UMSA gui: update_gamelist: time overall: {(time3-time1)*1000:.0f}ms')


def popup_gamelist(gui, gamelist, label, pos=0, sort=None, options=None,
                   kind=KIND_SOFTWARE, select_what=None):
    """Pop up gamelist.

    ``kind`` tells the click and move handlers what the list holds
    (``KIND_*``); ``select_what`` is the menu code of a ``KIND_SELECT`` list.
    ``options`` are option keys: the entries carry them in label2.
    """

    gui.gamelist_kind = kind
    gui.gamelist_select = select_what

    list_items = []
    for i in gamelist:
        if not i:
            xbmc.log(f"UMSA gui: popup_gamelist: item in gamelist {label} broken: {i}", xbmc.LOGERROR)
            continue
        listitem = xbmcgui.ListItem(i['name'], str(i['id']))
        if 'year' in i:
            listitem.setInfo('video', {'Writer': i['year'], 'Studio': i['maker']})
        list_items.append(listitem)

    gui.getControl(GAME_LIST_LABEL).setLabel(label)
    gui.getControl(GAME_LIST_OPTIONS).reset()
    if options:
        gui.getControl(GAME_LIST_OPTIONS).addItems(
            [xbmcgui.ListItem(option_label(option), option) for option in options])
    gui.getControl(GAME_LIST_SORT).reset()
    if sort:
        gui.getControl(GAME_LIST_SORT).addItems(sort)
    gui.getControl(GAME_LIST).reset()
    gui.getControl(GAME_LIST).addItems(list_items)
    gui.getControl(GAME_LIST).selectItem(pos)

    gui.setFocus(gui.getControl(GAME_LIST))
    # load snap, all_machines for the entry at pos: selectItem() runs
    # asynchronously in Kodi, getSelectedItem() would still return entry 0
    gui.gamelist_move(pos)
    # reload once Kodi applied the selection
    gui.schedule_gamelist_settle()


def gamelist_move(gui, pos=None, force=False):
    """Load snap and machines for a gamelist entry.

    ``pos`` names the entry explicitly (default: the selected one).
    ``force`` re-applies already loaded data without a database lookup so
    that Kodi refreshes the info labels of the selected entry.
    """

    # only software lists have a snap and machines to load
    if gui.gamelist_kind != KIND_SOFTWARE:
        xbmc.log(f"UMSA gui: gamelist_move: list kind {gui.gamelist_kind} = return")
        return
    control = gui.getControl(GAME_LIST)
    if pos is None:
        pos = control.getSelectedPosition()
        gamelist_item = control.getSelectedItem()
    else:
        gamelist_item = control.getListItem(pos) if 0 <= pos < control.size() else None
    # check if we have an item
    if not gamelist_item:
        xbmc.log("UMSA gui: gamelist_move: no selected item = return")
        return
    gamelist_id = gamelist_item.getLabel2()
    # check if gamelist_id is valid (0 = invalid, prev/next = paging entries)
    if gamelist_id in ("0", "prev", "next") or "::" in gamelist_id:
        xbmc.log(f"UMSA gui: gamelist_move: pos {pos}: no software id ({gamelist_id}) = return")
        return
    # data already loaded: only refresh when forced
    if gamelist_item.getProperty('text'):
        if force:
            snap = gamelist_item.getProperty('snap')
            if snap:
                gamelist_item.setArt({'icon': snap})
            gamelist_item.setProperty('text', gamelist_item.getProperty('text'))
            xbmc.log(f"UMSA gui: gamelist_move: pos {pos}: refreshed {gamelist_id} (force)")
        else:
            xbmc.log(f"UMSA gui: gamelist_move: pos {pos}: text already there = return")
        return
    # get snap, machines
    xbmc.log(f"UMSA gui: gamelist_move: pos {pos}: db fetch snap, machines for {gamelist_id}")
    snap = gui.ggdb.get_artwork_by_software_id(
        gamelist_id, 'snap', gui.artwork_source_roots())
    # set info to gamelist item
    if snap[0]:
        gamelist_item.setArt({'icon': snap[0]})
        gamelist_item.setProperty('snap', snap[0])
    gamelist_item.setProperty('text', snap[1])
    xbmc.log(f"UMSA gui: gamelist_move: properties set = {gamelist_item.getProperty('text')}")


def gamelist_switch_filter(gui):
    """Switch filter in gamelist"""

    if gui.ggdb.use_filter:
        gui.ggdb.set_filter_enabled(False)
    else:
        gui.ggdb.set_filter_enabled(True)

    content = int(gui.getControl(GAME_LIST_LABEL_ID).getLabel())
    gui.setFocus(gui.getControl(GAME_LIST_OPTIONS))
    gui.update_gamelist(content)


def show_fulllist(gui, what, label):
    """Show full list of maker, cat, year...

    Menu entries without such a list (Show all, Series, Recommended,
    Screensaver session, Play Status) are ignored.
    """

    if what == M_MAKER:
        my_list = gui.ggdb.get_maker()
    elif what == M_SWL:
        my_list = gui.ggdb.get_swl()
    elif what == M_SOURCE:
        my_list = []
        for i in gui.ggdb.get_source():
            my_list.append({'id': "source", 'name': i['source']})
    elif what == M_YEAR:
        my_list = gui.ggdb.get_year()
    elif what == M_PLAYERS:
        my_list = gui.ggdb.get_players()
    elif what == M_CAT:
        my_list = gui.ggdb.get_categories()
    else:
        xbmc.log(
            f"UMSA gui: show_fulllist: no select list for menu code {what}",
            xbmc.LOGDEBUG)
        return
    gui.popup_gamelist(
        my_list, tr(S.LIST_SELECT, label), kind=KIND_SELECT, select_what=what)
