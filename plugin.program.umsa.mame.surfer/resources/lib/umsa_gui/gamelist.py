"""Gamelist construction, presentation and navigation.

``update_gamelist`` dispatches to the strategies in ``gamelist_strategies`` and
``popup_gamelist`` fills the game list control. The activation of a gamelist
entry lives in ``gamelist_actions``.
"""

import threading
import time
from dataclasses import dataclass
from functools import partial

import xbmc
import xbmcgui
from gamelist_strategies import EARLY_RETURN, GAMELIST_STRATEGIES

from . import media_list, menu, software_selector
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
    LISTMODE_MENU,
    M_ALLEMUS,
    M_CAT,
    M_MACHINE,
    M_MAKER,
    M_MEDIA,
    M_PLAYERS,
    M_SEARCH,
    M_SEARCH_NEW,
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


def ask_search_term():
    """Ask for a search term; None when the keyboard was cancelled."""

    keyboard = xbmc.Keyboard('', tr(S.SEARCH_FOR), 0)
    keyboard.doModal()
    if not keyboard.isConfirmed():
        return None
    return keyboard.getText()


def list_items(rows):
    """Game-list entries for ``rows`` (``name``, ``id``, optional ``year``/``maker``).

    label2 carries the id the click and move handlers dispatch on.
    """

    items = []
    for row in rows:
        if not row:
            xbmc.log(f"UMSA gui: list_items: broken row: {row}", xbmc.LOGERROR)
            continue
        item = xbmcgui.ListItem(row['name'], str(row['id']))
        if 'year' in row:
            item.setInfo('video', {'Writer': row['year'], 'Studio': row['maker']})
        items.append(item)
    return items


def show_play_status(ctx, key):
    """Refill the game list with the play status ordered by ``key``."""

    rows, _pos = ctx.services.ggdb.software.get_last_played(key)
    control = ctx.view.getControl(GAME_LIST)
    control.reset()
    control.addItems(list_items(rows))
    ctx.view.setFocus(control)


@dataclass
class GamelistUiCtx:
    """Game list control, its state and what a list entry needs."""

    view: object = None
    services: object = None
    listing: object = None
    software: object = None
    history: object = None
    settings: object = None
    # deferred reload of the selected entry (GamelistSettle)
    settle: object = None
    # contexts of the modules the game list calls
    menu: object = None
    media: object = None
    selector: object = None


@dataclass
class GamelistCtx:
    """What a gamelist strategy (``gamelist_strategies``) works with."""

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


def _open_list(ctx, item):
    """Make the game list the list of the menu code ``item`` (still empty)."""

    ctx.view.getControl(GAME_LIST_LABEL_ID).setLabel(str(item))
    ctx.view.getControl(GAME_LIST).reset()


