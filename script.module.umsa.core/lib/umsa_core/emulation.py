"""Module for general emulation handling."""

import os
import socket
import subprocess
from platform import platform
from select import select as select_wait
from threading import Event, Thread
from time import sleep as time_sleep

from umsa_core import (
    ProcessRunner,
    ProcessState,
    ProcessStatus,
    calculate_playback_plan,
    log,
    parse_vgm_header,
)
from umsa_core.chd_extractor import (
    CHDExtractionCancelled,
    CHDExtractionError,
    extract_chd,
)
from umsa_core.launch_preparer import LaunchPreparer
from umsa_core.rom_extractor import extract_rom
from umsa_core.rom_finder import NONMAME, find_nonmame_roms, find_roms
from umsa_core.vgm_player import VgmPlayer

PLATFORM = platform()
CHD_PROCESS_STOP_TIMEOUT = 2
VGM_RANDOM_BATCH_SIZE = 100
VGM_RANDOM_MAX_CONSECUTIVE_UNPLAYABLE = 5


def _time_sleep_ms(milliseconds):
    """Sleep for milliseconds via ``time.sleep`` (Kodi-free default)."""

    time_sleep(milliseconds / 1000.0)


def format_vgm_info(track_filename, gamename, header, plan):
    """Build the human readable VGM info string shared by all play modes."""

    minutes, seconds = divmod(int(header.total_seconds), 60)
    return (
        f'Song "{track_filename[:-4].title()}" from "{gamename}" '
        f'{minutes}:{seconds:02d} ({plan.reason})'
    )


#
# vgmplay.lua logging protocol
#
# Python -> Lua (commands, unchanged): newline terminated plain verbs,
#   "exit\n", "volume_up\n", "volume_down\n"
# Lua -> Python (log frames, new):
#   LOG|<LEVEL>|<TEXT>\n
# Both directions share the same TCP connection but have their own buffers,
# so log frames can never end up in the Lua command parser.
# The Lua side truncates TEXT and replaces CR/LF/tab, so one frame is one line.
#
LUA_LOG_TAG = 'LOG'
# Lua level name -> Core logger level name.
LUA_LOG_LEVELS = {
    'DEBUG' : 'debug',
    'INFO'  : 'info',
    'WARN'  : 'warning',
    'ERROR' : 'error',
}
# Level used for frames with an unknown/empty level name.
LUA_LOG_FALLBACK_LEVEL = 'warning'
# Prefix keeping the origin of forwarded messages visible in Kodi.log.
LUA_LOG_MSG_PREFIX = 'UMSA Emu lua'
# Reader poll timeout, keeps reader shutdown bounded and deterministic.
LUA_READ_POLL_TIMEOUT = 0.2
# Bounded join when stopping the reader thread.
LUA_READER_JOIN_TIMEOUT = 1.0
# Maximum size of an unparsed Lua log line before the buffer is dropped.
# Lua truncates each message (~480 bytes), this only guards against garbage.
LUA_LOG_MAX_LINE_BYTES = 8192

# TODO push to settings
VGMPLAY_DEFAULT_PORT = 1234


def _parse_vgmplay_port(value):
    """Return a valid VGMPlay port, or None for a set invalid value."""
    if value is None:
        return VGMPLAY_DEFAULT_PORT
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

def update_dialog(dialog, percent, msg):
    """Helper for emulator dialog from Kodi."""

    if dialog:
        dialog.update(percent, msg)

def vgm_header_info(zip_path, member):
    """Return VGM header stats (total/loop/intro seconds, volume) for a zip member.

    Used for experiment logging only; returns None on any parse failure.
    """
    header = parse_vgm_header(zip_path, member, logger=log)
    if not header.header_valid:
        return None
    return {
        'total_s': header.total_seconds,
        'loop_s': header.loop_seconds,
        'intro_s': header.intro_seconds,
        'has_loop': header.has_loop,
        'volume_modifier': header.volume_modifier,
        'header_gain_factor': header.header_gain_factor,
        'header_gain_db': header.header_gain_db,
        'extra_header_present': header.extra_header_present,
        'has_chip_volumes': header.has_chip_volumes,
    }

