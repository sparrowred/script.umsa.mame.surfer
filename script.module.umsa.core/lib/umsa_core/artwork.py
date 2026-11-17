"""Artwork paths, root keys and layout categories of artwork types."""

import hashlib
import os
from typing import Any
from urllib.parse import quote


def check_image_aspect(set_info: dict) -> str:
    """Return the skin orientation ``'Vertical'``, ``'Horizontal'`` or ``'NotScaled'``.

    ``set_info`` needs ``display_rotation``, ``display_type``, ``category``
    and ``swl_name``.
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


LEFT_IMAGELIST = (
    'snap', 'titles', 'howto', 'logo', 'bosses', 'ends',
    'gameover', 'scores', 'select', 'versus', 'warning'
)

RIGHT_IMAGELIST = (
    'cabinets', 'cpanel', 'flyers', 'marquees', 'media',
    'cabdevs', 'pcb', 'artpreview', 'covers',
    'projectmess_covers'
)

# Excludes videosnaps, manuals, soundtrack and ips.
IMAGE_ART_TYPES = LEFT_IMAGELIST + RIGHT_IMAGELIST


def find_local_snapshots(snapshot_dir: str, set_info: dict) -> list[str]:
    """Return the paths of every entry in the set's MAME snapshot directory.

    ``snapshot_dir`` is the snapshot directory of mame.ini; ``set_info``
    needs ``swl_name`` and ``name``. Unfiltered and unsorted; ``[]`` when the
    directory does not exist.
    """

    if set_info['swl_name'] == 'mame':
        snap_dir = os.path.join(snapshot_dir, set_info['name'])
    else:
        snap_dir = os.path.join(snapshot_dir, set_info['swl_name'], set_info['name'])
    if not os.path.isdir(snap_dir):
        return []
    return [os.path.join(snap_dir, name) for name in os.listdir(snap_dir)]


def categorize_art_type(art_type: str) -> str:
    """Return the layout slot: ``right``, ``left``, ``video``, ``manual``, ``unknown``."""

    if art_type in RIGHT_IMAGELIST:
        return 'right'
    if art_type in LEFT_IMAGELIST:
        return 'left'
    if art_type == 'videosnaps':
        return 'video'
    if art_type == 'manuals':
        return 'manual'
    return 'unknown'


# Root keys computed by root_key_for_path, by root path string. The resolver
# reads them instead of calling realpath for every artwork row.
_ROOT_KEYS: dict[str, str] = {}
_ROOT_KEYS_MAX = 64


def root_key_for_path(root_path: str) -> str:
    """Return the SHA256 root key of a path (realpath, no trailing separator).

    Records of a previous root can then never be resolved against a new one.
    The key is always computed afresh and stored for
    :func:`resolve_artwork_path`, so a scan also refreshes the key the
    resolver uses (e.g. after a symlinked root was moved).
    """

    if root_path is None:
        return ''

    try:
        normalized = os.path.realpath(os.path.abspath(root_path))
    except OSError:
        normalized = os.path.abspath(root_path)

    normalized = normalized.rstrip(os.sep)
    if os.altsep:
        normalized = normalized.rstrip(os.altsep)

    key = hashlib.sha256(normalized.encode('utf-8', errors='replace')).hexdigest()
    if len(_ROOT_KEYS) >= _ROOT_KEYS_MAX and root_path not in _ROOT_KEYS:
        _ROOT_KEYS.clear()
    _ROOT_KEYS[root_path] = key
    return key


def _cached_root_key(root_path: str) -> str:
    """Return the root key of ``root_path``, computed once per path string."""

    key = _ROOT_KEYS.get(root_path)
    if key is None:
        key = root_key_for_path(root_path)
    return key


def _safe_relative(relative_path: str) -> bool:
    """Return whether a stored ``relative_path`` stays inside its root.

    Absolute paths (also ``\\``-rooted or with a drive letter) and paths with
    a ``..`` component are unsafe: ``os.path.join`` would drop or leave the
    configured root.
    """

    if os.path.isabs(relative_path) or relative_path[:1] in ('/', '\\'):
        return False
    if relative_path[1:2] == ':':
        return False
    parts = relative_path.replace('\\', '/').split('/')
    return '..' not in parts


def resolve_artwork_path(art: dict[str, Any], set_info: dict[str, Any],
                         source_roots: dict[str, str]) -> str:
    """Return the full path of an artwork row, or ``''`` if it cannot be resolved.

    A ZIP member gives a Kodi ``zip://`` path (not extracted). The row's
    ``root_key`` must match the configured root of its source; a
    ``relative_path`` that is absolute or contains ``..`` gives ``''``.

    Args:
        art: Artwork row (``source``, ``root_key``, ``type``, ``extension``,
            ``relative_path``, ``archive_member``).
        set_info: Set info with ``swl_name`` and ``name``.
        source_roots: ``{source name: configured root directory}``.
    """

    source = art.get('source')
    if not source:
        return _build_legacy_path(art, set_info, source_roots)

    current_root = source_roots.get(source) if source_roots else None
    if not current_root:
        return ''

    art_root_key = art.get('root_key', '')
    current_root_key = _cached_root_key(current_root)
    if art_root_key and current_root_key and art_root_key != current_root_key:
        return ''

    archive_member = art.get('archive_member')
    relative_path = art.get('relative_path')
    # A DB row must never point outside its root (absolute path or "..").
    if relative_path and not _safe_relative(relative_path):
        return ''

    if archive_member:
        if relative_path:
            archive_full = os.path.join(current_root, relative_path)
            # Kodi archive path: the URL-encoded archive path is the host part,
            # /tmp/x/a.zip -> zip://%2ftmp%2fx%2fa.zip/member.mp4
            encoded_archive = quote(archive_full, safe='')
            return f"zip://{encoded_archive}/{archive_member}"
        return ''

    if relative_path:
        return os.path.join(current_root, relative_path)

    # Without a relative path the location follows the progettosnaps layout.
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
        # eXoDOS/GB64 rows normally carry a relative path.
        filename = os.path.join(current_root, art_type, f"{set_info['name']}.{extension}")
    else:
        filename = os.path.join(
            current_root, art_type, set_info.get('swl_name', ''),
            f"{set_info['name']}.{extension}"
        )
    return filename


def _build_legacy_path(art: dict[str, Any], set_info: dict[str, Any],
                       source_roots: dict[str, str]) -> str:
    """Return the path of an artwork dict without ``source`` (old row layout)."""

    art_path_flag = art.get('path')
    progettosnaps = source_roots.get('progettosnaps', '')
    own_artwork = source_roots.get('own_artwork', '')

    if art_path_flag:
        path_root = progettosnaps
    else:
        path_root = own_artwork

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


def build_artwork_path(art: dict, set_info: dict, progettosnaps: str, own_artwork: str) -> str:
    """Return the full path of an artwork dict for the two MAME artwork roots.

    Accepts both the current row layout (resolved by
    :func:`resolve_artwork_path`) and the old one without ``source``.
    """

    source_roots = {
        'progettosnaps': progettosnaps,
        'own_artwork': own_artwork,
    }

    if art.get('source') or art.get('root_key') is not None or art.get('relative_path') is not None:
        return resolve_artwork_path(art, set_info, source_roots)

    return _build_legacy_path(art, set_info, source_roots)


def machine_set_name(set_info: dict) -> str | None:
    """Return the MAME set name whose cabinet shows the machine of ``set_info``.

    Software list sets use their machine (``machine_name``), MAME machine sets
    themselves; other MAME sets (arcade games) have none (``None``).
    """

    if set_info["machine_name"] != "mame":
        return set_info["machine_name"]
    if set_info["is_machine"]:
        return set_info["name"]
    return None


def get_machine_artwork_path(
    set_info: dict, cab_path: str, fallback_media_dir: str,
    cabinets: dict | None = None, source_roots: dict | None = None,
) -> str:
    """Return the path of the machine picture of a set.

    Args:
        set_info: Dict with ``machine_name``, ``name``, ``is_machine`` and
            ``category``.
        cab_path: Cabinet folder (e.g. ``/progettosnaps/cabinets/cabinets``),
            used when the artwork database has no cabinet for the machine.
        fallback_media_dir: Folder with ``pinball.png``, ``reels.png`` and
            ``arcade.png``.
        cabinets: Optional ``{machine set name: art row}`` from
            ``ArtworkQueries.get_machine_cabinets``.
        source_roots: Artwork source roots to resolve the ``cabinets`` rows.
    """

    machine = machine_set_name(set_info)
    if machine is not None:
        art = (cabinets or {}).get(machine)
        if art:
            # set_name: parent or clone whose cabinet stands in for the machine.
            path = resolve_artwork_path(
                art, {"name": art.get("set_name", machine), "swl_name": "mame"},
                source_roots or {})
            # Empty when the source root changed since the scan.
            if path:
                return path
        return os.path.join(cab_path, machine + ".png")
    if set_info["category"] == "Electromechanical / Pinball":
        return os.path.join(fallback_media_dir, "pinball.png")
    if "Reels" in set_info["category"]:
        return os.path.join(fallback_media_dir, "reels.png")
    return os.path.join(fallback_media_dir, "arcade.png")
