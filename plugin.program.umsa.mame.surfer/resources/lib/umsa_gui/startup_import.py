"""Startup of the UMSA frontend: legacy import and history handling.

The legacy import itself already ran when the database was opened; this module
only drives the import/cleanup and the user notification. The in-memory
history is owned by the frontend and persisted in ``status.db``.
"""

import os

import xbmc
import xbmcgui


def run_startup_import(gui):
    """Run the one-time legacy import and report its outcome.

    The migration itself already ran at `DBMod` open; this only drives the
    import/cleanup and the user notification. A failure here never aborts
    startup: an unrecorded failure retries on the next start by design,
    and a recorded `failed` marker is only cleared by `retry_import`.
    """

    # Check if the import was already completed before this startup.
    # We only show the success notification if the import is newly performed.
    marker = gui.ggdb.get_import_marker()
    already_completed = marker is not None and marker.get("status") in (
        "completed", "completed_discards", "completed_no_source"
    )

    try:
        result = gui.ggdb.run_legacy_import()
    except Exception as exc:
        xbmc.log(f"UMSA gui: legacy import failed: {exc}", xbmc.LOGERROR)
        gui.dialog.notification(
            'UMSA migration',
            'Legacy data import failed, will retry on next start.',
            xbmcgui.NOTIFICATION_ERROR, 5000, False)
        return

    xbmc.log(f"UMSA gui: legacy import result: {result.status}")
    # Only show success/discard notifications if the import was newly performed.
    if not already_completed:
        if result.status == 'completed':
            gui.dialog.notification(
                'UMSA migration', 'History and filters migrated.',
                xbmcgui.NOTIFICATION_INFO, 4000, False)
        elif result.status == 'completed_discards':
            gui.dialog.notification(
                'UMSA migration',
                'Migrated, discarded: ' + ', '.join(result.discarded),
                xbmcgui.NOTIFICATION_WARNING, 6000, False)
        elif result.status == 'completed_no_source':
            gui.dialog.notification(
                'UMSA migration', 'Nothing to migrate.',
                xbmcgui.NOTIFICATION_INFO, 3000, False)
    elif result.status == 'completed_discards':
        # Previously completed but with new discards - still show the discard notification
        gui.dialog.notification(
            'UMSA migration',
            'Migrated, discarded: ' + ', '.join(result.discarded),
            xbmcgui.NOTIFICATION_WARNING, 6000, False)

    if result.status == 'failed':
        detail = result.error or 'unknown'
        if result.discarded:
            detail += ' (discarded: ' + ', '.join(result.discarded) + ')'
        gui.dialog.notification(
            'UMSA migration',
            f'Import failed: {detail} (use retry_import).',
            xbmcgui.NOTIFICATION_ERROR, 7000, False)
    if result.pending_cleanup:
        names = ', '.join(
            os.path.basename(path) for path in result.pending_cleanup
        )
        gui.dialog.notification(
            'UMSA migration',
            f'{len(result.pending_cleanup)} legacy file(s) not removed: '
            f'{names}.',
            xbmcgui.NOTIFICATION_WARNING, 5000, False)


def save_lastgames(gui):
    """Persist the current in-memory history without trimming it."""

    if gui.ggdb is not None:
        gui.ggdb.save_lastgames(gui.last)


def remember_and_select(gui, software_id):
    """Insert a display event, select it, and persist only on success.

    A failed display (empty `select_software`) must not leave a phantom
    entry: the in-memory insert is rolled back and nothing is persisted.
    Pointer semantics match the previous insert-and-advance callers.
    """

    gui.lastptr += 1
    gui.last.insert(gui.lastptr, software_id)
    if not gui.select_software(software_id):
        del gui.last[gui.lastptr]
        gui.lastptr -= 1
        return False
    # Cap in-memory history at 100 entries to match persistent storage limit.
    # Only applied after successful selection; failed selection fully rolls back.
    if len(gui.last) > 100:
        del gui.last[0]
        gui.lastptr -= 1
    gui._save_lastgames()
    return True
