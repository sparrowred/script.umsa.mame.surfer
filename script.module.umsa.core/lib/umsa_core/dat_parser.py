"""Parsers for MAME support DAT files and the History XML.

The parsers are pure: they never touch a database and never import SQLite.
Each parser consumes raw input (an iterable of text lines, or a binary XML
file object) plus a mapping from ``"<swl>:<set>"`` to a UMSA set id, and
yields :class:`DatEntry` records. An optional :class:`DatFileReport` collects
the file version from the header and what could not be matched.

The generated text, the ``dat.file`` display category and the set
associations are those of the historical ``scan_dat()``/``scan_history()``
helpers, with these differences:

* ``- xxx -`` in ``command.dat`` without an open section goes to ``others``
  (it raised ``KeyError`` before, C-L15);
* only the list name ``info`` exactly is mapped to ``mame`` (C-L15);
* a block or History ``<entry>`` without a single matching set yields nothing
  (C-L16); driver sections (``$drv``) are always kept;
* a line ``$end<rest>`` ends the entry and ``<rest>`` is read as a new line;
* empty set names (``$info=``) are skipped.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field


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
        driver: The MAME driver source name of a driver entry (``$drv``
            section of ``mameinfo.dat``/``messinfo.dat``), exactly as the DAT
            names it (``1942.cpp`` or, for ambiguous names,
            ``jaleco/dday.cpp``). ``None`` for every other entry.
    """

    file: str
    entry: str | None
    set_ids: tuple
    driver: str | None = None


@dataclass
class DatFileReport:
    """What a parser found in one input file besides the entries.

    Attributes:
        file: Name of the input file.
        version: Version from the file header, ``None`` when none was found.
        date: Raw date text from the file header, or ``None``.
        entries: Number of :class:`DatEntry` records yielded.
        unmatched_entries: One line per discarded block, listing its
            ``"<swl>:<set>"`` names (``"mame:24c01, mame:24c02"``).
        unmatched_sets: Every ``"<swl>:<set>"`` name without a UMSA set, of
            discarded and of kept blocks.
        unmatched_drivers: ``$drv`` names without a ``sets.source``.
        malformed: ``"line <n>: <text>"`` for lines the parser had to repair
            and entries without ``$end``.
    """

    file: str
    version: str | None = None
    date: str | None = None
    entries: int = 0
    unmatched_entries: list = field(default_factory=list)
    unmatched_sets: list = field(default_factory=list)
    unmatched_drivers: list = field(default_factory=list)
    malformed: list = field(default_factory=list)


# Display categories (``dat.file``) the parsers write. The frontend orders,
# hides and dispatches on them (``umsa_gui.constants.TEXTLIST_ORDER``), so it
# imports these names instead of repeating the texts.
#: ``$bio`` of history.dat and the ``<text>`` of the History XML.
DAT_HISTORY = 'History'
#: ``$bio`` of every file not listed in ``_BIO_TAGS``; ``$mame``/``romset:`` lines.
DAT_INFO = 'Info'
#: ``$bio`` of mameinfo.dat.
DAT_MINFO = 'MInfo'
#: ``$bio`` of sysinfo.dat.
DAT_SYSINFO = 'Sysinfo'
#: ``$story`` (story.dat high scores).
DAT_SCORE = 'Score'
#: ``$cmd`` (command.dat).
DAT_COMMAND = 'Command'
#: Headings of mameinfo.dat/messinfo.dat.
DAT_WIP = 'WIP'
DAT_STORY = 'Story'
DAT_START = 'Start'
DAT_SETUP = 'Setup'
DAT_GAMEPLAY = 'Gameplay'
DAT_PLAY_INST = 'Play Inst.'
#: ``Recommended Games`` lines (``game_repository.parse_recommended_games``).
DAT_REC = 'Rec'
#: Text outside any category.
DAT_OTHERS = 'others'
#: Free heading ``- CONTRIBUTE -`` (any ``- xxx -`` heading becomes ``Xxx``).
DAT_CONTRIBUTE = 'Contribute'
#: Display category of the WIP history of a MAME driver.
DRIVER_WIP = 'WIP Driver'

