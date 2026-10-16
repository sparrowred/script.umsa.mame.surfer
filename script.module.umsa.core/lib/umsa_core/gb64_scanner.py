"""GameBase64 support-file scanner.

This module owns the GameBase64 import algorithm: it loads the ``gb64_*`` set
mapping from ``umsa.db`` once, inventories the ``Extras/Cover`` and
``Screenshots`` directory trees once each, reads every ``Games/<set>.zip``
``VERSION.NFO`` at most once, and writes the resulting DAT metadata and
artwork through :mod:`umsa_core.dat_repository` and
:mod:`umsa_core.artwork_repository`.

The scanner never imports or touches ``DBMod`` and owns its own short-lived
worker connections. All SQL lives in the repositories; the scanner only
coordinates them. Each game archive is one scan unit (``Games/<set>.zip``), so
a failure mid-scan leaves everything already processed committed, preserves the
previous records for the failed unit, and keeps it retryable.

The legacy screenshot unit (``Screenshots``) is retired only after a completely
successful scan (no errors, no cancellation, no incomplete discovery); until
then its records are preserved.
"""

from __future__ import annotations

import os
import stat as stat_module
from zipfile import ZipFile

from .artwork import root_key_for_path
from .artwork_repository import ArtworkRepository, create_artwork_tables
from .dat_repository import ORIGIN_GB64, DatRepository, create_dat_tables
from .gb64_parser import parse_cover_filename, parse_version_nfo
from .logging import log
from .sqlite import connect_sqlite

SOURCE = "gb64"
DAT_FILE = "GameBase64"
COVER_UNIT = "Extras/Cover"
SCREENSHOT_DIR = "Screenshots"
LEGACY_SCREENSHOT_UNIT = "Screenshots"
GAMES_DIR = "Games"


