"""Module for general emulation handling."""

import os
import shutil
import socket
import subprocess
from platform import platform
from random import randint
from select import select as select_wait
from threading import Event, Thread
from time import sleep as time_sleep
from zipfile import BadZipfile, ZipFile

from umsa_core import (
    ProcessRunner,
    ProcessState,
    ProcessStatus,
    calculate_playback_plan,
    log,
    parse_vgm_header,
)
from umsa_core.support import marp_download

PLATFORM = platform()
EXTENSIONS = {
    'snes'     : '.sfc',
    'gameboy'  : '.gb',
    'gbcolor'  : '.gbc',
    'gba'      : '.gba',
    'n64'      : '.n64',
    'n64dd'    : '.ndd',
    'nes'      : '.nes',
    'vboy'     : '.vb',
    'megadriv' : '.md',
    '32x'      : '.32x',
    'sms'      : '.sms'
}
NONMAME = ('exodos','gb64_quik','gb64_cart','gb64_cass','gb64_flop','whdload_games','whdload_demos')
CHD_PROCESS_STOP_TIMEOUT = 2


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


class CHDExtractionCancelled(Exception):
    """Raised when the user cancels a running CHD extraction."""


class CHDExtractionError(RuntimeError):
    """Raised when chdman fails to extract a CHD."""


def _terminate_and_reap_process(process):
    """Stop a child process, escalating to kill if it ignores terminate."""
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=CHD_PROCESS_STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.wait()
    else:
        process.wait()


