"""Temporary extraction of eXoDOS videosnaps stored in ZIP archives.

Kodi cannot play a member of a ZIP archive directly, so the selected
videosnap is extracted into the screensaver temp directory and removed
again when the video ends or when the screensaver ends.

Every extraction gets its own file name: there is no cache of already
extracted videos, so a file is never reused and never deleted while it is
still queued for playback.
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

# Prefix of every extracted file of the screensaver
TEMP_FILE_PREFIX = 'umsa_video_'

# Suffix of a not completely extracted file
PART_SUFFIX = '.part'


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


def temp_dir(vfs):
    """Return the translated path of the screensaver temp directory."""

    return vfs.translatePath(TEMP_DIR)


def is_in_temp_dir(file_path, vfs):
    """Return whether the path belongs to the screensaver temp directory.

    Only files of the add-on specific directory may be deleted by the
    screensaver, everything else belongs to the user.
    """

    if not file_path:
        return False
    try:
        directory = temp_dir(vfs)
    except (AttributeError, RuntimeError, TypeError):
        return False
    try:
        return path.dirname(path.abspath(file_path)) == path.abspath(directory)
    except (OSError, ValueError):
        return False


def extract_exodos_video(art, roots, vfs, kodi):
    """Extract an eXoDOS videosnap from a ZIP archive to Kodi's temp dir.

    Args:
        art: Artwork metadata dict with source, relative_path,
            archive_member, id (set_id)
        roots: Mapping of source names to root paths
        vfs: The ``xbmcvfs`` module
        kodi: The ``xbmc`` module

    Returns:
        Extracted file path (str) or None if extraction failed or not
        applicable. Every call extracts a new file: an already extracted
        video is never reused.
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

    # Validate relative_path: must be relative, no absolute paths or traversal
    if path.isabs(relative_path):
        kodi.log(f"UMSA SSaver: absolute relative_path rejected: {relative_path}", kodi.LOGERROR)
        return None
    if '..' in relative_path.split(path.sep) or (path.altsep and '..' in relative_path.split(path.altsep)):
        kodi.log(f"UMSA SSaver: traversal in relative_path rejected: {relative_path}", kodi.LOGERROR)
        return None

    # Normalize paths for lexical containment check
    archive_full = path.join(exodos_root, relative_path)
    try:
        exodos_norm = path.normpath(path.abspath(exodos_root))
        archive_norm = path.normpath(path.abspath(archive_full))
        # Verify archive_norm is inside exodos_norm using commonpath
        if path.commonpath([archive_norm, exodos_norm]) != exodos_norm:
            kodi.log(f"UMSA SSaver: archive path outside eXoDOS root: {archive_full}", kodi.LOGERROR)
            return None
    except (OSError, ValueError):
        kodi.log(f"UMSA SSaver: cannot validate archive path: {archive_full}", kodi.LOGERROR)
        return None

    # Validate archive_member: reject absolute paths and traversal components
    if path.isabs(archive_member) or '..' in archive_member.split('/'):
        kodi.log(f"UMSA SSaver: invalid archive member path: {archive_member}", kodi.LOGERROR)
        return None

    # Generate a unique temp filename in the screensaver specific directory
    directory = temp_dir(vfs)
    try:
        vfs.mkdirs(directory)
    except OSError as error:
        kodi.log(f"UMSA SSaver: cannot create temp dir {directory}: {error}", kodi.LOGERROR)
        return None

    extension = art.get('extension') or 'mp4'
    temp_filename = f"{TEMP_FILE_PREFIX}{uuid.uuid4().hex}.{extension}"
    temp_path = path.join(directory, temp_filename)
    temp_partial = temp_path + PART_SUFFIX

    # Extract the specific member from the ZIP
    # Use archive_full (validated path) - OS will follow symlinks naturally
    try:
        with ZipFile(archive_full, 'r') as archive:
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
        kodi.log(f"UMSA SSaver: failed to extract {archive_member} from {archive_full}: {error}", kodi.LOGERROR)
        # Clean up partial file if it exists
        try:
            if path.exists(temp_partial):
                os.remove(temp_partial)
        except OSError:
            pass
        return None

    kodi.log(f"UMSA SSaver: extracted eXoDOS video to {temp_path}", kodi.LOGDEBUG)
    return temp_path


def delete_temp_file(file_path, vfs, kodi):
    """Delete one extracted video of the screensaver temp directory.

    Returns ``True`` when the file is gone afterwards. A failed deletion
    is logged as an error; the file is left in place so a later cleanup
    can try again.
    """

    if not file_path:
        return True
    if not is_in_temp_dir(file_path, vfs):
        kodi.log(
            f"UMSA SSaver: not deleting {file_path}, it is outside the screensaver temp directory",
            kodi.LOGWARNING)
        return False
    try:
        if not vfs.exists(file_path):
            return True
    except (OSError, RuntimeError) as error:
        kodi.log(f"UMSA SSaver: cannot check temp video {file_path}: {error}", kodi.LOGERROR)
        return False
    try:
        deleted = vfs.delete(file_path)
    except (OSError, RuntimeError) as error:
        kodi.log(f"UMSA SSaver: failed to delete temp video {file_path}: {error}", kodi.LOGERROR)
        return False
    if not deleted:
        kodi.log(f"UMSA SSaver: failed to delete temp video {file_path}", kodi.LOGERROR)
        return False
    kodi.log(f"UMSA SSaver: cleaned up temp video: {file_path}", kodi.LOGDEBUG)
    return True


def cleanup_temp_dir(vfs, kodi):
    """Remove the files of the screensaver temp directory.

    The directory is inspected directly - no cache is used as an
    inventory - and only the files of the add-on specific directory are
    removed: incomplete ``.part`` files of a failed extraction as well as
    the extracted videos. Sub directories are never touched and the
    directory itself is kept.

    Returns the list of files that could not be deleted.
    """

    directory = temp_dir(vfs)
    try:
        if not vfs.exists(directory):
            return []
    except (OSError, RuntimeError) as error:
        kodi.log(f"UMSA SSaver: cannot check temp dir {directory}: {error}", kodi.LOGERROR)
        return []

    try:
        _dirs, files = vfs.listdir(directory)
    except (OSError, RuntimeError) as error:
        kodi.log(f"UMSA SSaver: cannot list temp dir {directory}: {error}", kodi.LOGERROR)
        return []

    failed = []
    for name in files:
        full_path = path.join(directory, name)
        if not delete_temp_file(full_path, vfs, kodi):
            failed.append(full_path)
    if failed:
        kodi.log(
            f"UMSA SSaver: {len(failed)} temp file(s) could not be deleted",
            kodi.LOGWARNING)
    return failed
