"""Pure parsers for MAME support DAT files and the History XML (no database).

They map ``"<swl>:<set>"`` names to set ids and yield :class:`DatEntry`
records; a DAT block becomes one entry labelled with the file name without
extension. Only the list name ``info`` maps to ``mame``; a block without a
matching set yields nothing, a driver block (``$drv``) is always kept.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DatEntry:
    """One parsed DAT information entry.

    Attributes:
        file: The label (``dat.file``): the input file name without extension
            for a DAT block (``mameinfo``, ``sysinfo`` ...), :data:`DAT_HISTORY`
            for the History XML, :data:`DRIVER_WIP` for a driver block.
        entry: The whole entry text, every line ended by ``[CR]``; ``None``
            for an empty History ``<text>`` element.
        set_ids: The ids of every matched UMSA set, in discovery order; an id
            may appear more than once.
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


# Labels (``dat.file``) the parsers write besides the DAT file names. The
# frontend orders and dispatches on them, so it imports these names instead
# of repeating the texts.
#: The ``<text>`` of the History XML.
DAT_HISTORY = 'history'
#: Label of the WIP history of a MAME driver (``$drv`` block).
DRIVER_WIP = 'WIP Driver'

# Tag lines of a block that are not part of its text.
_TAG_LINES = frozenset(('$mame', '$bio', '$cmd', '$story', '$drv'))

#: Labels of the info texts whose ``WIP:`` section is shown as an entry of its
#: own (:func:`split_info_text`), mapped to the label of that entry.
INFO_WIP_LABELS = {'mameinfo': 'WIP Mame', 'messinfo': 'WIP Mess'}

_CR = '[CR]'
_RECOMMENDED = 'Recommended Games'
_WIP = 'WIP:'
# Lines that end a "Recommended Games" section: a heading ("Other Emulators:",
# "WIP:") or one of the size/level lines that follow the list in mameinfo.dat.
_SECTION_END = re.compile(r'(?:.*:$|(?:romset|chd|levels):)', re.IGNORECASE)

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


def recommended_text(text) -> str:
    """Return the ``Recommended Games`` sections of an entry text.

    Every section ``Recommended Games[ (<group>)][:]`` runs up to the next
    heading (a line ending with ``:``), a ``Romset:``/``CHD:``/``LEVELS:``
    line, the next section or the end of the text. The result has the format
    :func:`umsa_core.game_repository.parse_recommended_games` reads: per
    section ``- <group>:[CR]`` (nothing for a section without group), then
    one ``<name>[CR]`` per line. A text without section (or ``None``) gives
    ``''``.
    """

    if not text or _RECOMMENDED not in text:
        return ''
    parts = []
    inside = False
    for line in text.split(_CR):
        if line.startswith(_RECOMMENDED):
            inside = True
            if '(' in line:
                parts.append("- {}:{}".format(
                    line[line.find('(') + 1:line.find(')')], _CR))
        elif inside and line:
            if _SECTION_END.match(line):
                inside = False
            else:
                parts.append(line + _CR)
    return ''.join(parts)


def _join_paragraphs(lines) -> str:
    """Join text lines with ``[CR]``, collapsing empty lines into one paragraph break.

    Empty lines at the ends are dropped.
    """

    out = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    while out and not out[-1]:
        out.pop()
    return ''.join(line + _CR for line in out)


def split_info_text(text) -> tuple:
    """Split an info text (``mameinfo``/``messinfo``) for the display.

    Returns ``(rest, wip)``: ``wip`` is the text of the ``WIP:`` section
    without its heading, ``rest`` everything else without the ``Recommended
    Games`` sections (the menu entry "Recommended" shows them). A section
    runs up to the next heading (a line ending with ``:``, not a ``-`` list
    line) or a ``Romset:``/``CHD:``/``LEVELS:`` line; that line belongs to
    the rest. A text without both sections comes back as it is with
    ``wip == ''``; ``None`` gives ``('', '')``.
    """

    if not text:
        return '', ''
    if _WIP not in text and _RECOMMENDED not in text:
        return text, ''
    rest = []
    wip = []
    target = rest
    for line in text.split(_CR):
        if line.rstrip() == _WIP:
            target = wip
            continue
        if line.startswith(_RECOMMENDED):
            target = None
            continue
        if (target is not rest and line and not line.startswith('-')
                and _SECTION_END.match(line)):
            target = rest
        if target is not None:
            target.append(line)
    return _join_paragraphs(rest), _join_paragraphs(wip)


def find_recommended(set_dats) -> str:
    """Return the first :func:`recommended_text` of the texts of one set.

    ``set_dats`` maps the labels of a set to its texts (one value of
    ``DatRepository.get_dat_for_sets``). Returns ``''`` when no text has a
    ``Recommended Games`` section.
    """

    for text in set_dats.values():
        rec = recommended_text(text)
        if rec:
            return rec
    return ''


