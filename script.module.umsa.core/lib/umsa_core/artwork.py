"""Artwork-related domain logic (Kodi-independent)."""

import os


def check_image_aspect(set_info: dict) -> str:
    """Return the artwork orientation used by the GUI skin.

    Args:
        set_info: Dictionary with keys 'display_rotation', 'display_type',
            'category', 'swl_name'

    Returns:
        'Vertical', 'Horizontal', or 'NotScaled'
    """

    aspect_ratio = 'Vertical' if set_info['display_rotation'] in [90, 270] else 'Horizontal'
    if (
        set_info['display_type'] == 'lcd'
        or set_info['category'] in (
            'Electromechanical / Pinball', 'Handheld Game')
        or set_info['swl_name'] in (
            'gameboy', 'lynx', 'gamegear', 'vboy', 'vectrex')
    ):
        aspect_ratio = 'NotScaled'
    return aspect_ratio


# Artwork type categorization for UI layout
LEFT_IMAGELIST = (
    'snap', 'titles', 'howto', 'logo', 'bosses', 'ends',
    'gameover', 'scores', 'select', 'versus', 'warning'
)

RIGHT_IMAGELIST = (
    'cabinets', 'cpanel', 'flyers', 'marquees', 'media',
    'cabdevs', 'pcb', 'artpreview', 'covers',
    'projectmess_covers'
)

# All artwork types that are images (excludes videosnaps, manuals, soundtrack, ips)
IMAGE_ART_TYPES = LEFT_IMAGELIST + RIGHT_IMAGELIST


def find_local_snapshots(snapshot_dir: str, set_info: dict) -> list[str]:
    """Find local MAME snapshot files for a game set.

    Args:
        snapshot_dir: Base snapshot directory from mame.ini
        set_info: Dict with 'swl_name' and 'name' keys

    Returns:
        Full paths of every entry in the set's snapshot directory, in
        os.listdir order (no extension filtering or sorting).
    """

    if set_info['swl_name'] == 'mame':
        snap_dir = os.path.join(snapshot_dir, set_info['name'])
    else:
        snap_dir = os.path.join(snapshot_dir, set_info['swl_name'], set_info['name'])
    if not os.path.isdir(snap_dir):
        return []
    return [os.path.join(snap_dir, name) for name in os.listdir(snap_dir)]


def categorize_art_type(art_type: str) -> str:
    """Categorize an artwork type for UI layout.

    Args:
        art_type: Artwork type from the database

    Returns:
        'right', 'left', 'video', 'manual', or 'unknown'
    """

    if art_type in RIGHT_IMAGELIST:
        return 'right'
    if art_type in LEFT_IMAGELIST:
        return 'left'
    if art_type == 'videosnaps':
        return 'video'
    if art_type == 'manuals':
        return 'manual'
    return 'unknown'


def build_artwork_path(art: dict, set_info: dict, progetto: str, other_artwork: str) -> str:
    """Build the full filesystem path for an artwork entry.

    Args:
        art: Artwork metadata (type, extension, path, filename)
        set_info: Game set info (swl_name, name)
        progetto: ProgettoSnaps base path
        other_artwork: Alternative artwork base path

    Returns:
        Full path to the artwork file
    """

    if art['path']:
        path = progetto
    else:
        path = other_artwork

    if set_info['swl_name'] == 'mame':
        filename = os.path.join(
            path, art['type'], art['type'], set_info['name']+'.'+art['extension']
        )
    elif (set_info['swl_name'] == 'exodos') or (set_info['swl_name'][:5] == 'gb64_'):
        filename = art['filename']
    else:
        filename = os.path.join(
            path, art['type'], set_info['swl_name'],
            "{}.{}".format(set_info['name'], art['extension'])
        )
    return filename


def get_machine_artwork_path(
    set_info: dict, cab_path: str, fallback_media_dir: str
) -> str:
    """Return the machine artwork path for a game set.

    Args:
        set_info: Dict with keys 'machine_name', 'name', 'is_machine',
            'category'
        cab_path: Base cabinet artwork path (e.g. /progetto/cabinets/cabinets)
        fallback_media_dir: Directory with fallback images (pinball.png,
            reels.png, arcade.png)

    Returns:
        Full path to the machine artwork image
    """

    if set_info["machine_name"] != "mame":
        return os.path.join(cab_path, set_info["machine_name"] + ".png")
    if set_info["is_machine"]:
        return os.path.join(cab_path, set_info["name"] + ".png")
    if set_info["category"] == "Electromechanical / Pinball":
        return os.path.join(fallback_media_dir, "pinball.png")
    if "Reels" in set_info["category"]:
        return os.path.join(fallback_media_dir, "reels.png")
    return os.path.join(fallback_media_dir, "arcade.png")
