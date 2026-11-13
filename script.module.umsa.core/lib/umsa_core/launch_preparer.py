"""Emulator-specific launch preparation."""

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from umsa_core import log
from umsa_core.cmdline import get_cmd_line_options
from umsa_core.rom_cache import CacheLayout, cache_archives
from umsa_core.rom_finder import NONMAME
from umsa_core.savestates import state_subdir
from umsa_core.support import marp_download


def _remove_owned_symlink(emurun: dict) -> None:
    """Remove this run's temporary link unless its path has been replaced."""

    owned = emurun.pop("_chd_directory_symlink", None)
    if owned is None:
        return
    launch_id = emurun.get("launch_id", "unknown")
    link_path, device, inode = owned
    try:
        info = os.lstat(link_path)
    except FileNotFoundError:
        log(
            f"UMSA Emu: launch={launch_id} temporary CHD symlink already "
            f"absent: {link_path}",
            level="debug",
        )
        return
    if (
        not os.path.islink(link_path)
        or info.st_dev != device
        or info.st_ino != inode
    ):
        log(
            f"UMSA Emu: launch={launch_id} preserving replaced symlink "
            f"during cleanup: {link_path}",
            level="warning",
        )
        return
    try:
        os.unlink(link_path)
    except FileNotFoundError:
        log(
            f"UMSA Emu: launch={launch_id} temporary CHD symlink already "
            f"absent: {link_path}",
            level="debug",
        )
    except OSError as error:
        log(
            f"UMSA Emu: launch={launch_id} could not remove temporary "
            f"symlink {link_path}: {error}",
            level="error",
        )
        raise
    else:
        log(
            f"UMSA Emu: launch={launch_id} removed temporary CHD symlink: "
            f"{link_path}",
            level="debug",
        )


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
        rom_cache: bool = False,
        cache_layout: CacheLayout | None = None,
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
        # setting rom_cache: copy archives that are started directly
        self.rom_cache = rom_cache
        self._cache_layout = cache_layout

    @property
    def cache_layout(self):
        """Layout of the ROM cache; without one a flat layout in ``temp_dir``."""

        if self._cache_layout is not None:
            return self._cache_layout
        return CacheLayout(self.temp_dir)

    @cache_layout.setter
    def cache_layout(self, layout):
        self._cache_layout = layout

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
            filename = os.path.join(
                self.nonmame['gb64'], 'Games', actset['name'] + '.zip')
            emurun['args'] = [
                'c64p', f"-{actset['swl_name'][-4:]}", filename]
        # start a swl item
        else:
            if dialog is not None:
                dialog.update(20, 'create swl options...')
            # get cmd options
            emurun['args'] = get_cmd_line_options(
                ggdb.games, actset['id'], actset['name'],
                actset['machine_name'], actset['swl_name'])
        # folder of the set's save states (umsa_core.savestates)
        emurun['state_subdir'] = state_subdir(actset, emurun['args'])

    def demul(self, emurun):
        """Set parameters for Demul.

        CMD: demul -run=[dc,naomi,awave,...] -rom=
        """
        err = ''
        params = []
        # dreamcast
        if emurun['swl_name'] == 'dc' and emurun['chds']:
            params.extend(['-run=dc', f'-image={emurun["chds"][0]}'])
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

    def _prepare_chd_directory_symlink(self, emurun):
        """Link an unextracted MAME CHD beside its discovered ROM ZIP if needed."""

        launch_id = emurun.get("launch_id", "unknown")
        chds = emurun.get('chds') or []
        zips = emurun.get('zips') or []
        if 'extractcd' in emurun:
            log(
                f"UMSA Emu: launch={launch_id} CHD symlink skipped: "
                "CHD was extracted",
                level="debug",
            )
            return None
        if not chds or not chds[0]:
            log(
                f"UMSA Emu: launch={launch_id} CHD symlink skipped: "
                "no CHD was discovered",
                level="debug",
            )
            return None
        if not zips or not zips[0]:
            log(
                f"UMSA Emu: launch={launch_id} CHD symlink skipped: "
                "no ROM ZIP was discovered",
                level="debug",
            )
            return None

        chd_file = Path(chds[0]).resolve(strict=True)
        if not chd_file.is_file():
            raise FileNotFoundError(f"CHD file does not exist: {chd_file}")
        zip_file = Path(os.path.abspath(zips[0]))
        if not zip_file.is_file():
            raise FileNotFoundError(f"ROM ZIP does not exist: {zip_file}")

        link_path = zip_file.with_suffix("")
        source_dir = chd_file.parent
        if os.path.realpath(link_path) == str(source_dir):
            log(
                f"UMSA Emu: launch={launch_id} CHD symlink not needed: "
                f"ROM set directory {link_path} already contains CHD "
                f"directory {source_dir}",
                level="debug",
            )
            return None

        if os.path.lexists(link_path):
            if link_path.is_symlink() and os.path.realpath(link_path) == str(source_dir):
                log(
                    f"UMSA Emu: launch={launch_id} reusing existing CHD "
                    f"symlink {link_path} -> {source_dir}",
                    level="debug",
                )
                return str(link_path)
            raise FileExistsError(
                f"refusing to replace existing path: {link_path}"
            )

        os.symlink(source_dir, link_path, target_is_directory=True)
        info = os.lstat(link_path)
        emurun["_chd_directory_symlink"] = (
            str(link_path), info.st_dev, info.st_ino)
        log(
            f"UMSA Emu: launch={launch_id} created temporary CHD symlink "
            f"{link_path} -> {source_dir}",
            level="debug",
        )
        return str(link_path)

    def cleanup_symlinks(self, emurun):
        """Remove only symlinks owned by this launch operation."""

        _remove_owned_symlink(emurun)

    def other_emulator(self, emurun, emu_infos, dialog=None, sleep=None, wait=None):
        """Prepare run for other emulators.

        ``wait`` (``umsa_core.abort.Wait``) makes a CHD extraction stop on a
        shutdown request (``ShutdownRequested``).
        """
        ret_val = True
        update_dialog(dialog, 10, 'searching roms/chds...')

        # set temporary folder
        emurun['folder'] = self.cache_layout.extract_dir(
            emurun['swl_name'], emurun['set_name'], emurun.get('source'))
        # set emulator, working dir and mode
        emurun['emu_exe'] = emu_infos['exe']
        emurun['working_dir'] = emu_infos['dir']
        if 'mode' in emu_infos:
            emurun['emulation_start'] = emu_infos['mode']

        # find file by the name of the set
        launch_id = emurun.get("launch_id", "unknown")
        log(
            f'UMSA Emu: launch={launch_id} preparing emulator='
            f'{emu_infos.get("name", "")!r} exe={emu_infos.get("exe", "")!r} '
            f'swl={emurun["swl_name"]!r} set={emurun["set_name"]!r} '
            f'mode={emurun.get("emulation_start")} '
            f'extract={not emu_infos.get("zip", False)}',
            level='debug',
        )
        log(
            f'UMSA Emu: launch={launch_id} searching for non-MAME source '
            f'{emurun["swl_name"]!r}',
            level='debug',
        )
        find_nonmame = self._find_nonmame_roms
        if find_nonmame is None:
            from umsa_core.rom_finder import find_nonmame_roms
            find_nonmame = find_nonmame_roms
        find_roms_func = self._find_roms
        if find_roms_func is None:
            from umsa_core.rom_finder import find_roms
            find_roms_func = find_roms
        uses_mame_rompath = emurun['swl_name'] not in NONMAME
        if not uses_mame_rompath:
            find_nonmame(emurun, self.nonmame)
        else:
            find_roms_func(emurun, self.mame_ini.get('rompath', []))

        zips = emurun.get('zips') or []
        chds = emurun.get('chds') or []
        log(
            f"UMSA Emu: launch={launch_id} ROM/CHD search complete: "
            f"zips={zips!r} chds={chds!r}",
            level="debug",
        )
        if not zips + chds:
            log(
                f'UMSA Emu err: rom/chd not found; launch={launch_id} '
                f'swl={emurun["swl_name"]!r} set={emurun["set_name"]!r}',
                level='warning',
            )
            ret_val = False
        # extract rom_file if needed
        elif not emu_infos.get('zip', False):
            log(
                f"UMSA Emu: launch={launch_id} extraction requested "
                f"for ZIPs={zips!r} CHDs={chds!r}",
                level="debug",
            )
            # TODO check len of zips, should not happen?
            if zips and zips[0]:
                update_dialog(dialog, 20, 'extracting zip...')
                extract_rom_func = self._extract_rom
                if extract_rom_func is None:
                    from umsa_core.rom_extractor import extract_rom
                    extract_rom_func = extract_rom
                extract_error = extract_rom_func(emurun)
                if extract_error:
                    # never start the emulator without its file
                    log(
                        f'UMSA Emu err: {extract_error} launch={launch_id} '
                        f'zip={zips[0]!r}',
                        level='warning',
                    )
                    ret_val = False
            # extract 1st chd
            if chds and chds[0]:
                update_dialog(dialog, 20, 'extracting chd...')
                extract_chd_func = self._extract_chd
                if extract_chd_func is None:
                    from umsa_core.chd_extractor import extract_chd
                    extract_chd_func = extract_chd
                extract_chd_func(emurun, self.chdman_exe, sleep, dialog, wait)
            log(
                f"UMSA Emu: launch={launch_id} extraction complete: "
                f"extract_files={emurun.get('extract_files')!r} "
                f"extractcd={emurun.get('extractcd')!r}",
                level="debug",
            )
            # set args
            if emurun.get('extract_files'):
                emurun['args'] = os.path.join(
                    emurun['folder'], emurun['extract_files'][0])
            elif 'extractcd' in emurun:
                emurun['args'] = os.path.join(
                    emurun['folder'], emurun['extractcd'][0])
        # set 1st rom or chd as argument
        else:
            if self.rom_cache:
                # start from a copy in the ROM cache
                update_dialog(dialog, 20, 'caching roms/chds...')
                cache_archives(emurun, self.cache_layout, dialog, wait)
                zips = emurun.get('zips') or []
                chds = emurun.get('chds') or []
            if zips and zips[0]:
                emurun['args'] = zips[0]
            elif chds and chds[0]:
                emurun['args'] = chds[0]
            log(
                f"UMSA Emu: launch={launch_id} direct-start selected "
                f"argument={emurun.get('args')!r}",
                level="debug",
            )

        if emurun['swl_name'] == 'mame' and emu_infos.get('zip', False):
            try:
                self._prepare_chd_directory_symlink(emurun)
            except OSError as error:
                log(
                    f"UMSA Emu: launch={launch_id} CHD symlink preparation "
                    f"failed for swl={emurun['swl_name']!r} "
                    f"set={emurun['set_name']!r}: {error}",
                    level="error",
                )
                raise
        else:
            reason = (
                "software list is not mame"
                if emurun['swl_name'] != 'mame'
                else "extraction is enabled"
            )
            log(
                f"UMSA Emu: launch={launch_id} CHD symlink skipped: {reason}",
                level="debug",
            )

        # special emulator handling
        exe_lower = emu_infos['exe'].lower()
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

        log(
            f"UMSA Emu: launch={launch_id} preparation complete: "
            f"emulator={emu_infos.get('name', '')!r} "
            f"exe={emurun.get('emu_exe')!r} "
            f"working_dir={emurun.get('working_dir')!r} "
            f"args={emurun.get('args')!r} success={ret_val}",
            level="debug",
        )
        return ret_val