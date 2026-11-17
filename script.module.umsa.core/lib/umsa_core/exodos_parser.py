"""Pure parser for the eXoDOS metadata XML ``xml/all/MS-DOS.xml`` (no I/O).

Every field is read afresh for each ``<Game>``, so a missing tag never
inherits the previous game's value; missing or empty tags become ``""``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass

DAT_FILE = "eXoDOS"

# The tags rendered into the metadata note, in this order.
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
    """One parsed eXoDOS record, shaped like :class:`~umsa_core.dat_parser.DatEntry`.

    Attributes:
        file: The display category, always :data:`DAT_FILE`.
        entry: The rendered metadata text (see :func:`render_note`).
        set_ids: One-element tuple with the matched set id.
        root_folder: The matched final RootFolder component (diagnostics).
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
            be mapped (also empty ones), in document order.
    """

    records: tuple
    unmatched: tuple


def render_note(genre, developer, publisher, notes, source, rating, series,
                region) -> str:
    """Return the eXoDOS metadata text stored in ``dat.entry``."""

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


def _root_folder_component(text: str | None) -> str:
    """Return the final path component of a RootFolder value.

    Backslashes and forward slashes are accepted on every OS; a missing value
    gives ``""``.
    """

    if not text:
        return ""
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def _match_set_id(root_folder: str,
                  root_folder_map: Mapping[str, int]) -> int | None:
    """Return the set id of a RootFolder component, or ``None``.

    An exact match wins; otherwise the keys are compared case-insensitively.
    A case-insensitive match on several keys with different set ids is
    ambiguous and gives ``None``.
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

    ``root_folder_map`` maps a RootFolder component to a set id.

    Raises:
        ExodosParseError: On malformed XML, so a failed parse never looks like
            an empty result that would wipe existing data.
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
