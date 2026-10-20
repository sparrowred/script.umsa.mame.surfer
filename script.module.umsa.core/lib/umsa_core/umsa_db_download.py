"""UMSA database download helper.

This module provides the UMSA database download and extraction functionality.
It is Kodi-free and uses only standard library dependencies.
"""

from io import BytesIO
from pathlib import Path
from urllib.request import urlopen
import zipfile


def download_and_update_umsa_db(data_dir, progress, title='Updating UMSA database'):
    """Download and extract the UMSA database archive into ``data_dir``.

    ``progress`` is called as ``progress(percent, title, message)``; ``message``
    is ``None`` for the plain percentage updates during download.
    """

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    db_zip = bytearray()
    url = urlopen("http://umsa.info/umsa_db.zip", timeout=10)
    # float with *1.0 for percentage
    db_zip_size = int(url.info()['Content-Length']) * 1.0
    while len(db_zip) < db_zip_size:
        db_zip.extend(url.read(102400))
        progress(int((len(db_zip) / db_zip_size) * 99), title, None)

    progress(99, title, 'unzip file...')
    zipfile.ZipFile(BytesIO(db_zip)).extractall(data_dir)