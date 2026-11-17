"""Software details composed from umsa.db, status.db, dat.db and artwork.db.

The single-database reads live in the repositories; this module combines them
(sets grouped by machine, the play status list, the machine of a
software-list set) and holds no connection.
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
    """Return the play status dict of a status row (``None`` stays ``None``)."""

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
    """Return the machine MAME starts a software-list set on, or ``None``.

    ``machines`` is the machine list of the software list
    (``GameRepository.get_machines(swl_name)[0]``), ``detail`` the detail
    text of the set (its country decides between several machines) and
    ``swl_machine_id`` the default system of the software list.

    TODO
    - rework: no more list, use dict from get_machines !!!
    - but machine_id into return
    """

    if len(machines) == 0:
        return None
    if len(machines) == 1:
        return machines[0]
    if (machines[0]['status'] == "original" and
            machines[1]['status'] == "compatible"
       ):
        return machines[0]

    best_machine = None
    for machine in machines:
        if machine['id'] == swl_machine_id:
            best_machine = machine

    if not best_machine:
        best_machine = machines[0]
    # TODO famicom should be disconnected in mame source
    if swl_name == "famicom_flop":
        best_machine = machines[1]

    # The detail is NULL in umsa.db for some sets.
    detail_text = (detail or '').lower()
    for country_sorted in sorted(COUNTRIES.keys()):
        for country in COUNTRIES[country_sorted]:
            if country in detail_text:
                # The current best machine wins if its name has the country.
                for country2 in COUNTRIES[country_sorted]:
                    if country2 in (best_machine['fullname'] or '').lower():
                        return best_machine
                for machine in machines:
                    for country2 in COUNTRIES[country_sorted]:
                        if country2 in (machine['fullname'] or '').lower():
                            best_machine = machine
                            return best_machine
    return best_machine


def add_driver_wip(dats, all_dat, set_drivers):
    """Add the ``WIP Driver`` text of each set's driver to ``all_dat``.

    ``dats`` is the DAT repository. ``set_drivers`` maps a set id to its
    driver source (``sets.source``, e.g. ``snk/lasso.cpp``); the DATs name a
    driver by its file name and only use the path for ambiguous names, so
    both are tried.
    """

    keys = {set_id: driver_lookup_keys(src)
            for set_id, src in set_drivers.items()}
    wanted = {key for set_keys in keys.values() for key in set_keys}
    if not wanted:
        return
    try:
        wip = dats.get_driver_wip(wanted)
    except sqlite3.OperationalError as exc:
        # A dat.db without the driver column: no driver WIP until a rescan.
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
        """Keep the repositories; no connection is opened."""
        self._games = games
        self._status = status
        self._dats = dats
        self._artwork = artwork

    def get_status_for_set(self, set_id):
        """Return the play status dict of a set id, or ``None``."""

        return status_dict(self._status.get_status_for_set(set_id))

    def get_latest_by_software(self, software_id):
        """Return the id of the latest played set of a software, or ``None``."""

        sets = self._games.get_set_ids_for_software(software_id)
        return self._status.get_latest_by_set_ids(sets)

    def get_last_played(self, order):
        """Return the play status list ``(results, pos)``, best first.

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

        status_rows = self._status.get_played_sets(order)
        software_by_set = self._games.get_software_for_sets(
            i['id'] for i in status_rows)
        for i in status_rows:
            software = software_by_set.get(i['id'])
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

    def get_all_for_software(self, software_id, set_id=None):
        """Return all sets of a software and of software with the same name.

        Returns ``(machines, pos_machine, pos_set, all_dat, all_art)``:
        ``machines`` is a list per machine (sorted by year) of set dicts with
        play status and the machine to start on; ``all_dat`` and ``all_art``
        map set ids to DAT texts and artwork. ``pos_machine``/``pos_set``
        point to ``set_id`` when it is one of the sets (search result), else
        to the latest played set, else to the first one.

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

        repo = self._games

        # One list per software: all_sets[software][set].
        all_sets.append(repo.get_sets_for_software(software_id))

        software_name = repo.get_software_name(software_id)
        for other_id in repo.get_software_ids_for_name(software_name):
            if software_id == other_id:
                continue
            all_sets.append(repo.get_sets_for_software(other_id))

        status_rows = self._status.get_status_for_sets(
            machine['id'] for diff_software in all_sets
            for machine in diff_software)
        # Machine list per software list and name per system, read once each.
        swl_machines = {}
        machine_names = {}

        diff_machines = {}
        set_ids = []
        # Set id -> driver source whose WIP is shown as "WIP Driver".
        set_drivers = {}
        system_sources = {}
        count = 1
        for diff_software in all_sets:
            for machine in diff_software:

                set_ids.append(str(machine['id']))
                resulting_machine = ''
                last_played = status_dict(status_rows.get(machine['id']))

                if machine['system_id'] == 270257: # mame
                    # Arcade sets are grouped by their parent.
                    if machine['cloneof_id']:
                        resulting_machine = machine['cloneof_id']
                    else:
                        resulting_machine = machine['id']
                    best_machine = None
                    machine_name = 'mame'
                    if machine['category_flag']: # ismachine
                        machine_label = machine['category']
                    else:
                        # TODO handhelds are not arcade, but a game not a machine
                        machine_label = 'Arcade'
                    set_drivers[machine['id']] = machine['source']
                else: # swl
                    # TODO: to test used machine name from swl
                    resulting_machine = str(machine['system_id'])
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
                    # Driver of the machine the set runs on, else of the
                    # default system of the software list.
                    driver = best_machine.get('source') if best_machine else None
                    if not driver and machine['system_id']:
                        if machine['system_id'] not in system_sources:
                            system_sources[machine['system_id']] = (
                                repo.get_set_source(machine['system_id']))
                        driver = system_sources[machine['system_id']]
                    set_drivers[machine['id']] = driver

                if resulting_machine not in diff_machines:
                    diff_machines[resulting_machine] = {
                        'id'      : count,
                        'year'    : machine['year'],
                        'setlist' : []
                    }
                    count += 1
                # The earliest year sorts the machine.
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

        return_list = []
        for i in sorted(diff_machines.items(), key=lambda t: t[1]['year']):
            return_list.append(i[1]['setlist'])
        # TODO search for pref. country when not last played
        latest_set_id = self.get_latest_by_software(software_id)
        if latest_set_id:
            for count1, i in enumerate(return_list):
                for count2, j in enumerate(i):
                    if j['id'] == latest_set_id:
                        pos_machine = count1
                        pos_set = count2
                        break
        # A requested set (search result) wins over the latest played one.
        if set_id is not None:
            for count1, i in enumerate(return_list):
                for count2, j in enumerate(i):
                    if j['id'] == set_id:
                        pos_machine = count1
                        pos_set = count2
        all_dat = self._dats.get_dat_for_sets(set_ids)
        add_driver_wip(self._dats, all_dat, set_drivers)
        all_art = self._artwork.get_artwork_for_sets(set_ids)
        time2 = time.time()
        log(f"UMSA database: get_all_for_software: time = {(time2-time1)*1000.0:.0f}ms", level='debug')

        return return_list, pos_machine, pos_set, all_dat, all_art
