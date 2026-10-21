"""VGM socket transport and Lua log protocol handling.

This module encapsulates the TCP transport lifecycle and Lua log protocol
between Python and the MAME Lua script (vgmplay.lua).
"""

import os
import socket
import select
import threading
import time
from typing import Callable, Optional

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


def _parse_vgmplay_port(value: Optional[str]) -> Optional[int]:
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


def _get_vgmplay_port(value: Optional[str]) -> int:
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
        logger: Optional[Callable] = None,
        process_exited: Optional[Callable[[], bool]] = None,
    ):
        """
        Args:
            logger: Logger callback, defaults to umsa_core.log
            process_exited: Callable returning True if the child process has exited
        """
        self._logger = logger or log
        self._process_exited = process_exited or (lambda: False)

        self._listener: Optional[socket.socket] = None
        self._client: Optional[socket.socket] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._reader_stop: Optional[threading.Event] = None
        self._port_env: Optional[str] = None
        self._bound_port: Optional[int] = None
        self._lock = threading.Lock()

    def start_server(self, port_env: Optional[str] = None) -> bool:
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
                    self._logger("UMSA VGM: socket disabled (invalid port)", level='debug')
                    return False

            try:
                self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._listener.bind(("127.0.0.1", port))
                self._listener.listen(1)
                self._bound_port = port
                self._logger(f"UMSA VGM: listening on 127.0.0.1:{port}", level='debug')
                return True
            except Exception as err:
                self._logger(f"UMSA VGM: failed to start socket server: {err}", level='warning')
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
                if self._process_exited():
                    self._logger("UMSA VGM: process exited before Lua connection", level='debug')
                    return False
                try:
                    conn, _ = listener.accept()
                except socket.timeout:
                    continue
                except Exception as err:
                    self._logger(f"UMSA VGM: accept failed: {err}", level='debug')
                    return False

                with self._lock:
                    if self._client:
                        self._close_client()
                    self._client = conn
                    self._start_reader(conn)
                return True
        finally:
            try:
                listener.settimeout(None)
            except Exception:
                pass

        return False

    def _start_reader(self, conn):
        """Start the daemon reader thread for Lua log frames."""
        self._stop_reader()
        stop = threading.Event()
        self._reader_stop = stop
        thread = threading.Thread(target=self._reader_loop, args=(conn, stop), daemon=True)
        self._reader_thread = thread
        thread.start()
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
            stop.set()
        thread.join(LUA_READER_JOIN_TIMEOUT)
        if thread.is_alive():
            self._logger("UMSA VGM: reader thread still alive after join", level='debug')

    def _reader_loop(self, conn, stop):
        """Drain LOG frames sent by vgmplay.lua. Never raises into the caller."""
        buf = b''
        try:
            while not stop.is_set():
                try:
                    readable = select.select([conn], [], [], LUA_READ_POLL_TIMEOUT)[0]
                except Exception as err:
                    self._logger(f"UMSA VGM: reader select error: {err}", level='debug')
                    return
                if not readable:
                    continue
                try:
                    data = conn.recv(4096)
                except Exception as err:
                    self._logger(f"UMSA VGM: reader recv error: {err}", level='debug')
                    return
                if not data:
                    # Lua closed its side
                    return
                buf += data
                while b'\n' in buf:
                    line, _, buf = buf.partition(b'\n')
                    self._forward_log_frame(line)
                if len(buf) > LUA_LOG_MAX_LINE_BYTES:
                    self._logger("UMSA VGM: log line too long, buffer dropped", level='warning')
                    buf = b''
            # Shutdown requested: last drain
            self._drain_buffer(conn, buf)
        except Exception as err:
            self._logger(f"UMSA VGM: reader loop error: {err}", level='warning')
        finally:
            try:
                conn.close()
            except OSError as err:
                self._logger(f"UMSA VGM: reader close error: {err}", level='debug')

    def _drain_buffer(self, conn, buf=b''):
        """Read frames already buffered by the kernel, non-blocking and bounded."""
        logged = 0
        while True:
            try:
                readable = select.select([conn], [], [], 0)[0]
            except Exception:
                return logged
            if not readable:
                return logged
            try:
                data = conn.recv(4096)
            except Exception:
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
        self._logger(f'{LUA_LOG_MSG_PREFIX}: {text}', level=level)
        return True

    def send_command(self, data: bytes) -> bool:
        """Send a command to the Lua script over the accepted connection."""
        self._logger("UMSA VGM: sending command", level='debug')
        with self._lock:
            if not self._client:
                self._logger("UMSA Emu: no lua socket connection (not accepted)", level='warning')
                return False
            if not data.endswith(b'\n'):
                data = data + b'\n'
            try:
                self._client.sendall(data)
                self._logger(f"UMSA VGM: command sent: {data!r}", level='debug')
                return True
            except Exception as err:
                self._logger(f"UMSA VGM: send failed: {err}", level='warning')
                return False

    def close_client(self):
        """Close the accepted client connection and stop its reader thread."""
        with self._lock:
            self._close_client()

    def _close_client(self):
        """Internal: close client connection without lock."""
        self._stop_reader()
        if self._client:
            try:
                self._client.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def close_server(self):
        """Close the listening socket and any client connection."""
        with self._lock:
            self._close_all()

    def _close_all(self):
        """Internal: close all sockets without lock."""
        self._stop_reader()
        if self._client:
            try:
                self._client.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        if self._listener:
            try:
                self._listener.close()
            except Exception:
                pass
            self._listener = None
        self._bound_port = None

    @property
    def bound_port(self) -> Optional[int]:
        """The port the server is bound to."""
        return self._bound_port

    @property
    def is_connected(self) -> bool:
        """Whether a client is currently connected."""
        return self._client is not None