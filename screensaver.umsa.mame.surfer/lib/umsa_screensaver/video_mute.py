"""Silent start of the screensaver videos (``ssaver_video_mute``).

The Kodi Python API has no mute for a single player, so the videos are
muted through the global Kodi mute (JSON-RPC ``Application.SetMute``).
The previous state is restored: the screensaver only mutes a Kodi that was
not muted before, and only unmutes what it muted itself.

No Kodi import here: the JSON-RPC call (``xbmc.executeJSONRPC``) and the
log function are passed in.

Kodi keeps the mute state in ``guisettings.xml``: a Kodi that crashes while
a muted screensaver video plays starts muted again.
"""

import json


def _call(execute, method, params):
    """Run one JSON-RPC request and return its ``result``, ``None`` on failure."""

    request = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    try:
        response = json.loads(execute(request))
    except (TypeError, ValueError, RuntimeError):
        return None
    if not isinstance(response, dict) or "result" not in response:
        return None
    return response["result"]


def is_muted(execute):
    """Return whether Kodi is muted, ``None`` when the state is unknown."""

    result = _call(execute, "Application.GetProperties", {"properties": ["muted"]})
    if not isinstance(result, dict) or "muted" not in result:
        return None
    return bool(result["muted"])


def set_muted(execute, muted):
    """Set the Kodi mute; return ``True`` when Kodi confirmed the new state."""

    result = _call(execute, "Application.SetMute", {"mute": bool(muted)})
    return result is not None and bool(result) == bool(muted)


class VideoMute:
    """Mutes Kodi for the screensaver videos and restores the previous state."""

    def __init__(self, execute, log):
        self._execute = execute
        self._log = log
        # the screensaver muted Kodi and has to unmute it again
        self._muted_by_saver = False

    @property
    def active(self):
        """Return whether the screensaver muted Kodi."""

        return self._muted_by_saver

    def mute(self):
        """Mute Kodi unless it is muted already; repeated calls are safe."""

        if self._muted_by_saver:
            return
        state = is_muted(self._execute)
        if state is None:
            self._log("UMSA SSaver: mute state unknown, videos keep their sound", "warning")
            return
        if state:
            # muted by the user: leave it alone, also when the videos end
            self._log("UMSA SSaver: Kodi is muted already", "debug")
            return
        if set_muted(self._execute, True):
            self._muted_by_saver = True
            self._log("UMSA SSaver: muted Kodi for the screensaver videos", "info")
        else:
            self._log("UMSA SSaver: could not mute Kodi, videos keep their sound", "warning")

    def restore(self):
        """Unmute Kodi when the screensaver muted it; repeated calls are safe."""

        if not self._muted_by_saver:
            return
        self._muted_by_saver = False
        if set_muted(self._execute, False):
            self._log("UMSA SSaver: restored the Kodi sound", "info")
        else:
            self._log("UMSA SSaver: could not unmute Kodi after the videos", "error")
