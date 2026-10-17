"""eXoDOS image and videosnap artwork indexer.

This module owns the filesystem side of the eXoDOS artwork import. It walks
``Images/MS-DOS`` and ``Content/GameData/eXoDOS`` exactly once each, builds the
complete row collection for every scan unit in memory and publishes each unit
through :class:`umsa_core.artwork_repository.ArtworkRepository`, so a unit is
replaced atomically and repeated scans stay idempotent.

The image walk feeds three consumers from the single traversal: category
observation, the ``Screenshot - Game Title`` hashes used to drop mislabelled
``Box - Front`` covers and the artwork association itself. The GameData walk
feeds both the videosnap rows and the set of archives that still exist, which
drives safe stale-unit cleanup.

A unit that cannot be inventoried completely (a filesystem error, an unreadable
archive or a cancellation) is never published and never cleaned up: its previous
artwork survives and the failure is reported. Cleanup only runs after a
complete, successful, non-cancelled phase, so a temporarily unavailable root can
never look like an empty result.

The module is Kodi-independent and never imports or touches :class:`DBMod`.
"""

from __future__ import annotations

import os
import posixpath
import re
from zipfile import ZipFile

from .artwork import root_key_for_path
from .logging import log
from .support import exodos_type_convert, md5sum

SOURCE = "exodos"

IMAGE_EXTENSIONS = ('.gif', '.png', '.jpg')
VIDEO_EXTENSION = '.mp4'
VIDEOSNAP_TYPE = 'videosnaps'
TITLE_CATEGORY = 'Screenshot - Game Title'
BOX_FRONT_CATEGORY = 'Box - Front'

IMAGES_SUBDIR = ('Images', 'MS-DOS')
GAMEDATA_SUBDIR = ('Content', 'GameData', 'eXoDOS')

# A trailing parenthetical group, e.g. " (1993)" in "Doom (1993)".
_PARENTHETICAL_SUFFIX = re.compile(r'\s*\([^()]*\)\s*$')
_UNIT_SEPARATORS = re.compile(r'[\\/]+')


# -- helpers ---------------------------------------------------------------

def _noop_progress(percent=None, what=None):
    """Default progress callback that ignores every update."""


def _never_cancelled():
    """Default cancellation predicate that never requests a stop."""

    return False


def _normalize_name(name):
    """Normalize a game name the same way the set mapping keys are built."""

    return (name or '').replace(':', '_').replace(
        "'", '_').replace('?', '_').lower()


def _split_unit(scan_unit):
    """Split a stored scan unit into path components (portable separators)."""

    return [part for part in _UNIT_SEPARATORS.split(scan_unit or '') if part]


def _first_component(relative_path):
    """Return the top-level component of a relative path, or ``None``."""

    parts = _split_unit(relative_path)
    return parts[0] if parts else None


def _is_videosnap_unit(scan_unit):
    """Return ``True`` when a stored unit is a GameData videosnap archive.

    Classification is by normalized relative path only: the unit must live under
    ``Content/GameData/eXoDOS`` and its filename must carry a ``.zip`` suffix.
    Unknown or ambiguous units therefore never classify and are never removed.
    """

    parts = _split_unit(scan_unit)
    if len(parts) < len(GAMEDATA_SUBDIR) + 1:
        return False
    if tuple(parts[:len(GAMEDATA_SUBDIR)]) != GAMEDATA_SUBDIR:
        return False
    return parts[-1].lower().endswith('.zip')


def _match_set_name(base_name, exodos_sets):
    """Map a GameData archive basename to an ``exodos_sets`` key.

    The archive stem is tried exactly first; then trailing parenthetical groups
    are stripped one at a time and retried, so ``Doom (1993)`` and
    ``Campaign (Empire Software)(1992)`` both resolve. Returns the matching key
    or ``None`` when the archive cannot be mapped unambiguously.
    """

    candidate = posixpath.splitext(base_name or '')[0]
    while candidate:
        key = _normalize_name(candidate)
        if key in exodos_sets:
            return key
        stripped = _PARENTHETICAL_SUFFIX.sub('', candidate).rstrip()
        if stripped == candidate:
            return None
        candidate = stripped
    return None


