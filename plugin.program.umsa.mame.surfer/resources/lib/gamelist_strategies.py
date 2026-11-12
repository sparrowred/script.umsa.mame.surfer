"""Gamelist dispatch strategies used by UMSA.update_gamelist.

Strategies receive a minimal context object with only the data and callbacks
they need. They return either the 4-tuple `(results, pos, gl_label, gl_options)`
or `EARLY_RETURN` when they have fully handled the request themselves.
"""

from umsa_gui import strings as S
from umsa_gui.constants import (
    ACTION_CHOOSE_EMULATOR,
    ACTION_START_EXODOS,
    ACTION_START_EXODOS_ALT,
    ACTION_START_KODI,
    ACTION_START_MAME,
    ENTRY_ACTION,
    OPTION_NEW_SEARCH,
    OPTIONS_ORDER,
    OPTIONS_PLAY_STATUS,
)
from umsa_gui.strings import tr

EARLY_RETURN = object()


def _action_row(action, name):
    """Return a list row that starts ``action`` when clicked."""

    return {'id': f"{ENTRY_ACTION}::{action}", 'name': name,
            'year': ">>>", 'maker': "<<<"}


def all_games(ctx):
    results, pos = [], 0
    import xbmc
    xbmc.log("UMSA gui: update_gamelist: get_by_software")
    results, pos, count = ctx.db.get_by_software(ctx.actset['id'])
    gl_label = tr(S.LIST_COMPLETE, count)
    gl_options = OPTIONS_ORDER

    return results, pos, gl_label, gl_options

def software_list(ctx):
    results, pos = [], 0
    import xbmc
    xbmc.log("UMSA gui: update_gamelist: get_by_swl")
    results, pos, count = ctx.db.get_by_swl(
        ctx.actset['swl_name'],
        ctx.actset['id'],
    )
    gl_label = tr(S.LIST_SWL, ctx.actset['swl_name'], count)
    gl_options = ("all swls", "get connected swls")

    return results, pos, gl_label, gl_options

def category(ctx):
    results, pos = [], 0
    results, pos, count = ctx.db.get_by_cat(
        ctx.actset['category'], ctx.actset['id']
    )
    gl_label = tr(S.LIST_CATEGORY, ctx.actset['category'], count)
    gl_options = OPTIONS_ORDER

    return results, pos, gl_label, gl_options

def year(ctx):
    results, pos = [], 0
    results, pos, count = ctx.db.get_by_year(
        ctx.actset['year'],
        ctx.actset['id']
    )
    gl_label = tr(S.LIST_YEAR, ctx.actset['year'], count)
    gl_options = ('±0', '±1', '±2')

    return results, pos, gl_label, gl_options

def players(ctx):
    results, pos = [], 0
    results, pos, count = ctx.db.get_by_players(
        ctx.actset['nplayers'],
        ctx.actset['id']
    )
    gl_label = tr(S.LIST_PLAYERS, ctx.actset['nplayers'], count)
    gl_options = OPTIONS_ORDER

    return results, pos, gl_label, gl_options

def maker(ctx):
    results, pos = [], 0
    results, pos, count = ctx.db.get_by_maker(
        ctx.actset['publisher'],
        ctx.actset['id']
    )
    gl_label = tr(S.LIST_PUBLISHER, ctx.actset['publisher'], count)
    gl_options = OPTIONS_ORDER

    return results, pos, gl_label, gl_options

def play_status(ctx):
    results, pos = [], 0
    results, pos = ctx.db.get_last_played("time_played")
    gl_label = tr(S.LIST_PLAY_STATUS)
    gl_options = OPTIONS_PLAY_STATUS

    return results, pos, gl_label, gl_options

def machine(ctx):
    results, pos = [], 0
    if ctx.actset['swl_name'] == "mame":
        emus = ctx.db.get_emulators(source=ctx.actset['source'])
        gl_label = tr(
            S.LIST_EMULATORS_FOR_SOURCE, ctx.actset['source'][:-4], len(emus))
    else:
        emus = ctx.db.get_emulators(swl_name=ctx.actset['swl_name'])
        temp_results, pos = ctx.db.get_machines(
            ctx.actset['swl_name'], ctx.actset['machine_name']
        )
        results.extend(temp_results)
        results.append({'id': 0, 'name': "----------", 'year': '', 'maker': ''})
        gl_label = tr(S.LIST_MACHINES_FOR, ctx.actset['swl_name'], len(results))
    for i in emus:
        results.append({'id': "emu_conn::{}".format(i['emu_conn_id']),
                        'name': i['name'], 'year': '', 'maker': ''})
    if ctx.actset['swl_name'] == 'exodos':
        results.append(_action_row(ACTION_START_EXODOS, tr(S.START_EXODOS)))
        results.append(_action_row(
            ACTION_START_EXODOS_ALT, tr(S.START_EXODOS_ALT)))
    results.append(_action_row(ACTION_START_MAME, tr(S.START_MAME)))
    results.append(_action_row(ACTION_START_KODI, tr(S.START_KODI)))
    results.append(_action_row(ACTION_CHOOSE_EMULATOR, tr(S.CHOOSE_EMULATOR)))
    gl_options = OPTIONS_ORDER

    return results, pos, gl_label, gl_options

