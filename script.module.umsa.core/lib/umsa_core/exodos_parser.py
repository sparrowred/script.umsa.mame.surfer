"""Pure parser for the eXoDOS MS-DOS metadata XML.

The parser is pure: it never touches a database, the filesystem or a ZIP
archive, and never imports SQLite or Kodi. It consumes the already-read text of
``xml/all/MS-DOS.xml`` (from ``Content/XODOSMetadata.zip``) plus the
RootFolder-to-UMSA-set mapping and returns :class:`ExodosMetadata` records
grouped in an :class:`ExodosParseResult`.

The generated metadata text, the ``eXoDOS`` display category and the RootFolder
matching are a direct extraction of the historical XML loop that used to write
straight into ``dat``/``dat_set`` from ``support.py``: only the database access
was removed, so the stored text stays byte-for-byte identical.

Every metadata field is initialised independently for each ``<Game>`` element,
so a field missing from one game can never inherit the value of the preceding
game. Missing tags and tags whose ``.text`` is ``None`` become an empty string
rather than the literal ``"None"``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Mapping, Optional

DAT_FILE = "eXoDOS"

# The tags rendered into the metadata note, in the historical field order.
_FIELD_TAGS = (
    "Genre",
    "Developer",
    "Publisher",
    "Notes",
    "Source",
    "Rating",
    "Series",
    "Region",
)


class ExodosParseError(ValueError):
    """Raised when the eXoDOS metadata XML cannot be parsed."""


@dataclass(frozen=True)
class ExodosMetadata:
    """One parsed eXoDOS metadata record, ready for the DAT repository.

    Attributes:
        file: The display category, always :data:`DAT_FILE` (``eXoDOS``),
            matching the historical ``dat.file`` value.
        entry: The complete rendered metadata text (see :func:`render_note`).
        set_ids: The matched UMSA set ids. Exactly one id for a matched game;
            kept as a tuple so the record is directly usable by the DAT
            repository, which accepts the same ``file``/``entry``/``set_ids``
            shape as :class:`umsa_core.dat_parser.DatEntry`.
        root_folder: The final RootFolder path component that was matched, kept
            for diagnostics.
    """

    file: str
    entry: str
    set_ids: tuple
    root_folder: str


@dataclass(frozen=True)
class ExodosParseResult:
    """The outcome of parsing the eXoDOS metadata XML.

    Attributes:
        records: The matched records, in document order.
        unmatched: The final RootFolder component of every game that could not
            be mapped (including missing/empty RootFolder values), in document
            order, so the caller can log them.
    """

    records: tuple
    unmatched: tuple


def render_note(genre, developer, publisher, notes, source, rating, series,
                region) -> str:
    """Render the human-readable eXoDOS metadata text.

    The layout, label spelling and blank lines reproduce exactly what the
    historical ``scan_exodos()`` XML loop stored, including the blank line after
    ``Genre:``, the blank line before the notes, the blank line before
    ``Source:`` and the trailing newline.
    """

    return (
        f"Genre: {genre}\n"
        f"\n"
        f"Developer: {developer}\n"
        f"Publisher: {publisher}\n"
        f"\n"
        f"{notes}\n"
        f"\n"
        f"Source: {source}\n"
        f"Rating: {rating}\n"
        f"Series: {series}\n"
        f"Region: {region}\n"
    )


def _root_folder_component(text: Optional[str]) -> str:
    """Return the final path component of a RootFolder value.

    Both Windows-style backslashes and forward slashes are accepted regardless
    of the host operating system. A missing or empty value yields an empty
    string, which the caller treats as unmatched.
    """

    if not text:
        return ""
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def _match_set_id(root_folder: str,
                  root_folder_map: Mapping[str, int]) -> Optional[int]:
    """Map a RootFolder component to a UMSA set id.

    An exact mapping match is preferred. Otherwise a genuine case-insensitive
    fallback compares the RootFolder against every mapping key (the keys keep
    their original casing, so lower-casing only the lookup value would never
    match them). A fallback that matches several keys with *different* set ids
    is ambiguous and left unmatched, so it can never silently pick the wrong
    set. Returns ``None`` when nothing matches.
    """

    if not root_folder:
        return None
    if root_folder in root_folder_map:
        return root_folder_map[root_folder]

    lowered = root_folder.lower()
    matched_id: int | None = None
    for key, set_id in root_folder_map.items():
        if key.lower() != lowered:
            continue
        if matched_id is None:
            matched_id = set_id
        elif matched_id != set_id:
            # Two different sets share this case-insensitive name: ambiguous.
            return None
    return matched_id


def parse_exodos_metadata(xml_text: str,
                          root_folder_map: Mapping[str, int]
                          ) -> ExodosParseResult:
    """Parse eXoDOS ``MS-DOS.xml`` text into metadata records.

    ``xml_text`` is the already-read XML document; ``root_folder_map`` maps a
    RootFolder component to a UMSA set id (the historical ``exodos_sets_names``
    mapping). Returns an :class:`ExodosParseResult`.

    Malformed XML raises :class:`ExodosParseError` (chaining the original
    :class:`xml.etree.ElementTree.ParseError`); it never returns a
    valid-looking empty result, so a failed parse cannot wipe existing data.
    """

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ExodosParseError(str(exc)) from exc

    records = []
    unmatched = []

    for game in root.iter("Game"):
        fields = {tag: "" for tag in _FIELD_TAGS}
        root_folder = ""
        for child in game.iter():
            tag = child.tag
            if tag == "RootFolder":
                root_folder = _root_folder_component(child.text)
            elif tag in fields:
                fields[tag] = child.text if child.text is not None else ""

        set_id = _match_set_id(root_folder, root_folder_map)
        if set_id is None:
            unmatched.append(root_folder)
            continue

        note = render_note(
            fields["Genre"],
            fields["Developer"],
            fields["Publisher"],
            fields["Notes"],
            fields["Source"],
            fields["Rating"],
            fields["Series"],
            fields["Region"],
        )
        records.append(ExodosMetadata(DAT_FILE, note, (set_id,), root_folder))

    return ExodosParseResult(tuple(records), tuple(unmatched))