class _Inventory:
    """The result of one ``os.walk`` over a root."""

    def __init__(self, root):
        self.root = root
        self.exists = False
        self.complete = False
        self.cancelled = False
        self.files = []
        self.dirs = []


def _walk_inventory(root, is_cancelled):
    """Walk ``root`` once, recording files, directories and completeness."""

    result = _Inventory(root)
    if not root or not os.path.isdir(root):
        return result

    result.exists = True
    failed = False

    def onerror(exc):
        nonlocal failed
        failed = True
        log(f"UMSA exodos artwork: cannot read "
            f"'{getattr(exc, 'filename', root)}': {exc}", level='error')

    for dirpath, _dirnames, filenames in os.walk(root, onerror=onerror):
        if is_cancelled():
            result.cancelled = True
            return result
        if dirpath != root:
            result.dirs.append(dirpath)
        for name in filenames:
            result.files.append(os.path.join(dirpath, name))

    result.complete = not failed
    return result


def _cleanup_obsolete_units(art_repo, root_key, present_units, classify):
    """Remove persisted units that ``classify`` recognizes but no longer exist.

    Never removes a unit that is not recognized by ``classify``, and never
    touches another source or root. All listing and deletion goes through the
    repository. Returns the number of removed artwork rows.
    """

    present = {tuple(_split_unit(unit)) for unit in present_units}
    try:
        persisted = art_repo.list_scan_units(SOURCE, root_key)
    except Exception as exc:
        log(f"UMSA exodos artwork: cannot list existing units: {exc}",
            level='error')
        return 0

    obsolete = [
        unit for unit in persisted
        if classify(unit) and tuple(_split_unit(unit)) not in present
    ]
    if not obsolete:
        return 0

    try:
        removed = art_repo.delete_scan_units(SOURCE, root_key, obsolete)
    except Exception as exc:
        log(f"UMSA exodos artwork: cannot remove obsolete units: {exc}",
            level='error')
        return 0
    log(f"UMSA exodos artwork: removed {removed} artwork rows of "
        f"{len(obsolete)} obsolete unit(s)", level='info')
    return removed


# -- image phase -----------------------------------------------------------

