"""Find the ROM zips and CHDs of a set in the MAME rompath or the non-MAME folders."""

import os
from platform import platform

PLATFORM = platform()
NONMAME = ('exodos', 'gb64_quik', 'gb64_cart', 'gb64_cass', 'gb64_flop', 'whdload_games', 'whdload_demos')
EXTENSIONS = {
    'snes': '.sfc',
    'gameboy': '.gb',
    'gbcolor': '.gbc',
    'gba': '.gba',
    'n64': '.n64',
    'n64dd': '.ndd',
    'nes': '.nes',
    'vboy': '.vb',
    'megadriv': '.md',
    '32x': '.32x',
    'sms': '.sms'
}


def find_roms(emurun, rom_paths):
    """Set ``emurun['zips']`` and ``emurun['chds']`` from the MAME rompath.

    ``emurun`` needs ``swl_name``, ``set_name`` and optionally ``set_clone``
    and ``disks``. MAME CHDs are found by listing the set directories,
    because umsa.db has no file names for them; software-list CHDs use the
    disk names of ``emurun['disks']``.

    Returns:
        The first zip for a software-list set (VGM uses it), else ``None``.
    """
    zips, chds, all_chds = [], [], []
    swl_name = emurun.get('swl_name')
    set_name = emurun.get('set_name')
    set_clone = emurun.get('set_clone')
    disks = emurun.get('disks', []) or []

    if 'swl_name' in emurun and 'set_name' in emurun and not (swl_name == 'mame' and set_name):
        zip_name = os.path.join(swl_name, set_name + '.zip')
    elif swl_name == 'mame':
        zip_name = set_name + '.zip'
    else:
        zip_name = os.path.join(swl_name, set_name + '.zip')

    if swl_name == 'mame':
        set_dirs = [set_name]
        if set_clone and set_clone != set_name:
            set_dirs.append(set_clone)
        seen_chds = set()
        for path in rom_paths:
            for directory_name in set_dirs:
                chd_dir = os.path.join(path, directory_name)
                try:
                    with os.scandir(chd_dir) as entries:
                        for entry in sorted(
                            entries, key=lambda item: (item.name.casefold(), item.name)
                        ):
                            if (
                                entry.name.lower().endswith('.chd')
                                and entry.is_file()
                                and entry.path not in seen_chds
                            ):
                                chds.append(entry.path)
                                seen_chds.add(entry.path)
                except (FileNotFoundError, NotADirectoryError):
                    continue
    else:
        for i in disks:
            try:
                disk_name = i['disk']
            except (KeyError, IndexError, TypeError):
                continue
            if not disk_name:
                continue
            all_chds.append(os.path.join(
                swl_name, set_name,
                f'{disk_name}.chd'))
            # Also the parent, for merged sets.
            if set_clone:
                all_chds.append(os.path.join(
                    swl_name, set_clone,
                    f'{disk_name}.chd'))

    for path in rom_paths:
        if swl_name != 'mame' and all_chds:
            for i in all_chds:
                chd_file = os.path.join(path, i)
                if os.path.isfile(chd_file):
                    chds.append(chd_file)
        zip_file = os.path.join(path, zip_name)
        if os.path.isfile(zip_file):
            zips.append(zip_file)

    emurun['zips'] = zips
    emurun['chds'] = chds

    if 'swl_name' in emurun and 'set_name' in emurun and not (swl_name == 'mame' and set_name):
        return zips[0] if zips else None
    return None


def find_nonmame_roms(emurun, nonmame_paths, exodos_shell=''):
    """Set ``emurun['zips']`` (and for eXoDOS ``emu_exe``) for a non-MAME set.

    Args:
        emurun: Needs ``swl_name``, ``set_name``; WHDLoad also
            ``description`` and ``publisher``.
        nonmame_paths: Roots by ``'exodos'``, ``'gb64'`` and ``'whdload'``.
        exodos_shell: ``'shell'`` or ``'alt'`` selects the eXoDOS launcher.
    """
    zips, chds = [], []
    filename = ''

    swl_name = emurun.get('swl_name', '')
    set_name = emurun.get('set_name', '')

    if swl_name == 'exodos':
        dosext = '.bat'
        dospath = os.path.join(nonmame_paths.get('exodos', ''), 'eXo/eXoDOS/!dos/', set_name)
        if os.path.isdir(dospath):
            dosfiles = os.listdir(dospath)
            shellname = ''
            for i in dosfiles:
                if dosext in i and not any(x in i for x in ('install', 'exception')):
                    shellname = i
                    break
            if exodos_shell == 'alt':
                emurun['emu_exe'] = os.path.join(dospath, 'Extras/Alternate Launcher' + dosext)
            elif exodos_shell == 'shell':
                emurun['emu_exe'] = os.path.join(dospath, shellname)
            zipname = os.path.basename(shellname)[:-len(dosext)] + '.zip'
            filename = os.path.join(nonmame_paths.get('exodos', ''), 'eXo/eXoDOS/', zipname)
        else:
            pass
    elif 'gb64_' in swl_name:
        filename = os.path.join(nonmame_paths.get('gb64', ''), 'Games/', set_name + '.zip')
    elif 'whdload' in swl_name:
        description = emurun.get('description', '')
        publisher = emurun.get('publisher', '')
        filename = description.replace(', ', '_')
        filename = filename.replace('(', '_').replace(')', '').replace(' ', '')
        filename = filename[0] + '/' + filename
        if filename[0].isnumeric():
            filename = '0' + filename[1:]
        if 'demo' in swl_name:
            filename = filename + '_' + publisher
        whdpath = swl_name.split('_')[-1] + '/'
        filename = os.path.join(nonmame_paths.get('whdload', ''), whdpath, filename + '.lha')

    if os.path.isfile(filename):
        zips.append(filename)
    else:
        # Not found: zips stays empty, the caller warns.
        pass

    emurun['zips'] = zips
    emurun['chds'] = chds