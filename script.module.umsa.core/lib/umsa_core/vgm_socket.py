"""TCP link to vgmplay.lua: commands to Lua, ``LOG|<LEVEL>|<TEXT>`` frames back.

The listener binds to 127.0.0.1; a connection is accepted only after the
``HELLO|<token>`` handshake of the current playback.
"""

import hmac
import math
import select
import socket
import threading
import time
from collections.abc import Callable

from umsa_core import log
from umsa_core.settings import DEFAULT_VGM_PORT

LUA_LOG_TAG = 'LOG'
LUA_LOG_LEVELS = {
    'DEBUG': 'debug',
    'INFO': 'info',
    'WARN': 'warning',
    'ERROR': 'error',
}
LUA_LOG_FALLBACK_LEVEL = 'warning'
LUA_LOG_MSG_PREFIX = 'UMSA Emu lua'
LUA_READ_POLL_TIMEOUT = 0.2
LUA_READER_JOIN_TIMEOUT = 1.0
LUA_LOG_MAX_LINE_BYTES = 8192
# Seconds; bounds one sendall when vgmplay.lua stops reading (full send buffer).
LUA_SEND_TIMEOUT = 1.0
# Token handshake: vgmplay.lua's first bytes are ``HELLO|<token>\n``. A late
# MAME of an earlier track must not take over the next playback.
LUA_HELLO_TIMEOUT = 2.0
LUA_HELLO_MAX_BYTES = 128
LUA_HELLO_PREFIX = b'HELLO|'

# Frames of vgmplay.lua that carry ``gain_db=`` and ``state=`` (end of the
# music info): playback start, leveling step, leveling lock, manual change.
LUA_LEVEL_TAGS = (
    'LEVEL_INITIAL:', 'LEVEL_ADJ:', 'LEVEL_LOCKED:', 'VGM VOLUME UP:', 'VGM VOLUME DOWN:')
LUA_GAIN_FIELD = 'gain_db='
LUA_STATE_FIELD = 'state='
# auto = leveling adjusts, locked = leveling frozen, manual = user changed it.
LUA_LEVEL_STATES = ('auto', 'locked', 'manual')

# One default for the setting, the listener and (as a literal) vgmplay.lua.
VGMPLAY_DEFAULT_PORT = DEFAULT_VGM_PORT


def _parse_vgmplay_port(value: str | None) -> int | None:
    """Return a valid VGMPlay port, or ``None`` for an invalid or unset value."""
    if value is None:
        return None
    if not value.isascii() or not value.isdigit():
        return None
    significant_value = value.lstrip('0') or '0'
    if len(significant_value) > 5:
        return None
    port = int(significant_value)
    if not 1 <= port <= 65535:
        return None
    return port


def parse_lua_log_line(line):
    """Return ``(level, text)`` of a ``LOG|<LEVEL>|<TEXT>`` frame, else ``None``.

    ``|`` inside the text is kept; an unknown level maps to
    ``LUA_LOG_FALLBACK_LEVEL``.
    """
    if isinstance(line, str):
        line = line.encode('utf-8', errors='replace')
    if not isinstance(line, (bytes, bytearray)):
        return None
    parts = bytes(line).rstrip().split(b'|', 2)
    if len(parts) != 3 or parts[0] != LUA_LOG_TAG.encode('ascii'):
        return None
    level = parts[1].decode('ascii', errors='replace').strip().upper()
    text = parts[2].decode('utf-8', errors='replace').strip()
    return LUA_LOG_LEVELS.get(level, LUA_LOG_FALLBACK_LEVEL), text


def parse_lua_level(text):
    """Return ``(gain_db, state)`` of a level frame text, else ``None``.

    vgmplay.lua reports the gain it puts on the track and who sets it as
    ``gain_db=<dB> state=<auto|locked|manual>`` in ``LEVEL_INITIAL`` (start),
    ``LEVEL_ADJ`` (leveling step), ``LEVEL_LOCKED`` (leveling frozen) and
    ``VGM VOLUME UP/DOWN`` (manual change). Both fields are needed; an
    unknown state or a gain that is no finite number gives None.
    """
    if not isinstance(text, str) or not text.startswith(LUA_LEVEL_TAGS):
        return None
    gain = state = None
    for token in text.split():
        if gain is None and token.startswith(LUA_GAIN_FIELD):
            try:
                gain = float(token[len(LUA_GAIN_FIELD):])
            except ValueError:
                return None
        elif state is None and token.startswith(LUA_STATE_FIELD):
            state = token[len(LUA_STATE_FIELD):]
    # inf/nan never reach the label.
    if gain is None or not math.isfinite(gain) or state not in LUA_LEVEL_STATES:
        return None
    return gain, state