def parse_mame_ini(ini_file):
    """Parse mame.ini."""

    mame_ini = {}
    try:
        with open(ini_file, 'r', encoding='utf-8') as fobj:
            for line in fobj:
                line = line.strip()
                if len(line) == 0:
                    continue
                if line[0] == '#':
                    continue
                option = line.split(' ', 1)
                if len(option) > 0:
                    # linux replace $HOME
                    home_dir = os.path.expanduser('~')
                    # can contain multiple directories
                    if 'path' in option[0]:
                        mame_ini[option[0].strip()] = option[1].replace('$HOME', home_dir).strip().split(';')
                    # only one directory
                    if 'directory' in option[0]:
                        mame_ini[option[0].strip()] = option[1].replace('$HOME', home_dir).strip()
    except OSError:
        return mame_ini
    return mame_ini


def resolve_mame_paths(mame_ini, mame_dir):
    """Resolve mame.ini path/directory options against the MAME directory.

    ``path`` options are semicolon-separated lists, ``directory`` options are
    single values. Absolute entries pass through unchanged (os.path.join
    semantics), matching the cwd (mame_dir) MAME is launched with.
    """

    resolved = {}
    for key, value in mame_ini.items():
        if isinstance(value, list):
            resolved[key] = [os.path.join(mame_dir, entry) for entry in value]
        elif 'directory' in key:
            resolved[key] = os.path.join(mame_dir, value)
        else:
            resolved[key] = value
    return resolved


