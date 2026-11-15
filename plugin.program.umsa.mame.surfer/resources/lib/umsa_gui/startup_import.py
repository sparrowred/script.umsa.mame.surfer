"""Startup of the UMSA frontend: the one-time legacy import.

The legacy import itself already ran when the database was opened; this module
only drives the import/cleanup and the user notification.
"""

import os
from dataclasses import dataclass

import xbmc
import xbmcgui

from . import strings as S
from .strings import tr


@dataclass
class ImportCtx:
    """Database and dialog of the legacy import."""

    services: object = None


def run_startup_import(ctx):
    """Run the one-time legacy import and report its outcome.

    The migration itself already ran at `DBMod` open; this only drives the
    import/cleanup and the user notification. A failure here never aborts
    startup: an unrecorded failure retries on the next start by design,
    and a recorded `failed` marker is only cleared by `retry_import`.
    """

    # Check if the import was already completed before this startup.
    # We only show the success notification if the import is newly performed.
    marker = ctx.services.ggdb.history.get_import_marker()
    already_completed = marker is not None and marker.get("status") in (
        "completed", "completed_discards", "completed_no_source"
    )

    try:
        result = ctx.services.ggdb.run_legacy_import()
    except Exception as exc:
        xbmc.log(f"UMSA gui: legacy import failed: {exc}", xbmc.LOGERROR)
        ctx.services.dialog.notification(
            tr(S.IMPORT_TITLE), tr(S.IMPORT_FAILED_RETRY),
            xbmcgui.NOTIFICATION_ERROR, 5000, False)
        return

    xbmc.log(f"UMSA gui: legacy import result: {result.status}")
    # Only show success/discard notifications if the import was newly performed.
    if not already_completed:
        if result.status == 'completed':
            ctx.services.dialog.notification(
                tr(S.IMPORT_TITLE), tr(S.IMPORT_DONE),
                xbmcgui.NOTIFICATION_INFO, 4000, False)
        elif result.status == 'completed_discards':
            ctx.services.dialog.notification(
                tr(S.IMPORT_TITLE),
                tr(S.IMPORT_DISCARDED, ', '.join(result.discarded)),
                xbmcgui.NOTIFICATION_WARNING, 6000, False)
        elif result.status == 'completed_no_source':
            ctx.services.dialog.notification(
                tr(S.IMPORT_TITLE), tr(S.IMPORT_NOTHING),
                xbmcgui.NOTIFICATION_INFO, 3000, False)
    elif result.status == 'completed_discards':
        # Previously completed but with new discards - still show the discard notification
        ctx.services.dialog.notification(
            tr(S.IMPORT_TITLE),
            tr(S.IMPORT_DISCARDED, ', '.join(result.discarded)),
            xbmcgui.NOTIFICATION_WARNING, 6000, False)

    if result.status == 'failed':
        detail = result.error or tr(S.IMPORT_UNKNOWN_ERROR)
        if result.discarded:
            detail = tr(
                S.IMPORT_ERROR_DISCARDED, detail, ', '.join(result.discarded))
        ctx.services.dialog.notification(
            tr(S.IMPORT_TITLE), tr(S.IMPORT_FAILED, detail),
            xbmcgui.NOTIFICATION_ERROR, 7000, False)
    if result.pending_cleanup:
        names = ', '.join(
            os.path.basename(path) for path in result.pending_cleanup
        )
        ctx.services.dialog.notification(
            tr(S.IMPORT_TITLE),
            tr(S.IMPORT_NOT_REMOVED, len(result.pending_cleanup), names),
            xbmcgui.NOTIFICATION_WARNING, 5000, False)
