"""Database update and support file scans of the UMSA frontend.

The heavy work is done by the Core helpers; this module drives the progress
dialogs and the database re-connect.
"""

import os

import xbmc
import xbmcgui
from umsa_core.database import (
    DBMod,
    download_and_update_umsa_db,
    run_scan_with_progress,
)


def update(gui, what, core_data_paths):
    """Update UMSA database, artwork or support files"""

    settings_folder = core_data_paths.filters_dir

    # update umsa.db
    if what == 'db':

        progress_dialog = xbmcgui.DialogProgress()
        progress_dialog.create('Updating UMSA database', 'downloading zip...')
        # close db before update (keep status.db open for the re-connect)
        if gui.ggdb:
            gui.ggdb.close_umsa_db()

        def progress(percent, title, message):
            if message is None:
                progress_dialog.update(percent)
            else:
                progress_dialog.update(percent, message)

        download_and_update_umsa_db(core_data_paths.data_dir, progress)

        # re-connect to db
        if gui.ggdb:
            progress_dialog.update(100, 'reopening database...')
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

    # scan support files / eXoDOS / GameBase64 / artwork
    elif what in ('dat', 'exo', 'gb64', 'art'):
        gui.setFocus(gui.getControl(gui.main_focus))

        titles = {
            'dat': 'Scan support files',
            'exo': 'Scan eXoDOS files',
            'gb64': 'Scan GameBase64 files',
            'art': 'Scan artwork folders',
        }
        title = titles[what]
        gui.progress_dialog.create(title, 'warm up')

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

        scan_result = run_scan_with_progress(
            gui.ggdb, scan_method, scan_args, progress, title, xbmc.sleep)

        if isinstance(scan_result, dict) and scan_result.get('busy'):
            gui.progress_dialog.close()
            gui.dialog.notification(
                'Scan Status', 'another scan is already running...',
                xbmcgui.NOTIFICATION_ERROR, 4000)
            return

        # Scanner workflows now write directly to the authoritative source databases
        # (artwork.db, dat.db). No post-scan synchronization copy is needed.
        try:
            gui.progress_dialog.close()
        except Exception as error:
            xbmc.log(
                f'UMSA gui: could not close scan progress dialog: {error}',
                xbmc.LOGWARNING)
