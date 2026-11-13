"""Artwork selection, path resolution and machine picture helpers.

The module knows the artwork sources of the screensaver, wraps the shared
Core resolver and derives the aspect handling of an artwork row. It does
not touch Kodi controls.
"""

from os import path

from umsa_core import check_image_aspect, get_machine_artwork_path, resolve_artwork_path
from umsa_core.artwork import machine_set_name

from .constants import ART_TYPES_BY_MODE

# Artwork types that are validated as image files
SNAPSHOT_TYPES = ('snap', 'titles', 'covers')

# Artwork types that keep their aspect ratio
ASPECT_TYPES = ('snap', 'titles')

def art_types_for_mode(mode):
    """Return the artwork types shown in the given screensaver mode."""

    return list(ART_TYPES_BY_MODE.get(mode, []))


def source_roots(paths, umsa):
    """Return the source roots used by the Core artwork resolver.

    ``paths`` is the (own_artwork, progettosnaps) pair of the shared
    settings, ``umsa`` the runtime object holding the non-MAME roots.
    """

    if hasattr(umsa, "nonmame"):
        exodos = umsa.nonmame.get("exodos")
        gb64 = umsa.nonmame.get("gb64")
    else:
        exodos = ""
        gb64 = ""
    return {
        "progettosnaps": paths[1] if len(paths) > 1 else paths[0],
        "own_artwork": paths[0] if len(paths) > 0 else "",
        "exodos": exodos,
        "gb64": gb64,
    }


def resolve_art_path(art, roots):
    """Resolve an artwork path with the shared Core resolver.

    ``art`` carries the ``art_set`` fields (source, root_key,
    relative_path, archive_member). Further artwork of the set (the left
    picture) comes from the database: ``ArtworkQueries.get_set_artwork``.
    """

    return resolve_artwork_path(art, art, roots)


def machine_picture(use_set, ggdb, roots, media_folder):
    """Return the full path of the machine picture of a set.

    Same Core functions as the frontend's machine wraplist: the scanned
    cabinet (``ArtworkQueries.get_machine_cabinets``, own artwork before
    progettosnaps)
    wins, without an artwork scan the fixed progettosnaps cabinet path is
    used; pinballs, reels and arcade games get the internal pictures.
    """

    machine = machine_set_name(use_set)
    cabinets = ggdb.art_queries.get_machine_cabinets([machine]) if machine else {}
    cab_path = path.join(roots.get('progettosnaps', ''), 'cabinets/cabinets')
    return get_machine_artwork_path(use_set, cab_path, media_folder, cabinets, roots)


def aspect_for(art):
    """Return the aspect handling of an artwork row.

    ``NotScaled`` keeps the artwork inside its control, every other value
    comes from the shared Core aspect detection.
    """

    if art['type'] not in ASPECT_TYPES:
        return 'NotScaled'
    return check_image_aspect(art)


def display_for(art):
    """Return the display orientation of the game screen of a row.

    ``Horizontal``, ``Vertical`` or ``NotScaled`` from the shared Core
    detection, independent of the artwork type of the row.
    """

    return check_image_aspect(art)


def needs_snapshot_check(art_type):
    """Return ``True`` when the artwork type is validated as image file."""

    return art_type in SNAPSHOT_TYPES


def left_picture_type(art):
    """Return the artwork type used as left picture of a set."""

    return 'flyers' if art['swl_name'] == 'mame' else 'covers'
