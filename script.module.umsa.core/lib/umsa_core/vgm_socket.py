"""VGM socket transport and Lua log protocol handling.

This module encapsulates the TCP transport lifecycle and Lua log protocol
between Python and the MAME Lua script (vgmplay.lua).
"""

import select
import socket
import threading
import time
from collections.abc import Callable

from umsa_core import log

# Lua log protocol constants
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

VGMPLAY_DEFAULT_PORT = 1234


def _parse_vgmplay_port(value: str | None) -> int | None:
    """Return a valid VGMPlay port, or None for a set invalid value or unset."""
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


def _get_vgmplay_port(value: str | None) -> int:
    """Return a valid VGMPlay port, using default if unset or invalid."""
    port = _parse_vgmplay_port(value)
    if port is None:
        return VGMPLAY_DEFAULT_PORT
    return port


def parse_lua_log_line(line):
    """Parse one Lua log frame, pure function, socket independent.

    Returns (level, text) for "LOG|<LEVEL>|<TEXT>" frames and None for
    anything else (empty lines, commands, binary junk, truncated frames).
    Splitting stops after two separators, so "|" inside the text is kept.
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


class VgmSocketServer:
    """Manages the VGM TCP transport lifecycle and Lua log protocol.

    Encapsulates:
    - Listener creation and binding
    - Port selection and validation
    - Listener and accepted-client sockets
    - Connection acceptance with bounded waiting
    - Sending newline-terminated Python-to-Lua commands
    - Receiving and buffering Lua-to-Python log frames
    - LOG|LEVEL|TEXT parsing and log forwarding
    - Reader-thread creation, shutdown and bounded joining
    - Client connection cleanup
    - Listener shutdown and cleanup after errors
    """

    def __init__(
        self,
        logger: Callable | None = None,
        process_exited: Callable[[], bool] | None = None,
    ):
        """
        Args:
            logger: Logger callback, defaults to umsa_core.log
            process_exited: Callable returning True if the child process has exited
        """
        self._logger = logger or log
        self._process_exited = process_exited or (lambda: False)

        self._listener: socket.socket | None = None
        self._client: socket.socket | None = None
        self._reader_thread: threading.Thread | None = None
        self._reader_stop: threading.Event | None = None
        self._port_env: str | None = None
        self._bound_port: int | None = None
        self._lock = threading.Lock()

    def _log(self, message: str, level: str = 'debug'):
        """Forward one diagnostic without allowing logger failures to escape."""
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
        """Create and start the listening socket.

        Args:
            port_env: Optional VGMPLAY_PORT environment variable value

        Returns:
            True if server started successfully, False if disabled
        """
        with self._lock:
            self._close_all()
            self._port_env = port_env
            if port_env is None:
                # Use default port when not explicitly configured
                port = VGMPLAY_DEFAULT_PORT
            else:
                # Explicit port configuration - must be valid
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

    def wait_for_connection(self, timeout: float = 30.0) -> bool:
        """Accept a connection from the Lua client with bounded waiting.

        Waits for the Lua client to connect, or for the child process to exit,
        or for the timeout to expire.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if connection accepted, False otherwise
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

                with self._lock:
                    if self._client:
                        self._close_client()
                    self._client = conn
                    try:
                        self._start_reader(conn)
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

    def _start_reader(self, conn):
        """Start the daemon reader thread for Lua log frames."""
        self._stop_reader()
        stop = threading.Event()
        self._reader_stop = stop
        thread = threading.Thread(target=self._reader_loop, args=(conn, stop), daemon=True)
        self._reader_thread = thread
        try:
            thread.start()
        except Exception:
            self._reader_thread = None
            self._reader_stop = None
            raise
        return thread

    def _stop_reader(self):
        """Signal the reader thread to drain and exit, join with bounded timeout."""
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

    def _reader_loop(self, conn, stop):
        """Drain LOG frames sent by vgmplay.lua. Never raises into the caller."""
        buf = b''
        try:
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
                    # Lua closed its side
                    return
                buf += data
                while b'\n' in buf:
                    line, _, buf = buf.partition(b'\n')
                    self._forward_log_frame(line)
                if len(buf) > LUA_LOG_MAX_LINE_BYTES:
                    self._log("UMSA VGM: log line too long, buffer dropped", level='warning')
                    buf = b''
            # Shutdown requested: last drain
            self._drain_buffer(conn, buf)
        except Exception as err:
            self._log(f"UMSA VGM: reader loop error: {err}", level='warning')
        finally:
            try:
                conn.close()
            except Exception as err:
                self._log_socket_error("reader close error", err)

    def _drain_buffer(self, conn, buf=b''):
        """Read frames already buffered by the kernel, non-blocking and bounded."""
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
        """Forward one Lua log frame to the application logger."""
        parsed = parse_lua_log_line(line)
        if not parsed:
            return False
        level, text = parsed
        self._log(f'{LUA_LOG_MSG_PREFIX}: {text}', level=level)
        return True

    def send_command(self, data: bytes) -> bool:
        """Send a command to the Lua script over the accepted connection."""
        self._log("UMSA VGM: sending command", level='debug')
        with self._lock:
            if not self._client:
                self._log("UMSA Emu: no lua socket connection (not accepted)", level='warning')
                return False
            if not data.endswith(b'\n'):
                data = data + b'\n'
            try:
                self._client.sendall(data)
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
        """Internal: close client connection without lock."""
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
        """Internal: close all sockets without lock."""
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
        """The port the server is bound to."""
        return self._bound_port

    @property
    def is_connected(self) -> bool:
        """Whether a client is currently connected."""
        return self._client is not None