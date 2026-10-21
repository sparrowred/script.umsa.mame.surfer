"""Filter user interface of the UMSA frontend.

The filter lists are partitioned by the Core helper ``build_filter_lists``;
this module only drives the dialogs and the skin controls.
"""

import xbmc
import xbmcgui
from umsa_core.database import build_filter_lists

from .constants import (
    FILTER_CATEGORY_KEYS,
    FILTER_CATEGORY_LIST,
    FILTER_CONTENT_LIST_ACTIVE,
    FILTER_CONTENT_LIST_INACTIVE,
    FILTER_LABEL,
    FILTER_LABEL2,
    LABEL_STATUS,
)


def empty_filter_lists():
    """Return a fresh filter dict with all five categories empty."""

    return {key: [] for key in FILTER_CATEGORY_KEYS}


def close_filterlist(gui, no_update=None):
    """Close filter list window"""

    xbmc.log("UMSA gui: close_filterlist")
    # update filter
    if not no_update:
        gui.getControl(LABEL_STATUS).setLabel(
            "%s filtered items" % (gui.ggdb.define_filter(gui.filter_lists),)
        )
    gui.setFocus(gui.getControl(gui.main_focus))


def filter_category(gui):
    """Open filter category, load and save filters"""

    # get filter category and set filter content list
    cat = gui.getControl(FILTER_CATEGORY_LIST).getSelectedItem().getLabel()

    # save/load filter
    if cat in ("Load Filter", "Save Filter"):
        files = gui.ggdb.list_filter_names()

        if cat == "Load Filter":
            ret = gui.dialog.select('Load Filter', files)
            if ret == -1:
                return
            gui.filter_lists = gui.ggdb.load_filter_selections(files[ret])
            gui.getControl(LABEL_STATUS).setLabel(
                "%s filtered items" % (gui.ggdb.define_filter(gui.filter_lists),)
            )
            gui.act_filter = files[ret]
            gui.getControl(FILTER_CONTENT_LIST_ACTIVE).reset()
            gui.getControl(FILTER_CONTENT_LIST_INACTIVE).reset()
            gui.getControl(FILTER_LABEL).setLabel("Select category")
            gui.getControl(FILTER_LABEL2).setLabel(f'Filter: {gui.act_filter}')
            gui.setFocus(gui.getControl(FILTER_CATEGORY_LIST))

        else:
            files.append(' or create a new filter')
            ret = gui.dialog.select('Save Filter', files)
            if ret == -1:
                return
            if files[ret] == ' or create a new filter':
                keyboard = xbmc.Keyboard('', "Name for Filter", 0)
                keyboard.doModal()
                if keyboard.isConfirmed():
                    filter_filename = keyboard.getText()
                else:
                    return
            else:
                filter_filename = files[ret]

            # save filters
            gui.ggdb.save_filter_selections(filter_filename, gui.filter_lists)
            gui.act_filter = filter_filename
            gui.getControl(FILTER_LABEL2).setLabel(f'Filter: {gui.act_filter}')
            #gui.getControl(FILTER_LABEL).setLabel(
            #    'saved ' + filter_filename
            #)

    # or set choosen category
    else:
        gui.set_filter_content(cat)


def filter_content(gui, which_content):
    """filter content

    Gets called with action on filter list
    """

    if which_content == 'active':
        contentlist = FILTER_CONTENT_LIST_ACTIVE
    else:
        contentlist = FILTER_CONTENT_LIST_INACTIVE

    # get actual category
    filter_category_name = gui.getControl(FILTER_LABEL).getLabel()
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


def set_filter_content(gui, cat, update=None):
    """Set filter content"""

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
    lists = build_filter_lists(gui.filter_lists, cat, gui.ggdb)
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
    gui.getControl(FILTER_LABEL).setLabel(cat)

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
    else:
        # switch to inactive when active is empty
        if len(active) > 0:
            gui.setFocus(gui.getControl(FILTER_CONTENT_LIST_ACTIVE))
        else:
            gui.setFocus(gui.getControl(FILTER_CONTENT_LIST_INACTIVE))
