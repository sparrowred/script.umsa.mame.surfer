"""Emulator-specific launch preparation."""

import os
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from platform import platform
from threading import RLock

from umsa_core import log
from umsa_core.rom_finder import NONMAME
from umsa_core.support import marp_download

PLATFORM = platform()

_SYMLINK_LOCK = RLock()


@dataclass
class _ActiveSymlink:
    target: str
    references: int
    device: int
    inode: int


_ACTIVE_SYMLINKS: dict[str, _ActiveSymlink] = {}


def _is_within(path: str, root: str) -> bool:
    """Return whether path is equal to or nested under root."""

    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _link_matches(path: str, target: str, active: _ActiveSymlink) -> bool:
    """Check that a registered link still identifies the file we created."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return (
        stat.S_ISLNK(info.st_mode)
        and info.st_dev == active.device
        and info.st_ino == active.inode
        and os.path.realpath(path) == target
    )


def _create_or_reuse_symlink(
    emurun: dict,
    link_path: str,
    target_path: str,
    *,
    target_is_directory: bool,
) -> str:
    """Create a symlink, or reuse an identical one without claiming ownership."""

    link_path = os.path.abspath(link_path)
    target_path = os.path.realpath(target_path)
    owned_links = emurun.setdefault("_owned_symlinks", [])
    if not isinstance(owned_links, list):
        raise TypeError("emurun['_owned_symlinks'] must be a list")

    with _SYMLINK_LOCK:
        active = _ACTIVE_SYMLINKS.get(link_path)
        if active is not None:
            if active.target != target_path or not _link_matches(
                link_path, target_path, active
            ):
                raise FileExistsError(
                    f"refusing to reuse changed symlink path: {link_path}"
                )
            active.references += 1
            owned_links.append(link_path)
            return link_path

        if os.path.lexists(link_path):
            if (
                os.path.islink(link_path)
                and os.path.exists(link_path)
                and os.path.realpath(link_path) == target_path
                and os.path.isdir(link_path) == target_is_directory
            ):
                return link_path
            raise FileExistsError(
                f"refusing to replace existing path: {link_path}"
            )

        os.symlink(target_path, link_path, target_is_directory=target_is_directory)
        info = os.lstat(link_path)
        _ACTIVE_SYMLINKS[link_path] = _ActiveSymlink(
            target=target_path,
            references=1,
            device=info.st_dev,
            inode=info.st_ino,
        )
        owned_links.append(link_path)
    return link_path


def _release_owned_symlinks(emurun: dict) -> None:
    """Release links created for this run, preserving replaced or shared links."""

    first_error = None
    for link_path in reversed(emurun.pop("_owned_symlinks", [])):
        with _SYMLINK_LOCK:
            active = _ACTIVE_SYMLINKS.get(link_path)
            if active is None:
                continue
            active.references -= 1
            if active.references:
                continue
            del _ACTIVE_SYMLINKS[link_path]
            if not _link_matches(link_path, active.target, active):
                log(
                    f"UMSA Emu: preserving changed symlink during cleanup: "
                    f"{link_path}",
                    level="warning",
                )
                continue
            try:
                os.unlink(link_path)
            except FileNotFoundError:
                continue
            except OSError as error:
                log(
                    f"UMSA Emu: could not remove temporary symlink "
                    f"{link_path}: {error}",
                    level="error",
                )
                if first_error is None:
                    first_error = error
    if first_error is not None:
        raise first_error


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
        if emurun.get('chds') and emurun['chds'][0] and 'extractcd' not in emurun:
            self._prepare_chd_directory_symlink(emurun)
        # dreamcast
        if emurun['swl_name'] == 'dc' and emurun['chds']:
            # make symlink in tmp as spaces and brackets are not nice
            if 'Linux' in PLATFORM and 'extractcd' not in emurun:
                link_path = os.path.join(
                    emurun['folder'], emurun['set_name'])
                os.makedirs(emurun['folder'], exist_ok=True)
                emurun['symlink'] = _create_or_reuse_symlink(
                    emurun,
                    link_path,
                    emurun['chds'][0],
                    target_is_directory=False,
                )
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
        """Expose an external, unextracted CHD directory in the ROM layout."""

        if emurun.get('chds') and emurun['chds'][0]:
            self._prepare_chd_directory_symlink(emurun)

    def _prepare_chd_directory_symlink(self, emurun):
        """Link an external CHD directory at the standard ROM lookup path."""

        if 'extractcd' in emurun:
            return None
        chds = emurun.get('chds') or []
        if not chds or not chds[0]:
            return None

        chd_file = Path(chds[0]).resolve(strict=True)
        if not chd_file.is_file():
            raise FileNotFoundError(f"CHD file does not exist: {chd_file}")
        source_dir = str(chd_file.parent)

        rom_paths = self.mame_ini.get('rompath', [])
        if isinstance(rom_paths, str):
            rom_paths = [rom_paths]
        rom_roots = [str(Path(path).resolve()) for path in rom_paths if path]
        if not rom_roots:
            return None

        rom_root = rom_roots[0]
        for zip_path in emurun.get('zips') or []:
            resolved_zip = str(Path(zip_path).resolve())
            matching_root = next(
                (root for root in rom_roots if _is_within(resolved_zip, root)),
                None,
            )
            if matching_root is not None:
                rom_root = matching_root
                break

        if not os.path.isdir(rom_root):
            raise FileNotFoundError(f"ROM directory does not exist: {rom_root}")
        if _is_within(source_dir, rom_root):
            return None

        swl_name = emurun['swl_name']
        set_name = emurun['set_name']
        if (
            not swl_name
            or not set_name
            or os.path.basename(swl_name) != swl_name
            or os.path.basename(set_name) != set_name
            or swl_name in ('.', '..')
            or set_name in ('.', '..')
        ):
            raise ValueError("software-list and set names must be path components")

        link_path = os.path.join(rom_root, swl_name, set_name)
        os.makedirs(os.path.dirname(link_path), exist_ok=True)
        emurun['chd_directory_symlink'] = _create_or_reuse_symlink(
            emurun,
            link_path,
            source_dir,
            target_is_directory=True,
        )
        return emurun['chd_directory_symlink']

    def cleanup_symlinks(self, emurun):
        """Remove only symlinks owned by this launch operation."""

        _release_owned_symlinks(emurun)

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