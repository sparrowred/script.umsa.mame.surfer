"""Artwork-related domain logic (Kodi-independent)."""

import hashlib
import os
from typing import Any, Dict, Optional


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


def root_key_for_path(root_path: str) -> str:
    """Generate a deterministic root key from a filesystem path.

    Normalizes the path (realpath, strips trailing separators) and returns
    a stable SHA256 hex digest. This ensures records from a previous root
    cannot be accidentally resolved against a new root.
    """

    if root_path is None:
        return ''

    try:
        normalized = os.path.realpath(os.path.abspath(root_path))
    except OSError:
        normalized = os.path.abspath(root_path)

    # Strip trailing path separators for consistency
    normalized = normalized.rstrip(os.sep)
    if os.altsep:
        normalized = normalized.rstrip(os.altsep)

    return hashlib.sha256(normalized.encode('utf-8', errors='replace')).hexdigest()


def resolve_artwork_path(art: Dict[str, Any], set_info: Dict[str, Any],
                         source_roots: Dict[str, str]) -> str:
    """Resolve the full filesystem path for an artwork entry.

    Supports both ordinary files and files stored inside ZIP archives.
    For archive records, returns a Kodi-compatible archive path (not extracted).
    The function does not rely on absolute roots stored in the database and
    validates root_key against the current configured root.

    Args:
        art: Artwork metadata from database (new schema). May contain:
            source, root_key, scan_unit, type, extension, relative_path,
            archive_member
        set_info: Game set info (swl_name, name)
        source_roots: Mapping from source name to configured root directory

    Returns:
        Full path to artwork file, or empty string if cannot resolve
    """

    source = art.get('source')
    if not source:
        # Fallback to old-style reconstruction if needed
        return _build_legacy_path(art, set_info, source_roots)

    current_root = source_roots.get(source) if source_roots else None
    if not current_root:
        return ''

    # Validate root key matches current root to prevent cross-root resolution
    art_root_key = art.get('root_key', '')
    current_root_key = root_key_for_path(current_root)
    if art_root_key and current_root_key and art_root_key != current_root_key:
        return ''

    archive_member = art.get('archive_member')
    relative_path = art.get('relative_path')

    # Handle archive-contained files
    if archive_member:
        if relative_path:
            archive_full = os.path.join(current_root, relative_path)
            # Kodi archive path format
            return f"zip://{archive_full}/{archive_member}"
        # If no relative_path but archive member exists, cannot construct
        return ''

    # Handle ordinary files
    if relative_path:
        # For sources that store explicit relative paths (exodos/gb64)
        return os.path.join(current_root, relative_path)

    # Reconstruct from set info and type (progetto-style)
    art_type = art.get('type', '')
    extension = art.get('extension', '')

    if set_info.get('swl_name') == 'mame':
        filename = os.path.join(
            current_root, art_type, art_type,
            f"{set_info['name']}.{extension}"
        )
    elif (set_info.get('swl_name') == 'exodos') or (
        set_info.get('swl_name', '')[:5] == 'gb64_'
    ):
        # Fallback - should not happen if relative_path is properly stored
        filename = os.path.join(current_root, art_type, f"{set_info['name']}.{extension}")
    else:
        filename = os.path.join(
            current_root, art_type, set_info.get('swl_name', ''),
            f"{set_info['name']}.{extension}"
        )
    return filename


def _build_legacy_path(art: Dict[str, Any], set_info: Dict[str, Any],
                       source_roots: Dict[str, str]) -> str:
    """Build path using old-style art dict (for backward compatibility)."""

    art_path_flag = art.get('path')
    progetto = source_roots.get('progettosnaps') or source_roots.get('progetto', '')
    other_artwork = source_roots.get('artwork2') or source_roots.get('otherart', '')

    if art_path_flag:
        path_root = progetto
    else:
        path_root = other_artwork

    if set_info['swl_name'] == 'mame':
        filename = os.path.join(
            path_root, art['type'], art['type'], set_info['name'] + '.' + art['extension']
        )
    elif (set_info['swl_name'] == 'exodos') or (set_info['swl_name'][:5] == 'gb64_'):
        filename = art.get('filename', '')
    else:
        filename = os.path.join(
            path_root, art['type'], set_info['swl_name'],
            "{}.{}".format(set_info['name'], art['extension'])
        )
    return filename


def build_artwork_path(art: dict, set_info: dict, progetto: str, other_artwork: str) -> str:
    """Build the full filesystem path for an artwork entry (legacy API).

    Args:
        art: Artwork metadata (type, extension, path, filename) - old style
            or new style fields
        set_info: Game set info (swl_name, name)
        progetto: ProgettoSnaps base path
        other_artwork: Alternative artwork base path

    Returns:
        Full path to the artwork file
    """

    source_roots = {
        'progettosnaps': progetto,
        'progetto': progetto,
        'artwork2': other_artwork,
        'otherart': other_artwork,
    }

    # Try new resolver if it looks like new schema
    if art.get('source') or art.get('root_key') is not None or art.get('relative_path') is not None:
        return resolve_artwork_path(art, set_info, source_roots)

    # Fall back to legacy
    return _build_legacy_path(art, set_info, source_roots)


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