# internal tag collecting the lines that follow ``$drv`` before the first
# section heading (the first one is "<version> [<authors>]")
_DRIVER_HEAD = '_driver_head'

_NEXT = "-----NEXT--------[CR]"

# category of ``$bio`` per input file; every other file uses "Info"
_BIO_TAGS = {
    'history.dat': DAT_HISTORY,
    'mameinfo.dat': DAT_MINFO,
    'sysinfo.dat': DAT_SYSINFO,
}

_SECTION_TAGS = {
    '$story': DAT_SCORE,
    '$cmd': DAT_COMMAND,
}

# headings of mameinfo.dat/messinfo.dat and their categories
_HEADINGS = {
    'WIP:': DAT_WIP,
    'STORY:': DAT_STORY,
    'STORY AND PLAY INSTRUCTIONS:': DAT_STORY,  # only 2 times in mameinfo.dat
    'START:': DAT_START,
    'SETUP:': DAT_SETUP,
    'GAMEPLAY:': DAT_GAMEPLAY,
    'PLAY INSTRUCTIONS:': DAT_PLAY_INST,
}

_VERSION_PATTERNS = (
    re.compile(r'\.dat\s+v?(\d+(?:\.\d+)+\w*)', re.IGNORECASE),
    re.compile(r'\bversion:?\s+v?(\d[\w.]*)', re.IGNORECASE),
    re.compile(r'(\d+\.\d+\w*)\s+version', re.IGNORECASE),
)
_DATE_PATTERN = re.compile(r'(?:latest|last) update:\s*(.+?)\s*$', re.IGNORECASE)


def driver_lookup_keys(source) -> tuple:
    """Return the DAT driver names to try for a ``sets.source`` value.

    The DATs name a driver by its file name (``lasso.cpp``) and only use the
    path for ambiguous names (``jaleco/dday.cpp``), so the full source is
    tried first, then its base name. An empty source returns ``()``.
    """

    if not source:
        return ()
    source = source.replace('\\', '/')
    base = source.rsplit('/', 1)[-1]
    if base == source:
        return (source,)
    return (source, base)


def _driver_entry(driver: str, dat: dict):
    """Build the single ``WIP Driver`` entry of a ``$drv`` section, or ``None``."""

    head = dat.get(_DRIVER_HEAD, '').split('[CR]', 1)[0].strip()
    wip = dat.get(DAT_WIP, '')
    if not wip:
        return DatEntry(DRIVER_WIP, head + '[CR]', (), driver) if head else None
    if head:
        return DatEntry(DRIVER_WIP, f"{head}[CR][CR]{wip}", (), driver)
    return DatEntry(DRIVER_WIP, wip, (), driver)


def _is_entry_start(line: str) -> bool:
    return line[0] == '$' and '=' in line


def read_dat_header(lines: Iterable[str]) -> tuple:
    """Return ``(version, date)`` from the comment lines of a DAT header.

    Only ``#`` lines before the first entry count. Per line the version
    patterns are tried in order; the first line that matches wins. Values not
    found are ``None``.
    """

    version = None
    date = None
    for line in lines:
        line = line.lstrip('﻿').rstrip()
        if not line:
            continue
        if _is_entry_start(line):
            break
        if line[0] != '#':
            continue
        if version is None:
            for pattern in _VERSION_PATTERNS:
                match = pattern.search(line)
                if match:
                    version = match.group(1)
                    break
        if date is None:
            match = _DATE_PATTERN.search(line)
            if match:
                date = match.group(1)
        if version is not None and date is not None:
            break
    return version, date


class _Block:
    """State of the entry being read (between ``$<swl>=<sets>`` and ``$end``)."""

    __slots__ = ('dat', 'driver', 'header', 'line', 'sets', 'swl', 'tag')

    def __init__(self, number: int, line: str) -> None:
        self.line = number
        self.header = line
        # remove last ,
        if line[-1:] == ',':
            line = line[:-1]
        swl_str, sets_str = line[1:].split('=', 1)
        self.swl = ['mame' if name == 'info' else name
                    for name in swl_str.split(',') if name]
        self.sets = [name for name in sets_str.split(',') if name]
        self.dat = {}
        self.tag = ""
        self.driver = None


