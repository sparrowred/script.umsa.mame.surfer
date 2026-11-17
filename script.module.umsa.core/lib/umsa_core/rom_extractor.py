"""ZIP extraction and ROM-specific post-processing."""

import os
from zipfile import BadZipFile, ZipFile

from umsa_core import log
from umsa_core.rom_cache import staged_dir
from umsa_core.rom_finder import EXTENSIONS


class _EmptyArchive(Exception):
    """Raised when the archive holds no file to start."""


def _listing(folder):
    """Return the sorted file names of a folder; the first one is the launch file."""

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

    # Other emulators want one file: two files are concatenated.
    if len(zfiles) == 2 and swl_name in EXTENSIONS:
        # NES: prg before chr; otherwise by name.
        if zfiles[0][-3:] == 'chr' and zfiles[1][-3:] == 'prg':
            _join_files(folder, zfiles[1], zfiles[0])
        elif zfiles[0][-3:] == 'prg' and zfiles[1][-3:] == 'chr':
            _join_files(folder, zfiles[0], zfiles[1])
        else:
            _join_files(folder, zfiles[0], zfiles[1])
        zfiles = _listing(folder)

    # Other emulators recognise the system by the extension.
    if swl_name in EXTENSIONS:
        if os.path.splitext(zfiles[0])[1] != EXTENSIONS[swl_name]:
            os.rename(
                os.path.join(folder, zfiles[0]),
                # EXTENSIONS values already start with a dot.
                os.path.join(folder, zfiles[0] + EXTENSIONS[swl_name])
            )


def extract_rom(emurun):
    """Extract the first ROM zip of ``emurun`` into ``emurun['folder']``.

    The folder is filled through :func:`umsa_core.rom_cache.staged_dir`, so it
    only exists once the extraction is complete; an existing, non-empty
    folder is reused. ``emurun['extract_files']`` gets the sorted file names.

    Returns:
        ``''`` on success, else an error text.
    """
    folder = emurun['folder']
    if os.path.isdir(folder) and not os.listdir(folder):
        # Leftover of an extraction that produced nothing.
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