def all_emulators(ctx):
    results, pos = [], 0
    for i in ctx.db.get_emulators():
        results.append(
            {'id': "emu::{}".format(i['id']),
             'name': i['name'],
             'year': '', 'maker': "{} / {}".format(i['mode'], i['zip'])})
    gl_label = tr(S.EMULATORS)
    gl_options = ""

    return results, pos, gl_label, gl_options

def source(ctx):
    results, pos = [], 0
    results, pos, result_count = ctx.db.get_software_for_source(
        ctx.actset['id'], ctx.actset['source']
    )
    gl_label = tr(S.LIST_SOURCE, ctx.actset['source'], result_count)
    gl_options = OPTIONS_ORDER

    return results, pos, gl_label, gl_options

def last_saver(ctx):
    results, pos = [], 0
    results = []
    # Use database-backed screensaver history instead of legacy file
    history = ctx.db.get_screensaver_history()
    for entry in history:
        set_id = entry['set_id']
        software_id = entry['software_id']
        set_info = ctx.db.get_set_info_by_id(set_id)
        if set_info is None:
            # Stale history record: set no longer exists in umsa.db
            # Skip but do not delete the history record
            import xbmc
            xbmc.log(
                f"UMSA gui: last_saver: skipping stale history entry for set_id={set_id}",
                xbmc.LOGWARNING
            )
            continue
        results.append(
            {'name': set_info['name'],
             'id': str(software_id),
             'year': set_info['year'],
             'maker': set_info['maker'],
            }
        )
    gl_label = tr(S.LIST_SAVER_SESSION)
    gl_options = OPTIONS_ORDER
    pos = 0

    return results, pos, gl_label, gl_options

def series(ctx):
    results = ctx.db.get_series(ctx.last[ctx.lastptr])
    if results and ctx.popup_gamelist:
        ctx.popup_gamelist(results, tr(S.LIST_SERIES))
    #gui.getControl(GAME_LIST_TEXT).setText('')
    return EARLY_RETURN


def recommended(ctx):
    if ctx.show_rec:
        ctx.show_rec()
    #gui.getControl(GAME_LIST_TEXT).setText('')
    return EARLY_RETURN


def search_new(ctx):
    results, pos = [], 0
    import xbmc
    keyboard = xbmc.Keyboard('', tr(S.SEARCH_FOR), 0)
    keyboard.doModal()
    if keyboard.isConfirmed():
        ctx.searchold = keyboard.getText()
    else:
        return EARLY_RETURN
    results, pos, result_count = ctx.db.get_searchresults(ctx.searchold)
    gl_label = tr(S.LIST_SEARCH_RESULTS, result_count, ctx.searchold)
    gl_options = (OPTION_NEW_SEARCH,)

    return results, pos, gl_label, gl_options

def search(ctx):
    results, pos = [], 0
    import xbmc
    if not getattr(ctx, 'searchold', None):
        keyboard = xbmc.Keyboard('', tr(S.SEARCH_FOR), 0)
        keyboard.doModal()
        if keyboard.isConfirmed():
            ctx.searchold = keyboard.getText()
        else:
            return EARLY_RETURN
    results, pos, result_count = ctx.db.get_searchresults(ctx.searchold)
    gl_label = tr(S.LIST_SEARCH_RESULTS, result_count, ctx.searchold)
    gl_options = (OPTION_NEW_SEARCH,)

    return results, pos, gl_label, gl_options

GAMELIST_STRATEGIES = {
    61: all_games,  # M_ALL
    66: software_list,  # M_SWL
    63: category,  # M_CAT
    64: year,  # M_YEAR
    90: players,  # M_PLAYERS
    62: maker,  # M_MAKER
    83: play_status,  # M_PLAYSTAT
    21: machine,  # M_MACHINE
    22: all_emulators,  # M_ALLEMUS
    65: source,  # M_SOURCE
    84: last_saver,  # M_LSSAVER
    3: series,  # M_SERIES
    67: recommended,  # M_REC
    51: search_new,  # M_SEARCH_NEW
    5: search,  # M_SEARCH
}
