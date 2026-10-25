"""Pure command-line assembly helpers for MAME."""


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