def _open(dat: dict, tag: str) -> str:
    """Start category ``tag``, or separate a repeated one; return ``tag``."""

    if tag in dat:
        dat[tag] += _NEXT
    else:
        dat[tag] = ""
    return tag


def _add_text(block: _Block, line: str) -> None:
    """Append a text line to the open category, else to ``others``."""

    if block.tag not in block.dat:
        block.tag = _open(block.dat, DAT_OTHERS)
    block.dat[block.tag] += line + "[CR]"


def _is_info_line(line: str) -> bool:
    return (line == '$mame'
            or line[:7] == 'LEVELS:'
            or line[:7].lower() == 'romset:'
            or line == 'Other Emulators:')


def _add_line(block: _Block, line: str, bio_tag: str, command_dat: bool) -> None:
    """Add one line (not ``$end``) of an entry to ``block``."""

    dat = block.dat
    if line == '$drv':
        # driver section: "$info=<driver>.cpp" followed by "$drv"
        block.driver = block.sets[0] if block.sets else None
        block.tag = _DRIVER_HEAD
        dat.setdefault(_DRIVER_HEAD, "")
    elif line == '$bio':
        block.tag = _open(dat, bio_tag)
    elif line in _SECTION_TAGS:
        block.tag = _open(dat, _SECTION_TAGS[line])
    elif line[:2] == '- ' and line[-2:] == ' -':
        if not command_dat:
            tag = line[2:-2].lower().capitalize()
            if tag == "Tips and tricks":
                tag = "Tips/Tricks"
            block.tag = _open(dat, tag)
        elif block.tag in dat:
            dat[block.tag] += "[CR]" + line
        else:
            _add_text(block, line)
    elif _is_info_line(line):
        # keeps the historical quirk: the first such line only opens "Info"
        block.tag = DAT_INFO
        if DAT_INFO in dat:
            dat[DAT_INFO] += line + "[CR]"
        else:
            dat[DAT_INFO] = ""
    elif line in _HEADINGS:
        block.tag = _open(dat, _HEADINGS[line])
    elif line[:17] == 'Recommended Games':
        block.tag = DAT_REC
        if '(' in line:
            cat = "- {}:[CR]".format(line[line.find('(')+1:line.find(')')])
        else:
            cat = ""
        dat[DAT_REC] = dat.get(DAT_REC, '') + cat
    else:
        _add_text(block, line)


def _is_sysinfo_stub(text: str) -> bool:
    """Return ``True`` for a sysinfo.dat stub ("just a stub", only ``=`` lines)."""

    if "just a stub" in text:
        return True
    return all(not part or part[0] == '=' for part in text.split('[CR]'))


def _finish_block(block: _Block, all_sets: Mapping[str, int],
                  report: DatFileReport, drivers):
    """Yield the entries of a complete block and fill ``report``."""

    if block.driver is not None:
        if drivers is not None and block.driver not in drivers:
            report.unmatched_drivers.append(block.driver)
        entry = _driver_entry(block.driver, block.dat)
        if entry is not None:
            report.entries += 1
            yield entry
        return

    keys = [f"{swl}:{name}" for swl in block.swl for name in block.sets]
    set_ids = tuple(all_sets[key] for key in keys if key in all_sets)
    missing = [key for key in dict.fromkeys(keys) if key not in all_sets]
    report.unmatched_sets.extend(missing)
    if not set_ids:
        if keys:
            report.unmatched_entries.append(", ".join(missing))
        return

    for tag, text in block.dat.items():
        if tag == "Sysinfo" and _is_sysinfo_stub(text):
            continue
        report.entries += 1
        yield DatEntry(tag, text, set_ids)


