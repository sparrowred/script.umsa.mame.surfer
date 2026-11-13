"""Software details composed from several databases.

What the frontend shows for one software needs ``umsa.db`` (sets, machines),
``status.db`` (play status), ``dat.db`` (texts) and ``artwork.db`` together.
The single-database reads live in the repositories; this module composes
them:

- :meth:`SoftwareDetails.get_all_for_software`: all sets of a software,
  grouped by machine, with play status, DAT texts and artwork;
- :meth:`SoftwareDetails.get_last_played`: the play status list;
- :func:`best_machine_for_set`: the machine MAME starts a software-list set on.

The module is Kodi-independent and holds no connection: ``DBMod`` builds a
:class:`SoftwareDetails` from its repositories on every access of
``DBMod.software``.
"""

import sqlite3
import time

from .dat_parser import DRIVER_WIP, driver_lookup_keys
from .game_labels import make_time_nice
from .logging import log
from .status_repository import PLAY_STATUS_DEFAULT, PLAY_STATUS_ORDERS

COUNTRIES = {
    '1NTSC' : ('ntsc',),
    '2PAL'  : ('pal',),
    '3US'   : ('usa', 'america', 'nintendo entertainment system /', 'world'),
    '4JP'   : ('jpn', 'japan', 'famicom'),
    '5EU'   : ('euro',),
    '6EU'   : ('euro', 'pal'),
    '7KR'   : ('kor',),
    '8BR'   : ('bra',),
}


def status_dict(i):
    """Return the play status dict of a status row (``None`` stays ``None``)"""

    if not i:
        return None

    time_played = make_time_nice(i[2])

    status = {
        'last_played': i[1],
        'time_played': time_played,
        'time_played2': i[2],
        'play_count': i[3],
        'options': i[4],
        'last_nice': make_time_nice(i[1], now=True),
    }
    return status


def best_machine_for_set(machines, swl_name, detail, swl_machine_id):
    """Determine which machine to take for MAME emulation

    ``machines`` is the machine list of the software list
    (``GameRepository.get_machines(swl_name)[0]``), ``detail`` the detail
    text of the set (its country decides between several machines) and
    ``swl_machine_id`` the default system of the software list.

    TODO
    - rework: no more list, use dict from get_machines !!!
    - but machine_id into return
    """

    # no machine found
    if len(machines) == 0:
        return None
    # only 1 machine
    if len(machines) == 1:
        return machines[0]
    # only 1 original
    if (machines[0]['status'] == "original" and
            machines[1]['status'] == "compatible"
       ):
        return machines[0]

    best_machine = None
    # check if swl_machine is in machines
    for machine in machines:
        if machine['id'] == swl_machine_id:
            best_machine = machine

    # no hit until now, set first machine
    if not best_machine:
        best_machine = machines[0]
    # exception for famicom_flop
    # TODO famicom should be disconnected in mame source
    if swl_name == "famicom_flop":
        best_machine = machines[1]

    # get country from detail
    for country_sorted in sorted(COUNTRIES.keys()):
        for country in COUNTRIES[country_sorted]:
            if country in detail.lower():
                # check gamename of machines for country from detail
                # first try actual best
                for country2 in COUNTRIES[country_sorted]:
                    if country2 in best_machine['fullname'].lower():
                        return best_machine
                # now check all machines
                for machine in machines:
                    for country2 in COUNTRIES[country_sorted]:
                        if country2 in machine['fullname'].lower():
                            best_machine = machine
                            return best_machine
    return best_machine


def add_driver_wip(dats, all_dat, set_drivers):
    """Add the ``WIP Driver`` text of each set's driver to ``all_dat``.

    ``dats`` is the DAT repository. ``set_drivers`` maps a set id to its driver source (``sets.source``,
    e.g. ``snk/lasso.cpp``); the DATs name a driver by its file name and
    only use the path for ambiguous names, so both are tried.
    """

    keys = {set_id: driver_lookup_keys(src)
            for set_id, src in set_drivers.items()}
    wanted = {key for set_keys in keys.values() for key in set_keys}
    if not wanted:
        return
    try:
        wip = dats.get_driver_wip(wanted)
    except sqlite3.OperationalError as exc:
        # dat.db from before the driver column: no driver WIP until rescan
        log(f"UMSA database: driver WIP unavailable: {exc}", level='debug')
        return
    for set_id, set_keys in keys.items():
        for key in set_keys:
            if key in wip:
                all_dat.setdefault(set_id, {})[DRIVER_WIP] = wip[key]
                break


