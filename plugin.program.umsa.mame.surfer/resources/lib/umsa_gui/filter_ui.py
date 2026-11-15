"""Filter user interface of the UMSA frontend.

The filter lists are partitioned by the Core helper ``build_filter_lists``;
this module only drives the dialogs and the skin controls.
"""

from dataclasses import dataclass

import xbmc
import xbmcgui
from umsa_core import FILTER_CATEGORIES
from umsa_core.gamelist_filter import build_filter_lists

from . import strings as S
from .constants import (
    FILTER_CATEGORY_KEYS,
    FILTER_CATEGORY_LIST,
    FILTER_CONTENT_LIST_ACTIVE,
    FILTER_CONTENT_LIST_INACTIVE,
    FILTER_KEY_LOAD,
    FILTER_KEY_SAVE,
    FILTER_LABEL,
    FILTER_LABEL2,
    LABEL_STATUS,
)
from .strings import tr

# category shown after loading or saving a filter
FILTER_START_CATEGORY = "Softwarelists"

# entries of Core's FILTER_CATEGORIES that are no category: their key
FILTER_ENTRY_KEYS = {
    "Load Filter": FILTER_KEY_LOAD,
    "Save Filter": FILTER_KEY_SAVE,
}


# text of the filter category list entries, by key
CATEGORY_LABELS = {
    "Softwarelists": S.FILTER_CAT_SOFTWARELISTS,
    "Game Categories": S.FILTER_CAT_GAME_CATEGORIES,
    "Machine Categories": S.FILTER_CAT_MACHINE_CATEGORIES,
    "Players": S.FILTER_CAT_PLAYERS,
    "Years": S.FILTER_CAT_YEARS,
    FILTER_KEY_LOAD: S.FILTER_LOAD,
    FILTER_KEY_SAVE: S.FILTER_SAVE,
}


@dataclass
class FilterCtx:
    """Filter lists, the database they are applied to and the focus to return to."""

    view: object = None
    services: object = None
    filters: object = None
    listing: object = None


def category_label(key):
    """Return the text shown for the filter category (or action) ``key``."""

    string_id = CATEGORY_LABELS.get(key)
    return tr(string_id) if string_id else key


def category_list_items():
    """Return the entries of the filter category list.

    label2 holds the key the handlers dispatch on: the category name as it
    is stored in status.db, ``FILTER_KEY_LOAD`` / ``FILTER_KEY_SAVE`` for the
    two actions and nothing for the separator.
    """

    items = []
    for name in FILTER_CATEGORIES:
        if name in FILTER_CATEGORY_KEYS:
            key = name
        else:
            key = FILTER_ENTRY_KEYS.get(name, '')
        # the separator has no key and shows as it is
        items.append(xbmcgui.ListItem(category_label(key) if key else name, key))
    return items


def empty_filter_lists():
    """Return a fresh filter dict with all five categories empty."""

    return {key: [] for key in FILTER_CATEGORY_KEYS}


def close_filterlist(ctx, no_update=None):
    """Close filter list window"""

    xbmc.log("UMSA gui: close_filterlist")
    # update filter
    if not no_update:
        ctx.view.getControl(LABEL_STATUS).setLabel(
            tr(S.FILTERED_ITEMS, ctx.services.ggdb.gamelist.define_filter(ctx.filters.filter_lists))
        )
    ctx.view.setFocus(ctx.view.getControl(ctx.listing.main_focus))


def filter_category(ctx):
    """Open filter category, load and save filters"""

    # get filter category and set filter content list
    cat = ctx.view.getControl(FILTER_CATEGORY_LIST).getSelectedItem().getLabel2()

    # save/load filter
    if cat in (FILTER_KEY_LOAD, FILTER_KEY_SAVE):
        files = ctx.services.ggdb.history.list_filter_names()

        if cat == FILTER_KEY_LOAD:
            ret = ctx.services.dialog.select(tr(S.FILTER_LOAD), files)
            if ret == -1:
                return
            ctx.filters.filter_lists = ctx.services.ggdb.history.load_filter_selections(files[ret])
            ctx.view.getControl(LABEL_STATUS).setLabel(
                tr(S.FILTERED_ITEMS, ctx.services.ggdb.gamelist.define_filter(ctx.filters.filter_lists))
            )
            ctx.filters.act_filter = files[ret]
            ctx.view.getControl(FILTER_LABEL2).setLabel(tr(S.FILTER_NAME, ctx.filters.act_filter))
            show_start_category(ctx)

        else:
            # the entry after the saved filters creates a new one
            ret = ctx.services.dialog.select(
                tr(S.FILTER_SAVE), list(files) + [tr(S.FILTER_CREATE_NEW)])
            if ret == -1:
                return
            if ret == len(files):
                keyboard = xbmc.Keyboard('', tr(S.FILTER_NAME_PROMPT), 0)
                keyboard.doModal()
                if keyboard.isConfirmed():
                    filter_filename = keyboard.getText()
                else:
                    return
            else:
                filter_filename = files[ret]

            # save filters
            ctx.services.ggdb.history.save_filter_selections(filter_filename, ctx.filters.filter_lists)
            ctx.filters.act_filter = filter_filename
            ctx.view.getControl(FILTER_LABEL2).setLabel(tr(S.FILTER_NAME, ctx.filters.act_filter))
            show_start_category(ctx)

    # or load the content lists of the chosen category and move into them
    elif cat in FILTER_CATEGORY_KEYS:
        set_filter_content(ctx, cat)


