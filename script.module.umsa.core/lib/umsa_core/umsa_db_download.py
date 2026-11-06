"""UMSA database download helper.

This module provides the UMSA database download and extraction functionality.
It is Kodi-free and uses only standard library dependencies.

The archive is downloaded into memory, only its ``umsa.db`` member is extracted
into a temporary file next to the live database, checked with
``PRAGMA integrity_check`` and then moved into place with ``os.replace``. An
interrupted or broken download therefore never touches the existing
``umsa.db``, and the archive can not overwrite any other file in the profile
directory (for example ``status.db``).
"""

import os
import shutil
import sqlite3
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

UMSA_DB_URL = "http://umsa.info/umsa_db.zip"
UMSA_DB_NAME = "umsa.db"
CHUNK_SIZE = 102400


class UmsaDbDownloadError(RuntimeError):
    """The UMSA database could not be downloaded or validated."""


def _content_length(response):
    """Return the announced size in bytes, or ``None`` when unknown."""

    try:
        value = int(response.info()['Content-Length'])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def _download(progress, title):
    """Read the whole archive; stop on an empty read instead of looping."""

    data = bytearray()
    with urlopen(UMSA_DB_URL, timeout=10) as response:
        size = _content_length(response)
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            data.extend(chunk)
            if size:
                progress(min(int(len(data) / size * 99), 99), title, None)
    if size and len(data) < size:
        raise UmsaDbDownloadError(
            f"download incomplete: got {len(data)} of {size} bytes")
    if not data:
        raise UmsaDbDownloadError("download returned no data")
    return data


def _extract_db(data, target):
    """Write the ``umsa.db`` member of the archive ``data`` to ``target``."""

    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            try:
                member = archive.getinfo(UMSA_DB_NAME)
            except KeyError as error:
                raise UmsaDbDownloadError(
                    f"archive does not contain {UMSA_DB_NAME}") from error
            with archive.open(member) as source, open(target, 'wb') as dest:
                shutil.copyfileobj(source, dest)
    except zipfile.BadZipFile as error:
        raise UmsaDbDownloadError(f"invalid archive: {error}") from error


def _check_integrity(path):
    """Raise when ``path`` is not an intact SQLite database."""

    try:
        connection = sqlite3.connect(os.fspath(path))
        try:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        raise UmsaDbDownloadError(
            f"downloaded {UMSA_DB_NAME} is not a valid database: {error}"
        ) from error
    if rows != [('ok',)]:
        raise UmsaDbDownloadError(
            f"downloaded {UMSA_DB_NAME} failed integrity check: {rows[:3]}")


def download_and_update_umsa_db(data_dir, progress, title='Updating UMSA database'):
    """Download the UMSA database archive and replace ``data_dir/umsa.db``.

    ``progress`` is called as ``progress(percent, title, message)``; ``message``
    is ``None`` for the plain percentage updates during download (only sent
    when the server announces a ``Content-Length``).

    Raises ``UmsaDbDownloadError`` when the download is incomplete, the archive
    is broken or lacks ``umsa.db``, or the database fails its integrity check;
    network errors (``OSError``) propagate unchanged. In every error case the
    existing ``umsa.db`` stays untouched.
    """

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    data = _download(progress, title)

    progress(99, title, 'unzip file...')
    fd, tmp_name = tempfile.mkstemp(
        prefix=f'.{UMSA_DB_NAME}.', suffix='.part', dir=data_dir)
    os.close(fd)
    tmp_db = Path(tmp_name)
    try:
        _extract_db(data, tmp_db)
        _check_integrity(tmp_db)
        os.replace(tmp_db, data_dir / UMSA_DB_NAME)
    finally:
        if tmp_db.exists():
            tmp_db.unlink()