def update_gamelist(ctx, item, focus=True):
    """Update gamelist

    ``focus=False`` is the preview of the list-mode submenu: the list is
    filled while the focus stays in the submenu, a single hit is listed
    instead of selected, an empty result shows an empty list without a
    notification, and the submenu is not rebuilt.
    """

    results, pos = [], 0

    # a new search (or a repeated one without a term) asks first: a cancelled
    # keyboard leaves the shown list alone. The new term replaces the stored
    # one (and the shown list) only when it fills a list: more than one hit.
    new_term = None
    if item == M_SEARCH_NEW or (item == M_SEARCH and not ctx.listing.searchold):
        new_term = ask_search_term() if focus else None
        if new_term is None:
            return
        item = M_SEARCH

    xbmc.log(f"UMSA gui: update_gamelist: item = {item}")
    if new_term is None:
        _open_list(ctx, item)

    # without list popup
    if item == M_MEDIA:
        media_list.choose_media(ctx.media)
        return

    # show loading status (popup title and status line)
    if new_term is None:
        ctx.view.getControl(GAME_LIST_LABEL).setLabel(tr(S.LOADING))
    ctx.view.getControl(LABEL_STATUS).setLabel(tr(S.LOADING))
    time1 = time.time()

    strategy = GAMELIST_STRATEGIES.get(item)
    if strategy is not None:
        gl_ctx = GamelistCtx(
            db=ctx.services.ggdb,
            actset=ctx.software.actset,
            last=ctx.history.last,
            lastptr=ctx.history.lastptr,
            searchold=new_term if new_term is not None else ctx.listing.searchold,
            popup_gamelist=(partial(popup_gamelist, ctx) if focus
                            else partial(popup_gamelist, ctx, focus=False)),
            show_rec=(partial(media_list.show_rec, ctx.media) if focus
                      else partial(media_list.show_rec, ctx.media, focus=False)),
        )
        outcome = strategy(gl_ctx)
        if outcome is EARLY_RETURN:
            # Ensure the submenu is populated for strategies that open a gamelist
            # (Series, Recommended) so that left navigation from the gamelist works.
            if focus:
                menu.build_sublist_menu(ctx.menu, item)
            ctx.listing.listmode_shown = item
            ctx.view.getControl(LABEL_STATUS).setLabel('')
            return
        results, pos, gl_label, gl_options = outcome

    # preview without results: empty list, no notification
    if not focus and len(results) == 0:
        ctx.view.getControl(LABEL_STATUS).setLabel('')
        ctx.view.getControl(GAME_LIST_LABEL).setLabel(gl_label if strategy is not None else '')
        ctx.view.getControl(GAME_LIST_OPTIONS).reset()
        ctx.view.getControl(GAME_LIST_SORT).reset()
        ctx.listing.gamelist_kind = LIST_KINDS.get(item, KIND_SOFTWARE)
        ctx.listing.gamelist_select = None
        ctx.listing.listmode_shown = item
        return

    # no results = close list (a new search term leaves the shown list and the
    # stored term alone; a stored term is never forgotten)
    if len(results) == 0:
        ctx.view.getControl(LABEL_STATUS).setLabel('')
        ctx.services.dialog.notification(tr(S.SEARCH), tr(S.SEARCH_NOTHING),
            xbmcgui.NOTIFICATION_ERROR, 3000, False)
        return

    # one software result = select (a new search term with one hit leaves the
    # shown list and the stored term alone)
    if focus and len(results) == 1 and item not in (M_MACHINE, M_ALLEMUS):
        ctx.services.dialog.notification(tr(S.SEARCH), tr(S.SEARCH_ONE_HIT),
            xbmcgui.NOTIFICATION_INFO, 2000, False)
        # TODO: check if this id is the one already shown
        software_selector.remember_and_select(ctx.selector, results[0]['id'])
        ctx.view.setFocus(ctx.view.getControl(SOFTWARE_BUTTON))
        return

    # the new term fills the list: it is the stored term now
    if new_term is not None:
        ctx.listing.searchold = new_term
        _open_list(ctx, item)

    if ctx.services.ggdb.gamelist.use_filter:
        use_filter = [tr(S.LIST_FILTER_ON), tr(S.LIST_FILTER_OFF)]
    else:
        use_filter = [tr(S.LIST_FILTER_OFF), tr(S.LIST_FILTER_ON)]

    time2 = time.time()
    ctx.view.getControl(LABEL_STATUS).setLabel(
        tr(S.QUERY_TOOK, f'{(time2-time1)*1000:.0f}')
    )

    # now show gamelist with gathered info from above
    popup_gamelist(ctx,
        results, gl_label, pos=pos, sort=use_filter, options=gl_options,
        kind=LIST_KINDS.get(item, KIND_SOFTWARE), focus=focus)
    ctx.listing.listmode_shown = item
    # build submenu with lists in it
    if focus:
        menu.build_sublist_menu(ctx.menu, item)

    time3 = time.time()
    xbmc.log(f'UMSA gui: update_gamelist: popup in gui: {(time3-time2)*1000:.0f}ms')
    xbmc.log(f'UMSA gui: update_gamelist: time overall: {(time3-time1)*1000:.0f}ms')