def _scan_images(exodos_path, exodos_sets, art_repo, root_key,
                 report_progress, is_cancelled):
    """Index the ``Images/MS-DOS`` tree in one pass.

    Returns ``{'units', 'rows', 'errors', 'aborted'}``.
    """

    result = {'units': 0, 'rows': 0, 'errors': 0, 'aborted': False}
    images_root = os.path.join(exodos_path, *IMAGES_SUBDIR)
    report_progress(None, 'scan all exodos art...')

    inventory = _walk_inventory(images_root, is_cancelled)
    if not inventory.exists:
        log("UMSA exodos artwork: no Images/MS-DOS tree, skipping image scan",
            level='debug')
        return result
    if inventory.cancelled:
        result['aborted'] = True
        return result
    if not inventory.complete:
        # A partial inventory is not a valid empty result: nothing is replaced
        # and nothing is cleaned up, so the previous artwork survives.
        result['errors'] += 1
        log("UMSA exodos artwork: incomplete image inventory, keeping "
            "existing image artwork", level='error')
        return result

    def record_error(scan_unit, exc):
        result['errors'] += 1
        log(f"UMSA exodos artwork: unit '{scan_unit}' failed: {exc}",
            level='error')
        try:
            art_repo.set_scan_unit_error(SOURCE, root_key, scan_unit, str(exc))
        except Exception as status_exc:
            log(f"UMSA exodos artwork: could not record error for unit "
                f"'{scan_unit}': {status_exc}", level='error')

    # Every recognized category that exists (even an empty directory) is an
    # observed unit, so its stale rows are cleared by the normal replacement.
    observed = set()
    for directory in inventory.dirs:
        category = _first_component(os.path.relpath(directory, images_root))
        if category in exodos_type_convert:
            observed.add(category)
    for path in inventory.files:
        if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS:
            category = _first_component(os.path.relpath(path, images_root))
            if category in exodos_type_convert:
                observed.add(category)

    image_units = {category: [] for category in observed}
    failed_units = set()

    # Hash the title screenshots once, from the same inventory, so mislabelled
    # Box - Front covers can be dropped without a second traversal.
    title_hashes = set()
    hashes = {}
    titles_complete = True
    title_files = [
        path for path in inventory.files
        if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS
        and _first_component(os.path.relpath(path, images_root)) == TITLE_CATEGORY
    ]
    maxno = len(title_files)
    report_progress(None, 'scan md5sum for titles...')
    for count, path in enumerate(title_files, 1):
        if is_cancelled():
            result['aborted'] = True
            return result
        try:
            digest = md5sum(path)
            hashes[path] = digest
            title_hashes.add(digest)
        except Exception as exc:
            titles_complete = False
            result['errors'] += 1
            log(f"UMSA exodos artwork: cannot hash title screenshot "
                f"'{path}': {exc}", level='error')
        report_progress(int(count / maxno * 100) if maxno else 100, None)

    if not titles_complete:
        log("UMSA exodos artwork: title screenshots incomplete, keeping "
            "existing image artwork", level='error')
        return result

    maxno = len(inventory.files)
    for count, path in enumerate(inventory.files, 1):
        if is_cancelled():
            result['aborted'] = True
            return result
        extension = os.path.splitext(path)[1].lower()
        if extension not in IMAGE_EXTENSIONS:
            continue
        category = _first_component(os.path.relpath(path, images_root))
        if category not in exodos_type_convert or category in failed_units:
            continue
        basename = os.path.basename(path)
        pic_fullname = os.path.splitext(basename)[0]
        pic_name, _separator, _pic_no = pic_fullname.rpartition('-')
        if _normalize_name(pic_name) not in exodos_sets:
            continue
        try:
            if category == BOX_FRONT_CATEGORY:
                digest = hashes.get(path)
                if digest is None:
                    digest = md5sum(path)
                    hashes[path] = digest
                if digest in title_hashes:
                    continue
            image_units[category].append(
                (exodos_sets[_normalize_name(pic_name)], SOURCE, root_key,
                 category, exodos_type_convert[category], extension[1:],
                 os.path.relpath(path, exodos_path) if exodos_path else path,
                 None)
            )
        except Exception as exc:
            # Do not publish a partially collected unit: keep its previous
            # artwork and report the failure.
            failed_units.add(category)
            image_units.pop(category, None)
            record_error(category, exc)
        report_progress(int(count / maxno * 100) if maxno else 100, None)

    if result['aborted']:
        return result

    for category, rows in image_units.items():
        if category in failed_units:
            continue
        try:
            art_repo.replace_scan_unit(SOURCE, root_key, category, rows)
            result['units'] += 1
            result['rows'] += len(rows)
        except Exception as exc:
            failed_units.add(category)
            record_error(category, exc)

    # Cleanup only after a complete, successful, non-cancelled phase. A failed
    # unit is still "present" (it was seen), so it is never a cleanup candidate.
    if result['errors'] == 0 and not result['aborted']:
        _cleanup_obsolete_units(
            art_repo, root_key, set(image_units),
            lambda unit: unit in exodos_type_convert)

    return result


# -- videosnap phase -------------------------------------------------------

