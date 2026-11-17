"""Scan entry points and the shared state of the one active scan.

``Scans`` runs the DAT, artwork, eXoDOS and GameBase64 scanners; each opens
its own connections. ``ScanState`` holds the progress (``percent``, ``what``)
and the stop signal every scanner polls (``running``).
"""

from __future__ import annotations

from contextlib import contextmanager

from .artwork_repository import create_artwork_tables
from .artwork_scanner import ArtworkScanner
from .dat_repository import create_dat_tables
from .dat_scanner import DatScanner
from .exodos_scanner import ExodosScanner
from .gb64_scanner import GB64Scanner
from .scan_coordinator import ScanBusyError, ScanLockContext, scan_coordinator


class ScanState:
    """Progress and stop signal of the one active scan.

    ``running`` is ``True`` only while the owner of the scan lock runs a scan
    that nobody asked to stop; every scanner polls ``is_cancelled``.
    """

    def __init__(self):
        self.percent = 0
        self.what = 'nothing'
        self.running = False

    def report(self, percent=None, what=None):
        """Progress callback of the scanners; ``None`` keeps a value."""

        if percent is not None:
            self.percent = percent
        if what is not None:
            self.what = what

    def is_cancelled(self):
        return not self.running

    def request_stop(self):
        self.running = False

    @contextmanager
    def own(self, start_what):
        """Own the state fields for one scan; yield whether the scan lock was taken.

        The process-wide scan lock is taken *before* any field is touched.
        When another scan owns it, the context yields ``False`` and leaves the
        fields alone, so a competing call can neither overwrite the active
        scan's progress nor cancel it. ``running`` is cleared on exit. The
        lock is re-entrant per thread.
        """

        lock_ctx = ScanLockContext(scan_coordinator)
        try:
            lock_ctx.__enter__()
        except ScanBusyError:
            yield False
            return

        try:
            self.percent = 0
            self.what = start_what
            self.running = True
            try:
                yield True
            finally:
                self.running = False
        finally:
            lock_ctx.__exit__(None, None, None)


class Scans:
    """The scan entry points of the GUI.

    Every method returns the scanner's summary dictionary; a scan that finds
    another one running returns the scanner's ``busy`` summary and leaves
    ``state`` alone.

    Args:
        db_paths: Resolved :class:`~umsa_core.data_paths.CoreDataPaths`.
        nonmame: Getter of the ``{'exodos', 'gb64', 'whdload'}`` roots
            (``SharedSettings.nonmame``); asked on every scan, so changed
            settings apply to the next one.
    """

    def __init__(self, db_paths, nonmame=lambda: None):
        self.db_paths = db_paths
        self._nonmame = nonmame
        self.state = ScanState()

    def _root(self, key):
        """Return the configured root of collection ``key``, or ``''``."""
        roots = self._nonmame() or {}
        return roots.get(key, '')

    def dats(self, datdir):
        """Read all MAME DAT files of ``datdir`` (see :meth:`DatScanner.scan`)."""

        with self.state.own('files'):
            return DatScanner(
                self.db_paths,
                initialize_tables=create_dat_tables,
                progress=self.state.report,
                is_cancelled=self.state.is_cancelled,
            ).scan(datdir)

    def artwork(self, paths, listdir=None, source=None, cancel_event=None,
                only_types=None, resume=True):
        """Scan artwork folders, resumable (:meth:`ArtworkScanner.scan`)."""

        with self.state.own('discovering'):
            return ArtworkScanner(
                self.db_paths,
                create_artwork_tables,
                progress=self.state.report,
                is_cancelled=self.state.is_cancelled,
                listdir=listdir,
            ).scan(
                paths,
                source=source,
                only_types=only_types,
                resume=resume,
                cancel_event=cancel_event,
            )

    def exodos(self):
        """Read the eXoDOS metadata and artwork of the configured folder."""

        with self.state.own('reading MS-DOS.xml from zip'):
            return ExodosScanner(
                self.db_paths,
                initialize_dat=create_dat_tables,
                initialize_art=create_artwork_tables,
                progress=self.state.report,
                is_cancelled=self.state.is_cancelled,
            ).scan(self._root('exodos'))

    def gb64(self):
        """Read the GameBase64 metadata and artwork of the configured folder."""

        with self.state.own('reading covers...'):
            return GB64Scanner(
                self.db_paths,
                initialize_dat=create_dat_tables,
                initialize_art=create_artwork_tables,
                progress=self.state.report,
                is_cancelled=self.state.is_cancelled,
            ).scan(self._root('gb64'))