def popup_gamelist(ctx, gamelist, label, pos=0, sort=None, options=None,
                   kind=KIND_SOFTWARE, select_what=None, focus=True):
    """Pop up gamelist.

    ``kind`` tells the click and move handlers what the list holds
    (``KIND_*``); ``select_what`` is the menu code of a ``KIND_SELECT`` list.
    ``options`` are option keys: the entries carry them in label2.
    ``focus=False`` fills the list without moving the focus into it.
    """

    # the list no longer shows a submenu entry (update_gamelist sets it again)
    ctx.listing.listmode_shown = None
    ctx.listing.gamelist_kind = kind
    ctx.listing.gamelist_select = select_what

    entries = list_items(gamelist)

    ctx.view.getControl(GAME_LIST_LABEL).setLabel(label)
    ctx.view.getControl(GAME_LIST_OPTIONS).reset()
    if options:
        ctx.view.getControl(GAME_LIST_OPTIONS).addItems(
            [xbmcgui.ListItem(option_label(option), option) for option in options])
    ctx.view.getControl(GAME_LIST_SORT).reset()
    if sort:
        ctx.view.getControl(GAME_LIST_SORT).addItems(sort)
    ctx.view.getControl(GAME_LIST).reset()
    ctx.view.getControl(GAME_LIST).addItems(entries)
    ctx.view.getControl(GAME_LIST).selectItem(pos)

    if focus:
        ctx.view.setFocus(ctx.view.getControl(GAME_LIST))
    # load snap, all_machines for the entry at pos: selectItem() runs
    # asynchronously in Kodi, getSelectedItem() would still return entry 0
    gamelist_move(ctx, pos)
    # reload once Kodi applied the selection
    ctx.settle.schedule()


def preview_listmode_gamelist(ctx):
    """Load the gamelist of the selected list-mode submenu entry.

    The focus stays in the submenu. An entry whose list is already shown is
    not reloaded, so callbacks that queued up while a key was held cost
    nothing.
    """

    item = ctx.view.getControl(LISTMODE_MENU).getSelectedItem()
    if not item:
        return
    try:
        menu_item = int(item.getLabel2())
    except ValueError:
        return
    if ctx.listing.listmode_shown == menu_item:
        return
    update_gamelist(ctx, menu_item, focus=False)


def gamelist_move(ctx, pos=None, force=False):
    """Load snap and machines for a gamelist entry.

    ``pos`` names the entry explicitly (default: the selected one).
    ``force`` re-applies already loaded data without a database lookup so
    that Kodi refreshes the info labels of the selected entry.
    """

    # only software lists have a snap and machines to load
    if ctx.listing.gamelist_kind != KIND_SOFTWARE:
        xbmc.log(f"UMSA gui: gamelist_move: list kind {ctx.listing.gamelist_kind} = return")
        return
    control = ctx.view.getControl(GAME_LIST)
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
    snap = ctx.services.ggdb.art_queries.get_artwork_by_software_id(
        gamelist_id, 'snap', ctx.settings.artwork_source_roots())
    # set info to gamelist item
    if snap[0]:
        gamelist_item.setArt({'icon': snap[0]})
        gamelist_item.setProperty('snap', snap[0])
    gamelist_item.setProperty('text', snap[1])
    xbmc.log(f"UMSA gui: gamelist_move: properties set = {gamelist_item.getProperty('text')}")


def gamelist_switch_filter(ctx):
    """Switch filter in gamelist"""

    if ctx.services.ggdb.gamelist.use_filter:
        ctx.services.ggdb.gamelist.set_filter_enabled(False)
    else:
        ctx.services.ggdb.gamelist.set_filter_enabled(True)

    content = int(ctx.view.getControl(GAME_LIST_LABEL_ID).getLabel())
    ctx.view.setFocus(ctx.view.getControl(GAME_LIST_OPTIONS))
    update_gamelist(ctx, content)


def show_fulllist(ctx, what, label):
    """Show full list of maker, cat, year...

    Menu entries without such a list (Show all, Series, Recommended,
    Screensaver session, Play Status) are ignored.
    """

    if what == M_MAKER:
        my_list = ctx.services.ggdb.games.get_maker()
    elif what == M_SWL:
        my_list = ctx.services.ggdb.games.get_swl()
    elif what == M_SOURCE:
        my_list = []
        for i in ctx.services.ggdb.games.get_source():
            my_list.append({'id': "source", 'name': i['source']})
    elif what == M_YEAR:
        my_list = ctx.services.ggdb.games.get_year()
    elif what == M_PLAYERS:
        my_list = ctx.services.ggdb.games.get_players()
    elif what == M_CAT:
        my_list = ctx.services.ggdb.games.get_categories()
    else:
        xbmc.log(
            f"UMSA gui: show_fulllist: no select list for menu code {what}",
            xbmc.LOGDEBUG)
        return
    popup_gamelist(ctx,
        my_list, tr(S.LIST_SELECT, label), kind=KIND_SELECT, select_what=what)