class VgmSocketServer:
    """Listener, accepted client and reader thread of the vgmplay.lua link.

    A daemon reader thread forwards the Lua log frames to the logger and to
    ``frame_listener``. Sends are bounded by ``LUA_SEND_TIMEOUT`` and never
    hold the lifecycle lock, so closing the connection never waits for a
    blocked send.

    Args:
        logger: Logger callback, default :func:`umsa_core.log`.
        process_exited: Returns ``True`` once the MAME process has exited;
            ends the wait for a connection early.
        frame_listener: Gets the text of every Lua log frame (reader thread).
    """

    def __init__(
        self,
        logger: Callable | None = None,
        process_exited: Callable[[], bool] | None = None,
        frame_listener: Callable[[str], None] | None = None,
    ):
        """Create an unbound server (see the class docstring)."""
        self._logger = logger or log
        self._process_exited = process_exited or (lambda: False)
        self._frame_listener = frame_listener

        self._listener: socket.socket | None = None
        self._client: socket.socket | None = None
        self._reader_thread: threading.Thread | None = None
        self._reader_stop: threading.Event | None = None
        self._port_env: str | None = None
        self._bound_port: int | None = None
        self._lock = threading.Lock()
        # Serialises the senders only (no interleaved lines); taken before
        # _lock, never by the close paths.
        self._send_lock = threading.Lock()

    def _log(self, message: str, level: str = 'debug'):
        """Log one message; a failing logger never raises."""
        try:
            self._logger(message, level=level)
        except Exception:
            if self._logger is log:
                return
            try:
                log(message, level=level)
            except Exception:
                return

    def _log_socket_error(self, operation: str, err: Exception):
        """Log socket shutdown/read failures, quieting expected OSError cases."""
        level = 'debug' if isinstance(err, OSError) else 'warning'
        self._log(f"UMSA VGM: {operation}: {err}", level=level)

    def start_server(self, port_env: str | None = None) -> bool:
        """Start listening on 127.0.0.1; return ``False`` when that failed.

        ``port_env`` is the ``VGMPLAY_PORT`` value; ``None`` uses the default
        port, an invalid value disables the socket.
        """
        with self._lock:
            self._close_all()
            self._port_env = port_env
            if port_env is None:
                port = VGMPLAY_DEFAULT_PORT
            else:
                port = _parse_vgmplay_port(port_env)
                if port is None:
                    self._log("UMSA VGM: socket disabled (invalid port)", level='debug')
                    return False

            try:
                self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._listener.bind(("127.0.0.1", port))
                self._listener.listen(1)
                self._bound_port = port
                self._log(f"UMSA VGM: listening on 127.0.0.1:{port}", level='debug')
                return True
            except Exception as err:
                self._log(f"UMSA VGM: failed to start socket server: {err}", level='warning')
                self._close_all()
                return False

    def wait_for_connection(self, timeout: float = 30.0,
                            token: str | None = None) -> bool:
        """Wait for vgmplay.lua to connect; return whether a client was accepted.

        The wait ends early when the MAME process exits.

        Args:
            timeout: Maximum wait in seconds.
            token: Session token; only a connection whose first line is
                ``HELLO|<token>`` is accepted, every other one is dropped and
                the wait goes on. ``None``: no handshake.
        """
        if not self._listener:
            return False

        listener = self._listener
        deadline = time.monotonic() + timeout
        listener.settimeout(0.5)

        try:
            while time.monotonic() < deadline:
                try:
                    process_exited = self._process_exited()
                except Exception as err:
                    self._log(f"UMSA VGM: process exit check failed: {err}",
                              level='warning')
                    return False
                if process_exited:
                    self._log("UMSA VGM: process exited before Lua connection", level='debug')
                    return False
                try:
                    conn, _ = listener.accept()
                except TimeoutError:
                    continue
                except Exception as err:
                    self._log(f"UMSA VGM: accept failed: {err}", level='debug')
                    return False

                try:
                    conn.settimeout(LUA_SEND_TIMEOUT)
                except OSError as err:
                    self._log(f"UMSA VGM: could not set client send timeout: "
                              f"{err}", level='warning')
                    self._close_socket(conn, 'client', shut_down=True)
                    return False

                rest = b''
                if token is not None:
                    ok, rest = self._read_hello(conn, token, deadline)
                    if not ok:
                        self._log("UMSA VGM: dropped connection without matching HELLO",
                                  level='debug')
                        self._close_socket(conn, 'client', shut_down=True)
                        continue

                with self._lock:
                    if self._client:
                        self._close_client()
                    self._client = conn
                    try:
                        self._start_reader(conn, rest)
                    except Exception as err:
                        self._log(f"UMSA VGM: reader start failed: {err}",
                                  level='warning')
                        self._close_client()
                        return False
                return True
        finally:
            try:
                listener.settimeout(None)
            except Exception as err:
                self._log(f"UMSA VGM: could not restore listener timeout: "
                          f"{err}", level='warning')

        return False

    def _read_hello(self, conn, token, deadline):
        """Read the first line of a new connection and check the handshake.

        Returns ``(ok, rest)``; ``rest`` are the bytes behind the HELLO line
        (they belong to the reader). Reads at most ``LUA_HELLO_MAX_BYTES``
        bytes for at most ``LUA_HELLO_TIMEOUT`` seconds, never beyond
        ``deadline``. The token is never logged.
        """
        end = min(time.monotonic() + LUA_HELLO_TIMEOUT, deadline)
        buf = b''
        while b'\n' not in buf:
            remaining = end - time.monotonic()
            if remaining <= 0 or len(buf) >= LUA_HELLO_MAX_BYTES:
                return False, b''
            try:
                if not select.select([conn], [], [], remaining)[0]:
                    continue
                data = conn.recv(LUA_HELLO_MAX_BYTES + 1 - len(buf))
            except Exception as err:
                self._log_socket_error("hello read error", err)
                return False, b''
            if not data:
                return False, b''
            buf += data
        line, _, rest = buf.partition(b'\n')
        if len(line) >= LUA_HELLO_MAX_BYTES:
            return False, b''
        expected = LUA_HELLO_PREFIX + token.encode('utf-8')
        if not hmac.compare_digest(line.rstrip(b'\r'), expected):
            return False, b''
        return True, rest

    def _start_reader(self, conn, initial=b''):
        """Start the daemon reader thread for Lua log frames."""
        self._stop_reader()
        stop = threading.Event()
        self._reader_stop = stop
        thread = threading.Thread(target=self._reader_loop, args=(conn, stop, initial), daemon=True)
        self._reader_thread = thread
        try:
            thread.start()
        except Exception:
            self._reader_thread = None
            self._reader_stop = None
            raise
        return thread

    def _stop_reader(self):
        """Signal the reader thread to drain and exit; join with a bounded timeout."""
        thread = self._reader_thread
        stop = self._reader_stop
        self._reader_thread = None
        self._reader_stop = None
        if not thread:
            return
        if stop:
            try:
                stop.set()
            except Exception as err:
                self._log(f"UMSA VGM: reader stop signal failed: {err}",
                          level='warning')
        stage = 'join'
        try:
            thread.join(LUA_READER_JOIN_TIMEOUT)
            stage = 'state check'
            alive = thread.is_alive()
        except Exception as err:
            self._log(f"UMSA VGM: reader thread {stage} failed: {err}",
                      level='warning')
            return
        if alive:
            self._log("UMSA VGM: reader thread still alive after join", level='debug')

    def _forward_buffered_lines(self, buf):
        """Forward every complete line of ``buf`` and return the remainder."""
        while b'\n' in buf:
            line, _, buf = buf.partition(b'\n')
            self._forward_log_frame(line)
        return buf

    def _reader_loop(self, conn, stop, buf=b''):
        """Forward the LOG frames sent by vgmplay.lua until stopped; never raises.

        ``buf`` holds bytes read behind the HELLO line.
        """
        try:
            buf = self._forward_buffered_lines(buf)
            while not stop.is_set():
                try:
                    readable = select.select([conn], [], [], LUA_READ_POLL_TIMEOUT)[0]
                except Exception as err:
                    self._log_socket_error("reader select error", err)
                    return
                if not readable:
                    continue
                try:
                    data = conn.recv(4096)
                except Exception as err:
                    self._log_socket_error("reader recv error", err)
                    return
                if not data:
                    return
                buf = self._forward_buffered_lines(buf + data)
                if len(buf) > LUA_LOG_MAX_LINE_BYTES:
                    self._log("UMSA VGM: log line too long, buffer dropped", level='warning')
                    buf = b''
            self._drain_buffer(conn, buf)
        except Exception as err:
            self._log(f"UMSA VGM: reader loop error: {err}", level='warning')
        finally:
            try:
                conn.close()
            except Exception as err:
                self._log_socket_error("reader close error", err)

    def _drain_buffer(self, conn, buf=b''):
        """Forward the frames the kernel already buffered; return the count."""
        logged = 0
        while True:
            try:
                readable = select.select([conn], [], [], 0)[0]
            except Exception as err:
                self._log_socket_error("drain select error", err)
                return logged
            if not readable:
                return logged
            try:
                data = conn.recv(4096)
            except Exception as err:
                self._log_socket_error("drain recv error", err)
                return logged
            if not data:
                return logged
            buf += data
            while b'\n' in buf:
                line, _, buf = buf.partition(b'\n')
                if self._forward_log_frame(line):
                    logged += 1
        return logged

    def _forward_log_frame(self, line) -> bool:
        """Log a Lua log frame and pass it to ``frame_listener``; ``False`` for no frame."""
        parsed = parse_lua_log_line(line)
        if not parsed:
            return False
        level, text = parsed
        self._log(f'{LUA_LOG_MSG_PREFIX}: {text}', level=level)
        if self._frame_listener:
            try:
                self._frame_listener(text)
            except Exception as error:  # noqa: BLE001  (foreign callback must not stop the reader)
                self._log(f'UMSA VGM: frame listener failed: {error}', level='debug')
        return True

    def send_command(self, data: bytes) -> bool:
        """Send a newline-terminated command to vgmplay.lua; return whether it was sent.

        ``sendall`` is bounded by ``LUA_SEND_TIMEOUT`` and runs outside the
        lifecycle lock: a ``close_client`` meanwhile shuts the socket down and
        the send fails. A timeout or failure returns False (``stop_vgm`` then
        terminates MAME); a partly sent command is not repaired.
        """
        self._log("UMSA VGM: sending command", level='debug')
        if not data.endswith(b'\n'):
            data = data + b'\n'
        with self._send_lock:
            with self._lock:
                client = self._client
            if client is None:
                self._log("UMSA Emu: no lua socket connection (not accepted)", level='warning')
                return False
            try:
                client.sendall(data)
                self._log(f"UMSA VGM: command sent: {data!r}", level='debug')
                return True
            except Exception as err:
                self._log(f"UMSA VGM: send failed: {err}", level='warning')
                return False

    def close_client(self):
        """Close the accepted client connection and stop its reader thread."""
        with self._lock:
            self._close_client()

    def _close_client(self):
        """Close the client connection; the caller holds the lock."""
        try:
            self._stop_reader()
        except Exception as err:
            self._log(f"UMSA VGM: client reader cleanup failed: {err}",
                      level='warning')
        client = self._client
        self._client = None
        if client is not None:
            self._close_socket(client, 'client', shut_down=True)

    def close_server(self):
        """Close the listening socket and any client connection."""
        with self._lock:
            self._close_all()

    def _close_all(self):
        """Close all sockets; the caller holds the lock."""
        try:
            self._close_client()
        except Exception as err:
            self._log(f"UMSA VGM: client cleanup failed before listener "
                      f"close: {err}", level='warning')
        listener = self._listener
        self._listener = None
        self._bound_port = None
        if listener is not None:
            self._close_socket(listener, 'listener', shut_down=False)

    def _close_socket(self, sock, resource: str, *, shut_down: bool):
        """Close one socket, logging shutdown and close failures independently."""
        if shut_down:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception as err:
                self._log_socket_error(f"{resource} shutdown failed", err)
        try:
            sock.close()
        except Exception as err:
            self._log(f"UMSA VGM: {resource} close failed: {err}",
                      level='warning')

    @property
    def bound_port(self) -> int | None:
        """Return the port the server is bound to, ``None`` when not listening."""
        return self._bound_port