def _numbered_lines(fobj: Iterable[str], report: DatFileReport):
    """Yield ``(line number, line)`` of the non-empty, right-stripped lines.

    A line ``$end<rest>`` is split into ``$end`` and ``<rest>`` and noted in
    ``report.malformed``.
    """

    for number, raw in enumerate(fobj, 1):
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith('$end') and len(line) > 4:
            report.malformed.append(f"line {number}: {line}")
            yield number, '$end'
            line = line[4:]
        yield number, line


def parse_dat(fobj: Iterable[str], all_sets: Mapping[str, int], datfile: str,
              report: DatFileReport | None = None, drivers=None):
    """Parse a MAME support file, yielding one :class:`DatEntry` per category.

    ``fobj`` is any iterable of text lines (for example an open file or a
    ``StringIO``). ``all_sets`` maps ``"<swl>:<set>"`` to a UMSA set id.
    ``datfile`` is the input file name, which selects the ``$bio`` category
    (``history.dat``/``mameinfo.dat``/``sysinfo.dat``) and the ``- xxx -``
    handling of ``command.dat``.

    ``report`` (optional) receives the header version/date, the number of
    yielded entries and what was not found; it is complete once the
    generator is exhausted. ``drivers`` is the set of known driver names
    (full ``sets.source`` and base name, see :func:`driver_lookup_keys`);
    ``None`` skips the driver check.

    The generator keeps only the current entry in memory, so large DAT files
    are streamed.
    """

    if report is None:
        report = DatFileReport(datfile)
    bio_tag = _BIO_TAGS.get(datfile, DAT_INFO)
    command_dat = datfile == 'command.dat'
    header = []
    header_read = False
    block = None

    for number, line in _numbered_lines(fobj, report):
        if block is None:
            if _is_entry_start(line):
                if not header_read:
                    report.version, report.date = read_dat_header(header)
                    header_read = True
                block = _Block(number, line)
            elif not header_read:
                header.append(line)
            continue

        if line == '$end':
            yield from _finish_block(block, all_sets, report, drivers)
            block = None
        else:
            _add_line(block, line, bio_tag, command_dat)

    if not header_read:
        report.version, report.date = read_dat_header(header)
    if block is not None:
        report.malformed.append(f"line {block.line}: {block.header} (no $end)")


def _history_entry(entry, all_sets: Mapping[str, int], report: DatFileReport):
    """Yield the ``History`` entries of one ``<entry>`` element."""

    keys = []
    set_ids = []
    for child in entry:
        if child.tag in ('systems', 'software'):
            for innerchild in child:
                name = innerchild.attrib['name']
                if not name:
                    continue
                if child.tag == 'systems':
                    key = f"mame:{name}"
                else:
                    key = f"{innerchild.attrib['list']}:{name}"
                keys.append(key)
                if key in all_sets:
                    set_ids.append(all_sets[key])
        elif child.tag == 'text' and set_ids:
            report.entries += 1
            yield DatEntry(DAT_HISTORY, child.text, tuple(set_ids))

    missing = [key for key in dict.fromkeys(keys) if key not in all_sets]
    report.unmatched_sets.extend(missing)
    if keys and not set_ids:
        report.unmatched_entries.append(", ".join(missing))


def parse_history(source, all_sets: Mapping[str, int],
                  report: DatFileReport | None = None):
    """Parse the History XML, yielding one :class:`DatEntry` per ``<text>``.

    ``source`` is a binary file object (or a file name). Every
    ``<systems>``/``<software>`` item encountered before a ``<text>``
    contributes its matched UMSA set ids to that text entry; an entry without
    any matched set yields nothing. ``report`` (optional) receives the
    ``version``/``date`` attributes of the root element and what was not
    found. Each processed entry is cleared, so the file is streamed.
    """

    if report is None:
        report = DatFileReport('history.xml')
    root = None
    depth = 0
    for event, elem in ET.iterparse(source, events=('start', 'end')):
        if event == 'start':
            if root is None:
                root = elem
                report.version = elem.get('version')
                report.date = elem.get('date')
            depth += 1
            continue
        depth -= 1
        if depth == 1:
            yield from _history_entry(elem, all_sets, report)
            elem.clear()
            root.remove(elem)
