"""Parsers for GameBase64 support data.

The parsers are pure: they never touch a database, the filesystem or a ZIP
archive, and never import SQLite. :func:`parse_version_nfo` consumes the raw
text of a ``VERSION.NFO`` file and returns a :class:`Gb64VersionNfo`;
:func:`parse_cover_filename` maps a cover image's file name to a title and an
artwork type. Both can therefore be unit-tested without a Kodi runtime, an
archive or a database.

The behaviour is a direct extraction of the historical ``scan_gb64_nfo()``
helper that used to write straight into ``dat``/``dat_set``/``art_set`` from
``support.py``: the generated metadata text, the cover ``[Back]``/``(…)``
handling and the ``Screenshot:``/``SID:`` extraction are preserved. Only the
database access was removed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Gb64VersionNfo:
    """The parsed content of one ``VERSION.NFO`` file.

    Attributes:
        entry: The complete metadata text stored in ``dat.entry``. It joins the
            ``GAME INFO:``, ``VERSION INFO:`` and ``NOTES:`` sections with the
            historical separators (a newline between every line and between the
            sections), even when a section is empty.
        screenshot: The ``Screenshot:`` value, with backslashes normalised to
            forward slashes. Empty when the section is absent. It is a reference
            relative to the ``Screenshots`` directory, not a filesystem path.
        sid: The ``SID:`` value. Empty when the section is absent. It is kept
            for completeness even though the DAT/artwork import does not use it.
        game_info: The raw ``GAME INFO:`` lines, in order.
        version_info: The raw ``VERSION INFO:`` lines, in order.
        notes: The raw ``NOTES:`` lines, in order.
    """

    entry: str
    screenshot: str
    sid: str
    game_info: tuple
    version_info: tuple
    notes: tuple


def parse_version_nfo(nfo_text: str) -> Gb64VersionNfo:
    """Parse GameBase64 ``VERSION.NFO`` text into a :class:`Gb64VersionNfo`.

    Lines containing ``-----`` or ``=====`` are treated as separators and
    skipped. ``GAME INFO:``/``VERSION INFO:``/``NOTES:`` select the current
    section; lines before any of them are discarded, matching the historical
    behaviour. ``Screenshot:`` and ``SID:`` are extracted with
    ``split(':')[-1].strip()`` and are not added to any section.
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


def parse_cover_filename(filename: str) -> Optional[Tuple[str, str, str]]:
    """Map a cover file name to ``(title, art_type, extension)``.

    ``filename`` is the base name including its extension. The extension is
    returned without the leading dot (``''`` when there is none). A trailing
    ``[Back]`` token selects the ``covers - back`` type and is removed; a
    trailing ``(…)`` parenthesised token is always dropped. The remaining
    ``_``-separated tokens are joined with spaces to form the title.

    Returns ``None`` when no title token remains (for example a file named only
    ``[Back].png``), so callers can skip it instead of matching an empty title.
    """

    filebase, filext = os.path.splitext(filename)
    extension = filext[1:] if filext.startswith('.') else filext

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
