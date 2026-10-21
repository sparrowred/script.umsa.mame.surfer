"""ROM and non-MAME file discovery."""

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
    """Search for rom zipfiles and chd files within MAME rompath.

    Args:
        emurun: Emulation run state dict containing swl_name, set_name, set_clone, disks
        rom_paths: List of MAME rom paths to search

    Returns:
        The first zip path if called with explicit swl_name/set_name (for VGM), otherwise None.
    """
    zips, chds, all_chds = [], [], []
    swl_name = emurun.get('swl_name')
    set_name = emurun.get('set_name')
    set_clone = emurun.get('set_clone')
    disks = emurun.get('disks', []) or []

    # set zip name
    if 'swl_name' in emurun and 'set_name' in emurun and not (swl_name == 'mame' and set_name):
        # called with explicit swl_name/set_name for VGM
        zip_name = os.path.join(swl_name, set_name + '.zip')
    elif swl_name == 'mame':
        zip_name = set_name + '.zip'
    else:
        zip_name = os.path.join(swl_name, set_name + '.zip')

    # create chd filenames
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
        # also check parent in case we have merged sets
        if set_clone:
            all_chds.append(os.path.join(
                swl_name, set_clone,
                f'{disk_name}.chd'))

    # search filename
    for path in rom_paths:
        # check for chd
        if all_chds:
            for i in all_chds:
                chd_file = os.path.join(path, i)
                if os.path.isfile(chd_file):
                    chds.append(chd_file)
        # check for zip
        zip_file = os.path.join(path, zip_name)
        if os.path.isfile(zip_file):
            zips.append(zip_file)

    emurun['zips'] = zips
    emurun['chds'] = chds

    # For VGM mode, return the first zip found
    if 'swl_name' in emurun and 'set_name' in emurun and not (swl_name == 'mame' and set_name):
        return zips[0] if zips else None
    return None


def find_nonmame_roms(emurun, nonmame_paths, exodos_shell=''):
    """Search for files from other sources than MAME.

    Args:
        emurun: Emulation run state dict containing swl_name, set_name, description, publisher
        nonmame_paths: Dict with keys 'exodos', 'gb64', 'whdload' pointing to root paths
        exodos_shell: 'shell' or 'alt' for eXoDOS launcher selection
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
            # set normal or alternate exodos launcher
            if exodos_shell == 'alt':
                emurun['emu_exe'] = os.path.join(dospath, 'Extras/Alternate Launcher' + dosext)
            elif exodos_shell == 'shell':
                emurun['emu_exe'] = os.path.join(dospath, shellname)
            # set zip- and filename
            zipname = os.path.basename(shellname)[:-len(dosext)] + '.zip'
            filename = os.path.join(nonmame_paths.get('exodos', ''), 'eXo/eXoDOS/', zipname)
        else:
            # folder not found - leave filename empty
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
        # file not found - leave zips empty, caller handles warning
        pass

    emurun['zips'] = zips
    emurun['chds'] = chds