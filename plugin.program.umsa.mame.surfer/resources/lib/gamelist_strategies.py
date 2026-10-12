"""Gamelist dispatch strategies used by UMSA.update_gamelist.

Pure GUI-side extraction (Step 12): each function is the verbatim former body
of one `update_gamelist` branch (mechanical `self.` -> `gui.` rename).  A
strategy receives the UMSA instance and returns either the 4-tuple
`(results, pos, gl_label, gl_options)` or `EARLY_RETURN` when it has fully
handled the request itself (the dispatcher then returns immediately).
"""

from umsa_core import load_lastsaver

EARLY_RETURN = object()

def all_games(gui):
    results, pos = [], 0
    import xbmc
    xbmc.log("UMSA gui: update_gamelist: get_by_software")
    results, pos, count = gui.ggdb.get_by_software(gui.actset['id'])
    gl_label = "Complete list (%d)" % (count,)
    gl_options = ('name', 'year', 'publisher')

    return results, pos, gl_label, gl_options

def software_list(gui):
    results, pos = [], 0
    import xbmc
    xbmc.log("UMSA gui: update_gamelist: get_by_swl")
    results, pos, count = gui.ggdb.get_by_swl(
        gui.actset['swl_name'],
        gui.actset['id'],
    )
    gl_label = "swl: %s (%d)" % (
        gui.actset['swl_name'], count
    )
    gl_options = ("all swls", "get connected swls")

    return results, pos, gl_label, gl_options

def category(gui):
    results, pos = [], 0
    results, pos, count = gui.ggdb.get_by_cat(
        gui.actset['category'], gui.actset['id']
    )
    gl_label = "Category: %s (%d)" % (
        gui.actset['category'], count
    )
    gl_options = ('name', 'year', 'publisher')

    return results, pos, gl_label, gl_options

def year(gui):
    results, pos = [], 0
    results, pos, count = gui.ggdb.get_by_year(
        gui.actset['year'],
        gui.actset['id']
    )
    gl_label = "Year: %s (%d)" % (gui.actset['year'], count)
    gl_options = ('±0', '±1', '±2')

    return results, pos, gl_label, gl_options

def players(gui):
    results, pos = [], 0
    results, pos, count = gui.ggdb.get_by_players(
        gui.actset['nplayers'],
        gui.actset['id']
    )
    gl_label = "Players: {} ({})".format(gui.actset['nplayers'], count)
    gl_options = ('name', 'year', 'publisher')

    return results, pos, gl_label, gl_options

def maker(gui):
    results, pos = [], 0
    results, pos, count = gui.ggdb.get_by_maker(
        gui.actset['publisher'],
        gui.actset['id']
    )
    gl_label = "Publisher: %s (%d)" % (gui.actset['publisher'], count)
    gl_options = ('name', 'year', 'publisher')

    return results, pos, gl_label, gl_options

def play_status(gui):
    results, pos = [], 0
    results, pos = gui.ggdb.get_last_played("time_played")
    gl_label = ("play status")
    gl_options = ('time_played', 'last_played', 'play_count')

    return results, pos, gl_label, gl_options

def machine(gui):
    results, pos = [], 0
    if gui.actset['swl_name'] == "mame":
        emus = gui.ggdb.get_emulators(source=gui.actset['source'])
        gl_label = 'Emulators for source {} ({})'.format(
            gui.actset['source'][:-4], len(results))
    else:
        emus = gui.ggdb.get_emulators(swl_name=gui.actset['swl_name'])
        temp_results, pos = gui.ggdb.get_machines(
            gui.actset['swl_name'], gui.actset['machine_name']
        )
        results.extend(temp_results)
        results.append({'id': 0, 'name': "----------", 'year': '', 'maker': ''})
        gl_label = 'Machines for {} ({})'.format(gui.actset['swl_name'], len(results))
    for i in emus:
        results.append({'id': "emu_conn::{}".format(i['emu_conn_id']),
                        'name': i['name'], 'year': '', 'maker': ''})
    if gui.actset['swl_name'] == 'exodos':
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

def all_emulators(gui):
    results, pos = [], 0
    for i in gui.ggdb.get_emulators():
        results.append(
            {'id': "emu::{}".format(i['id']),
             'name': i['name'],
             'year': '', 'maker': "{} / {}".format(i['mode'], i['zip'])})
    gl_label = "Emulators"
    gl_options = ""

    return results, pos, gl_label, gl_options

def source(gui):
    results, pos = [], 0
    results, pos, result_count = gui.ggdb.get_software_for_source(
        gui.actset['id'], gui.actset['source']
    )
    gl_label = "source: %s (%d)" % (gui.actset['source'], result_count)
    gl_options = ('name', 'year', 'publisher')

    return results, pos, gl_label, gl_options

def last_saver(gui):
    results, pos = [], 0
    import gui as gui_module
    results = []
    for i in load_lastsaver(gui_module.CORE_DATA_PATHS.lastsaver_file):
        saver_list = gui.ggdb.get_info_by_set_and_swl(i[0], i[1])
        results.append(
            {'name': saver_list['name'],
             'id': str(saver_list['software_id']),
             'year': saver_list['year'],
             'maker': saver_list['maker'],
            }
        )
    gl_label = 'last screensaver session'
    gl_options = ('name', 'year', 'publisher')
    pos = 0

    return results, pos, gl_label, gl_options

def series(gui):
    results, pos = [], 0

    results = gui.ggdb.get_series(gui.last[gui.lastptr])
    if results:
        gui.popup_gamelist(results, 'Series')
    #gui.getControl(GAME_LIST_TEXT).setText('')
    return EARLY_RETURN


def recommended(gui):
    results, pos = [], 0

    gui.show_rec()
    #gui.getControl(GAME_LIST_TEXT).setText('')
    return EARLY_RETURN


def search_new(gui):
    results, pos = [], 0
    import xbmc
    keyboard = xbmc.Keyboard('', "Search for", 0)
    keyboard.doModal()
    if keyboard.isConfirmed():
        gui.searchold = keyboard.getText()
    else:
        return EARLY_RETURN
    results, pos, result_count = gui.ggdb.get_searchresults(gui.searchold)
    gl_label = '%d results for %s' % (result_count, gui.searchold)
    gl_options = ('new search',)

    return results, pos, gl_label, gl_options

def search(gui):
    results, pos = [], 0
    import xbmc
    if not gui.searchold:
        keyboard = xbmc.Keyboard('', "Search for", 0)
        keyboard.doModal()
        if keyboard.isConfirmed():
            gui.searchold = keyboard.getText()
        else:
            return EARLY_RETURN
    results, pos, result_count = gui.ggdb.get_searchresults(gui.searchold)
    gl_label = '%d results for %s' % (result_count, gui.searchold)
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
