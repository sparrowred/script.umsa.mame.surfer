"""Default filter that is created on the first start.

``default_filter.json`` (next to this module) describes the filter per
category as an exclusion list of names: every entry of the matching umsa.db
table is selected except the excluded names. Names instead of ids keep the
description valid across umsa.db versions; categories missing from the file
stay empty (unfiltered).

Softwarelists of the other collections (eXoDOS, GameBase64, WHDLoad) whose
folder is not configured are left out as well (``nonmame_exclusions``).

The filter is written to status.db once (marker ``default_filter_seeded`` in
``status_meta``), so a filter the user deleted later is not created again.
Kodi-free; the GUI and the screensaver call it through
``DBMod.ensure_default_filter``.
"""

import json
from pathlib import Path

from .logging import log

DEFAULT_FILTER_NAME = "default"
DEFAULT_FILTER_SEEDED_KEY = "default_filter_seeded"
DEFAULT_FILTER_SPEC_PATH = Path(__file__).with_name("default_filter.json")

# public filter category -> (umsa.db table, extra predicate)
_CATEGORY_TABLES = {
    "Softwarelists": ("swl", ""),
    "Game Categories": ("category", "WHERE flag = 0"),
    "Machine Categories": ("category", "WHERE flag = 1"),
    "Years": ("year", ""),
    "Players": ("nplayers", ""),
}


def nonmame_exclusions(nonmame):
    """Return a matcher for softwarelists of collections without a folder.

    ``nonmame`` maps the collection keys (``exodos``, ``gb64``, ``whdload``)
    to their root folders. A collection with an empty folder excludes the
    softwarelist named like the key and all named ``<key>_...``
    (``gb64_cart``, ``whdload_games``, ...).
    """

    missing = tuple(key for key, path in (nonmame or {}).items() if not path)

    def is_excluded(swl_name):
        return any(swl_name == key or swl_name.startswith(key + "_") for key in missing)

    return is_excluded


def load_default_filter_spec(path=DEFAULT_FILTER_SPEC_PATH):
    """Return the parsed default filter description."""

    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def resolve_default_filter(connection, spec, nonmame=None):
    """Return ``{public category: [id strings]}`` for the umsa.db behind ``connection``.

    Each category named in ``spec`` selects all rows of its table except the
    excluded names; excluded names that do not exist are ignored. All other
    categories stay empty. With ``nonmame`` given, softwarelists of
    collections without a folder are excluded too.
    """

    swl_excluded = nonmame_exclusions(nonmame)

    filter_lists = {category: [] for category in _CATEGORY_TABLES}
    cursor = connection.cursor()
    try:
        for category, (table, predicate) in _CATEGORY_TABLES.items():
            entry = spec.get(category)
            if not isinstance(entry, dict):
                continue
            excluded = {str(name) for name in entry.get("exclude", [])}
            cursor.execute(f"SELECT id, name FROM {table} {predicate} ORDER BY id")
            rows = cursor.fetchall()
            filter_lists[category] = [
                str(row[0]) for row in rows
                if str(row[1]) not in excluded
                and not (category == "Softwarelists" and swl_excluded(str(row[1])))
            ]
            log(
                f"UMSA default filter: {category}: {len(filter_lists[category])} "
                f"of {len(rows)} selected",
                level="debug",
            )
    finally:
        cursor.close()
    return filter_lists
