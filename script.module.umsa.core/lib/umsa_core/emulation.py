"""Module for general emulation handling."""

import os
import socket
import subprocess
from platform import platform
from threading import Thread
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
from umsa_core.vgm_socket import VgmSocketServer, parse_lua_log_line

# Compatibility re-exports for existing code that imports from emulation
from umsa_core.vgm_socket import (
    LUA_LOG_TAG,
    LUA_LOG_LEVELS,
    LUA_LOG_FALLBACK_LEVEL,
    LUA_LOG_MSG_PREFIX,
    LUA_READ_POLL_TIMEOUT,
    LUA_READER_JOIN_TIMEOUT,
    LUA_LOG_MAX_LINE_BYTES,
    VGMPLAY_DEFAULT_PORT,
    _parse_vgmplay_port,
    parse_lua_log_line,
)

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

        # VGM socket transport
        self.vgm_socket = VgmSocketServer(
            logger=log,
            process_exited=lambda: self.process is not None and self.process.poll() is not None,
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
    vgm_port_env = None

    # Compatibility properties for socket access
    @property
    def lua_server(self):
        return self.vgm_socket._listener

    @lua_server.setter
    def lua_server(self, value):
        self.vgm_socket._listener = value

    @property
    def lua_socket(self):
        return self.vgm_socket._client

    @lua_socket.setter
    def lua_socket(self, value):
        self.vgm_socket._client = value

    @property
    def lua_log_thread(self):
        return self.vgm_socket._reader_thread

    @property
    def lua_log_stop(self):
        return self.vgm_socket._reader_stop

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
        # Use the raw environment variable value for the child process,
        # not the parsed port. This preserves the original behavior where
        # an unset VGMPLAY_PORT results in no VGMPLAY_PORT in the child env.
        port_env = os.environ.get('VGMPLAY_PORT')
        return self.vgm_player._vgm_process_env(port_env)

    def _start_vgm_server(self):
        """Create and start listening socket for vgmplay.lua (client)."""
        port_env = os.environ.get('VGMPLAY_PORT')
        if not self.vgm_socket.start_server(port_env):
            log("UMSA VGM: failed to start socket server, VGM playback disabled", level='warning')
            self.vgm_socket.close_server()
            return False
        return True

    def _accept_vgm_conn(self):
        """Accept connection from vgmplay.lua client with bounded waiting."""
        return self.vgm_socket.wait_for_connection(timeout=30.0)

    def _close_vgm_sockets(self):
        self.vgm_socket.close_server()

    def send_vgmaction(self, data):
        """Send command to MAME Lua script over accepted socket connection."""
        return self.vgm_socket.send_command(data)

    def _start_lua_log_reader(self, conn):
        """Compatibility wrapper: start the daemon reader thread for Lua -> Python log frames."""
        return self.vgm_socket._start_reader(conn)

    def _stop_lua_log_reader(self):
        """Compatibility wrapper: signal the reader thread to drain and exit."""
        self.vgm_socket._stop_reader()

    def _close_accepted_conn(self):
        """Compatibility wrapper: close the accepted client connection."""
        self.vgm_socket.close_client()

    def _drain_lua_log(self, conn, buf=b''):
        """Compatibility wrapper: read frames already buffered by the kernel."""
        return self.vgm_socket._drain_buffer(conn, buf)

    def play_vgm_thread(self, vgm, sec2run=90, sleep=None, intro=False, close_server=True,
                    plan=None, info=None):
        """Play vgm."""
        port = self.vgm_socket.bound_port
        port_str = str(port) if port is not None else None
        self.vgm_player.prepare_vgm_run(self.emurun, vgm, sec2run, intro, plan, info, port_str)
        try:
            self.run()
            self._accept_vgm_conn()
            # wait until emu is finished
            if self.process:
                my_rc = self.process.wait()
                log(f'UMSA Emu: MAME vgmplay returncode = {my_rc}', level='debug')
            else:
                log(f'UMSA Emu: MAME vgmplay has not returned a process: {self.run}', level='debug')
        finally:
            self.playvgm = False
            if close_server:
                self._close_vgm_sockets()
            else:
                self.vgm_socket.close_client()
            if info:
                self.vgm_player._notify_vgm_stopped()

    def play_random_vgm_thread(self, ggdb=None, textinfo=None, db_path=None, sleep=None):
        """Play random vgm until ordered to stop playing."""
        if not self._start_vgm_server():
            self.playrandomvgm = False
            self.vgm_player._notify_vgm_stopped()
            return
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
        if not self._start_vgm_server():
            self.playvgm = False
            if info:
                self.vgm_player._notify_vgm_stopped()
            return
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
