"""Module for general emulation handling."""

import os
import shlex
import subprocess
from platform import platform
from threading import Event, Thread, current_thread
from time import monotonic

from umsa_core import (
    ProcessLaunchError,
    ProcessRunner,
    ProcessState,
    ProcessStatus,
    log,
)

# Compatibility re-exports for existing code that imports from emulation.
from umsa_core.abort import ShutdownRequested, resolve_wait
from umsa_core.chd_extractor import (
    CHDExtractionCancelled,  # noqa: F401
    CHDExtractionError,  # noqa: F401
    extract_chd,
)
from umsa_core.launch_preparer import LaunchPreparer
from umsa_core.rom_extractor import extract_rom
from umsa_core.rom_finder import (
    NONMAME,  # noqa: F401
    find_nonmame_roms,
    find_roms,
)
from umsa_core.vgm_header import (
    MAX_PLAYBACK_SECONDS,
    format_vgm_title,  # noqa: F401  (re-exported for the GUI)
)
from umsa_core.vgm_player import (
    VGM_RANDOM_BATCH_SIZE,  # noqa: F401  (re-exported)
    VGM_RANDOM_MAX_CONSECUTIVE_UNPLAYABLE,  # noqa: F401  (re-exported)
    VgmPlayer,
)
from umsa_core.vgm_socket import VgmSocketServer

