"""Artwork selection, path resolution and machine picture helpers.

The module knows the artwork sources of the screensaver, wraps the shared
Core resolver and derives the aspect handling of an artwork row. It does
not touch Kodi controls.
"""

from os import path

from umsa_core import check_image_aspect, resolve_artwork_path

from .constants import ART_TYPES_BY_MODE

# Artwork types that are validated as image files
SNAPSHOT_TYPES = ('snap', 'titles', 'covers')

# Artwork types that keep their aspect ratio
ASPECT_TYPES = ('snap', 'titles')

# Machine categories that use a dedicated fallback picture
MACHINE_CATEGORIES = (
    'Handheld / Electronic Game', "Handheld / Plug n' Play TV Game",
    'Electromechanical / Reels', 'Casino / Reels',
    'Slot Machine / Reels', 'Slot Machine / Video Slot'
)


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


def resolve_art_path(art, roots, art_type=None, extension=None):
    """Resolve an artwork path with the shared Core resolver.

    ``art`` carries the ``art_set`` fields (source, root_key,
    relative_path, archive_member). When ``art_type`` is given, an
    alternate artwork of the same set (the flyer, cover or snap shown
    next to the main image) is resolved instead of the stored row.
    """

    if art_type is None:
        return resolve_artwork_path(art, art, roots)

    derived = dict(art)
    derived['type'] = art_type
    derived['relative_path'] = None
    derived['archive_member'] = None
    if extension is not None:
        derived['extension'] = extension
    return resolve_artwork_path(derived, art, roots)


def machine_picture(use_set, progettosnaps, media_folder):
    """Return the full path of the machine picture of a set.

    Uses the internal cabinet picture for pinballs, reels and arcade
    machines of the MAME software list.
    """

    cab_path = path.join(progettosnaps, 'cabinets/cabinets')
    pic = None
    # set machine pic for mame
    if use_set['machine_name'] == 'mame':
        if use_set['is_machine']:
            pic = path.join(cab_path, use_set['name']+'.png')
        elif use_set['category'] == 'Electromechanical / Pinball':
            pic = path.join(media_folder, "pinball.png")
        elif use_set['category'] in MACHINE_CATEGORIES:
            # TODO check if cabinet or artpreview is available for set
            # fallback
            if not pic:
                if 'Reels' in use_set['category']:
                    pic = path.join(media_folder, "reels.png")
                if not pic:
                    pic = path.join(media_folder, "arcade.png")
        else:
            if not pic:
                pic = path.join(media_folder, "arcade.png")
    # set machine pic for swl
    else:
        if not pic:
            # TODO fallback media pic for missing swl machine cab
            pic = path.join(cab_path, use_set['machine_name']+'.png')
    return pic


def aspect_for(art):
    """Return the aspect handling of an artwork row.

    ``NotScaled`` keeps the artwork inside its control, every other value
    comes from the shared Core aspect detection.
    """

    if art['type'] not in ASPECT_TYPES:
        return 'NotScaled'
    return check_image_aspect(art)


def needs_snapshot_check(art_type):
    """Return ``True`` when the artwork type is validated as image file."""

    return art_type in SNAPSHOT_TYPES


def left_picture_type(art):
    """Return the artwork type used as left picture of a set."""

    return 'flyers' if art['swl_name'] == 'mame' else 'covers'
