"""Gamelist dispatch strategies used by UMSA.update_gamelist.

Strategies receive a minimal context object with only the data and callbacks
they need. They return either the 4-tuple `(results, pos, gl_label, gl_options)`
or `EARLY_RETURN` when they have fully handled the request themselves.
"""

EARLY_RETURN = object()

def all_games(ctx):
    results, pos = [], 0
    import xbmc
    xbmc.log("UMSA gui: update_gamelist: get_by_software")
    results, pos, count = ctx.db.get_by_software(ctx.actset['id'])
    gl_label = f"Complete list ({count})"
    gl_options = ('name', 'year', 'publisher')

    return results, pos, gl_label, gl_options

def software_list(ctx):
    results, pos = [], 0
    import xbmc
    xbmc.log("UMSA gui: update_gamelist: get_by_swl")
    results, pos, count = ctx.db.get_by_swl(
        ctx.actset['swl_name'],
        ctx.actset['id'],
    )
    gl_label = f"swl: {ctx.actset['swl_name']} ({count})"
    gl_options = ("all swls", "get connected swls")

    return results, pos, gl_label, gl_options

def category(ctx):
    results, pos = [], 0
    results, pos, count = ctx.db.get_by_cat(
        ctx.actset['category'], ctx.actset['id']
    )
    gl_label = f"Category: {ctx.actset['category']} ({count})"
    gl_options = ('name', 'year', 'publisher')

    return results, pos, gl_label, gl_options

def year(ctx):
    results, pos = [], 0
    results, pos, count = ctx.db.get_by_year(
        ctx.actset['year'],
        ctx.actset['id']
    )
    gl_label = f"Year: {ctx.actset['year']} ({count})"
    gl_options = ('±0', '±1', '±2')

    return results, pos, gl_label, gl_options

def players(ctx):
    results, pos = [], 0
    results, pos, count = ctx.db.get_by_players(
        ctx.actset['nplayers'],
        ctx.actset['id']
    )
    gl_label = f"Players: {ctx.actset['nplayers']} ({count})"
    gl_options = ('name', 'year', 'publisher')

    return results, pos, gl_label, gl_options

def maker(ctx):
    results, pos = [], 0
    results, pos, count = ctx.db.get_by_maker(
        ctx.actset['publisher'],
        ctx.actset['id']
    )
    gl_label = f"Publisher: {ctx.actset['publisher']} ({count})"
    gl_options = ('name', 'year', 'publisher')

    return results, pos, gl_label, gl_options

def play_status(ctx):
    results, pos = [], 0
    results, pos = ctx.db.get_last_played("time_played")
    gl_label = ("play status")
    gl_options = ('time_played', 'last_played', 'play_count')

    return results, pos, gl_label, gl_options

def machine(ctx):
    results, pos = [], 0
    if ctx.actset['swl_name'] == "mame":
        emus = ctx.db.get_emulators(source=ctx.actset['source'])
        gl_label = 'Emulators for source {} ({})'.format(
            ctx.actset['source'][:-4], len(results))
    else:
        emus = ctx.db.get_emulators(swl_name=ctx.actset['swl_name'])
        temp_results, pos = ctx.db.get_machines(
            ctx.actset['swl_name'], ctx.actset['machine_name']
        )
        results.extend(temp_results)
        results.append({'id': 0, 'name': "----------", 'year': '', 'maker': ''})
        gl_label = 'Machines for {} ({})'.format(ctx.actset['swl_name'], len(results))
    for i in emus:
        results.append({'id': "emu_conn::{}".format(i['emu_conn_id']),
                        'name': i['name'], 'year': '', 'maker': ''})
    if ctx.actset['swl_name'] == 'exodos':
        results.append({'id': 1,
                        'name': "Start eXoDOS Shell launcher",
                        'year': ">>>", 'maker': "<<<"})
        results.append({'id': 1,
                        'name': "Start eXoDOS Alternate Shell launcher",
                        'year': ">>>", 'maker': "<<<"})
    results.append({'id': 1,
                    'name': "Start with M.A.M.E.",
                    'year': ">>>", 'maker': "<<<"})
    results.append({'id': 1,
                    'name': "Start with Kodi Retroplayer",
                    'year': ">>>", 'maker': "<<<"})
    results.append({'id': 1,
                    'name': "Choose a different emulator",
                    'year': ">>>", 'maker': "<<<"})
    gl_options = ('name', 'year', 'publisher')

    return results, pos, gl_label, gl_options

def all_emulators(ctx):
    results, pos = [], 0
    for i in ctx.db.get_emulators():
        results.append(
            {'id': "emu::{}".format(i['id']),
             'name': i['name'],
             'year': '', 'maker': "{} / {}".format(i['mode'], i['zip'])})
    gl_label = "Emulators"
    gl_options = ""

    return results, pos, gl_label, gl_options

def source(ctx):
    results, pos = [], 0
    results, pos, result_count = ctx.db.get_software_for_source(
        ctx.actset['id'], ctx.actset['source']
    )
    gl_label = f"source: {ctx.actset['source']} ({result_count})"
    gl_options = ('name', 'year', 'publisher')

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
    gl_label = 'last screensaver session'
    gl_options = ('name', 'year', 'publisher')
    pos = 0

    return results, pos, gl_label, gl_options

def series(ctx):
    results, pos = [], 0

    results = ctx.db.get_series(ctx.last[ctx.lastptr])
    if results and ctx.popup_gamelist:
        ctx.popup_gamelist(results, 'Series')
    #gui.getControl(GAME_LIST_TEXT).setText('')
    return EARLY_RETURN


def recommended(ctx):
    results, pos = [], 0

    if ctx.show_rec:
        ctx.show_rec()
    #gui.getControl(GAME_LIST_TEXT).setText('')
    return EARLY_RETURN


def search_new(ctx):
    results, pos = [], 0
    import xbmc
    keyboard = xbmc.Keyboard('', "Search for", 0)
    keyboard.doModal()
    if keyboard.isConfirmed():
        ctx.searchold = keyboard.getText()
    else:
        return EARLY_RETURN
    results, pos, result_count = ctx.db.get_searchresults(ctx.searchold)
    gl_label = f"{result_count} results for {ctx.searchold}"
    gl_options = ('new search',)

    return results, pos, gl_label, gl_options

def search(ctx):
    results, pos = [], 0
    import xbmc
    if not getattr(ctx, 'searchold', None):
        keyboard = xbmc.Keyboard('', "Search for", 0)
        keyboard.doModal()
        if keyboard.isConfirmed():
            ctx.searchold = keyboard.getText()
        else:
            return EARLY_RETURN
    results, pos, result_count = ctx.db.get_searchresults(ctx.searchold)
    gl_label = f"{result_count} results for {ctx.searchold}"
    gl_options = ('new search',)

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