PLATFORM = platform()
CHD_PROCESS_STOP_TIMEOUT = 2
# stop_vgm(): time the VGM workers get to end after the stop request, and
# after the kill that follows when they did not
VGM_STOP_TIMEOUT = 3.0
VGM_KILL_JOIN_TIMEOUT = 1.0


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
                    chdman_exe=None, vgmlua_script=None, vgm_info_callback=None, nonmame=None,
                    terminal='', vgmplay_exe='', vgm_stopped_callback=None,
                    vgm_max_duration=MAX_PLAYBACK_SECONDS, rom_cache=False,
                    cache_layout=None):
        self.percent = 0 # chd convert
        self.mame_exe = mame_exe
        self.mame_dir = mame_dir
        self.chdman_exe = chdman_exe
        self.process = None
        # VGM playback: the MAME process of the running track, the stop
        # request of stop_vgm() and the worker threads
        self._vgm_process = None
        self._vgm_stop = Event()
        self.rvgm_thread = None
        self.pvgm_thread = None
        self.process_runner = ProcessRunner()
        self.temp_dir = temp_dir
        self.emurun = {}
        self.lua_script = vgmlua_script
        # A fresh dict per instance, so instances never share one default
        self.nonmame = nonmame if nonmame is not None else {}
        self.terminal = terminal
        self.vgmplay_exe = vgmplay_exe

        self.mame_ini = self._load_mame_ini(mame_ini_file, mame_dir)

        self.launch_preparer = LaunchPreparer(
            mame_exe=mame_exe,
            mame_dir=mame_dir,
            nonmame=self.nonmame,
            mame_ini=self.mame_ini,
            temp_dir=temp_dir,
            terminal=terminal,
            chdman_exe=chdman_exe,
            find_roms=find_roms,
            find_nonmame_roms=find_nonmame_roms,
            extract_rom=extract_rom,
            extract_chd=extract_chd,
            rom_cache=rom_cache,
            cache_layout=cache_layout,
        )

        self.vgm_player = VgmPlayer(
            mame_exe=mame_exe,
            mame_dir=mame_dir,
            vgmplay_exe=vgmplay_exe,
            vgmlua_script=vgmlua_script,
            rom_paths=self.mame_ini.get('rompath', []),
            vgm_info_callback=vgm_info_callback,
            vgm_stopped_callback=vgm_stopped_callback,
            max_vgm_duration=vgm_max_duration,
        )

        # VGM socket transport
        self.vgm_socket = VgmSocketServer(
            logger=log,
            process_exited=lambda: self.process is not None and self.process.poll() is not None,
            # eff_db of LEVEL_ADJ frames feeds the music info
            frame_listener=self.vgm_player.on_lua_log,
        )

    @staticmethod
    def _load_mame_ini(mame_ini_file, mame_dir):
        """Parsed mame.ini with its paths resolved, {} without a file."""
        if not mame_ini_file:
            return {}
        return resolve_mame_paths(parse_mame_ini(mame_ini_file), mame_dir)

    def apply_settings(self, temp_dir, mame_ini_file, mame_dir, mame_exe, chdman_exe,
                       nonmame, terminal, vgmplay_exe, vgm_max_duration,
                       rom_cache=False, cache_layout=None):
        """Take over changed settings without recreating the instance.

        Keeps the running process, the VGM socket and the playback state;
        an emulator or VGM track that already runs keeps its arguments, the
        next start uses the new values. LaunchPreparer and VgmPlayer hold
        copies, so they are updated too.
        """
        self.temp_dir = temp_dir
        self.mame_dir = mame_dir
        self.mame_exe = mame_exe
        self.chdman_exe = chdman_exe
        self.nonmame = nonmame if nonmame is not None else {}
        self.terminal = terminal
        self.vgmplay_exe = vgmplay_exe
        self.mame_ini = self._load_mame_ini(mame_ini_file, mame_dir)

        preparer = self.launch_preparer
        preparer.mame_exe = mame_exe
        preparer.mame_dir = mame_dir
        preparer.nonmame = self.nonmame
        preparer.mame_ini = self.mame_ini
        preparer.temp_dir = temp_dir
        preparer.terminal = terminal
        preparer.chdman_exe = chdman_exe
        preparer.rom_cache = rom_cache
        preparer.cache_layout = cache_layout

        player = self.vgm_player
        player.mame_exe = mame_exe
        player.mame_dir = mame_dir
        player.vgmplay_exe = vgmplay_exe
        player.rom_paths = self.mame_ini.get('rompath', [])
        player.max_vgm_duration = vgm_max_duration

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
    def snapshot_directory(self):
        """Absolute MAME snapshot directory ('' when unset)."""

        return self.mame_ini.get('snapshot_directory', '')

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
        # Watch has no pipes here: nothing reads the output of this process
        # (captured launches go through start_managed_process)
        if self.emurun['emulation_start'] in (0, 1): # Normal, Watch
            self.process = subprocess.Popen(
                args, cwd=self.emurun['working_dir'], **popen_env)
        elif self.emurun['emulation_start'] == 2: # Fallback
            self.process = None
            # most terminals hand the -e string to a shell; shlex.join quotes
            # every argument so names with quotes, $() or backticks stay data
            torun = [self.terminal, '-e', shlex.join(args)]
            launch_id = self.emurun.get("launch_id", "unknown")
            started_at = monotonic()
            log(
                f'UMSA Emulation: launch={launch_id} starting terminal '
                f'fallback command={args!r} working_dir='
                f'{self.emurun.get("working_dir")!r} terminal_command={torun!r}',
                level='debug')
            try:
                completed = subprocess.run(torun, check=False)
            except OSError as error:
                log(
                    f'UMSA Emulation: launch={launch_id} could not start '
                    f'terminal fallback '
                    f'{torun!r}: {error}', level='error')
                raise ProcessLaunchError(
                    f'could not start terminal fallback {torun!r}: {error}'
                ) from error
            duration = monotonic() - started_at
            log(
                f'UMSA Emulation: launch={launch_id} terminal fallback '
                f'completed with exit code {completed.returncode} after '
                f'{duration:.3f}s',
                level='debug')
            if completed.returncode != 0:
                log(
                    f'UMSA Emulation: launch={launch_id} terminal fallback '
                    f'exited with code {completed.returncode}: {torun!r}',
                    level='error')

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
        launch_id = self.emurun.get("launch_id", "unknown")
        working_dir = self.emurun['working_dir']
        log(
            f"UMSA Emulation: launch={launch_id} starting managed process "
            f"command={args!r} working_dir={working_dir!r}",
            level="debug",
        )
        try:
            self.process_runner.start(
                args,
                cwd=working_dir,
                capture_output=capture_output,
                env=self.emurun.get('env'),
            )
        except OSError as error:
            log(
                f"UMSA Emulation: launch={launch_id} managed process "
                f"startup failed: {error}",
                level="error",
            )
            raise
        log(
            f"UMSA Emulation: launch={launch_id} managed process started",
            level="debug",
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

    def wait_for_completion(self, dialog=None, sleep=None, wait=None):
        """Wait for the running emulator to stop or the user to cancel.

        Returns ``(stdout, stderr)``. ``wait`` is an abort-aware
        ``wait(milliseconds) -> bool`` (``umsa_core.abort.Wait``); without it
        the legacy millisecond ``sleep`` (for example ``xbmc.sleep``) or
        ``time.sleep`` is used and no stop request is ever seen.

        Raises ``ShutdownRequested`` when the host asks to stop while the
        emulator runs. The emulator keeps running (it is detached, neither
        terminated nor killed) and its captured output is not read; it keeps
        writing to the temporary files of the process runner.
        """

        wait = resolve_wait(wait, sleep)
        uses_process_runner = self.emurun['emulation_start'] in (0, 1)
        out, err = '', ''
        # wait for emulator process to stop or cancel press to kill
        wait_cancel = True
        while wait_cancel:
            if wait(1000):
                log(
                    "UMSA Emulation: shutdown requested, leaving the emulator "
                    "running (detached)",
                    level='warning')
                raise ShutdownRequested("shutdown while the emulator runs")
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
                # a shutdown request ends the grace time early: kill at once
                wait(3000)
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

        emurun = self.emurun
        try:
            self.launch_preparer.cleanup_symlinks(emurun)
        finally:
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

    def _vgm_workers(self):
        """Running VGM worker threads, without the calling thread."""
        return [
            thread for thread in (self.rvgm_thread, self.pvgm_thread)
            if thread is not None and thread is not current_thread()
            and thread.is_alive()]

    def _end_vgm_process(self, how):
        """Terminate or kill the MAME process of the running track."""
        process = self._vgm_process
        if process is None or process.poll() is not None:
            return
        log(f'UMSA Emu: stop vgm - {how} MAME vgmplay', level='debug')
        try:
            getattr(process, how)()
        except Exception as error:
            log(f'UMSA Emu: stop vgm - could not {how} MAME vgmplay: {error}',
                level='warning')

    def stop_vgm(self, timeout=VGM_STOP_TIMEOUT):
        """Stop the VGM playback (random and single track) in every state.

        ``exit`` over the Lua socket ends a connected track. Without a
        connection (MAME still starting) the process is terminated, and a
        random playback that sits between two tracks starts no further one.
        The workers get ``timeout`` seconds to end; the process is killed
        when they do not. ``timeout=0`` does not wait (Kodi window handlers).

        Returns True when no VGM worker runs any more. Never raises.
        """
        self._vgm_stop.set()
        self.playrandomvgm = False
        try:
            sent = self.send_vgmaction(b'exit')
        except Exception as error:
            log(f'UMSA Emu: stop vgm - exit command failed: {error}', level='warning')
            sent = False
        if not sent:
            self._end_vgm_process('terminate')
        if timeout <= 0:
            return not self._vgm_workers()

        deadline = monotonic() + timeout
        for thread in self._vgm_workers():
            thread.join(max(0.0, deadline - monotonic()))
        if self._vgm_workers():
            self._end_vgm_process('kill')
            deadline = monotonic() + VGM_KILL_JOIN_TIMEOUT
            for thread in self._vgm_workers():
                thread.join(max(0.0, deadline - monotonic()))
        if self._vgm_workers():
            log('UMSA Emu: stop vgm - playback thread still running', level='warning')
            return False
        return True

    def play_vgm_thread(self, vgm, sec2run=90, sleep=None, intro=False, close_server=True,
                    plan=None, info=None, title=None):
        """Play vgm.

        ``info`` (single track) and ``title`` (random playback, no stop
        notification per track) are the music info title; once vgmplay.lua
        connected the info counts the remaining time down.

        Returns False when MAME ended with an error before vgmplay.lua
        connected (broken MAME setup or script), True otherwise.
        """
        port = self.vgm_socket.bound_port
        port_str = str(port) if port is not None else None
        self.vgm_player.prepare_vgm_run(self.emurun, vgm, sec2run, intro, plan, info, port_str,
                                        title=title)
        try:
            if self._vgm_stop.is_set():
                # stopped while the track was prepared: do not start MAME
                return True
            self.run()
            # keep the process of this track: self.process also serves
            # emulator launches
            process = self._vgm_process = self.process
            if self._vgm_stop.is_set():
                # stop_vgm() ran before the process existed
                self._end_vgm_process('terminate')
            connected = self._accept_vgm_conn()
            if connected:
                self.vgm_player.start_info_ticker()
            # wait until emu is finished
            if process:
                my_rc = process.wait()
                log(f'UMSA Emu: MAME vgmplay returncode = {my_rc}', level='debug')
                if not connected and my_rc != 0 and not self._vgm_stop.is_set():
                    log(
                        f'UMSA Emu: MAME vgmplay failed before the Lua script '
                        f'connected (returncode {my_rc})', level='warning')
                    return False
            else:
                log(f'UMSA Emu: MAME vgmplay has not returned a process: {self.run}', level='debug')
            return True
        finally:
            self._vgm_process = None
            self.vgm_player.stop_info_ticker()
            self.playvgm = False
            if close_server:
                self._close_vgm_sockets()
            else:
                self.vgm_socket.close_client()
            if info:
                self.vgm_player._notify_vgm_stopped()

    def play_random_vgm_thread(self, ggdb=None, textinfo=None, db_path=None, sleep=None):
        """Play random vgm until ordered to stop playing."""
        self.vgm_player.begin_vgm_playback()
        if not self._start_vgm_server():
            self.playrandomvgm = False
            self.vgm_player._notify_vgm_stopped()
            return
        def run_func(vgm, sleep=None, close_server=True, plan=None, info=None, vgm_port_env=None,
                     title=None):
            return self.play_vgm_thread(
                vgm, sec2run=90, sleep=sleep, intro=False,
                close_server=close_server, plan=plan, info=info, title=title)

        try:
            self.vgm_player.play_random_vgm_thread(
                self.emurun, ggdb, textinfo, db_path, sleep,
                find_roms_func=lambda emurun, rom_paths: self.find_roms(),
                run_func=run_func)
        finally:
            self._close_vgm_sockets()

    def play_random_vgm(self, ggdb=None, textinfo=None, db_path=None, sleep=None):
        """Start random vgm playback in a thread.

        The socket server lifecycle stays with ``play_random_vgm_thread``,
        this wrapper only owns the worker thread.
        """
        if self.playvgm:
            return
        self._vgm_stop.clear()
        self.vgm_player.begin_vgm_playback()
        self.rvgm_thread = Thread(target=self.play_random_vgm_thread,
            args=(ggdb, textinfo, db_path, sleep))
        self.rvgm_thread.start()

    def play_vgm(self, vgm, sec2run=90, sleep=None, intro=False, info=None, plan=None):
        if self.playvgm:
            return
        self._vgm_stop.clear()
        self.vgm_player.begin_vgm_playback()
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

    def extract_chd(self, sleep=None, dialog=None, wait=None):
        """Extract MAME chd CD-ROM to CUE/BIN."""
        return extract_chd(self.emurun, self.chdman_exe, sleep, dialog, wait)

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

    def other_emulator(self, emu_infos, dialog=None, sleep=None, wait=None):
        """Prepare run for other emulators."""
        return self.launch_preparer.other_emulator(
            self.emurun, emu_infos, dialog, sleep, wait=wait)