class GB64Scanner:
    """Import GameBase64 metadata and artwork into the UMSA databases.

    Args:
        db_paths: Resolved Core data paths (needs ``umsa_db``, ``dat_db`` and
            ``artwork_db``).
        initialize_dat: Optional callable taking the DAT DB cursor; must ensure
            the ``dat``/``dat_set`` schema exists. Defaults to the repository's
            authoritative schema helper.
        initialize_art: Optional callable taking the artwork DB cursor; must
            ensure the ``art_set``/``art_scan_unit`` schema exists. Defaults to
            the repository's authoritative schema helper.
        progress: Optional ``progress(percent, what)`` callback. Either value
            may be ``None`` to leave it unchanged.
        is_cancelled: Optional predicate returning ``True`` when the host wants
            the scan to stop.
        listdir: Optional directory listing callable (defaults to
            ``os.listdir``).
        isfile: Optional file predicate callable (defaults to
            ``os.path.isfile``).
        open_zip: Optional archive opener (defaults to ``zipfile.ZipFile``),
            used once per archive.
    """

    def __init__(self, db_paths, initialize_dat=None, initialize_art=None,
                 progress=None, is_cancelled=None, listdir=None, isfile=None,
                 open_zip=None):
        self._db_paths = db_paths
        self._initialize_dat = initialize_dat
        self._initialize_art = initialize_art
        self._progress = progress
        self._is_cancelled = is_cancelled or (lambda: False)
        self._listdir = listdir or os.listdir
        self._isfile = isfile or os.path.isfile
        self._open_zip = open_zip or ZipFile

    # -- callbacks -------------------------------------------------------

    def _report(self, percent=None, what=None):
        """Forward a progress update to the host, if a callback was given."""

        if self._progress is not None:
            self._progress(percent, what)

    def _cancelled(self, cancel_event):
        """Return ``True`` when the host or the cancel event requested a stop."""

        if cancel_event is not None and cancel_event.is_set():
            return True
        try:
            return bool(self._is_cancelled())
        except Exception:
            return False

    # -- discovery helpers ----------------------------------------------

    def _walk_files(self, base_dir):
        """Inventory every file under ``base_dir`` recursively.

        Returns ``(paths, complete)`` where ``paths`` are sorted relative paths
        using forward slashes. ``complete`` is ``False`` when any directory or
        entry could not be inspected, so a failure is never mistaken for an
        empty directory. A genuinely missing ``base_dir`` is a complete, empty
        inventory (a missing directory hides no files).
        """

        files = []
        complete = True
        stack = [('', base_dir)]
        while stack:
            rel_dir, abs_dir = stack.pop()
            try:
                entries = list(self._listdir(abs_dir))
            except FileNotFoundError:
                continue
            except OSError as exc:
                log(f"UMSA gb64 scan: cannot list '{abs_dir}': {exc}",
                    level='error')
                complete = False
                continue
            for name in entries:
                child_rel = f"{rel_dir}/{name}" if rel_dir else name
                child_abs = os.path.join(abs_dir, name)
                try:
                    mode = os.stat(child_abs).st_mode
                except OSError as exc:
                    log(f"UMSA gb64 scan: cannot stat '{child_abs}': {exc}",
                        level='warning')
                    complete = False
                    continue
                if stat_module.S_ISDIR(mode):
                    stack.append((child_rel, child_abs))
                else:
                    files.append(child_rel)
        files.sort()
        return files, complete

    def _load_mappings(self):
        """Load ``{set name: id}`` and ``{title: id}`` for the gb64 sets.

        Titles keep the first id seen, matching the historical behaviour. The
        connection is opened and closed here so nothing is held open while the
        filesystem is traversed.
        """

        umsa_db = self._db_paths.umsa_db
        if not os.path.isfile(umsa_db):
            raise FileNotFoundError(f"UMSA database not found: {umsa_db}")

        gdb = connect_sqlite(umsa_db)
        try:
            cursor = gdb.cursor()
            try:
                cursor.execute(
                    "SELECT sets.id, sets.name, sets.gamename "
                    "FROM sets JOIN swl ON sets.swllink_id = swl.id "
                    "WHERE swl.name LIKE 'gb64_%'"
                )
                gb64_sets = {}
                gb64_name = {}
                for set_id, name, gamename in cursor.fetchall():
                    gb64_sets[name] = set_id
                    if gamename not in gb64_name:
                        gb64_name[gamename] = set_id
                return gb64_sets, gb64_name
            finally:
                cursor.close()
        finally:
            gdb.close()

    @staticmethod
    def _normalize_screenshot_ref(ref):
        """Normalise a ``Screenshot:`` value to a path relative to Screenshots.

        Backslashes become slashes, surrounding whitespace is stripped, a
        leading ``Screenshots/`` is dropped (so it is not prefixed twice) and
        absolute or parent-traversing references are rejected (returning
        ``''``), because a malicious or malformed NFO must never escape the
        artwork root.
        """

        if not ref:
            return ''
        raw = ref.replace('\\', '/').strip()
        if not raw:
            return ''
        if raw.startswith('/') or (len(raw) >= 2 and raw[1] == ':'):
            log(f"UMSA gb64 scan: rejecting absolute screenshot reference "
                f"'{ref}'", level='warning')
            return ''
        parts = [p for p in raw.split('/') if p not in ('', '.')]
        if any(p == '..' for p in parts):
            log(f"UMSA gb64 scan: rejecting traversing screenshot reference "
                f"'{ref}'", level='warning')
            return ''
        if parts and parts[0] == SCREENSHOT_DIR:
            parts = parts[1:]
        if not parts:
            return ''
        return '/'.join(parts)

    @staticmethod
    def _extension_of(path):
        """Return the extension of ``path`` without the leading dot."""

        ext = os.path.splitext(path)[1]
        return ext[1:] if ext.startswith('.') else ext

    def _screenshot_rows(self, set_id, root_key, unit, ref, screenshots):
        """Build the artwork rows for one game from its screenshot reference.

        Only references actually present in the (successfully enumerated)
        ``screenshots`` inventory produce a row, so a genuinely missing
        screenshot creates no record. The title image is the ``_1`` sibling of
        the snap in the same directory, computed with ``splitext`` so it works
        for any extension.
        """

        rows = []
        normalized = self._normalize_screenshot_ref(ref)
        if not normalized:
            return rows

        extension = self._extension_of(normalized)
        if normalized in screenshots:
            rows.append((
                set_id, SOURCE, root_key, unit, 'snap', extension,
                f"{SCREENSHOT_DIR}/{normalized}", None,
            ))

        snap_dir, snap_base = os.path.split(normalized)
        stem, snap_ext = os.path.splitext(snap_base)
        title_name = f"{stem}_1{snap_ext}"
        title_ref = f"{snap_dir}/{title_name}" if snap_dir else title_name
        if title_ref in screenshots:
            rows.append((
                set_id, SOURCE, root_key, unit, 'titles',
                self._extension_of(title_ref),
                f"{SCREENSHOT_DIR}/{title_ref}", None,
            ))
        return rows

    # -- scan ------------------------------------------------------------

    def scan(self, gb64_root, cancel_event=None):
        """Scan a GameBase64 installation.

        ``gb64_root`` is the configured GameBase64 directory (the one that
        contains ``Games``, ``Extras`` and ``Screenshots``). Returns a summary
        whose keys are ``sets``, ``processed``, ``zips``, ``dat``, ``artwork``,
        ``covers``, ``missing``, ``errors``, ``cancelled``, ``aborted``,
        ``discovery_incomplete`` and ``legacy_cleaned``.

        A missing/unreadable root or an unloadable UMSA mapping aborts before
        anything is written. A failed archive preserves its previous DAT and
        artwork and is left retryable; a missing archive is skipped with a
        warning. The legacy ``Screenshots`` unit is removed only when the whole
        scan completed without errors, cancellation or incomplete discovery.
        """

        summary = {
            'sets': 0,
            'processed': 0,
            'zips': 0,
            'dat': 0,
            'artwork': 0,
            'covers': 0,
            'missing': 0,
            'errors': 0,
            'cancelled': False,
            'aborted': False,
            'discovery_incomplete': False,
            'legacy_cleaned': 0,
        }

        if not gb64_root:
            log("UMSA gb64 scan: no GameBase64 root configured", level='error')
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        root = os.path.abspath(gb64_root)
        if not os.path.isdir(root):
            log(f"UMSA gb64 scan: root '{root}' is not a directory",
                level='error')
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        root_key = root_key_for_path(root)

        try:
            gb64_sets, gb64_name = self._load_mappings()
        except Exception as exc:
            log(f"UMSA gb64 scan: cannot load gb64 set mapping: {exc}",
                level='error')
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        # Inventory both directory trees once, before any database write, so
        # the filesystem is each traversed a single time.
        self._report(0, 'reading covers...')
        cover_files, covers_complete = self._walk_files(
            os.path.join(root, 'Extras', 'Cover'))
        screenshot_files, screenshots_complete = self._walk_files(
            os.path.join(root, SCREENSHOT_DIR))
        screenshots = set(screenshot_files)
        if not covers_complete or not screenshots_complete:
            summary['discovery_incomplete'] = True

        cover_rows = []
        if covers_complete:
            for rel in cover_files:
                parsed = parse_cover_filename(os.path.basename(rel))
                if parsed is None:
                    continue
                title, art_type, extension = parsed
                set_id = gb64_name.get(title)
                if set_id is None:
                    continue
                cover_rows.append((
                    set_id, SOURCE, root_key, COVER_UNIT, art_type,
                    extension, f"{COVER_UNIT}/{rel}", None,
                ))
        else:
            log("UMSA gb64 scan: cover tree could not be fully listed; "
                "existing covers preserved", level='error')

        dat_conn = None
        art_conn = None
        try:
            dat_conn = connect_sqlite(self._db_paths.dat_db)
            self._init_dat_schema(dat_conn)
            art_conn = connect_sqlite(self._db_paths.artwork_db)
            self._init_art_schema(art_conn)

            dat_repo = DatRepository(dat_conn)
            art_repo = ArtworkRepository(art_conn)

            if covers_complete:
                try:
                    art_repo.replace_scan_unit(
                        SOURCE, root_key, COVER_UNIT, cover_rows)
                    summary['covers'] = len(cover_rows)
                except Exception as exc:
                    log(f"UMSA gb64 scan: could not write covers: {exc}",
                        level='error')
                    summary['errors'] += 1
                    try:
                        art_repo.set_scan_unit_error(
                            SOURCE, root_key, COVER_UNIT, str(exc))
                    except Exception:
                        pass

            self._report(0, 'reading info files from zips...')
            setnames = sorted(gb64_sets)
            total = len(setnames)
            summary['sets'] = total
            for index, setname in enumerate(setnames):
                if self._cancelled(cancel_event):
                    summary['cancelled'] = True
                    log("UMSA gb64 scan: cancelled before archive")
                    break
                self._report(
                    int((index + 1) / total * 100) if total else 100, None)

                zip_path = os.path.join(root, GAMES_DIR, setname + '.zip')
                if not self._isfile(zip_path):
                    log(f"UMSA gb64 scan: zip not found {zip_path}",
                        level='warning')
                    summary['missing'] += 1
                    continue

                set_id = gb64_sets[setname]
                unit = f"{GAMES_DIR}/{setname}.zip"

                try:
                    with self._open_zip(zip_path) as archive:
                        raw = archive.read('VERSION.NFO')
                    nfo = parse_version_nfo(raw.decode('utf-8', 'ignore'))
                except Exception as exc:
                    log(f"UMSA gb64 scan: cannot read '{zip_path}': {exc}",
                        level='error')
                    summary['errors'] += 1
                    # Mark the unit errored so a corrupt archive is visible and
                    # stays retryable; its previous DAT/artwork is untouched.
                    self._record_unit_error(art_repo, root_key, unit, exc)
                    continue

                summary['zips'] += 1

                try:
                    art_repo.set_scan_unit_running(SOURCE, root_key, unit)
                except Exception as exc:
                    log(f"UMSA gb64 scan: could not mark unit '{unit}' running: "
                        f"{exc}", level='warning')

                # Write the DAT metadata first; it is authoritative and comes
                # from the archive itself. Only if it succeeds do we touch the
                # artwork, so a failed metadata write never replaces artwork.
                try:
                    dat_repo.replace_origin_for_set(
                        ORIGIN_GB64, set_id, DAT_FILE, nfo.entry)
                    summary['dat'] += 1
                except Exception as exc:
                    log(f"UMSA gb64 scan: could not store metadata for "
                        f"'{setname}': {exc}", level='error')
                    summary['errors'] += 1
                    self._record_unit_error(art_repo, root_key, unit, exc)
                    continue

                if not screenshots_complete:
                    # The screenshot tree could not be fully enumerated, so a
                    # missing reference cannot be trusted; keep the previous
                    # artwork and leave the unit not-done for a later retry.
                    log(f"UMSA gb64 scan: screenshot tree incomplete, keeping "
                        f"artwork for '{unit}'", level='warning')
                    continue

                rows = self._screenshot_rows(
                    set_id, root_key, unit, nfo.screenshot, screenshots)
                try:
                    art_repo.replace_scan_unit(SOURCE, root_key, unit, rows)
                    summary['artwork'] += 1
                    summary['processed'] += 1
                except Exception as exc:
                    log(f"UMSA gb64 scan: could not store artwork for '{unit}': "
                        f"{exc}", level='error')
                    summary['errors'] += 1
                    self._record_unit_error(art_repo, root_key, unit, exc)

            # Retire the legacy 'Screenshots' unit only after a fully
            # successful scan. A cleanup failure is logged and retried on the
            # next run without failing the scan.
            if (not summary['cancelled'] and not summary['aborted']
                    and not summary['discovery_incomplete']
                    and summary['errors'] == 0):
                try:
                    summary['legacy_cleaned'] = art_repo.delete_scan_unit(
                        SOURCE, root_key, LEGACY_SCREENSHOT_UNIT)
                except Exception as exc:
                    log(f"UMSA gb64 scan: could not retire legacy screenshot "
                        f"unit: {exc}", level='error')
                    summary['errors'] += 1
        finally:
            if art_conn is not None:
                try:
                    art_conn.close()
                except Exception:
                    pass
            if dat_conn is not None:
                try:
                    dat_conn.close()
                except Exception:
                    pass

        self._report(100, 'gamebase64 finished!')
        log(f"UMSA gb64 scan: finished sets={summary['sets']} "
            f"processed={summary['processed']} zips={summary['zips']} "
            f"dat={summary['dat']} artwork={summary['artwork']} "
            f"covers={summary['covers']} missing={summary['missing']} "
            f"errors={summary['errors']} cancelled={summary['cancelled']} "
            f"aborted={summary['aborted']} "
            f"discovery_incomplete={summary['discovery_incomplete']} "
            f"legacy_cleaned={summary['legacy_cleaned']}")
        return summary

    # -- schema helpers --------------------------------------------------

    def _init_dat_schema(self, conn):
        """Ensure the DAT schema exists on ``conn`` (committed separately)."""

        cursor = conn.cursor()
        try:
            if self._initialize_dat is not None:
                self._initialize_dat(cursor)
            else:
                create_dat_tables(cursor)
        finally:
            cursor.close()
        conn.commit()

    def _init_art_schema(self, conn):
        """Ensure the artwork schema exists on ``conn`` (committed separately)."""

        cursor = conn.cursor()
        try:
            if self._initialize_art is not None:
                self._initialize_art(cursor)
            else:
                create_artwork_tables(cursor)
        finally:
            cursor.close()
        conn.commit()

    @staticmethod
    def _record_unit_error(art_repo, root_key, unit, exc):
        """Best-effort: mark a unit errored without hiding the original failure."""

        try:
            art_repo.set_scan_unit_error(SOURCE, root_key, unit, str(exc))
        except Exception as status_exc:
            log(f"UMSA gb64 scan: could not record error status for '{unit}': "
                f"{status_exc}", level='error')
