"""Temporary extraction of eXoDOS videosnaps stored in ZIP archives.

Kodi cannot play a member of a ZIP archive directly, so the selected
videosnap is extracted into the screensaver temp directory and removed
again when the screensaver ends. The extraction is cached per set and
archive member.
"""

import os
import uuid
import zipfile
from os import path
from zipfile import ZipFile

# Kodi temp directory of the screensaver
TEMP_DIR = 'special://temp/umsa_screensaver_videos'

# Chunk size used while copying the archive member
COPY_CHUNK_SIZE = 8192


def cache_key(set_id, archive_member):
    """Return the cache key of an extracted video."""

    return f"{set_id}:{archive_member}"


def is_archive_videosnap(art):
    """Return ``True`` when the artwork is a videosnap inside a ZIP archive.

    Only those videos have to be extracted, every other artwork is played
    from its resolved path.
    """

    return bool(
        art.get('source') == 'exodos'
        and art.get('type') == 'videosnaps'
        and art.get('archive_member')
        and art.get('relative_path'))


def extract_exodos_video(art, roots, cache, vfs, kodi):
    """Extract an eXoDOS videosnap from a ZIP archive to Kodi's temp dir.

    Args:
        art: Artwork metadata dict with source, relative_path,
            archive_member, id (set_id)
        roots: Mapping of source names to root paths
        cache: Dictionary of already extracted files, keyed by set and
            archive member
        vfs: The ``xbmcvfs`` module
        kodi: The ``xbmc`` module

    Returns:
        Extracted file path (str) or None if extraction failed or not
        applicable
    """
    # Only handle eXoDOS videosnaps stored in archives
    if art.get('source') != 'exodos':
        return None
    if art.get('type') != 'videosnaps':
        return None
    archive_member = art.get('archive_member')
    if not archive_member:
        return None
    relative_path = art.get('relative_path')
    if not relative_path:
        return None

    exodos_root = roots.get('exodos')
    if not exodos_root:
        kodi.log("UMSA SSaver: eXoDOS root not configured", kodi.LOGWARNING)
        return None

    # Resolve full archive path and validate it's inside the eXoDOS root
    archive_full = path.join(exodos_root, relative_path)
    try:
        archive_real = path.realpath(archive_full)
        exodos_real = path.realpath(exodos_root)
        if not archive_real.startswith(exodos_real + path.sep) and archive_real != exodos_real:
            kodi.log(f"UMSA SSaver: archive path outside eXoDOS root: {archive_full}", kodi.LOGERROR)
            return None
    except OSError:
        kodi.log(f"UMSA SSaver: cannot resolve archive path: {archive_full}", kodi.LOGERROR)
        return None

    # Validate archive_member: reject absolute paths and traversal components
    if path.isabs(archive_member) or '..' in archive_member.split('/'):
        kodi.log(f"UMSA SSaver: invalid archive member path: {archive_member}", kodi.LOGERROR)
        return None

    # Check if we already have a cached extraction for this set_id + member
    set_id = art.get('id')
    key = cache_key(set_id, archive_member)
    if key in cache:
        cached_path = cache[key]
        if vfs.exists(cached_path):
            kodi.log(f"UMSA SSaver: reusing cached extraction: {cached_path}", kodi.LOGDEBUG)
            return cached_path
        # Cached file was deleted externally, remove from cache
        del cache[key]

    # Generate unique temp filename in screensaver-specific subdirectory
    temp_dir = vfs.translatePath(TEMP_DIR)
    try:
        vfs.mkdirs(temp_dir)
    except OSError as error:
        kodi.log(f"UMSA SSaver: cannot create temp dir {temp_dir}: {error}", kodi.LOGERROR)
        return None

    # Use set_id and a UUID for uniqueness, preserve .mp4 extension
    temp_filename = f"exodos_{set_id}_{uuid.uuid4().hex}.mp4"
    temp_path = path.join(temp_dir, temp_filename)
    temp_partial = temp_path + '.part'

    # Extract the specific member from the ZIP
    try:
        with ZipFile(archive_real, 'r') as archive:
            # Verify member exists
            if archive_member not in archive.namelist():
                kodi.log(f"UMSA SSaver: member not found in archive: {archive_member}", kodi.LOGWARNING)
                return None
            # Extract to a temporary name first, then rename atomically
            with archive.open(archive_member) as source, open(temp_partial, 'wb') as dest:
                # Read in chunks to handle large files
                while True:
                    chunk = source.read(COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    dest.write(chunk)
            # Atomic rename
            os.rename(temp_partial, temp_path)
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as error:
        kodi.log(f"UMSA SSaver: failed to extract {archive_member} from {archive_real}: {error}", kodi.LOGERROR)
        # Clean up partial file if it exists
        try:
            if path.exists(temp_partial):
                os.remove(temp_partial)
        except OSError:
            pass
        return None

    # Track for cleanup
    cache[key] = temp_path
    kodi.log(f"UMSA SSaver: extracted eXoDOS video to {temp_path}", kodi.LOGDEBUG)
    return temp_path


def cleanup_temp_videos(cache, keep_keys=None, *, vfs, kodi):
    """Clean up temporary video files no longer needed.

    Args:
        cache: Dictionary of tracked temporary files
        keep_keys: Set of cache keys (set_id:member) to preserve. If None,
            cleans all temp files (used on screensaver shutdown).
        vfs: The ``xbmcvfs`` module
        kodi: The ``xbmc`` module
    """
    if keep_keys is None:
        keep_keys = set()

    for key, temp_path in list(cache.items()):
        if key in keep_keys:
            continue
        try:
            if vfs.exists(temp_path):
                vfs.delete(temp_path)
                kodi.log(f"UMSA SSaver: cleaned up temp video: {temp_path}", kodi.LOGDEBUG)
        except OSError as error:
            kodi.log(f"UMSA SSaver: failed to delete temp video {temp_path}: {error}", kodi.LOGWARNING)
        finally:
            # Always remove from tracking dict
            cache.pop(key, None)
