"""Parsers for MAME support DAT files and the History XML.

The parsers are pure: they never touch a database and never import SQLite.
Each parser consumes raw input (an iterable of lines, or an XML string) plus a
mapping from ``"<swl>:<set>"`` to a UMSA set id, and yields :class:`DatEntry`
records.

The behaviour is a direct extraction of the historical ``scan_dat()`` and
``scan_history()`` helpers that used to write straight into ``dat``/``dat_set``
from ``support.py``. The generated text, the ``dat.file`` display category and
the set associations are preserved; only the database access was removed.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class DatEntry:
    """One parsed DAT information entry.

    Attributes:
        file: The display category, matching the historical ``dat.file`` value
            (for example ``Info``, ``MInfo``, ``History`` or ``Rec``).
        entry: The complete entry text, including the existing ``[CR]`` and
            ``-----NEXT--------[CR]`` separators. ``None`` is preserved for an
            empty History ``<text>`` element, matching the historical
            ``dat.entry`` value.
        set_ids: The ids of every matched UMSA set, in discovery order. An
            entry may be linked to several sets and the same id may appear more
            than once when the input names it through more than one
            software-list/set combination.
    """

    file: str
    entry: str | None
    set_ids: tuple


def _matched_set_ids(swl, sets, all_sets: Mapping[str, int]) -> tuple:
    """Return the UMSA set ids matching every ``swl``/``set`` combination."""

    set_ids = []
    for swl_name in swl:
        for set_name in sets:
            key = f"{swl_name}:{set_name}"
            if key in all_sets:
                set_ids.append(all_sets[key])
    return tuple(set_ids)


def parse_dat(fobj: Iterable[str], all_sets: Mapping[str, int], datfile: str):
    """Parse a MAME support file, yielding one :class:`DatEntry` per category.

    ``fobj`` is any iterable of text lines (for example an open file or a
    ``StringIO``). ``all_sets`` maps ``"<swl>:<set>"`` to a UMSA set id.
    ``datfile`` is the input file name, which selects the ``$bio`` category
    (``history.dat``/``mameinfo.dat``/``sysinfo.dat``) and the ``$cmd``
    handling.

    The generator keeps only the current entry in memory, so large DAT files
    are streamed.
    """

    swl = []
    sets = []
    dat = {}
    tag = ""
    flag = None

    for line in fobj:
        line = line.rstrip()
        if len(line) < 1:
            continue

        # into an entry
        if flag:
            # save entry
            if line == '$end':
                set_ids = _matched_set_ids(swl, sets, all_sets)
                for entry_tag, text in dat.items():

                    # check sysinfo.dat for stub entries
                    if entry_tag == "Sysinfo":
                        if "just a stub" in text:
                            continue
                        only_equals = True
                        for part in text.split('[CR]'):
                            if part and part[0] != '=':
                                only_equals = False
                        if only_equals:
                            continue

                    yield DatEntry(entry_tag, text, set_ids)

                # clear variables
                tag = ""
                swl = None
                sets = None
                flag = None
                dat = {}

            # add line to entry
            elif line == '$bio':
                if datfile == 'history.dat':
                    tag = 'History'
                elif datfile == 'mameinfo.dat':
                    tag = 'MInfo'
                elif datfile == 'sysinfo.dat':
                    tag = "Sysinfo"
                else:
                    tag = "Info"
                if tag not in dat:
                    dat[tag] = ""
                else:
                    dat[tag] += "-----NEXT--------[CR]"

            elif line == '$story':
                tag = 'Score'
                if tag not in dat:
                    dat[tag] = ""
                else:
                    dat[tag] += "-----NEXT--------[CR]"

            elif line == '$cmd':
                tag = 'Command'
                if tag not in dat:
                    dat[tag] = ""
                else:
                    dat[tag] += "-----NEXT--------[CR]"

            elif line[:2] == '- ' and line[-2:] == ' -':
                if datfile == 'command.dat':
                    dat[tag] += "[CR]"+line
                else:
                    tag = line[2:-2].lower().capitalize()
                    if tag == "Tips and tricks":
                        tag = "Tips/Tricks"
                    if tag not in dat:
                        dat[tag] = ""
                    else:
                        dat[tag] += "-----NEXT--------[CR]"

            elif (line == '$mame'
                  or line[:7] == 'LEVELS:'
                  or line[:7].lower() == 'romset:'
                  or line == 'Other Emulators:'):

                tag = 'Info'
                if tag not in dat:
                    dat[tag] = ""
                else:
                    dat[tag] += line + "[CR]"

            elif (line in (
                    'WIP:',
                    'STORY:',
                    'STORY AND PLAY INSTRUCTIONS:',  # TODO: only 2 times in mameinfo.dat
                    'START:',
                    'SETUP:',
                    'GAMEPLAY:',
                    'PLAY INSTRUCTIONS:',)):

                tag = line[:-1].lower().capitalize()
                if tag == 'Play instructions':
                    tag = 'Play Inst.'
                elif tag == 'Wip':
                    tag = 'WIP'
                elif tag == 'Story and play instructions':
                    tag = 'Story'
                if tag not in dat:
                    dat[tag] = ""
                else:
                    dat[tag] += "-----NEXT--------[CR]"

            elif line[:17] == 'Recommended Games':
                tag = "Rec"
                if '(' in line:
                    cat = "- {}:[CR]".format(line[line.find('(')+1:line.find(')')])
                else:
                    cat = ""
                if tag not in dat:
                    dat[tag] = cat
                else:
                    dat[tag] += cat

            else:
                if tag in dat:
                    dat[tag] += line + "[CR]"
                else:
                    tag = 'others'
                    if tag not in dat:
                        dat[tag] = line + "[CR]"
                    else:
                        dat[tag] += "-----NEXT--------[CR]"
                        dat[tag] += line + "[CR]"

        else:
            # check if entry begins
            if line[0] == '$' and '=' in line:
                flag = True

                # remove last ,
                if line[-1:] == ',':
                    line = line[:-1]

                # split at =
                swl_str, sets_str = line[1:].split('=', 1)

                # replace info with mame
                swl_str = swl_str.replace('info', 'mame')

                # split swl and sets by ,
                swl = swl_str.split(',')
                sets = sets_str.split(',')


def parse_history(history_string: str, all_sets: Mapping[str, int]):
    """Parse the History XML, yielding one :class:`DatEntry` per ``<text>``.

    Every ``<systems>``/``<software>`` entry encountered before a ``<text>``
    contributes its matched UMSA set ids to that text entry. Unmatched entries
    are kept (with an empty association), matching the historical behaviour.
    """

    root = ET.fromstring(history_string)

    for entry in root:
        new_db_entries = []
        for child in entry:
            if child.tag == 'systems':
                for innerchild in child:
                    set_info = f"mame:{innerchild.attrib['name']}"
                    if set_info in all_sets:
                        new_db_entries.append(all_sets[set_info])
            elif child.tag == 'software':
                for innerchild in child:
                    set_info = f"{innerchild.attrib['list']}:{innerchild.attrib['name']}"
                    if set_info in all_sets:
                        new_db_entries.append(all_sets[set_info])
            elif child.tag == 'text':
                yield DatEntry('History', child.text, tuple(new_db_entries))
