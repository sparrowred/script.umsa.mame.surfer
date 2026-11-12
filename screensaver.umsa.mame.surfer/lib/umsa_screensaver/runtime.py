"""Kodi runtime and lifecycle for the standalone screensaver add-on."""

import xbmc
import xbmcgui
from umsa_core import set_log
from umsa_core.database import DBMod
from umsa_core.default_filter import DEFAULT_FILTER_NAME
from umsa_core.screensaver_request import decode_request
from umsa_core_kodi import (
    get_core_data_paths,
    get_core_settings,
    is_emulator_running,
    send_software_open,
    set_screensaver_manual,
)

from . import strings as S
from .availability import REASON_NO_VIDEOS, AvailabilityError, plan_request
from .constants import (
    MODE_PROPERTY,
    RUNNING_PROPERTY,
    WINDOW_ID,
)
from .strings import tr
from .ui import Monitor


class ScreensaverRuntime:
    """Own screensaver settings, Core database access, and run lifecycle."""

    def __init__(self):
        self.ggdb = None
        self.monitor = None
        self.settings_folder = None
        self.nonmame = {}

    def _nonmame_roots(self):
        """Return the configured non-MAME roots for artwork path resolution."""

        settings = get_core_settings()
        nonmame = settings.nonmame
        self.nonmame = nonmame
        return nonmame

    def open_software(self, software_id):
        """Hand the currently displayed software back to the Games frontend.

        Reuses the running frontend over Kodi notifications. When no
        frontend is running the notification has no receiver and nothing
        opens, which is the intended limitation.
        """

        try:
            software_id = int(software_id)
        except (TypeError, ValueError):
            xbmc.log(
                f"UMSA Screensaver: invalid software id: {software_id!r}",
                xbmc.LOGWARNING,
            )
            return

        xbmc.log(
            f"UMSA Screensaver: reusing running GUI for software {software_id}",
            xbmc.LOGDEBUG,
        )
        send_software_open(software_id)

    def run_automatic(self):
        """Start an automatically selected configured screensaver mode."""

        self._run()

    def run_script(self, arguments):
        """Start the requested screensaver mode after validating its payload."""

        try:
            request = decode_request(arguments)
        except ValueError as error:
            xbmc.log(f"UMSA Screensaver: invalid launch request: {error}", xbmc.LOGERROR)
            return
        self._run(request)

    def _run(self, request=None):
        window = xbmcgui.Window(WINDOW_ID)
        if window.getProperty(RUNNING_PROPERTY):
            xbmc.log("UMSA Screensaver: another screensaver instance is active", xbmc.LOGWARNING)
            return
        # Prevent screensaver from starting while an external emulator is running
        if is_emulator_running():
            xbmc.log("UMSA saver: emulator running, not starting", xbmc.LOGINFO)
            return

        # Activate manual inhibition for explicit (script) invocations only
        manual = request is not None
        if manual:
            set_screensaver_manual(True)

        window.setProperty(RUNNING_PROPERTY, "true")
        window.setProperty(MODE_PROPERTY, "starting")
        try:
            set_log(lambda *args, level="debug": xbmc.log(
                " ".join(map(str, args)),
                {
                    "debug": xbmc.LOGDEBUG,
                    "info": xbmc.LOGINFO,
                    "warning": xbmc.LOGWARNING,
                    "error": xbmc.LOGERROR,
                }.get(level, xbmc.LOGDEBUG),
            ))
            self.core_data_paths = get_core_data_paths(create=True)
            self.settings_folder = self.core_data_paths.data_dir
            if not self.core_data_paths.umsa_db.is_file():
                xbmc.log(
                    "UMSA Screensaver: UMSA database is missing from the Core data directory",
                    xbmc.LOGWARNING,
                )
                return

            self.ggdb = DBMod(self.settings_folder, self._nonmame_roots())
            # random artwork follows the default filter (created on first start)
            self.ggdb.ensure_default_filter()
            self.ggdb.define_filter(self.ggdb.load_filter_selections(DEFAULT_FILTER_NAME))
            self.ggdb.set_filter_enabled(True)
            if request is not None and request["art_types"] is not None:
                available_art_types = set(self.ggdb.get_art_types())
                unknown_art_types = set(request["art_types"]) - available_art_types
                if unknown_art_types:
                    xbmc.log(
                        "UMSA Screensaver: ignoring request with unknown artwork types",
                        xbmc.LOGERROR,
                    )
                    return
            self.monitor = Monitor(itself=self)
            if request is None:
                self.monitor.startme()
            else:
                self._start_request(request, window, self.monitor)
        finally:
            # Kodi may close the saver window without Saver.close():
            # the overlay must not stay behind
            if self.monitor is not None:
                self.monitor.saver.close_overlay()
                # never leave Kodi muted by the screensaver videos
                self.monitor.saver.restore_video_sound()
            # Clear the manual inhibition of explicit invocations and of an
            # instance that kept running after Kodi woke it
            inhibited = self.monitor is not None and getattr(
                self.monitor, 'inhibits_kodi_screensaver', False)
            if manual or inhibited:
                set_screensaver_manual(False)
            try:
                if self.ggdb is not None:
                    self.ggdb.close()
            finally:
                window.clearProperty(MODE_PROPERTY)
                window.clearProperty(RUNNING_PROPERTY)

    def _start_request(self, request, window, monitor):
        """Start the explicitly requested screensaver mode.

        The requested mode is only started when the artwork database holds
        something to show for it. The video mode falls back to an artwork
        mode, every other mode is not replaced: without artwork the
        screensaver does not start at all.
        """

        saver = monitor.saver
        configured = list(saver.settings.get('type') or [])
        try:
            plan = plan_request(
                self.ggdb,
                request["mode"],
                request["art_types"],
                configured=configured)
        except AvailabilityError as error:
            xbmc.log(
                f"UMSA Screensaver: artwork check failed: {error}",
                xbmc.LOGERROR)
            saver.notify_user(tr(S.ARTWORK_CHECK_FAILED))
            return
        if not plan.ok:
            monitor.report_no_content(plan)
            return
        if plan.reason == REASON_NO_VIDEOS:
            xbmc.log(
                "UMSA Screensaver: no videosnap available, "
                f"using the {plan.mode} mode instead",
                xbmc.LOGWARNING)
            saver.notify_user(tr(S.NO_VIDEOS))
        # the artwork types of the request only belong to the requested
        # mode: a fallback mode uses its own artwork types
        saver.running = plan.mode
        saver.art_types = request["art_types"] if plan.mode == request["mode"] else None
        window.setProperty(MODE_PROPERTY, saver.running)
        saver.doModal()
