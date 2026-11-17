"""Pure parsers for GameBase64 data: ``VERSION.NFO`` text and cover file names.

No database, filesystem or archive access.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Gb64VersionNfo:
    """The parsed content of one ``VERSION.NFO`` file.

    Attributes:
        entry: The metadata text stored in ``dat.entry``: the ``GAME INFO:``,
            ``VERSION INFO:`` and ``NOTES:`` lines joined by newlines, with a
            newline between the sections even when one is empty.
        screenshot: The ``Screenshot:`` value with forward slashes, relative
            to the ``Screenshots`` directory; empty when absent.
        sid: The ``SID:`` value (unused by the import); empty when absent.
        game_info: The raw ``GAME INFO:`` lines.
        version_info: The raw ``VERSION INFO:`` lines.
        notes: The raw ``NOTES:`` lines.
    """

    entry: str
    screenshot: str
    sid: str
    game_info: tuple
    version_info: tuple
    notes: tuple


def parse_version_nfo(nfo_text: str) -> Gb64VersionNfo:
    """Parse GameBase64 ``VERSION.NFO`` text into a :class:`Gb64VersionNfo`.

    Lines containing ``-----`` or ``=====`` are separators.
    ``GAME INFO:``/``VERSION INFO:``/``NOTES:`` select the current section;
    lines before any of them are discarded. ``Screenshot:`` and ``SID:``
    lines are not added to any section.
    """

    infopart = 'internal'
    game_info = []
    version_info = []
    notes = []
    screenshot = ''
    sid = ''

    for line in nfo_text.split('\n'):
        if ('-----' in line) or ('=====' in line):
            continue
        elif 'GAME INFO:' in line:
            infopart = 'game'
        elif 'VERSION INFO:' in line:
            infopart = 'version'
        elif 'NOTES:' in line:
            infopart = 'notes'
        elif 'Screenshot:' in line:
            screenshot = line.split(':')[-1].strip().replace('\\', '/')
        elif 'SID:' in line:
            sid = line.split(':')[-1].strip()
        else:
            if infopart == 'game':
                game_info.append(line)
            elif infopart == 'version':
                version_info.append(line)
            elif infopart == 'notes':
                notes.append(line)

    entry = '\n'.join(game_info)
    entry += '\n' + '\n'.join(version_info)
    entry += '\n' + '\n'.join(notes)

    return Gb64VersionNfo(
        entry=entry,
        screenshot=screenshot,
        sid=sid,
        game_info=tuple(game_info),
        version_info=tuple(version_info),
        notes=tuple(notes),
    )


def parse_cover_filename(filename: str) -> tuple[str, str, str] | None:
    """Map a cover file name to ``(title, art_type, extension)``.

    The extension has no leading dot. A trailing ``[Back]`` token selects the
    ``covers - back`` type; a trailing ``(…)`` token is dropped; the remaining
    ``_``-separated tokens form the title. Returns ``None`` when no title
    token remains (e.g. ``[Back].png``).
    """

    filebase, filext = os.path.splitext(filename)
    extension = filext.removeprefix('.')

    tokens = filebase.split('_')
    if not tokens:
        return None

    art_type = 'covers'
    if tokens[-1] == '[Back]':
        art_type = 'covers - back'
        del tokens[-1]
    if not tokens:
        return None

    if tokens[-1].startswith('(') and tokens[-1].endswith(')'):
        tokens.pop()
    if not tokens:
        return None

    title = ' '.join(tokens)
    if not title:
        return None

    return title, art_type, extension
