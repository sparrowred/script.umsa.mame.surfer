"""ROM cache in the temp folder: extracted sets and copies of ROM zips and CHDs.

Copies are laid out like a MAME rompath and made only while the setting
``rom_cache`` is on. A cache entry only exists once it is complete. MAME,
MARP replays and the eXoDOS launcher never use the cache.
"""

import os
import shutil
from contextlib import contextmanager
from time import monotonic

from umsa_core import log
from umsa_core.abort import ShutdownRequested, resolve_wait

COPY_BLOCK_SIZE = 1024 * 1024
# Seconds between two progress updates / abort checks of a running copy.
COPY_PROGRESS_INTERVAL = 0.25
PART_SUFFIX = '.part'
# Folder of the copies without the Batocera layout.
ARCHIVE_ROOT = 'roms'
# Batocera system folder of everything the mapping does not know.
DEFAULT_SYSTEM = os.path.join('mame', 'roms')


class CacheCopyCancelled(Exception):
    """Raised when the user cancels a running copy into the cache."""


class CacheLayout:
    """Folders of the ROM cache below the ROM temp folder.

    ``batocera`` (setting ``batocera_layout``) sorts the entries into
    Batocera-style system folders; ``batomame`` maps a MAME driver source
    (arcade) or ``<softwarelist>.xml`` to its system folder.
    """

    def __init__(self, temp_dir, batocera=False, batomame=None):
        self.temp_dir = temp_dir
        self.batocera = bool(batocera)
        self.batomame = batomame or {}

    def system_dir(self, swl_name, source=None):
        """Return the Batocera system folder of a software list or arcade driver."""

        key = source if swl_name == 'mame' else f'{swl_name}.xml'
        return self.batomame.get(key) or DEFAULT_SYSTEM

    def extract_dir(self, swl_name, set_name, source=None):
        """Return the folder of an extracted set."""

        entry = f'{swl_name}_{set_name}'
        if not self.batocera:
            return os.path.join(self.temp_dir, entry)
        return os.path.join(self.temp_dir, self.system_dir(swl_name, source), entry)

    def archive_path(self, swl_name, set_name, filename, source=None, chd=False):
        """Return the path of the cached copy of a ROM zip (or of a CHD of the set)."""

        if not self.batocera:
            base = os.path.join(self.temp_dir, ARCHIVE_ROOT, swl_name)
        elif swl_name == 'mame':
            base = os.path.join(self.temp_dir, self.system_dir(swl_name, source))
        else:
            base = os.path.join(
                self.temp_dir, self.system_dir(swl_name, source), swl_name)
        if chd:
            base = os.path.join(base, set_name)
        return os.path.join(base, os.path.basename(filename))


@contextmanager
def staged_dir(folder):
    """Fill a new cache folder so that it only ever exists completely.

    Yields ``folder + '.part'`` (a leftover of a killed run is removed
    first) and renames it to ``folder`` when the block ends normally. Any
    exception - also a cancel or a shutdown request - removes the staging
    folder, so "the folder exists" always means "the content is complete".
    """

    staging = folder + PART_SUFFIX
    if os.path.lexists(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    try:
        yield staging
        os.rename(staging, folder)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def is_cached(src, dst):
    """Return whether ``dst`` is a complete, current copy of ``src``."""

    try:
        source, copy = os.stat(src), os.stat(dst)
    except OSError:
        return False
    # copystat keeps the mtime; file systems round it differently.
    return source.st_size == copy.st_size and abs(source.st_mtime - copy.st_mtime) < 2


def _remove_part(part):
    """Remove a partial copy; a failure is only logged."""
    try:
        os.remove(part)
    except FileNotFoundError:
        pass
    except OSError as error:
        log(f'UMSA cache: could not remove partial copy {part}: {error}',
            level='warning')


def copy_to_cache(src, dst, dialog=None, wait=None):
    """Copy ``src`` to ``dst`` unless a current copy exists; return ``dst``.

    The data goes to ``dst + '.part'`` and is renamed when complete, so a
    file under its final name is never half written. ``dialog`` shows the
    progress and can cancel (``CacheCopyCancelled``); ``wait``
    (:data:`umsa_core.abort.Wait`) stops the copy when the host shuts down
    (``ShutdownRequested``). Both remove the partial copy.
    """

    if is_cached(src, dst):
        log(f'UMSA cache: hit {dst}', level='debug')
        return dst

    wait = resolve_wait(wait, None)
    name = os.path.basename(src)
    total = os.path.getsize(src)
    part = dst + PART_SUFFIX
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    log(f'UMSA cache: copying {src} -> {dst} ({total} bytes)', level='debug')
    copied = 0
    last_check = monotonic()
    try:
        with open(src, 'rb') as source, open(part, 'wb') as target:
            while True:
                block = source.read(COPY_BLOCK_SIZE)
                if not block:
                    break
                target.write(block)
                copied += len(block)
                now = monotonic()
                if now - last_check < COPY_PROGRESS_INTERVAL:
                    continue
                last_check = now
                if dialog:
                    percent = int(copied * 100 / total) if total else 100
                    dialog.update(percent, f'caching {name}: {percent}%')
                    if dialog.iscanceled():
                        raise CacheCopyCancelled(f'copy of {name} cancelled')
                # 1 ms: only asks for the abort request.
                if wait(1):
                    raise ShutdownRequested('shutdown during cache copy')
        shutil.copystat(src, part)
        os.replace(part, dst)
    except BaseException:
        _remove_part(part)
        raise
    return dst


def cache_archives(emurun, layout, dialog=None, wait=None):
    """Copy the found ROM zip and CHDs into the cache and start from there.

    ``emurun['zips']`` / ``emurun['chds']`` get the cached paths, so the
    later steps use the cache without knowing about it; the original paths
    go to ``source_zips`` / ``source_chds``. Raises like
    :func:`copy_to_cache`.
    """

    swl_name = emurun['swl_name']
    set_name = emurun['set_name']
    source = emurun.get('source')
    zips = list(emurun.get('zips') or [])
    chds = list(emurun.get('chds') or [])
    emurun['source_zips'] = list(zips)
    emurun['source_chds'] = list(chds)

    if zips and zips[0]:
        zips[0] = copy_to_cache(
            zips[0], layout.archive_path(swl_name, set_name, zips[0], source),
            dialog, wait)
    for index, chd in enumerate(chds):
        if chd:
            chds[index] = copy_to_cache(
                chd,
                layout.archive_path(swl_name, set_name, chd, source, chd=True),
                dialog, wait)
    emurun['zips'] = zips
    emurun['chds'] = chds
