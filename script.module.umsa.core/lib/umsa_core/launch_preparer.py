"""Emulator-specific launch preparation."""

import os
import subprocess
from collections.abc import Callable
from platform import platform

from umsa_core import log
from umsa_core.rom_finder import NONMAME
from umsa_core.support import marp_download

PLATFORM = platform()


def update_dialog(dialog, percent, msg):
    """Helper for emulator dialog from Kodi."""

    if dialog:
        dialog.update(percent, msg)


class LaunchPreparer:
    """Handles emulator-specific launch preparation."""

    def __init__(
        self,
        mame_exe,
        mame_dir,
        nonmame,
        mame_ini,
        temp_dir,
        terminal,
        chdman_exe,
        find_roms: Callable | None = None,
        find_nonmame_roms: Callable | None = None,
        extract_rom: Callable | None = None,
        extract_chd: Callable | None = None,
    ):
        self.mame_exe = mame_exe
        self.mame_dir = mame_dir
        self.nonmame = nonmame
        self.mame_ini = mame_ini
        self.temp_dir = temp_dir
        self.terminal = terminal
        self.chdman_exe = chdman_exe
        self._find_roms = find_roms
        self._find_nonmame_roms = find_nonmame_roms
        self._extract_rom = extract_rom
        self._extract_chd = extract_chd

    def prepare_exodos_run(self, emurun, emu_infos):
        """Prepare emurun for eXoDOS."""
        alt = "shell"
        if 'alt' in emu_infos.get('exe', ''):
            alt = "alt"
        find_nonmame = self._find_nonmame_roms
        if find_nonmame is None:
            from umsa_core.rom_finder import find_nonmame_roms
            find_nonmame = find_nonmame_roms
        find_nonmame(emurun, self.nonmame, alt)
        emurun['args'] = []
        emurun['emulation_start'] = 2

    def prepare_marp_run(self, emurun, emu_infos):
        """Prepare emurun for a MARP replay."""
        emurun['emu_exe'] = self.mame_exe
        inp_file = marp_download(
            emu_infos['marp_dl'],
            self.mame_ini.get('input_directory', ''))
        emurun['args'] = [
            emu_infos['set_name'], "-playback", inp_file, "-exit_after_playback"]

    def prepare_mame_run(self, emurun, ggdb, actset, dialog=None):
        """Prepare emurun['args'] for MAME based on actset."""
        emurun['emu_exe'] = self.mame_exe
        if actset['swl_name'] == 'mame':
            emurun['args'] = actset['name']
        # check for Gamebase64 files
        elif actset['swl_name'].startswith('gb64_'):
            filename = self.nonmame['gb64'] + 'Games/' + actset['name'] + '.zip'
            emurun['args'] = [
                'c64p', f"-{actset['swl_name'][-4:]}", filename]
        # start a swl item
        else:
            if dialog is not None:
                dialog.update(20, 'create swl options...')
            # get cmd options
            emurun['args'] = ggdb.get_cmd_line_options(
                actset['id'], actset['name'],
                actset['machine_name'], actset['swl_name'])

    def demul(self, emurun):
        """Set parameters for Demul.

        CMD: demul -run=[dc,naomi,awave,...] -rom=
        """
        err = ''
        params = []
        # dreamcast
        if emurun['swl_name'] == 'dc' and emurun['chds']:
            # make symlink in tmp as spaces and brackets are not nice
            if 'Linux' in PLATFORM:
                emurun['symlink'] = os.path.join(
                    emurun['folder'], emurun['set_name'])
                os.symlink(emurun['chds'][0], emurun['symlink'])
                image = emurun['symlink']
            else:
                image = emurun['chds'][0]
            params.extend(['-run=dc', f'-image={image}'])
        # arcade
        else:
            # call -listroms to find parameter for -run=
            section = ''
            found = False
            try:
                listroms = subprocess.check_output([emurun['emu_exe'], '-listroms'])
            except subprocess.CalledProcessError:
                return "Error running Demul -listroms"
            for i in listroms.splitlines():
                i = i.decode('utf-8')
                if len(i) > 0 and i[0] != ' ':
                    section = i.rstrip()
                    log(f"UMSA Emu run_emulator: demul - section {section}", level='debug')
                elif emurun['set_name'] in i:
                    log(f"UMSA Emu run_emulator: demul - found {i}", level='debug')
                    found = True
                    break
            # Atomiswave exception
            if section == "Atomiswave":
                section = "awave"
            if found:
                params.extend([
                    f'-run={section.lower()}',
                    f'-rom={emurun["set_name"]}'
                ])
            else:
                err = "Can't find rom in Demul's rom list."
        emurun['args'] = params
        return err

    def fsuae(self, emurun):
        """Set parameters for FS-UAE.

        args: --floppies_dir=<temp_dir> --floppy_drive_0=disk1 ...
              --floppy_image_0=disk1 --floppy_image_1=disk2 ...
        or    --cdrom-drive-0=path/to/cd-image = cue/iso TODO test chd
        """
        params = []
        # set amiga model depending on softwarelist
        models = {'amigaaga_flop': "A1200", 'cd32': "CD32", 'cdtv': "CDTV"}
        try:
            params.append("--amiga_model={}".format(models[emurun['swl_name']]))
        except KeyError:
            params.append('--amiga_model=A500')
        # set cdrom/floppy
        if emurun['chds'] and emurun['chds'][0]:
            params.append('--cdrom-drive-0={}'.format(emurun['chds'][0]))
        else:
            # set floppies_dir
            params.append('--floppies_dir={}'.format(emurun['folder']))
            for count, file_name in enumerate(emurun.get('extract_files', [])):
                # set all floppy images so switching disk in fs-uae is available
                params.append('--floppy_image_{}={}'.format(
                    count, os.path.join(emurun['folder'], file_name)))
                # set up to 4 floppy drives with images
                if count <= 3:
                    params.append('--floppy_drive_{}={}'.format(
                        count, os.path.join(emurun['folder'], file_name)))
        emurun['args'] = params

    def flycast(self, emurun):
        """Create symlink for Naomi GD-ROMs.

        TODO check if we have mame chds as disks and if found: only use dir and symlink
        to path where zip is found. if no disks: use zip name and check for dir with name
        in rompath and if not same path: symlink
        """
        emurun['symlink'] = ""

    def other_emulator(self, emurun, emu_infos, dialog=None, sleep=None):
        """Prepare run for other emulators."""
        ret_val = True
        update_dialog(dialog, 10, 'searching roms/chds...')

        # set temporary folder
        emurun['folder'] = os.path.join(self.temp_dir, "{}_{}".format(
            emurun['swl_name'], emurun['set_name']))
        # set emulator, working dir and mode
        emurun['emu_exe'] = emu_infos['exe']
        emurun['working_dir'] = emu_infos['dir']
        if 'mode' in emu_infos:
            emurun['emulation_start'] = emu_infos['mode']

        # find file by the name of the set
        log(f'UMSA Emu: check for nonmame: {emurun["swl_name"]}', level='debug')
        find_nonmame = self._find_nonmame_roms
        if find_nonmame is None:
            from umsa_core.rom_finder import find_nonmame_roms
            find_nonmame = find_nonmame_roms
        find_roms_func = self._find_roms
        if find_roms_func is None:
            from umsa_core.rom_finder import find_roms
            find_roms_func = find_roms
        if emurun['swl_name'] in NONMAME:
            find_nonmame(emurun, self.nonmame)
        else:
            find_roms_func(emurun, self.mame_ini.get('rompath', []))

        if not emurun['zips'] + emurun['chds']:
            log('UMSA Emu err: rom/chd not found', level='warning')
            ret_val = False
        # extract rom_file if needed
        elif not emu_infos.get('zip', False):
            # TODO check len of zips, should not happen?
            if emurun['zips'] and emurun['zips'][0]:
                update_dialog(dialog, 20, 'extracting zip...')
                extract_rom_func = self._extract_rom
                if extract_rom_func is None:
                    from umsa_core.rom_extractor import extract_rom
                    extract_rom_func = extract_rom
                extract_rom_func(emurun)
            # extract 1st chd
            if emurun['chds'] and emurun['chds'][0]:
                update_dialog(dialog, 20, 'extracting chd...')
                extract_chd_func = self._extract_chd
                if extract_chd_func is None:
                    from umsa_core.chd_extractor import extract_chd
                    extract_chd_func = extract_chd
                extract_chd_func(emurun, self.chdman_exe, sleep, dialog)
            # set args
            if emurun.get('extract_files'):
                emurun['args'] = os.path.join(
                    emurun['folder'], emurun['extract_files'][0])
            elif 'extractcd' in emurun:
                emurun['args'] = os.path.join(
                    emurun['folder'], emurun['extractcd'][0])
        # set 1st rom or chd as argument
        else:
            if emurun['zips'] and emurun['zips'][0]:
                emurun['args'] = emurun['zips'][0]
            elif emurun['chds'] and emurun['chds'][0]:
                emurun['args'] = emurun['chds'][0]

        # special emulator handling
        exe_lower = emu_infos['exe'].lower()
        name_lower = emu_infos.get('name', '').lower()
        if 'demul' in exe_lower:
            err = self.demul(emurun)
            if err:
                log(f"UMSA Emu ERROR: {err}", level='warning')
                ret_val = False
        elif 'fs-uae-launcher' in exe_lower:
            emurun['emulation_start'] = 2
            emurun['args'] = ['--no-gui', '--config:amiga-model=A1200', emurun['zips'][0]]
        elif 'fs-uae' in exe_lower:
            self.fsuae(emurun)
        elif 'flycast' in name_lower:
            self.flycast(emurun)

        return ret_val