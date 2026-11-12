"""Database update and support file scans of the UMSA frontend.

The heavy work is done by the Core helpers; this module drives the progress
dialogs and the database re-connect.
"""

import os

import xbmc
import xbmcgui
from umsa_core import ShutdownRequested
from umsa_core.database import DBMod, download_and_update_umsa_db
from umsa_core.scan_progress import run_scan_with_progress
from umsa_core.umsa_db_download import UmsaDbDownloadError

from . import strings as S
from .strings import tr


class _DownloadCancelled(Exception):
    """The user pressed cancel in the download progress dialog."""


def _cancel_pressed(progress_dialog):
    """Return whether the cancel button of ``progress_dialog`` was pressed."""

    try:
        return bool(progress_dialog.iscanceled())
    except Exception:  # noqa: BLE001 - a closed dialog counts as not cancelled
        return False


def update(gui, what, core_data_paths):
    """Update UMSA database, artwork or support files

    For ``what == 'db'`` it returns True when the new umsa.db is open and False
    when the download failed or was cancelled. In that case the previous
    umsa.db (left untouched by the Core download) is reopened if there was one;
    on a first start ``gui.ggdb`` stays None.
    """

    settings_folder = core_data_paths.filters_dir

    # update umsa.db
    if what == 'db':

        progress_dialog = xbmcgui.DialogProgress()
        progress_dialog.create(tr(S.DB_UPDATING), tr(S.DB_DOWNLOADING))
        # close db before update (keep status.db open for the re-connect)
        if gui.ggdb:
            gui.ggdb.close_umsa_db()

        def progress(percent, title, message):
            if progress_dialog.iscanceled():
                raise _DownloadCancelled()
            if message is None:
                progress_dialog.update(percent)
            else:
                progress_dialog.update(percent, message)

        try:
            download_and_update_umsa_db(core_data_paths.data_dir, progress)
        except _DownloadCancelled:
            xbmc.log("UMSA gui: update: umsa.db download cancelled", xbmc.LOGINFO)
            failure = (tr(S.DB_DOWNLOAD_CANCELLED), xbmcgui.NOTIFICATION_INFO)
        except (UmsaDbDownloadError, OSError) as exc:
            xbmc.log(f"UMSA gui: update: umsa.db download failed: {exc}", xbmc.LOGERROR)
            failure = (tr(S.DB_DOWNLOAD_FAILED, exc), xbmcgui.NOTIFICATION_ERROR)
        else:
            failure = None

        if failure:
            progress_dialog.close()
            # the old umsa.db is unchanged, reopen it
            if gui.ggdb:
                gui.ggdb.open_db(settings_folder)
            gui.dialog.notification(tr(S.DB_TITLE), failure[0], failure[1], 5000)
            return False

        # re-connect to db
        if gui.ggdb:
            progress_dialog.update(100, tr(S.DB_REOPENING))
            gui.ggdb.open_db(settings_folder)
        # first run
        else:
            gui.ggdb = DBMod(
                settings_folder,
                gui.nonmame,
                gui.filter_lists,
                gui.pref_country,
            )

        progress_dialog.close()
        return True

    # scan support files / eXoDOS / GameBase64 / artwork
    elif what in ('dat', 'exo', 'gb64', 'art'):
        gui.setFocus(gui.getControl(gui.main_focus))

        titles = {
            'dat': S.SCAN_TITLE_DATS,
            'exo': S.SCAN_TITLE_EXODOS,
            'gb64': S.SCAN_TITLE_GB64,
            'art': S.SCAN_TITLE_ARTWORK,
        }
        title = tr(titles[what])
        gui.progress_dialog.create(title, tr(S.SCAN_WARM_UP))

        scans = {
            'dat': ('scan_dats', (gui.datdir, settings_folder)),
            'exo': ('scan_exodos_to_db', ('', settings_folder)),
            'gb64': ('scan_gb64_to_db', ('', settings_folder)),
            'art': (
                'scan_artwork',
                ([gui.progettosnaps, gui.own_artwork], settings_folder, os.listdir)
            ),
        }
        scan_method, scan_args = scans[what]

        def progress(percent, title, message):
            gui.progress_dialog.update(percent, title, message)

        try:
            scan_result = run_scan_with_progress(
                gui.ggdb, scan_method, scan_args, progress, title, xbmc.sleep,
                wait=getattr(gui, 'abort_wait', None),
                is_cancelled=lambda: _cancel_pressed(gui.progress_dialog))
        except ShutdownRequested:
            xbmc.log(f"UMSA gui: update: Kodi shuts down, {what} scan stopped", xbmc.LOGWARNING)
            try:
                gui.progress_dialog.close()
            except Exception as error:  # noqa: BLE001 - a dialog failure must not block the shutdown
                xbmc.log(
                    f'UMSA gui: could not close scan progress dialog: {error}',
                    xbmc.LOGWARNING)
            gui.exit()
            return

        if isinstance(scan_result, dict) and scan_result.get('busy'):
            gui.progress_dialog.close()
            gui.dialog.notification(
                tr(S.SCAN_STATUS), tr(S.SCAN_OTHER_RUNNING),
                xbmcgui.NOTIFICATION_ERROR, 4000)
            return

        cancelled = _cancel_pressed(gui.progress_dialog)
        # Scanner workflows now write directly to the authoritative source databases
        # (artwork.db, dat.db). No post-scan synchronization copy is needed.
        try:
            gui.progress_dialog.close()
        except Exception as error:
            xbmc.log(
                f'UMSA gui: could not close scan progress dialog: {error}',
                xbmc.LOGWARNING)
        if cancelled:
            xbmc.log(f"UMSA gui: update: {what} scan cancelled by the user", xbmc.LOGINFO)
            gui.dialog.notification(
                tr(S.SCAN_STATUS), tr(S.SCAN_CANCELLED),
                xbmcgui.NOTIFICATION_INFO, 4000)