def show_start_category(ctx):
    """Select the Softwarelists category and show its lists (focus stays)."""

    ctx.view.getControl(FILTER_CATEGORY_LIST).selectItem(
        FILTER_CATEGORIES.index(FILTER_START_CATEGORY))
    # selectItem() is applied asynchronously: name the category explicitly
    set_filter_content(ctx, FILTER_START_CATEGORY, focus_lists=False)


def show_category_content(ctx, force=False):
    """Fill the active/inactive lists for the selected filter category.

    The focus stays in the category list. Entries that are no category
    (separator, Load/Save Filter) leave the lists as they are. Without
    ``force`` an already shown category is not reloaded, so callbacks that
    queued up while a key was held cost nothing.
    """

    item = ctx.view.getControl(FILTER_CATEGORY_LIST).getSelectedItem()
    if not item:
        return
    cat = item.getLabel2()
    if cat not in FILTER_CATEGORY_KEYS:
        return
    if not force and ctx.filters.act_filter_category == cat:
        return
    set_filter_content(ctx, cat, focus_lists=False)


def filter_content(ctx, which_content):
    """filter content

    Gets called with action on filter list
    """

    if which_content == 'active':
        contentlist = FILTER_CONTENT_LIST_ACTIVE
    else:
        contentlist = FILTER_CONTENT_LIST_INACTIVE

    # get actual category
    filter_category_name = ctx.filters.act_filter_category
    # get db id for actual content entry
    filter_content_id = ctx.view.getControl(contentlist).getSelectedItem().getLabel2()

    # update internal list
    if which_content == 'active':
        xbmc.log(f"UMSA gui: filter_content: remove: {filter_content_id}")
        ctx.filters.filter_lists[filter_category_name].remove(filter_content_id)
    else:
        xbmc.log(f"UMSA gui: filter_content: append: {filter_content_id}")
        ctx.filters.filter_lists[filter_category_name].append(filter_content_id)

    # update the lists
    set_filter_content(ctx, filter_category_name, update=which_content)


def set_filter_content(ctx, cat, update=None, focus_lists=True):
    """Set filter content

    ``focus_lists=False`` keeps the focus in the category list on the
    initial fill (``update=None``).
    """

    filter_content_id = 0
    f_select = 0
    f_element = 0

    # only for action in list, not for inital fill
    if update == 'active':
        f_element = ctx.view.getControl(FILTER_CONTENT_LIST_ACTIVE).getSelectedPosition()
        filter_content_id = int(
            ctx.view.getControl(FILTER_CONTENT_LIST_ACTIVE).getSelectedItem().getLabel2()
        )
    elif update == 'inactive':
        f_element = ctx.view.getControl(FILTER_CONTENT_LIST_INACTIVE).getSelectedPosition()
        filter_content_id = int(
            ctx.view.getControl(FILTER_CONTENT_LIST_INACTIVE).getSelectedItem().getLabel2()
        )

    # partition entries into active and inactive lists
    lists = build_filter_lists(ctx.filters.filter_lists, cat, ctx.services.ggdb.games)
    active = [
        xbmcgui.ListItem(f"{entry['name']} ({entry['count']})", entry['id'])
        for entry in lists['active']
    ]
    inactive = [
        xbmcgui.ListItem(f"{entry['name']} ({entry['count']})", entry['id'])
        for entry in lists['inactive']
    ]

    # check for selected item id, so we can select this in the other list
    if update == 'active':
        for index, entry in enumerate(lists['inactive']):
            if entry['id'] == str(filter_content_id):
                f_select = index
                break
    elif update == 'inactive':
        for index, entry in enumerate(lists['active']):
            if entry['id'] == str(filter_content_id):
                f_select = index
                break

    # reset lists and refill
    ctx.view.setFocus(ctx.view.getControl(FILTER_CATEGORY_LIST))
    ctx.view.getControl(FILTER_CONTENT_LIST_ACTIVE).reset()
    ctx.view.getControl(FILTER_CONTENT_LIST_INACTIVE).reset()
    ctx.view.getControl(FILTER_CONTENT_LIST_ACTIVE).addItems(active)
    ctx.view.getControl(FILTER_CONTENT_LIST_INACTIVE).addItems(inactive)
    ctx.view.getControl(FILTER_LABEL).setLabel(category_label(cat))
    ctx.filters.act_filter_category = cat

    # set selected items and focus
    if update == 'active':
        if f_element == len(active):
            f_element -= 1
        ctx.view.getControl(FILTER_CONTENT_LIST_ACTIVE).selectItem(f_element)
        ctx.view.getControl(FILTER_CONTENT_LIST_INACTIVE).selectItem(f_select)
        if len(active) > 0:
            ctx.view.setFocus(ctx.view.getControl(FILTER_CONTENT_LIST_ACTIVE))
        else:
            ctx.view.setFocus(ctx.view.getControl(FILTER_CONTENT_LIST_INACTIVE))
    elif update:
        if f_element == len(inactive):
            f_element -= 1
        ctx.view.getControl(FILTER_CONTENT_LIST_INACTIVE).selectItem(f_element)
        ctx.view.getControl(FILTER_CONTENT_LIST_ACTIVE).selectItem(f_select)
        if len(inactive) > 0:
            ctx.view.setFocus(ctx.view.getControl(FILTER_CONTENT_LIST_INACTIVE))
        else:
            ctx.view.setFocus(ctx.view.getControl(FILTER_CONTENT_LIST_ACTIVE))
    elif focus_lists:
        # switch to inactive when active is empty
        if len(active) > 0:
            ctx.view.setFocus(ctx.view.getControl(FILTER_CONTENT_LIST_ACTIVE))
        else:
            ctx.view.setFocus(ctx.view.getControl(FILTER_CONTENT_LIST_INACTIVE))