class SoftwareDetails:
    """Details of a software, composed from the repositories.

    ``games``, ``status``, ``dats`` and ``artwork`` are the repositories of
    ``umsa.db``, ``status.db`` and the attached ``dat``/``art`` schemas
    (``DBMod.games`` ...).
    """

    def __init__(self, games, status, dats, artwork):
        self._games = games
        self._status = status
        self._dats = dats
        self._artwork = artwork

    def get_status_for_set(self, set_id):
        """Return play status for a set id"""

        return status_dict(self._status.get_status_for_set(set_id))

    def get_latest_by_software(self, software_id):
        """Return id of latest played set for a software id"""

        sets = self._games.get_set_ids_for_software(software_id)
        return self._status.get_latest_by_set_ids(sets)

    def get_last_played(self, order):
        """Return the play status list ``(results, pos)``, best first

        ``order`` is one of ``PLAY_STATUS_ORDERS`` (``time_played``,
        ``last_played``, ``play_count``); any other value falls back to
        ``time_played``. The played sets (at most 250) are summed up per
        software.
        """

        results = []
        software_dict = {}

        if order not in PLAY_STATUS_ORDERS:
            log(f"UMSA database get_last_played: unknown order {order!r}, "
                f"using {PLAY_STATUS_DEFAULT}", level='warning')
            order = PLAY_STATUS_DEFAULT

        # get status for sets
        status_rows = self._status.get_played_sets(order)
        # get software info for all sets in one query
        software_by_set = self._games.get_software_for_sets(
            i['id'] for i in status_rows)
        for i in status_rows:
            software = software_by_set.get(i['id'])
            # put in dict to summarize sets
            if software and software['id'] in software_dict:
                software_dict[software['id']]["play_count"] += i['play_count']
                software_dict[software['id']]["time_played"] += i['time_played']
                software_dict[software['id']]["last_played"] = max(software_dict[software['id']]["last_played"], i['last_played'])
            elif software:
                software_dict[software['id']] = {
                    "time_played": i['time_played'],
                    "last_played": i['last_played'],
                    "play_count": i['play_count'],
                    "name": software['name'],
                    "year": software['year'],
                    "maker": software['maker'],
                }
        # sort dict after value in var order and create list for return
        ordered = sorted(software_dict.items(), key=lambda t: t[1][order])
        for software_id, status in ordered[::-1]:

            time_played = make_time_nice(status["time_played"])

            last_nice = make_time_nice(status['last_played'], now=True)

            if order == "time_played":
                last = '{}x, {}'.format(
                    status["play_count"],
                    last_nice,
                )
                first = time_played
            elif order == "play_count":
                last = f'{time_played}, {last_nice}'
                first = '{}x'.format(status['play_count'])
            else:
                last = '{}, {}x'.format(
                    time_played,
                    status["play_count"],
                )
                first = last_nice

            name = "{} ({}, {})".format(status['name'], status['year'], status['maker'],)
            results.append({'id': software_id, 'name': name, 'year': first, 'maker': last,})

        return results, 0

    def get_all_for_software(self, software_id):
        """get all infos for software

        get all sets nicely sorted (last played, prefered history, year)
        includes a best machine to use for swl set

        all_sets.append is used instead of .extend
        so we have all_sets[software_with_same_name][sets] = {infos}
        and not all_sets[[software1],[software2]]

        TODO:
        - better document this function
        - have lists for each software with same name order by year
          connect at the end and add flag so gui can mark the other software with the same name
          also make search for software with same name a setting
        - include preferred country (select it or make it first in list?)
        - maybe dont order select by year, done later,
          order by name so usa, jap... are sorted correct
        """

        time1 = time.time()

        pos_machine = 0
        pos_set = 0
        all_sets = []

        # every read below goes through a repository; this method only
        # composes the game rows with the status/dat/artwork data
        repo = self._games

        # get all sets for software id
        all_sets.append(repo.get_sets_for_software(software_id))

        # check if we have other software by this name
        # get software name
        software_name = repo.get_software_name(software_id)
        # get all software ids for software name
        for other_id in repo.get_software_ids_for_name(software_name):
            if software_id == other_id:  # is the original
                continue
            all_sets.append(repo.get_sets_for_software(other_id))

        # play status of all sets in one query
        status_rows = self._status.get_status_for_sets(
            machine['id'] for diff_software in all_sets
            for machine in diff_software)
        # machine list per software list and name per system, read once each
        swl_machines = {}
        machine_names = {}

        diff_machines = {}
        set_ids = []
        # set id -> driver source whose WIP is shown as "WIP Driver"
        set_drivers = {}
        system_sources = {}
        count = 1
        for diff_software in all_sets:
            for machine in diff_software:

                set_ids.append(str(machine['id']))
                resulting_machine = ''
                # get last_played
                last_played = status_dict(status_rows.get(machine['id']))

                if machine['system_id'] == 270257: # mame
                    # resulting_machine is the parent
                    if machine['cloneof_id']:
                        resulting_machine = machine['cloneof_id']
                    else:
                        resulting_machine = machine['id']
                    # resulting_machine = machine['category'] use category
                    best_machine = None
                    machine_name = 'mame'
                    if machine['category_flag']: # ismachine
                        machine_label = machine['category']
                    else:
                        # TODO handhelds are not arcade, but a game not a machine
                        machine_label = 'Arcade'
                    set_drivers[machine['id']] = machine['source']
                else: # swl
                    # diff machine is swl machine
                    # TODO: to test used machine name from swl
                    resulting_machine = str(machine['system_id'])
                    # get best machine
                    if machine['swl'] not in swl_machines:
                        swl_machines[machine['swl']] = (
                            repo.get_machines(machine['swl'])[0])
                    best_machine = best_machine_for_set(
                        swl_machines[machine['swl']], machine['swl'],
                        machine['detail'], machine['system_id'])
                    if best_machine:
                        machine_name = best_machine['setname']
                        machine_label = best_machine['label2']
                    else:
                        if machine['system_id'] not in machine_names:
                            machine_names[machine['system_id']] = (
                                repo.get_machine_name(machine['system_id']))
                        machine_name, machine_label = (
                            machine_names[machine['system_id']])
                    # driver of the machine the set runs on, else of the
                    # default system of the software list
                    driver = best_machine.get('source') if best_machine else None
                    if not driver and machine['system_id']:
                        if machine['system_id'] not in system_sources:
                            system_sources[machine['system_id']] = (
                                repo.get_set_source(machine['system_id']))
                        driver = system_sources[machine['system_id']]
                    set_drivers[machine['id']] = driver

                # create key in diff_machines
                if resulting_machine not in diff_machines:
                    diff_machines[resulting_machine] = {
                        'id'      : count,
                        'year'    : machine['year'],
                        'setlist' : []
                    }
                    count += 1
                # remember earliest year for later sort
                else:
                    diff_machines[resulting_machine]['year'] = min(diff_machines[resulting_machine]['year'], machine['year'])

                # TODO: what is really needed?
                #  swl machine is not needed?
                #  make last_played 3 entries here?
                diff_machines[resulting_machine]['setlist'].append({
                    'id': machine['id'],
                    'name': machine['name'],
                    'gamename': machine['gamename'],
                    'detail': machine['detail'],
                    'source': machine['source'],
                    'year': machine['year'],
                    'publisher': machine['maker'],
                    'swl_name': machine['swl'],
                    'swl_machine_id': machine['system_id'],
                    'machine_name': machine_name,
                    'machine_label': machine_label,
                    'display_type': machine['display_type'],
                    'display_rotation': machine['display_rotation'],
                    'category': machine['category'],
                    'nplayers': machine['nplayers'],
                    'clone': machine['cloneof_id'],
                    'is_machine': machine['category_flag'],
                    'last_played': last_played,
                })

        # create list to return
        return_list = []
        # sort by year
        for i in sorted(diff_machines.items(), key=lambda t: t[1]['year']):
            return_list.append(i[1]['setlist'])
        # get absolut latest played
        # TODO search for pref. country when not last played
        latest_set_id = self.get_latest_by_software(software_id)
        # find latest in return_list
        if latest_set_id:
            for count1, i in enumerate(return_list):
                for count2, j in enumerate(i):
                    if j['id'] == latest_set_id:
                        pos_machine = count1
                        pos_set = count2
                        break
        all_dat = self._dats.get_dat_for_sets(set_ids)
        add_driver_wip(self._dats, all_dat, set_drivers)
        all_art = self._artwork.get_artwork_for_sets(set_ids)
        time2 = time.time()
        log(f"UMSA database: get_all_for_software: time = {(time2-time1)*1000.0:.0f}ms", level='debug')

        return return_list, pos_machine, pos_set, all_dat, all_art