def _scan_videosnaps(exodos_path, exodos_sets, art_repo, root_key,
                     report_progress, is_cancelled):
    """Index the ``Content/GameData/eXoDOS`` archives in one pass.

    Returns ``{'units', 'rows', 'errors', 'aborted', 'unmatched'}``.
    """

    result = {
        'units': 0, 'rows': 0, 'errors': 0,
        'aborted': False, 'unmatched': 0,
    }
    gamedata_root = os.path.join(exodos_path, *GAMEDATA_SUBDIR)
    report_progress(None, 'scan GameData zips...')

    inventory = _walk_inventory(gamedata_root, is_cancelled)
    if not inventory.exists:
        log("UMSA exodos artwork: no Content/GameData/eXoDOS tree, skipping "
            "videosnap scan", level='debug')
        return result
    if inventory.cancelled:
        result['aborted'] = True
        return result
    if not inventory.complete:
        result['errors'] += 1
        log("UMSA exodos artwork: incomplete GameData inventory, keeping "
            "existing videosnaps", level='error')
        return result

    def record_error(scan_unit, exc):
        result['errors'] += 1
        log(f"UMSA exodos artwork: unit '{scan_unit}' failed: {exc}",
            level='error')
        try:
            art_repo.set_scan_unit_error(SOURCE, root_key, scan_unit, str(exc))
        except Exception as status_exc:
            log(f"UMSA exodos artwork: could not record error for unit "
                f"'{scan_unit}': {status_exc}", level='error')

    present_units = []
    maxno = len(inventory.files)
    for count, archive_path in enumerate(inventory.files, 1):
        if is_cancelled():
            result['aborted'] = True
            return result
        if not archive_path.lower().endswith('.zip'):
            continue

        # The scan unit of a videosnap is the GameData ZIP archive itself. Its
        # relative path is both the scan unit and the stored relative path.
        scan_unit = os.path.relpath(archive_path, exodos_path)
        # The archive exists, so it is present for cleanup even if unreadable.
        present_units.append(scan_unit)

        rows = []
        matched = _match_set_name(os.path.basename(archive_path), exodos_sets)
        if matched is None:
            result['unmatched'] += 1
            log(f"UMSA exodos artwork: archive "
                f"'{os.path.basename(archive_path)}' matched no set",
                level='warning')
        try:
            with ZipFile(archive_path, 'r') as archive:
                for entry in archive.namelist():
                    if entry.endswith('/'):
                        # Directory entry: never a videosnap.
                        continue
                    if posixpath.splitext(entry)[1].lower() != VIDEO_EXTENSION:
                        continue
                    if matched is None:
                        continue
                    rows.append(
                        (exodos_sets[matched], SOURCE, root_key, scan_unit,
                         VIDEOSNAP_TYPE, 'mp4', scan_unit, entry)
                    )
        except Exception as exc:
            # The archive could not be read completely: keep the previous
            # videosnaps for this unit and report the failure.
            record_error(scan_unit, exc)
            report_progress(int(count / maxno * 100) if maxno else 100, None)
            continue

        try:
            # The unit is always published, even with zero rows: an archive
            # without a mapped set is a valid, registered empty unit.
            art_repo.replace_scan_unit(SOURCE, root_key, scan_unit, rows)
            result['units'] += 1
            result['rows'] += len(rows)
        except Exception as exc:
            record_error(scan_unit, exc)
        report_progress(int(count / maxno * 100) if maxno else 100, None)

    if result['errors'] == 0 and not result['aborted']:
        _cleanup_obsolete_units(
            art_repo, root_key, present_units, _is_videosnap_unit)

    return result


# -- public entry point ----------------------------------------------------

def scan_exodos_artwork(exodos_path, exodos_sets, art_repo,
                        report_progress=None, is_cancelled=None):
    """Index eXoDOS images and GameData videosnaps through the repository.

    ``exodos_sets`` maps the normalized gamename to the set id. ``art_repo`` is
    the caller-owned
    :class:`umsa_core.artwork_repository.ArtworkRepository` instance and owns
    every ``art_set``/``art_scan_unit`` write. ``is_cancelled`` is an optional
    predicate; when it returns ``True`` the current phase stops without
    publishing a partial unit, without cleaning up and without touching the
    other phase.

    Returns ``{'units': int, 'rows': int, 'errors': int, 'aborted': bool,
    'unmatched': int}``.
    """

    if report_progress is None:
        report_progress = _noop_progress
    if is_cancelled is None:
        is_cancelled = _never_cancelled

    summary = {
        'units': 0, 'rows': 0, 'errors': 0,
        'aborted': False, 'unmatched': 0,
    }
    if not exodos_path:
        summary['aborted'] = True
        return summary

    root_key = root_key_for_path(exodos_path)

    image_result = _scan_images(
        exodos_path, exodos_sets, art_repo, root_key,
        report_progress, is_cancelled)
    summary['units'] += image_result['units']
    summary['rows'] += image_result['rows']
    summary['errors'] += image_result['errors']
    summary['aborted'] = summary['aborted'] or image_result['aborted']

    if not summary['aborted'] and not is_cancelled():
        video_result = _scan_videosnaps(
            exodos_path, exodos_sets, art_repo, root_key,
            report_progress, is_cancelled)
        summary['units'] += video_result['units']
        summary['rows'] += video_result['rows']
        summary['errors'] += video_result['errors']
        summary['unmatched'] += video_result['unmatched']
        summary['aborted'] = summary['aborted'] or video_result['aborted']

    return summary