def _remove_partial_chd(folder):
    """Remove the new extraction directory and any partial CHD output files."""
    if os.path.isdir(folder):
        shutil.rmtree(folder)

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

    fobj = False
    mame_ini = {}
    try:
        fobj = open(ini_file, 'r', encoding='utf-8')
    except OSError:
        pass
    if fobj:
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
        fobj.close()
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
        self.playvgm = False
        self.playintrovgm = False
        self.playrandomvgm = False
        self.mame_exe = mame_exe
        self.mame_dir = mame_dir
        self.chdman_exe = chdman_exe
        self.process = None
        self.process_runner = ProcessRunner()
        self.temp_dir = temp_dir
        self.emurun = {}
        self.lua_socket = None
        self.lua_server = None
        self.lua_log_thread = None
        self.lua_log_stop = None
        self.vgm_port_env = None
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

        alt = "shell"
        if 'alt' in emu_infos['exe']:
            alt = "alt"
        self.find_nonmame_roms(alt)
        self.emurun['args'] = []
        self.emurun['emulation_start'] = 2

    def prepare_marp_run(self, emu_infos):
        """Prepare ``emurun`` for a MARP replay."""

        self.emurun['emu_exe'] = self.mame_exe
        inp_file = marp_download(
            emu_infos['marp_dl'],
            self.input_directory)
        self.emurun['args'] = [
            emu_infos['set_name'], "-playback", inp_file, "-exit_after_playback"]

    def prepare_mame_run(self, ggdb, actset, dialog=None):
        """Prepare ``emurun['args']`` for MAME based on ``actset``."""

        self.emurun['emu_exe'] = self.mame_exe
        if actset['swl_name'] == 'mame':
            self.emurun['args'] = actset['name']
        # check for Gamebase64 files
        elif actset['swl_name'].startswith('gb64_'):
            filename = self.nonmame['gb64'] + 'Games/' + actset['name'] + '.zip'
            self.emurun['args'] = [
                'c64p', f"-{actset['swl_name'][-4:]}", filename]
        # start a swl item
        else:
            if dialog is not None:
                dialog.update(20, 'create swl options...')
            # get cmd options
            self.emurun['args'] = ggdb.get_cmd_line_options(
                actset['id'], actset['name'],
                actset['machine_name'], actset['swl_name'])

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

    def _start_lua_log_reader(self, conn):
        """Start the daemon reader thread for Lua -> Python log frames."""
        self._stop_lua_log_reader()
        stop = Event()
        self.lua_log_stop = stop
        thread = Thread(target=self._lua_log_reader, args=(conn, stop), daemon=True)
        self.lua_log_thread = thread
        thread.start()
        return thread

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

    def _log_lua_line(self, line):
        """Forward one Lua log frame to the addon logger, ignore anything else."""
        parsed = parse_lua_log_line(line)
        if not parsed:
            return False
        level, text = parsed
        log(f'{LUA_LOG_MSG_PREFIX}: {text}', level=level)
        return True

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

    def _close_vgm_sockets(self):
        self._close_accepted_conn()
        if self.lua_server:
            try:
                self.lua_server.close()
            except Exception:
                pass
        self.lua_server = None

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

        log(f"UMSA emu: play_vgm_thread, vgmplay_exe: {self.vgmplay_exe}")
        self.playvgm = True
        self.playintrovgm = intro
        if info:
            self._notify_vgm_info(info)
        # Use plan.seconds_to_run if provided, else sec2run (backward compat)
        actual_sec = plan.seconds_to_run if plan else sec2run
        vgm_args = ['-videodriver', 'dummy', '-video', 'none', '-volume', '1', '-seconds_to_run', str(int(actual_sec)),
            '-autoboot_script', self.lua_script,
            'vgmplay', '-quik', vgm]
        self.emurun = {
            'args': vgm_args,
            'emu_exe': self.vgmplay_exe or self.mame_exe,
            'emulation_start': 0,
            'working_dir': self.mame_dir,
            'env': self._vgm_process_env(),
        }
        try:
            self.run()
            self._accept_vgm_conn()
            # wait until emu is finished
            if self.process:
                # TODO wait is blocking, not good in a thread? have some poll loop?
                my_rc = self.process.wait()
                log(f'UMSA Emu: MAME vgmplay returncode = {my_rc}', level='debug')
            else:
                log(f'UMSA Emu: MAME vgmplay has not returned a process: {self.run}', level='debug')
        finally:
            self.playvgm = False
            if close_server:
                self._close_vgm_sockets()
            else:
                self._close_accepted_conn()
            if info:
                self._notify_vgm_stopped()

    def _notify_vgm_info(self, message):
        """Forward a VGM info message to the Kodi integration layer."""

        if self.vgm_info_callback:
            try:
                self.vgm_info_callback(message)
            except Exception as error:
                log(f'UMSA Emu: VGM info callback failed: {error}', level='warning')

    def _notify_vgm_stopped(self):
        """Forward the end of a VGM playback to the Kodi integration layer."""

        if self.vgm_stopped_callback:
            try:
                self.vgm_stopped_callback()
            except Exception as error:
                log(f'UMSA Emu: VGM stopped callback failed: {error}', level='warning')

    def _vgm_process_env(self):
        """Pass the port captured for this listener only to the MAME process."""
        env = os.environ.copy()
        if self.vgm_port_env is None:
            env.pop('VGMPLAY_PORT', None)
        else:
            env['VGMPLAY_PORT'] = self.vgm_port_env
        return env

    def play_random_vgm_thread(self, ggdb=None, textinfo=None, db_path=None, sleep=None):
        """Play random vgm until ordered to stop playing."""

        self.playrandomvgm = True
        self._start_vgm_server()
        try:
            while self.playrandomvgm:
                if not ggdb:
                    break
                random_vgm = ggdb.get_random_vgm(db_path)
                self.emurun['swl_name'] = 'vgmplay'
                self.emurun['set_name'] = random_vgm['name']
                self.find_roms()
                if not self.emurun['zips']:
                    log(f"UMSA Emu: play random vgm - {random_vgm['name']}.zip not found", level='warning')
                    continue
                vgm_zipfile = self.emurun['zips'][0]
                vgm_tracklist = ZipFile(vgm_zipfile).namelist()
                random_track = randint(1, len(vgm_tracklist))
                play_vgm = f'{random_vgm["name"]}:{random_track:03d}'
                # Parse header and calculate playback plan
                header = parse_vgm_header(
                    vgm_zipfile,
                    vgm_tracklist[random_track - 1],
                    logger=log,
                )
                plan = calculate_playback_plan(header)
                log(
                    f'UMSA Emu: VGM PLAN: {play_vgm} | {plan.reason} \n'
                    #f'UMSA Emu: VGM header_valid={header.header_valid} header_sane={header.header_sane} \n'
                    #f'UMSA Emu: VGM loop_only={header.loop_only} has_loop={header.has_loop} \n'
                    f'UMSA Emu: VGM total={header.total_seconds:.1f}s loop={header.loop_seconds:.1f}s \n'
                    f'UMSA Emu: VGM intro={header.intro_seconds:.1f}s -> run={plan.seconds_to_run:.1f}s reps={plan.loop_repetitions} \n',
                    #f'UMSA Emu: VGM vol_mod={header.volume_modifier} gain={header.header_gain_factor:.4f} gain_db={header.header_gain_db:.2f} \n'
                    #f'UMSA Emu: VGM extra_hdr={header.extra_header_present} chip_vol={header.has_chip_volumes}',
                    level='debug')
                vgm_nice = format_vgm_info(
                    vgm_tracklist[random_track - 1], random_vgm["gamename"], header, plan)
                if self.vgm_info_callback:
                    self.vgm_info_callback(vgm_nice)
                if textinfo:
                    try:
                        textinfo.setLabel(vgm_nice)
                    except Exception:
                        pass
                self.play_vgm_thread(play_vgm, sleep=sleep, close_server=False, plan=plan)
        finally:
            self._close_vgm_sockets()
            self.playrandomvgm = False
            self._notify_vgm_stopped()

    def play_random_vgm(self, ggdb=None, textinfo=None, db_path=None, sleep=None):

        if self.playvgm:
            return
        self.rvgm_thread = Thread(target=self.play_random_vgm_thread,
            args=(ggdb, textinfo, db_path, sleep))
        self.rvgm_thread.start()

    def play_vgm(self, vgm, sec2run=90, sleep=None, intro=False, info=None, plan=None):

        if self.playvgm:
            return
        self._start_vgm_server()
        self.pvgm_thread = Thread(target=self.play_vgm_thread,
            args=(vgm, sec2run, sleep, intro), kwargs={'info': info, 'plan': plan})
        self.pvgm_thread.start()

    def find_nonmame_roms(self, exodos_shell=''):
        """Search for files from other sources than MAME."""

        zips, chds = [], []
        filename = ''

        if self.emurun['swl_name'] == 'exodos':
            # TODO for real exodos usage we need to check platform and set right extension
            dosext = '.bat'
            log(f'UMSA Emu: Platform: {PLATFORM}', level='debug')
            log(f'UMSA Emu: - eXoDOS arg: "{exodos_shell}"', level='debug')
            log(f'UMSA Emu: - emurun: {self.emurun}', level='debug')
            dospath = self.nonmame['exodos']+'eXo/eXoDOS/!dos/'+self.emurun['set_name']
            if os.path.isdir(dospath):
                # check for start file, needed to find zip
                dosfiles = os.listdir(dospath)
                for i in dosfiles:
                    # exclude install|exception.*
                    if dosext in i and not any(x in i for x in ('install', 'exception')):
                        shellname = i
                        log(f'UMSA Emu: exodos search !dos: {i}', level='debug')
                        break
                # set normal or alternate exosdos launcher
                if exodos_shell == 'alt':
                    self.emurun['emu_exe'] = dospath+'/Extras/Alternate Launcher'+dosext
                    log(f'UMSA Emu: eXoDOS Shell: "{self.emurun["emu_exe"]}"', level='debug')
                elif exodos_shell == 'shell':
                    self.emurun['emu_exe'] = dospath+'/'+shellname
                    log(f'UMSA Emu: eXoDOS Shell: "{self.emurun["emu_exe"]}"', level='debug')
                # set zip- and filename
                zipname = os.path.basename(shellname)[:0-len(dosext)]+'.zip'
                filename = os.path.join(
                    self.nonmame['exodos']+'eXo/eXoDOS/'+zipname)
            else:
                log(f'UMSA Emu - no rom found: {dospath}', level='warning')
        elif 'gb64_' in self.emurun['swl_name']:
            log(f"UMSA Emu - gb64: {self.nonmame}", level='debug')
            filename = self.nonmame['gb64']+'Games/'+self.emurun['set_name']+'.zip'
        elif 'whdload' in self.emurun['swl_name']:
            # TODO emurun needs complete description
            log(f"UMSA Emu - whdload: {self.emurun['description']}", level='debug')
            filename = self.emurun['description'].replace(', ','_')
            filename = filename.replace('(','_').replace(')','').replace(' ','')
            filename = filename[0]+'/'+filename
            if filename[0].isnumeric():
                filename = '0'+filename[1:]
            if 'demo' in self.emurun['swl_name']:
                filename = filename+'_'+self.emurun['publisher']
            # remove spaces from name + _ + details ", " to "_"
            whdpath = self.emurun['swl_name'].split('_')[-1]+'/'
            # TODO 3x is no lha
            filename = self.nonmame['whdload']+whdpath+filename+'.lha'

        if os.path.isfile(filename):
            zips.append(filename)
            log(f'UMSA Emu: found file {filename}', level='info')
        else:
            log(f'UMSA Emu: file not found "{filename}"', level='warning')

        self.emurun['zips'] = zips
        self.emurun['chds'] = chds

    def find_roms(self, swl_name=None, set_name=None):
        """Search for rom zipfiles and chd files within MAME rompath."""

        zips, chds, all_chds = [], [], []
        # set zip name
        if swl_name and set_name:
            zip_name = os.path.join(swl_name, set_name+'.zip')
        elif self.emurun['swl_name'] == 'mame':
            zip_name = self.emurun['set_name']+'.zip'
        else:
            zip_name = os.path.join(self.emurun['swl_name'], self.emurun['set_name']+'.zip')
        # create chd filenames
        if ('disks' in self.emurun and self.emurun['disks'] and
                'disk' in self.emurun['disks'][0].keys() and
                self.emurun['disks'][0]['disk']
           ):
            for i in self.emurun['disks']:
                if 'disk' in i.keys():
                    all_chds.append(os.path.join(
                        self.emurun['swl_name'], self.emurun['set_name'],
                        '{}.chd'.format(i['disk'])))
                    # also check parent in case we have merged sets
                    if self.emurun['set_clone']:
                        all_chds.append(os.path.join(
                            self.emurun['swl_name'], self.emurun['set_clone'],
                            '{}.chd'.format(i['disk'])))
        # search filename
        log(f"UMSA Emu: search {zip_name}", level='debug')
        for path in self.rom_paths:
            # check for chd
            if all_chds:
                for i in all_chds:
                    chd_file = os.path.join(path, i)
                    if os.path.isfile(chd_file):
                        chds.append(chd_file)
            # check for zip
            zip_file = os.path.join(path, zip_name)
            if os.path.isfile(zip_file):
                log(f"UMSA Emu: found {zip_file}", level='debug')
                zips.append(zip_file)
        self.emurun['zips'] = zips
        self.emurun['chds'] = chds
        if swl_name and set_name:
            return zips[0]

    def extract_chd(self, sleep=None, dialog=None):
        """Extract MAME chd CD-ROM to CUE/BIN."""

        log("UMSA Emu: starting chd extract", level='info')
        chd_name = os.path.basename(self.emurun['chds'][0])
        # dc needs gdi extension
        if self.emurun['swl_name'] == 'dc':
            file_ext = '.gdi'
        else:
            file_ext = '.cue'
        # check if chd is already converted
        if os.path.exists(self.emurun['folder']):
            self.percent = 100
            self.emurun['extractcd'] = os.listdir(self.emurun['folder'])
            return ""
        os.mkdir(self.emurun['folder'])
        output_file = os.path.join(self.emurun['folder'], chd_name+file_ext)
        log("UMSA Emu: create process", level='debug')
        proc = None
        try:
            proc = subprocess.Popen(
                [self.chdman_exe, 'extractcd', '-i', self.emurun['chds'][0], '-o',
                 output_file],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.percent = 0
            log("UMSA Emu: checking process", level='debug')
            while proc.poll() is None:
                chdman_progress = proc.stderr.read(34)
                rpos = str(chdman_progress)[::-1].find('%')
                if rpos > -1:
                    pos = len(chdman_progress)-rpos-1
                    try:
                        self.percent = int(float(chdman_progress[pos-4:pos]))
                    except ValueError:
                        pass
                update_dialog(
                    dialog, self.percent, f'extracting chd: {self.percent}')
                if dialog and dialog.iscanceled():
                    _terminate_and_reap_process(proc)
                    _remove_partial_chd(self.emurun['folder'])
                    raise CHDExtractionCancelled("CHD extraction canceled")
                if sleep:
                    sleep(250)
                else:
                    time_sleep(250)
            return_code = proc.wait()
            log(
                f"UMSA Emu extract_rom: chd extract: RC = {return_code}",
                level='debug')
            if return_code == 0:
                self.emurun['extractcd'] = [chd_name+file_ext]
                return ""
            _remove_partial_chd(self.emurun['folder'])
            raise CHDExtractionError(
                f"chdman extraction failed with exit code {return_code}")
        except CHDExtractionCancelled:
            raise
        except Exception:
            if proc is not None:
                _terminate_and_reap_process(proc)
            if os.path.isdir(self.emurun['folder']):
                _remove_partial_chd(self.emurun['folder'])
            raise
        finally:
            if proc is not None:
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None:
                        stream.close()

    def extract_rom(self):
        """Extract MAME rom zipfile."""

        # only extract when folder does not exists
        if os.path.exists(self.emurun['folder']):
            zfiles = os.listdir(self.emurun['folder'])
        else:
            # extract zipfile
            os.makedirs(self.emurun['folder'])
            try:
                zfile = ZipFile(self.emurun['zips'][0])
                zfile.extractall(self.emurun['folder'])
                zfile.close()
            except BadZipfile:
                os.rmdir(self.emurun['folder'])
                return "Error: zipfile extraction was unsucessfull."
            zfiles = os.listdir(self.emurun['folder'])

            # TODO create single rom for cartridges
            # we don't have the complete xml output with
            # the rom info and it's actually not possible to do
            # './mame64 nes -cart skatedi2 -listxml' to get this info

            # simple hack to concatenate files so other emulators can read them
            if len(zfiles) == 2 and self.emurun['swl_name'] in EXTENSIONS:
                # hack swl nes: prg before chr
                if zfiles[0][-3:] == 'chr' and zfiles[1][-3:] == 'prg':
                    log(f"UMSA Emu extract_rom: NES: 2. is prg... {zfiles}", level='debug')
                    with open(os.path.join(self.emurun['folder'], zfiles[1]), "ab") as prg_file, open(os.path.join(self.emurun['folder'], zfiles[0]), "rb") as chr_file:
                        prg_file.write(chr_file.read())
                    prg_file.close()
                    chr_file.close()
                    os.remove(os.path.join(self.emurun['folder'], zfiles[0]))
                elif zfiles[0][-3:] == 'prg' and zfiles[1][-3:] == 'chr':
                    log(f"UMSA Emu extract_rom: NES: 1. is prg... {zfiles}", level='debug')
                    with open(os.path.join(self.emurun['folder'], zfiles[0]), "ab") as prg_file, open(os.path.join(self.emurun['folder'], zfiles[1]), "rb") as chr_file:
                        prg_file.write(chr_file.read())
                    prg_file.close()
                    chr_file.close()
                    os.remove(os.path.join(self.emurun['folder'], zfiles[1]))
                # rest is simply sorted by name
                else:
                    log(f"UMSA Emu extract_rom: joining rom files: {zfiles}", level='debug')
                    zfiles_sort = sorted(zfiles)
                    log(f"UMSA Emu extract_rom: sorted: {zfiles_sort}", level='debug')
                    with open(os.path.join(self.emurun['folder'], zfiles_sort[0]), "ab") as file1, open(os.path.join(self.emurun['folder'], zfiles_sort[1]), "rb") as file2:
                        file1.write(file2.read())
                    file1.close()
                    os.remove(os.path.join(self.emurun['folder'], zfiles_sort[1]))
                zfiles = os.listdir(self.emurun['folder'])
            # rename
            if self.emurun['swl_name'] in EXTENSIONS:
                if os.path.splitext(zfiles[0])[1] != EXTENSIONS[self.emurun['swl_name']]:
                    os.rename(
                        os.path.join(self.emurun['folder'], zfiles[0]),
                        os.path.join(self.emurun['folder'], "{}.{}".format(
                            zfiles[0], EXTENSIONS[self.emurun['swl_name']]
                        ))
                    )
                zfiles = os.listdir(self.emurun['folder'])
        self.emurun['extract_files'] = zfiles
        return ""

    def demul(self):
        """Set parameters for Demul.

        CMD: demul -run=[dc,naomi,awave,...] -rom=
        """

        err = ''
        params = []
        # dreamcast
        if self.emurun['swl_name'] == 'dc' and self.emurun['chds'][0]:
            # make symlink in tmp as spaces and brackets are not nice
            if 'Linux' in PLATFORM:
                self.emurun['symlink'] = os.path.join(
                    self.emurun['folder'], self.emurun['set_name'])
                os.symlink(self.emurun['chds'][0], self.emurun['symlink'])
            else:
                image = self.emurun['chds'][0]
            params.extend(['-run=dc', f'-image={image}'])
        # arcade
        else:
            # call -listroms to find parameter for -run=
            section = ''
            found = False
            try:
                listroms = subprocess.check_output([self.emurun['emu_exe'], '-listroms'])
            except subprocess.CalledProcessError:
                return "Error running Demul -listroms"
            for i in listroms.splitlines():
                i = i.decode('utf-8')
                if len(i) > 0 and i[0] != ' ':
                    section = i.rstrip()
                    log(f"UMSA Emu run_emulator: demul - section {section}", level='debug')
                elif self.emurun['set_name'] in i:
                    log(f"UMSA Emu run_emulator: demul - found {i}", level='debug')
                    found = True
                    break
            # Atomiswave exception
            if section == "Atomiswave":
                section = "awave"
            if found:
                params.extend([
                    f'-run={section.lower()}',
                    '-rom={0}'.format(self.emurun['set_name'])
                ])
            else:
                err = "Can't find rom in Demul's rom list."
        self.emurun['args'] = params
        return err

    def fsuae(self):
        """Set parameters for FS-USA.

        args: --floppies_dir=<temp_dir> --floppy_drive_0=disk1 ...
              --floppy_image_0=disk1 --floppy_image_1=disk2 ...
        or    --cdrom-drive-0=path/to/cd-image = cue/iso TODO test chd
        """

        params = []
        # set amiga model depending on softwarelist
        models = {'amigaaga_flop': "A1200", 'cd32': "CD32", 'cdtv': "CDTV"}
        try:
            params.append("--amiga_model={}".format(models[self.emurun['swl_name']]))
        except KeyError:
            params.append('--amiga_model=A500')
        # set cdrom/floppy
        if self.emurun['chds'] and self.emurun['chds'][0]:
            params.append('--cdrom-drive-0={}'.format(self.emurun['chds'][0]))
        else:
            # set floppies_dir
            params.append('--floppies_dir={}'.format(self.emurun['folder']))
            for count, file_name in enumerate(self.emurun['extract_files']):
                # set all floppy images so switching disk in fs-uae is available
                params.append('--floppy_image_{}={}'.format(
                    count, os.path.join(self.emurun['folder'], file_name)))
                # set up to 4 floppy drives with images
                if count <= 3:
                    params.append('--floppy_drive_{}={}'.format(
                        count, os.path.join(self.emurun['folder'], file_name)))
        self.emurun['args'] = params

    def flycast(self):
        """Create symlink for Naomi GD-ROMs.

        TODO check if we have mame chds as disks and if found: only use dir and symlink
        to path where zip is found. if no disks: use zip name and check for dir with name
        in rompath and if not same path: symlink
        """

        self.emurun['symlink'] = ""

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
        """Prepare run for other emulators.

        """
        ret_val = True
        update_dialog(dialog, 10, 'searching roms/chds...')

        # set temporary folder
        self.emurun['folder'] = os.path.join(self.temp_dir, "{}_{}".format(
            self.emurun['swl_name'], self.emurun['set_name']))
        # set emulator, working dir and mode
        self.emurun['emu_exe'] = emu_infos['exe']
        self.emurun['working_dir'] = emu_infos['dir']
        if 'mode' in emu_infos:
            self.emurun['emulation_start'] = emu_infos['mode']

        # find file by the name of the set
        log(f'UMSA Emu: check for nonmame: {self.emurun["swl_name"]}', level='debug')
        if self.emurun['swl_name'] in NONMAME:
            self.find_nonmame_roms()
        else:
            self.find_roms()

        if not self.emurun['zips']+self.emurun['chds']:
            log('UMSA Emu err: rom/chd not found', level='warning')
            ret_val = False
        # extract rom_file if needed
        elif not emu_infos['zip']:
            # TODO check len of zips, should not happen?
            if self.emurun['zips'] and self.emurun['zips'][0]:
                update_dialog(dialog, 20, 'extracting zip...')
                self.extract_rom()
            # extract 1st chd
            if self.emurun['chds'] and self.emurun['chds'][0]:
                update_dialog(dialog, 20, 'extracting chd...')
                self.extract_chd(sleep, dialog)
            # set args
            if 'extract_files' in self.emurun and self.emurun['extract_files'][0]:
                self.emurun['args'] = os.path.join(
                    self.emurun['folder'], self.emurun['extract_files'][0])
            elif 'extractcd' in self.emurun:
                self.emurun['args'] = os.path.join(
                    self.emurun['folder'], self.emurun['extractcd'][0])
        # set 1st rom or chd as argument
        else:
            if self.emurun['zips'] and self.emurun['zips'][0]:
                self.emurun['args'] = self.emurun['zips'][0]
            elif self.emurun['chds'] and self.emurun['chds'][0]:
                self.emurun['args'] = self.emurun['chds'][0]

        # special emulator handling
        if 'demul' in emu_infos['exe'].lower():
            err = self.demul()
            if err:
                log(f"UMSA Emu ERROR: {err}", level='warning')
                ret_val = False
        elif 'fs-uae-launcher' in emu_infos['exe'].lower():
            self.emurun['emulation_start'] = 2
            self.emurun['args'] = ['--no-gui', '--config:amiga-model=A1200', self.emurun['zips'][0]]
        elif 'fs-uae' in emu_infos['exe'].lower():
            self.fsuae()
        elif 'flycast' in emu_infos['name'].lower():
            self.flycast()

        return ret_val
