"""Filter user interface of the UMSA frontend.

The filter lists are partitioned by the Core helper ``build_filter_lists``;
this module only drives the dialogs and the skin controls.
"""

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


def close_filterlist(gui, no_update=None):
    """Close filter list window"""

    xbmc.log("UMSA gui: close_filterlist")
    # update filter
    if not no_update:
        gui.getControl(LABEL_STATUS).setLabel(
            tr(S.FILTERED_ITEMS, gui.ggdb.gamelist.define_filter(gui.filter_lists))
        )
    gui.setFocus(gui.getControl(gui.main_focus))


def filter_category(gui):
    """Open filter category, load and save filters"""

    # get filter category and set filter content list
    cat = gui.getControl(FILTER_CATEGORY_LIST).getSelectedItem().getLabel2()

    # save/load filter
    if cat in (FILTER_KEY_LOAD, FILTER_KEY_SAVE):
        files = gui.ggdb.history.list_filter_names()

        if cat == FILTER_KEY_LOAD:
            ret = gui.dialog.select(tr(S.FILTER_LOAD), files)
            if ret == -1:
                return
            gui.filter_lists = gui.ggdb.history.load_filter_selections(files[ret])
            gui.getControl(LABEL_STATUS).setLabel(
                tr(S.FILTERED_ITEMS, gui.ggdb.gamelist.define_filter(gui.filter_lists))
            )
            gui.act_filter = files[ret]
            gui.getControl(FILTER_LABEL2).setLabel(tr(S.FILTER_NAME, gui.act_filter))
            show_start_category(gui)

        else:
            # the entry after the saved filters creates a new one
            ret = gui.dialog.select(
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
            gui.ggdb.history.save_filter_selections(filter_filename, gui.filter_lists)
            gui.act_filter = filter_filename
            gui.getControl(FILTER_LABEL2).setLabel(tr(S.FILTER_NAME, gui.act_filter))
            show_start_category(gui)

    # or load the content lists of the chosen category and move into them
    elif cat in FILTER_CATEGORY_KEYS:
        gui.set_filter_content(cat)


def show_start_category(gui):
    """Select the Softwarelists category and show its lists (focus stays)."""

    gui.getControl(FILTER_CATEGORY_LIST).selectItem(
        FILTER_CATEGORIES.index(FILTER_START_CATEGORY))
    # selectItem() is applied asynchronously: name the category explicitly
    gui.set_filter_content(FILTER_START_CATEGORY, focus_lists=False)


def show_category_content(gui, force=False):
    """Fill the active/inactive lists for the selected filter category.

    The focus stays in the category list. Entries that are no category
    (separator, Load/Save Filter) leave the lists as they are. Without
    ``force`` an already shown category is not reloaded, so callbacks that
    queued up while a key was held cost nothing.
    """

    item = gui.getControl(FILTER_CATEGORY_LIST).getSelectedItem()
    if not item:
        return
    cat = item.getLabel2()
    if cat not in FILTER_CATEGORY_KEYS:
        return
    if not force and gui.act_filter_category == cat:
        return
    gui.set_filter_content(cat, focus_lists=False)


def filter_content(gui, which_content):
    """filter content

    Gets called with action on filter list
    """

    if which_content == 'active':
        contentlist = FILTER_CONTENT_LIST_ACTIVE
    else:
        contentlist = FILTER_CONTENT_LIST_INACTIVE

    # get actual category
    filter_category_name = gui.act_filter_category
    # get db id for actual content entry
    filter_content_id = gui.getControl(contentlist).getSelectedItem().getLabel2()

    # update internal list
    if which_content == 'active':
        xbmc.log(f"UMSA gui: filter_content: remove: {filter_content_id}")
        gui.filter_lists[filter_category_name].remove(filter_content_id)
    else:
        xbmc.log(f"UMSA gui: filter_content: append: {filter_content_id}")
        gui.filter_lists[filter_category_name].append(filter_content_id)

    # update gui
    gui.set_filter_content(filter_category_name, update=which_content)


def set_filter_content(gui, cat, update=None, focus_lists=True):
    """Set filter content

    ``focus_lists=False`` keeps the focus in the category list on the
    initial fill (``update=None``).
    """

    filter_content_id = 0
    f_select = 0
    f_element = 0

    # only for action in list, not for inital fill
    if update == 'active':
        f_element = gui.getControl(FILTER_CONTENT_LIST_ACTIVE).getSelectedPosition()
        filter_content_id = int(
            gui.getControl(FILTER_CONTENT_LIST_ACTIVE).getSelectedItem().getLabel2()
        )
    elif update == 'inactive':
        f_element = gui.getControl(FILTER_CONTENT_LIST_INACTIVE).getSelectedPosition()
        filter_content_id = int(
            gui.getControl(FILTER_CONTENT_LIST_INACTIVE).getSelectedItem().getLabel2()
        )

    # partition entries into active and inactive lists
    lists = build_filter_lists(gui.filter_lists, cat, gui.ggdb.games)
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
    gui.setFocus(gui.getControl(FILTER_CATEGORY_LIST))
    gui.getControl(FILTER_CONTENT_LIST_ACTIVE).reset()
    gui.getControl(FILTER_CONTENT_LIST_INACTIVE).reset()
    gui.getControl(FILTER_CONTENT_LIST_ACTIVE).addItems(active)
    gui.getControl(FILTER_CONTENT_LIST_INACTIVE).addItems(inactive)
    gui.getControl(FILTER_LABEL).setLabel(category_label(cat))
    gui.act_filter_category = cat

    # set selected items and focus
    if update == 'active':
        if f_element == len(active):
            f_element -= 1
        gui.getControl(FILTER_CONTENT_LIST_ACTIVE).selectItem(f_element)
        gui.getControl(FILTER_CONTENT_LIST_INACTIVE).selectItem(f_select)
        if len(active) > 0:
            gui.setFocus(gui.getControl(FILTER_CONTENT_LIST_ACTIVE))
        else:
            gui.setFocus(gui.getControl(FILTER_CONTENT_LIST_INACTIVE))
    elif update:
        if f_element == len(inactive):
            f_element -= 1
        gui.getControl(FILTER_CONTENT_LIST_INACTIVE).selectItem(f_element)
        gui.getControl(FILTER_CONTENT_LIST_ACTIVE).selectItem(f_select)
        if len(inactive) > 0:
            gui.setFocus(gui.getControl(FILTER_CONTENT_LIST_INACTIVE))
        else:
            gui.setFocus(gui.getControl(FILTER_CONTENT_LIST_ACTIVE))
    elif focus_lists:
        # switch to inactive when active is empty
        if len(active) > 0:
            gui.setFocus(gui.getControl(FILTER_CONTENT_LIST_ACTIVE))
        else:
            gui.setFocus(gui.getControl(FILTER_CONTENT_LIST_INACTIVE))