def _is_entry_start(line: str) -> bool:
    """Return whether ``line`` starts an entry (``$<swl>=<sets>``)."""
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

    __slots__ = ('blank', 'driver', 'header', 'line', 'lines', 'sets', 'swl')

    def __init__(self, number: int, line: str) -> None:
        self.line = number
        self.header = line
        if line[-1:] == ',':
            line = line[:-1]
        swl_str, sets_str = line[1:].split('=', 1)
        self.swl = ['mame' if name == 'info' else name
                    for name in swl_str.split(',') if name]
        self.sets = [name for name in sets_str.split(',') if name]
        # ``blank`` notes empty lines since the last text line.
        self.lines = []
        self.blank = False
        self.driver = None

    def text(self) -> str:
        """Return the collected text, every line ended by ``[CR]``."""

        return ''.join(line + _CR for line in self.lines)


def _add_line(block: _Block, line: str) -> None:
    """Add one line (not ``$end``) of an entry to ``block``."""

    if not line:
        block.blank = True
    elif line in _TAG_LINES:
        if line == '$drv':
            # Driver section: "$info=<driver>.cpp" followed by "$drv".
            block.driver = block.sets[0] if block.sets else None
    else:
        if block.blank and block.lines:
            block.lines.append('')
        block.blank = False
        block.lines.append(line)


def _is_sysinfo_stub(text: str) -> bool:
    """Return ``True`` for a sysinfo.dat stub ("just a stub", only ``=`` lines)."""

    if "just a stub" in text:
        return True
    return all(not part or part[0] == '=' for part in text.split(_CR))


def _finish_block(block: _Block, label: str, all_sets: Mapping[str, int],
                  report: DatFileReport, drivers):
    """Yield the entry of a complete block and fill ``report``."""

    text = block.text()
    if block.driver is not None:
        if drivers is not None and block.driver not in drivers:
            report.unmatched_drivers.append(block.driver)
        if text:
            report.entries += 1
            yield DatEntry(DRIVER_WIP, text, (), block.driver)
        return

    keys = [f"{swl}:{name}" for swl in block.swl for name in block.sets]
    set_ids = tuple(all_sets[key] for key in keys if key in all_sets)
    missing = [key for key in dict.fromkeys(keys) if key not in all_sets]
    report.unmatched_sets.extend(missing)
    if not set_ids:
        if keys:
            report.unmatched_entries.append(", ".join(missing))
        return

    if not text or (label == 'sysinfo' and _is_sysinfo_stub(text)):
        return
    report.entries += 1
    yield DatEntry(label, text, set_ids)


def _numbered_lines(fobj: Iterable[str], report: DatFileReport):
    """Yield ``(line number, line)`` of the right-stripped lines.

    Empty lines are yielded as ``''`` (paragraph breaks of the text). A line
    ``$end<rest>`` is split into ``$end`` and ``<rest>`` and noted in
    ``report.malformed``.
    """

    for number, raw in enumerate(fobj, 1):
        line = raw.rstrip()
        if line.startswith('$end') and len(line) > 4:
            report.malformed.append(f"line {number}: {line}")
            yield number, '$end'
            line = line[4:]
        yield number, line


def parse_dat(fobj: Iterable[str], all_sets: Mapping[str, int], datfile: str,
              report: DatFileReport | None = None, drivers=None):
    """Parse a MAME support file, yielding one :class:`DatEntry` per block.

    The ``$`` tag lines are not part of the text; empty lines collapse into
    one paragraph break. A line ``$end<rest>`` ends the entry and ``<rest>``
    is read as a new line. A driver block yields a :data:`DRIVER_WIP` entry;
    ``sysinfo.dat`` stubs are dropped. Streams: only the current entry is
    kept in memory.

    Args:
        fobj: Iterable of text lines.
        all_sets: ``{"<swl>:<set>": set id}``.
        datfile: Input file name; without extension it labels every entry.
        report: Receives header version/date, the entry count and what was
            not found; complete once the generator is exhausted.
        drivers: Known driver names (see :func:`driver_lookup_keys`);
            ``None`` skips the driver check.
    """

    if report is None:
        report = DatFileReport(datfile)
    label = os.path.splitext(datfile)[0]
    header = []
    header_read = False
    block = None

    for number, line in _numbered_lines(fobj, report):
        if block is None:
            if not line:
                continue
            if _is_entry_start(line):
                if not header_read:
                    report.version, report.date = read_dat_header(header)
                    header_read = True
                block = _Block(number, line)
            elif not header_read:
                header.append(line)
            continue

        if line == '$end':
            yield from _finish_block(block, label, all_sets, report, drivers)
            block = None
        else:
            _add_line(block, line)

    if not header_read:
        report.version, report.date = read_dat_header(header)
    if block is not None:
        report.malformed.append(f"line {block.line}: {block.header} (no $end)")


def _history_entry(entry, all_sets: Mapping[str, int], report: DatFileReport):
    """Yield the :data:`DAT_HISTORY` entries of one ``<entry>`` element."""

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
