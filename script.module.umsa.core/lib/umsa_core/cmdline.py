"""Command-line options for a MAME run.

:func:`create_cmdline` is the pure assembly; :func:`get_cmd_line_options`
reads what it needs from the game repository.
"""

from .logging import log


def create_cmdline(parts, devices, setname):
    """Create command line options for a software-list item in MAME.

    Returns ``(cmd_options, first_device)`` or ``([], None)`` when nothing
    matches. The caller-provided ``parts`` list is never mutated.
    """

    cmd_options = []
    first_device = None

    hit = False
    # Work on a local copy: never mutate the caller's list.
    parts_list = list(parts)
    for device in devices:
        for interface in device[1].split(','):
            for part in parts_list:
                if interface == part[1]:
                    hit = True
                    cmd_options.extend(
                        [
                            f'-{device[0]}',
                            f'{setname}:{part[0]}',
                        ]
                    )
                    if not first_device:
                        first_device = device[0]
                    try:
                        parts_list.remove(part)
                    except ValueError:
                        pass
                    break
            if hit:
                break
        if hit:
            break

    if hit:
        return cmd_options, first_device
    else:
        return [], None


def get_cmd_line_options(games, set_id, set_name, machine_name, swl_name):
    """Create command line options for MAME emulator run

    Based on id, name of set, and the names of machine and swl. ``games``
    is the game repository (``DBMod.games``). Names umsa.db does not know
    never raise: an unknown software list has no extra options, an unknown
    machine no devices (the command line falls back to machine + set), and
    an unknown required set is passed by its bare name.
    """

    # get options for softwarelist
    ## this is manually set coz some swls need special options
    ## like a device in a slot so the machine supports hdds
    repo = games
    swlopt = repo.get_swl_options(swl_name)
    if swlopt is None:
        log(f"UMSA database: get_cmd_line_options: unknown swl {swl_name!r}", level='debug')
    # make swl_options a list
    if swlopt and swlopt[0]:
        swl_options = swlopt[0].strip().split(' ')
    else:
        swl_options = None

    # get id for machine
    machine_id = repo.get_machine_id(machine_name)

    # get devices supported by the machine
    if machine_id is None:
        log(f"UMSA database: get_cmd_line_options: unknown machine {machine_name!r}",
            level='debug')
        _devices = []
    else:
        _devices = repo.get_devices_for_machine(machine_id[0])

    # get all parts for the choosen set
    _part = repo.get_parts_for_set_id(set_id)

    # check if we have a requirement in sharedfeat
    _sharedfeat = repo.get_sharedfeat_requirement(set_id)

    # create cmd line
    _cmd_options, first_device = create_cmdline(
        list(_part), _devices, set_name
    )

    more_options = []
    if _cmd_options:
        # add additional manual swl options
        if swl_options:
            more_options += swl_options

        # add sharedfeat
        if _sharedfeat:
            # security if definition for sharedfeat_requirement
            # is not swl:set (split at the first colon only)
            if ':' in _sharedfeat[0]:
                _swl, _set = _sharedfeat[0].split(':', 1)
            else:
                _set = _sharedfeat[0]
                _swl = None
            _setinfo = None
            # when definition is ok
            if _swl:
                # create new cmdline option for requirement
                log(f"UMSA database: get_cmd_line_options: set {_set}, swl {_swl}", level='debug')
                try:
                    _setinfo = repo.get_info_by_set_and_swl(_set, _swl)
                except TypeError:  # no such set in umsa.db
                    log("UMSA database: get_cmd_line_options: required set unknown, "
                        "passing its name", level='debug')
                log(f"UMSA database: get_cmd_line_options: setid {_setinfo}", level='debug')
            if _setinfo:
                _parts2 = repo.get_parts_for_set_id(_setinfo['set_id'])
                log(f"UMSA database: get_cmd_line_options: parts {_parts2}", level='debug')
                _cmdopt = create_cmdline(list(_parts2), _devices, _set)[0]
                more_options += _cmdopt
            # else add the requirement set as option
            # directly after machine name
            # hopefully most of the time mame will then
            # find the correct swl entry
            else:
                more_options += [_set]

        # when we know the devices also set -statename
        cmd_options = [machine_name]+more_options+_cmd_options+[
            '-statename', f'%g/%d_{first_device}', ]

    elif swl_options:
        cmd_options = [machine_name] + swl_options + [set_name]
    else:
        cmd_options = [machine_name, set_name]
    cmd_options.extend(['-snapname', f'{swl_name}/{set_name}/%i'])

    return cmd_options
