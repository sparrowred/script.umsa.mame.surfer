"""Kodi runtime and lifecycle for the standalone screensaver add-on."""

import xbmc
import xbmcgui
from umsa_core import set_log
from umsa_core.database import DBMod
from umsa_core_kodi import get_core_data_paths

from .arguments import decode_request
from .ui import Monitor

_RUNNING_PROPERTY = "UMSA.Screensaver.Running"
_MODE_PROPERTY = "UMSA.Screensaver.Mode"
_WINDOW_ID = 10000


class ScreensaverRuntime:
    """Own screensaver settings, Core database access, and run lifecycle."""

    def __init__(self):
        self.ggdb = None
        self.monitor = None
        self.settings_folder = None

    def open_software(self, software_id):
        """Hand video-context selection back to the Games frontend."""

        software_id = int(software_id)
        xbmc.executebuiltin(
            f"RunScript(plugin.program.umsa.mame.surfer,select_software,{software_id})"
        )

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
        window = xbmcgui.Window(_WINDOW_ID)
        if window.getProperty(_RUNNING_PROPERTY):
            xbmc.log("UMSA Screensaver: another screensaver instance is active", xbmc.LOGWARNING)
            return

        window.setProperty(_RUNNING_PROPERTY, "true")
        window.setProperty(_MODE_PROPERTY, "starting")
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

            self.ggdb = DBMod(self.settings_folder)
            self.ggdb.use_filter = False
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
                saver = self.monitor.saver
                saver.running = request["mode"]
                saver.art_types = request["art_types"]
                window.setProperty(_MODE_PROPERTY, saver.running)
                saver.doModal()
        finally:
            try:
                if self.ggdb is not None:
                    self.ggdb.close_db()
            finally:
                window.clearProperty(_MODE_PROPERTY)
                window.clearProperty(_RUNNING_PROPERTY)
