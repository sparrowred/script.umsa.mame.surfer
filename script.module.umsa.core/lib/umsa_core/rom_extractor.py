"""ZIP extraction and ROM-specific post-processing."""

import os
from zipfile import BadZipFile, ZipFile

from umsa_core.rom_finder import EXTENSIONS


def extract_rom(emurun):
    """Extract MAME rom zipfile and apply platform-specific processing.

    Args:
        emurun: Emulation run state dict containing zips, folder, swl_name

    Returns:
        Empty string on success, error message string on failure.
    """
    # only extract when folder does not exists
    if os.path.exists(emurun['folder']):
        zfiles = os.listdir(emurun['folder'])
    else:
        # extract zipfile
        os.makedirs(emurun['folder'])
        try:
            with ZipFile(emurun['zips'][0]) as archive:
                archive.extractall(emurun['folder'])
        except BadZipFile:
            try:
                os.rmdir(emurun['folder'])
            except OSError:
                pass
            return "Error: zipfile extraction was unsuccessful."
        zfiles = os.listdir(emurun['folder'])

        # simple hack to concatenate files so other emulators can read them
        if len(zfiles) == 2 and emurun['swl_name'] in EXTENSIONS:
            # hack swl nes: prg before chr
            if zfiles[0][-3:] == 'chr' and zfiles[1][-3:] == 'prg':
                with open(os.path.join(emurun['folder'], zfiles[1]), "ab") as prg_file, \
                     open(os.path.join(emurun['folder'], zfiles[0]), "rb") as chr_file:
                    prg_file.write(chr_file.read())
                os.remove(os.path.join(emurun['folder'], zfiles[0]))
            elif zfiles[0][-3:] == 'prg' and zfiles[1][-3:] == 'chr':
                with open(os.path.join(emurun['folder'], zfiles[0]), "ab") as prg_file, \
                     open(os.path.join(emurun['folder'], zfiles[1]), "rb") as chr_file:
                    prg_file.write(chr_file.read())
                os.remove(os.path.join(emurun['folder'], zfiles[1]))
            # rest is simply sorted by name
            else:
                zfiles_sort = sorted(zfiles)
                with open(os.path.join(emurun['folder'], zfiles_sort[0]), "ab") as file1, \
                     open(os.path.join(emurun['folder'], zfiles_sort[1]), "rb") as file2:
                    file1.write(file2.read())
                os.remove(os.path.join(emurun['folder'], zfiles_sort[1]))
            zfiles = os.listdir(emurun['folder'])

        # rename
        if emurun['swl_name'] in EXTENSIONS:
            if os.path.splitext(zfiles[0])[1] != EXTENSIONS[emurun['swl_name']]:
                os.rename(
                    os.path.join(emurun['folder'], zfiles[0]),
                    os.path.join(emurun['folder'], "{}.{}".format(
                        zfiles[0], EXTENSIONS[emurun['swl_name']]
                    ))
                )
            zfiles = os.listdir(emurun['folder'])
    emurun['extract_files'] = zfiles
    return ""