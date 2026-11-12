"""ZIP extraction and ROM-specific post-processing."""

import os
from zipfile import BadZipFile, ZipFile

from umsa_core import log
from umsa_core.rom_cache import staged_dir
from umsa_core.rom_finder import EXTENSIONS


class _EmptyArchive(Exception):
    """The archive holds no file to start."""


def _listing(folder):
    """Sorted file names of a folder: the first one is the launch file."""

    return sorted(os.listdir(folder))


def _join_files(folder, first, second):
    """Append ``second`` to ``first`` and remove it."""

    with open(os.path.join(folder, first), "ab") as target, \
         open(os.path.join(folder, second), "rb") as source:
        target.write(source.read())
    os.remove(os.path.join(folder, second))


def _extract_into(folder, zip_file, swl_name):
    """Extract ``zip_file`` into ``folder`` and rebuild the ROM if needed."""

    with ZipFile(zip_file) as archive:
        archive.extractall(folder)
    zfiles = _listing(folder)
    if not zfiles:
        raise _EmptyArchive(zip_file)

    # simple hack to concatenate files so other emulators can read them
    if len(zfiles) == 2 and swl_name in EXTENSIONS:
        # hack swl nes: prg before chr
        if zfiles[0][-3:] == 'chr' and zfiles[1][-3:] == 'prg':
            _join_files(folder, zfiles[1], zfiles[0])
        elif zfiles[0][-3:] == 'prg' and zfiles[1][-3:] == 'chr':
            _join_files(folder, zfiles[0], zfiles[1])
        # rest is simply sorted by name
        else:
            _join_files(folder, zfiles[0], zfiles[1])
        zfiles = _listing(folder)

    # rename
    if swl_name in EXTENSIONS:
        if os.path.splitext(zfiles[0])[1] != EXTENSIONS[swl_name]:
            os.rename(
                os.path.join(folder, zfiles[0]),
                # EXTENSIONS values already start with a dot
                os.path.join(folder, zfiles[0] + EXTENSIONS[swl_name])
            )


def extract_rom(emurun):
    """Extract MAME rom zipfile and apply platform-specific processing.

    The folder is filled through ``rom_cache.staged_dir``: it only exists
    once the extraction is complete, so an existing, non-empty folder is a
    finished extraction and is reused.

    Args:
        emurun: Emulation run state dict containing zips, folder, swl_name

    Returns:
        Empty string on success, error message string on failure.
        ``emurun['extract_files']`` holds the sorted file names.
    """
    folder = emurun['folder']
    if os.path.isdir(folder) and not os.listdir(folder):
        # leftover of an extraction that produced nothing
        os.rmdir(folder)

    if not os.path.exists(folder):
        try:
            with staged_dir(folder) as staging:
                _extract_into(staging, emurun['zips'][0], emurun['swl_name'])
        except BadZipFile:
            return "Error: zipfile extraction was unsuccessful."
        except _EmptyArchive:
            return "Error: zipfile contains no files."
        except OSError as error:
            log(f"UMSA Emu: could not extract {emurun['zips'][0]}: {error}",
                level='warning')
            return f"Error: zipfile extraction failed: {error}"
    emurun['extract_files'] = _listing(folder)
    return ""