class Emulation:
    """Emulation handling class."""

    def __init__(self, temp_dir='.', mame_ini_file=None, mame_dir='.', mame_exe=None,
                    chdman_exe=None, vgmlua_script=None, vgm_info_callback=None, nonmame={},
                    terminal='', vgmplay_exe='', vgm_stopped_callback=None):
        self.percent = 0 # chd convert
        self.mame_exe = mame_exe
        self.mame_dir = mame_dir
        self.chdman_exe = chdman_exe
        self.process = None
        self.process_runner = ProcessRunner()
        self.temp_dir = temp_dir
        self.emurun = {}
        self.lua_script = vgmlua_script
        self.vgm_info_callback = vgm_info_callback
        self.vgm_stopped_callback = vgm_stopped_callback
        self.nonmame = nonmame
        self.terminal = terminal
        self.vgmplay_exe = vgmplay_exe

        self.mame_ini = {}
        if mame_ini_file:
            self.mame_ini = resolve_mame_paths(
                parse_mame_ini(mame_ini_file), mame_dir)

        self.launch_preparer = LaunchPreparer(
            mame_exe=mame_exe,
            mame_dir=mame_dir,
            nonmame=nonmame,
            mame_ini=self.mame_ini,
            temp_dir=temp_dir,
            terminal=terminal,
            chdman_exe=chdman_exe,
            find_roms=find_roms,
            find_nonmame_roms=find_nonmame_roms,
            extract_rom=extract_rom,
            extract_chd=extract_chd,
        )

        self.vgm_player = VgmPlayer(
            mame_exe=mame_exe,
            mame_dir=mame_dir,
            vgmplay_exe=vgmplay_exe,
            vgmlua_script=vgmlua_script,
            rom_paths=self.mame_ini.get('rompath', []),
            vgm_info_callback=vgm_info_callback,
            vgm_stopped_callback=vgm_stopped_callback,
        )

    # VGM state properties for backward compatibility
    @property
    def playvgm(self):
        return self.vgm_player.playvgm

    @playvgm.setter
    def playvgm(self, value):
        self.vgm_player.playvgm = value

    @property
    def playintrovgm(self):
        return self.vgm_player.playintrovgm

    @playintrovgm.setter
    def playintrovgm(self, value):
        self.vgm_player.playintrovgm = value

    @property
    def playrandomvgm(self):
        return self.vgm_player.playrandomvgm

    @playrandomvgm.setter
    def playrandomvgm(self, value):
        self.vgm_player.playrandomvgm = value

    @property
    def vgm_info_callback(self):
        return self.vgm_player.vgm_info_callback if hasattr(self, 'vgm_player') else None

    @vgm_info_callback.setter
    def vgm_info_callback(self, value):
        if hasattr(self, 'vgm_player'):
            self.vgm_player.vgm_info_callback = value

    @property
    def vgm_stopped_callback(self):
        return self.vgm_player.vgm_stopped_callback if hasattr(self, 'vgm_player') else None

    @vgm_stopped_callback.setter
    def vgm_stopped_callback(self, value):
        if hasattr(self, 'vgm_player'):
            self.vgm_player.vgm_stopped_callback = value

    # Socket state and VGM port - owned by Emulation
    lua_socket = None
    lua_server = None
    lua_log_thread = None
    lua_log_stop = None
    vgm_port_env = None

    @property
    def snapshot_directory(self):
        """Absolute MAME snapshot directory ('' when unset)."""

        return self.mame_ini.get('snapshot_directory', '')

    @property
    def input_directory(self):
        """Absolute MAME input directory ('' when unset)."""

        return self.mame_ini.get('input_directory', '')

    @property
    def rom_paths(self):
        """Absolute MAME rom path list ([] when unset)."""

        return self.mame_ini.get('rompath', [])

    def run(self):
        """Run the emulator."""

        args = self._process_args()
        popen_env = {}
        if 'env' in self.emurun:
            popen_env['env'] = self.emurun['env']
        # run executable depending on emulation start
        if self.emurun['emulation_start'] == 1: # Watch
            self.process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.emurun['working_dir'],
                **popen_env)
        elif self.emurun['emulation_start'] == 0: # Normal
            self.process = subprocess.Popen(
                args, cwd=self.emurun['working_dir'], **popen_env)
        elif self.emurun['emulation_start'] == 2: # Fallback
            self.process = None
            run = ''
            # escape parameters with double quotes
            for i in args:
                run += f'"{i}" '
            torun = [self.terminal, '-e', run]
            log(f'UMSA Emulation run {torun}', level='debug')
            subprocess.run(torun)

    def _process_args(self):
        """Build the command used by direct process launches."""

        args = []
        if isinstance(self.emurun['args'], list):
            args = [self.emurun['emu_exe']]+self.emurun['args']
        elif isinstance(self.emurun['args'], str):
            args = [self.emurun['emu_exe'], self.emurun['args']]
        else:
            log(f"UMSA Emulation, run: unknown type for args = {type(self.emurun['args'])}", level='warning')
        return args

    def start_managed_process(self, capture_output=False):
        """Start a non-VGM process using Core process ownership."""

        args = self._process_args()
        self.process_runner.start(
            args,
            cwd=self.emurun['working_dir'],
            capture_output=capture_output,
            env=self.emurun.get('env'),
        )

    def managed_process_status(self) -> ProcessStatus:
        """Return the status of the Core-managed game process."""

        return self.process_runner.status()

    def terminate_managed_process(self):
        """Terminate the Core-managed game process."""

        self.process_runner.terminate()

    def kill_managed_process(self):
        """Kill the Core-managed game process."""

        self.process_runner.kill()

    def read_managed_process_output(self):
        """Read stdout and stderr captured by the Core process runner."""

        return self.process_runner.read_output()

    def prepare_exodos_run(self, emu_infos):
        """Prepare ``emurun`` for eXoDOS."""
        self.launch_preparer.prepare_exodos_run(self.emurun, emu_infos)

    def prepare_marp_run(self, emu_infos):
        """Prepare ``emurun`` for a MARP replay."""
        self.launch_preparer.prepare_marp_run(self.emurun, emu_infos)

    def prepare_mame_run(self, ggdb, actset, dialog=None):
        """Prepare ``emurun['args']`` for MAME based on ``actset``."""
        self.launch_preparer.prepare_mame_run(self.emurun, ggdb, actset, dialog)

    def wait_for_completion(self, dialog=None, sleep=None):
        """Wait for the running emulator to stop or the user to cancel.

        Returns ``(stdout, stderr)``. ``sleep`` takes milliseconds so the GUI
        can pass ``xbmc.sleep``; the default maps them to ``time.sleep``.
        """

        if sleep is None:
            sleep = _time_sleep_ms
        sleep_ms = sleep
        uses_process_runner = self.emurun['emulation_start'] in (0, 1)
        out, err = '', ''
        # wait for emulator process to stop or cancel press to kill
        wait_cancel = True
        while wait_cancel:
            sleep_ms(1000)
            if uses_process_runner:
                if self.managed_process_status().state is not ProcessState.RUNNING:
                    wait_cancel = False
            else:
                wait_cancel = False
            if dialog is not None and dialog.iscanceled():
                dialog.update(60, 'emulator stopping...')
                wait_cancel = False
                log("UMSA gui: run_emulator: cancel pressed, sending SIGTERM")
                if uses_process_runner:
                    self.terminate_managed_process()
                else:
                    self.terminate()
                sleep(3000)
                if (uses_process_runner and
                        self.managed_process_status().state is ProcessState.RUNNING):
                    log(
                        "UMSA gui: run_emulator: process does not terminate, sending SIGKILL")
                    self.kill_managed_process()
        if self.emurun['emulation_start'] == 1:
            process_out, process_err = self.read_managed_process_output()
            out = process_out.decode('utf-8', errors='ignore')
            err = process_err.decode('utf-8', errors='ignore')
        return out, err


    def after_run(self):
        """Clean up after emulation run."""

        if self.emurun.get('symlink'):
            # TODO try except
            os.unlink(self.emurun['symlink'])
        self.emurun = {}

    def terminate(self):
        """Terminate the emulator process."""
        if self.process:
            self.process.terminate()

    def kill(self):
        """Kill the emulator process."""
        if self.process:
            self.process.kill()

    def _vgm_process_env(self):
        """Pass the port captured for this listener only to the MAME process."""
        return self.vgm_player._vgm_process_env(self.vgm_port_env)

    def _start_vgm_server(self):
        """Create and start listening socket for vgmplay.lua (client)."""
        self._close_vgm_sockets()
        self.vgm_port_env = os.environ.get('VGMPLAY_PORT')
        port = _parse_vgmplay_port(self.vgm_port_env)
        if port is None:
            self.lua_server = None
            self.lua_socket = None
            return
        self.lua_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.lua_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        self.lua_server.bind(("127.0.0.1", port))
        self.lua_server.listen(1)
        self.lua_socket = None

    def _accept_vgm_conn(self):
        """Accept connection from vgmplay.lua client. Closes old accepted conn if any."""
        if not self.lua_server:
            return False
        try:
            conn, _ = self.lua_server.accept()
        except Exception:
            return False
        if self.lua_socket:
            self._close_accepted_conn()
        self.lua_socket = conn
        # start reading Lua log frames right away, process.wait() below blocks
        # for the whole track, so nothing else would drain the connection
        self._start_lua_log_reader(conn)
        return True

    def _close_vgm_sockets(self):
        self._close_accepted_conn()
        if self.lua_server:
            try:
                self.lua_server.close()
            except Exception:
                pass
        self.lua_server = None

    def _close_accepted_conn(self):
        # reader first: it drains what lua already sent before shutdown(SHUT_RD)
        # discards the receive buffer on linux
        self._stop_lua_log_reader()
        if self.lua_socket:
            try:
                self.lua_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.lua_socket.close()
            except Exception:
                pass
        self.lua_socket = None

    def _stop_lua_log_reader(self):
        """Signal the reader thread to drain and exit, join with a bounded timeout."""
        thread = self.lua_log_thread
        stop = self.lua_log_stop
        self.lua_log_thread = None
        self.lua_log_stop = None
        if not thread:
            return
        if stop:
            stop.set()
        # bounded, never blocks playback longer than the poll timeout needs
        thread.join(LUA_READER_JOIN_TIMEOUT)
        if thread.is_alive():
            log("UMSA Emu: lua log reader still running after join", level='debug')

    def _start_lua_log_reader(self, conn):
        """Start the daemon reader thread for Lua -> Python log frames."""
        self._stop_lua_log_reader()
        stop = Event()
        self.lua_log_stop = stop
        thread = Thread(target=self._lua_log_reader, args=(conn, stop), daemon=True)
        self.lua_log_thread = thread
        thread.start()
        return thread

    def _lua_log_reader(self, conn, stop):
        """Drain LOG frames sent by vgmplay.lua. Never raises into the caller."""
        buf = b''
        try:
            while not stop.is_set():
                try:
                    readable = select_wait([conn], [], [], LUA_READ_POLL_TIMEOUT)[0]
                except Exception as err:
                    # closed socket on shutdown, bad fd, ...: reader is done
                    log(f"UMSA Emu: lua log reader select: {err}", level='debug')
                    return
                if not readable:
                    continue
                try:
                    data = conn.recv(4096)
                except Exception as err:
                    log(f"UMSA Emu: lua log reader recv: {err}", level='debug')
                    return
                if not data:
                    # lua closed its side (script exit or mame exit)
                    return
                buf += data
                while b'\n' in buf:
                    line, _, buf = buf.partition(b'\n')
                    self._log_lua_line(line)
                if len(buf) > LUA_LOG_MAX_LINE_BYTES:
                    log("UMSA Emu: lua log line too long, buffer dropped",
                        level='warning')
                    buf = b''
            # shutdown requested: last drain of already received frames
            self._drain_lua_log(conn, buf)
        except Exception as err:
            # defensive, a reader thread must never bubble up into playback
            log(f"UMSA Emu: lua log reader error: {err}", level='warning')
        finally:
            try:
                conn.close()
            except OSError as err:
                # already closed by _close_accepted_conn, nothing to do
                log(f"UMSA Emu: lua log reader close: {err}", level='debug')

    def _drain_lua_log(self, conn, buf=b''):
        """Read frames already buffered by the kernel, non blocking and bounded.

        Returns the number of log frames forwarded.
        """
        logged = 0
        while True:
            try:
                readable = select_wait([conn], [], [], 0)[0]
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
                logged += 1 if self._log_lua_line(line) else 0
        return logged

    def _log_lua_line(self, line):
        """Forward one Lua log frame to the addon logger, ignore anything else."""
        parsed = parse_lua_log_line(line)
        if not parsed:
            return False
        level, text = parsed
        log(f'{LUA_LOG_MSG_PREFIX}: {text}', level=level)
        return True

    def send_vgmaction(self, data):
        """Send command to MAME Lua script over accepted socket connection."""

        log("UMSA Emu: sending lua command", level='debug')
        if not self.lua_socket:
            log("UMSA Emu: no lua socket connection (not accepted)", level='warning')
            return False
        if not data.endswith(b'\n'):
            data = data + b'\n'
        try:
            self.lua_socket.sendall(data)
            log(f'UMSA Emu: lua command success: {data}', level='debug')
            return True
        except Exception:
            log("UMSA Emu: lua send failed", level='warning')
            return False

    def play_vgm_thread(self, vgm, sec2run=90, sleep=None, intro=False, close_server=True,
                    plan=None, info=None):
        """Play vgm."""
        self.vgm_player.prepare_vgm_run(self.emurun, vgm, sec2run, intro, plan, info, self.vgm_port_env)
        self.run()
        self._accept_vgm_conn()
        # wait until emu is finished
        if self.process:
            # TODO wait is blocking, not good in a thread? have some poll loop?
            my_rc = self.process.wait()
            log(f'UMSA Emu: MAME vgmplay returncode = {my_rc}', level='debug')
        else:
            log(f'UMSA Emu: MAME vgmplay has not returned a process: {self.run}', level='debug')
        self.playvgm = False
        if info:
            self.vgm_player._notify_vgm_stopped()

    def play_random_vgm_thread(self, ggdb=None, textinfo=None, db_path=None, sleep=None):
        """Play random vgm until ordered to stop playing."""
        def run_func(vgm, sleep=None, close_server=True, plan=None, info=None, vgm_port_env=None):
            self.play_vgm_thread(vgm, sec2run=90, sleep=sleep, intro=False,
                                 close_server=close_server, plan=plan, info=info)

        try:
            self.vgm_player.play_random_vgm_thread(
                self.emurun, ggdb, textinfo, db_path, sleep,
                find_roms_func=lambda emurun, rom_paths: self.find_roms(),
                run_func=lambda vgm, sleep=None, close_server=True, plan=None, info=None, vgm_port_env=None: 
                    self.play_vgm_thread(vgm, sec2run=90, sleep=sleep, intro=False,
                                         close_server=close_server, plan=plan, info=info))
        finally:
            self._close_vgm_sockets()

    def play_vgm(self, vgm, sec2run=90, sleep=None, intro=False, info=None, plan=None):
        if self.playvgm:
            return
        self._start_vgm_server()
        self.pvgm_thread = Thread(target=self.play_vgm_thread,
            args=(vgm, sec2run, sleep, intro), kwargs={'info': info, 'plan': plan})
        self.pvgm_thread.start()

    def find_nonmame_roms(self, exodos_shell=''):
        """Search for files from other sources than MAME."""
        find_nonmame_roms(self.emurun, self.nonmame, exodos_shell)

    def find_roms(self, swl_name=None, set_name=None):
        """Search for rom zipfiles and chd files within MAME rompath."""
        if swl_name and set_name:
            # For VGM mode, temporarily set emurun with the provided names
            old_swl = self.emurun.get('swl_name')
            old_set = self.emurun.get('set_name')
            self.emurun['swl_name'] = swl_name
            self.emurun['set_name'] = set_name
            result = find_roms(self.emurun, self.rom_paths)
            # Restore original values
            if old_swl is not None:
                self.emurun['swl_name'] = old_swl
            if old_set is not None:
                self.emurun['set_name'] = old_set
            return result
        else:
            find_roms(self.emurun, self.rom_paths)
            return None

    def extract_chd(self, sleep=None, dialog=None):
        """Extract MAME chd CD-ROM to CUE/BIN."""
        return extract_chd(self.emurun, self.chdman_exe, sleep, dialog)

    def extract_rom(self):
        """Extract MAME rom zipfile."""
        return extract_rom(self.emurun)

    def demul(self):
        """Set parameters for Demul.

        CMD: demul -run=[dc,naomi,awave,...] -rom=
        """
        return self.launch_preparer.demul(self.emurun)

    def fsuae(self):
        """Set parameters for FS-UAE.

        args: --floppies_dir=<temp_dir> --floppy_drive_0=disk1 ...
              --floppy_image_0=disk1 --floppy_image_1=disk2 ...
        or    --cdrom-drive-0=path/to/cd-image = cue/iso TODO test chd
        """
        self.launch_preparer.fsuae(self.emurun)

    def flycast(self):
        """Create symlink for Naomi GD-ROMs.

        TODO check if we have mame chds as disks and if found: only use dir and symlink
        to path where zip is found. if no disks: use zip name and check for dir with name
        in rompath and if not same path: symlink
        """
        self.launch_preparer.flycast(self.emurun)

    def mame(self):
        """MAME handling.

        TODO
        - make backup of cfg, check if changed, ask if to take over new cfg
          ^ what with default.cfg? also backup and ask
          ^ do i need to set -w anymore? no

        - general: delete for (swl: use machine)
          - cfg, diff, hi, nvram

        - general: when sta, offer to load?

        - psx: memcard with setname

        - saturn: own nvram (needed for others?)
        """

    def other_emulator(self, emu_infos, dialog=None, sleep=None):
        """Prepare run for other emulators."""
        return self.launch_preparer.other_emulator(self.emurun, emu_infos, dialog, sleep)
