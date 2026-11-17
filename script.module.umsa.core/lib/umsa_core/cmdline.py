"""Command-line options for a MAME run.

:func:`create_cmdline` is the pure assembly; :func:`get_cmd_line_options`
reads what it needs from the game repository.
"""

from .logging import log


def create_cmdline(parts, devices, setname):
    """Return ``(cmd_options, first_device)`` for a software-list item in MAME.

    The first device with an interface of one of the ``parts`` wins;
    ``([], None)`` when nothing matches. ``parts`` is not changed.
    """

    cmd_options = []
    first_device = None

    hit = False
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
    """Return the MAME arguments for a software-list set.

    ``games`` is the game repository (``DBMod.games``). Names umsa.db does
    not know never raise: an unknown software list has no extra options, an
    unknown machine no devices (the command line falls back to machine +
    set), and an unknown required set is passed by its bare name.
    """

    # The swl options are maintained by hand: some software lists need a
    # device in a slot, e.g. so the machine supports hard disks.
    repo = games
    swlopt = repo.get_swl_options(swl_name)
    if swlopt is None:
        log(f"UMSA database: get_cmd_line_options: unknown swl {swl_name!r}", level='debug')
    if swlopt and swlopt[0]:
        swl_options = swlopt[0].strip().split(' ')
    else:
        swl_options = None

    machine_id = repo.get_machine_id(machine_name)

    if machine_id is None:
        log(f"UMSA database: get_cmd_line_options: unknown machine {machine_name!r}",
            level='debug')
        _devices = []
    else:
        _devices = repo.get_devices_for_machine(machine_id[0])

    _part = repo.get_parts_for_set_id(set_id)

    _sharedfeat = repo.get_sharedfeat_requirement(set_id)

    _cmd_options, first_device = create_cmdline(
        list(_part), _devices, set_name
    )

    more_options = []
    if _cmd_options:
        if swl_options:
            more_options += swl_options

        if _sharedfeat:
            # The requirement is normally "swl:set"; split at the first colon.
            if ':' in _sharedfeat[0]:
                _swl, _set = _sharedfeat[0].split(':', 1)
            else:
                _set = _sharedfeat[0]
                _swl = None
            _setinfo = None
            if _swl:
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
            # Otherwise the required set goes right after the machine name;
            # MAME usually finds the right software list entry then.
            else:
                more_options += [_set]

        # With a known device, -statename keeps the save states per device.
        cmd_options = [machine_name]+more_options+_cmd_options+[
            '-statename', f'%g/%d_{first_device}', ]

    elif swl_options:
        cmd_options = [machine_name] + swl_options + [set_name]
    else:
        cmd_options = [machine_name, set_name]
    cmd_options.extend(['-snapname', f'{swl_name}/{set_name}/%i'])

    return cmd_options
