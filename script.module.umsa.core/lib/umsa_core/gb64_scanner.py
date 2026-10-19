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
successful scan (no missing archives, no errors, no cancellation, no incomplete
discovery); until then its records are preserved.
"""

from __future__ import annotations

import os
import sqlite3
import stat as stat_module
from zipfile import ZipFile

from .artwork import root_key_for_path
from .artwork_repository import ArtworkRepository, create_artwork_tables
from .dat_repository import ORIGIN_GB64, DatRepository, create_dat_tables
from .gb64_parser import parse_cover_filename, parse_version_nfo
from .logging import log
from .scan_coordinator import ScanBusyError, ScanLockContext, scan_coordinator
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
        using forward slashes. ``complete`` is ``False`` when the base directory
        itself is missing or when any directory or entry could not be
        inspected, so a missing or unreadable tree is never mistaken for a
        successfully empty one (which could otherwise delete valid artwork). A
        genuinely empty but readable directory is still ``complete``.
        """

        files = []
        complete = True
        stack = [('', base_dir)]
        while stack:
            rel_dir, abs_dir = stack.pop()
            try:
                entries = list(self._listdir(abs_dir))
            except FileNotFoundError as exc:
                # A missing required tree (or a child that vanished after it
                # was discovered) is incomplete, not an empty success.
                log(f"UMSA gb64 scan: directory missing '{abs_dir}': {exc}",
                    level='error')
                complete = False
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

        Titles keep the first id seen, matching the historical behaviour. Rows
        with an unusable (NULL/empty) set name are skipped, so an all-unusable
        result comes back empty and the caller aborts instead of scanning junk.
        The connection is opened and closed here so nothing is held open while
        the filesystem is traversed.
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
                    if not name:
                        # An unusable row (NULL/empty set name) cannot resolve
                        # to an archive; skip it so a mapping made only of such
                        # rows is rejected below instead of scanning junk.
                        continue
                    gb64_sets[name] = set_id
                    if gamename not in gb64_name:
                        gb64_name[gamename] = set_id
                return gb64_sets, gb64_name
            finally:
                cursor.close()
        finally:
            gdb.close()

    @staticmethod
    def _normalize_screenshot_ref(ref) -> tuple:
        """Classify a ``Screenshot:`` value and normalise it when usable.

        Returns ``(state, path)`` where ``state`` is one of:

        * ``'absent'``  -- no reference was given (a valid empty result); the
          returned ``path`` is ``''``.
        * ``'valid'``   -- a safe relative reference; ``path`` is relative to
          the ``Screenshots`` directory (backslashes normalised, surrounding
          whitespace stripped and a leading ``Screenshots/`` dropped so it is
          not prefixed twice).
        * ``'invalid'`` -- a non-empty unsafe reference (absolute or
          parent-traversing); the returned ``path`` is the original value for
          diagnostics. A malicious or malformed NFO must never escape the
          artwork root, and must not be silently turned into an empty success.
        """

        if not ref:
            return 'absent', ''
        raw = ref.replace('\\', '/').strip()
        if not raw:
            return 'absent', ''
        if raw.startswith('/') or (len(raw) >= 2 and raw[1] == ':'):
            log(f"UMSA gb64 scan: rejecting absolute screenshot reference "
                f"'{ref}'", level='warning')
            return 'invalid', ref
        parts = [p for p in raw.split('/') if p not in ('', '.')]
        if any(p == '..' for p in parts):
            log(f"UMSA gb64 scan: rejecting traversing screenshot reference "
                f"'{ref}'", level='warning')
            return 'invalid', ref
        if parts and parts[0] == SCREENSHOT_DIR:
            parts = parts[1:]
        if not parts:
            # A degenerate reference (e.g. just "Screenshots/") carries no
            # file; treat it the same as an absent reference.
            return 'absent', ''
        return 'valid', '/'.join(parts)

    @staticmethod
    def _extension_of(path):
        """Return the extension of ``path`` without the leading dot."""

        ext = os.path.splitext(path)[1]
        return ext.removeprefix('.')

    def _screenshot_rows(self, set_id, root_key, unit, normalized, screenshots):
        """Build the artwork rows for one game from its normalised reference.

        ``normalized`` is the already-validated path relative to ``Screenshots``
        (empty for an absent reference). Only references actually present in the
        (successfully enumerated) ``screenshots`` inventory produce a row, so a
        genuinely missing screenshot creates no record. The title image is the
        ``_1`` sibling of the snap in the same directory, computed with
        ``splitext`` so it works for any extension.
        """

        rows = []
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
        """Scan a GameBase64 installation under the shared scan lock.

        This public entry point owns the process-wide scan lock for the whole
        combined metadata/artwork workflow. When another covered scan is
        already running it returns immediately with ``busy`` set and leaves all
        data untouched.
        """

        busy_summary = {
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
            'busy': True,
        }

        try:
            lock_ctx = ScanLockContext(scan_coordinator)
            lock_ctx.__enter__()
        except ScanBusyError:
            log("UMSA gb64 scan: rejected, another scan is already running",
                level='warning')
            return busy_summary

        try:
            result = self._scan_locked(gb64_root, cancel_event)
            result['busy'] = False
            return result
        finally:
            lock_ctx.__exit__(None, None, None)

    def _scan_locked(self, gb64_root, cancel_event=None):
        """Scan a GameBase64 installation.

        ``gb64_root`` is the configured GameBase64 directory (the one that
        contains ``Games``, ``Extras`` and ``Screenshots``). Returns a summary
        whose keys are ``sets``, ``processed``, ``zips``, ``dat``, ``artwork``,
        ``covers``, ``missing``, ``errors``, ``cancelled``, ``aborted``,
        ``discovery_incomplete`` and ``legacy_cleaned``.

        A missing/unreadable root, an unloadable UMSA mapping or an empty
        GameBase64 set mapping (including one made only of unusable rows)
        aborts before anything is written. A failed archive preserves its
        previous DAT and artwork and is left retryable; a missing archive is
        skipped with a warning and counted in ``missing``. An invalid
        screenshot reference is a per-archive error that preserves the previous
        artwork. A failed required-root discovery sets ``discovery_incomplete``
        and increments ``errors`` once per failed root, so an incomplete scan
        never reports zero errors. The legacy ``Screenshots`` unit is removed
        only when the whole scan completed with no missing archives, no errors,
        no cancellation, no abort and no incomplete discovery.
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

        # An empty mapping means there is nothing to import; treat it as an
        # aborted scan rather than a successful empty one so existing DAT and
        # artwork records are preserved and no cleanup is attempted.
        if not gb64_sets:
            log("UMSA gb64 scan: no GameBase64 sets in the UMSA mapping; "
                "aborting without changes", level='error')
            summary['aborted'] = True
            summary['errors'] += 1
            return summary

        # Inventory both directory trees once, before any database write, so
        # the filesystem is each traversed a single time. Both roots are
        # required: an explicit check validates them before traversal so a
        # missing root can never be mistaken for an empty success. Each failed
        # root is counted once here (not once per affected unit) so the summary
        # reports the discovery failure without double-counting it.
        self._report(0, 'reading covers...')
        cover_dir = os.path.join(root, 'Extras', 'Cover')
        if os.path.isdir(cover_dir):
            cover_files, covers_complete = self._walk_files(cover_dir)
        else:
            log(f"UMSA gb64 scan: required directory '{cover_dir}' is "
                "missing or unreadable", level='error')
            cover_files, covers_complete = [], False
        screenshot_dir = os.path.join(root, SCREENSHOT_DIR)
        if os.path.isdir(screenshot_dir):
            screenshot_files, screenshots_complete = self._walk_files(
                screenshot_dir)
        else:
            log(f"UMSA gb64 scan: required directory '{screenshot_dir}' is "
                "missing or unreadable", level='error')
            screenshot_files, screenshots_complete = [], False
        screenshots = set(screenshot_files)
        if not covers_complete or not screenshots_complete:
            summary['discovery_incomplete'] = True
        if not covers_complete:
            summary['errors'] += 1
        if not screenshots_complete:
            summary['errors'] += 1

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
            dat_conn = connect_sqlite(
                self._db_paths.dat_db, row_factory=sqlite3.Row)
            self._init_dat_schema(dat_conn)
            art_conn = connect_sqlite(
                self._db_paths.artwork_db, row_factory=sqlite3.Row)
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
                    self._record_unit_error(art_repo, root_key, COVER_UNIT, exc)

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

                # Classify the screenshot reference. An invalid (absolute or
                # parent-traversing) reference is a per-archive error: keep the
                # previous artwork, mark the unit errored (not done) and leave
                # it retryable. The DAT metadata written above is unaffected.
                ref_state, normalized_ref = self._normalize_screenshot_ref(
                    nfo.screenshot)
                if ref_state == 'invalid':
                    log(f"UMSA gb64 scan: invalid screenshot reference for "
                        f"'{setname}': {nfo.screenshot}", level='error')
                    summary['errors'] += 1
                    self._record_unit_error(
                        art_repo, root_key, unit,
                        f"invalid screenshot reference: {nfo.screenshot}")
                    continue

                if not screenshots_complete:
                    # The screenshot tree could not be fully enumerated, so a
                    # missing reference cannot be trusted; keep the previous
                    # artwork and mark the unit errored (not done) so a later
                    # retry reprocesses it. The DAT metadata above is kept.
                    # The discovery failure itself was already counted once in
                    # summary['errors'] when the root was walked, so no
                    # per-archive error count is raised here.
                    log(f"UMSA gb64 scan: screenshot tree incomplete, keeping "
                        f"artwork for '{unit}'", level='warning')
                    self._record_unit_error(
                        art_repo, root_key, unit, "screenshot tree incomplete")
                    continue

                rows = self._screenshot_rows(
                    set_id, root_key, unit, normalized_ref, screenshots)
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
            # successful scan: every expected archive present (no missing), no
            # errors, no cancellation, no incomplete discovery and no abort. A
            # missing archive means the replacement data is incomplete, so the
            # legacy records are preserved until a later fully successful scan.
            # A cleanup failure is logged and retried on the next run without
            # failing the scan.
            if (not summary['cancelled'] and not summary['aborted']
                    and not summary['discovery_incomplete']
                    and summary['errors'] == 0
                    and summary['missing'] == 0):
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
