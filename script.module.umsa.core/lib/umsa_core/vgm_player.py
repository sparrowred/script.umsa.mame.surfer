"""VGM playback logic, header parsing, and playback callbacks.

This module handles VGM-specific logic: random VGM selection, header parsing,
playback plan calculation, and callback notifications. Socket management and
process execution are handled by the Emulation facade.
"""

import os
import time
from collections import deque
from random import randint
from threading import Event, Thread
from zipfile import BadZipFile, ZipFile

from umsa_core import log
from umsa_core.vgm_header import (
    MAX_PLAYBACK_SECONDS,
    format_vgm_status,
    format_vgm_title,
)
from umsa_core.vgm_socket import _parse_vgmplay_port, parse_lua_level_db

VGM_RANDOM_BATCH_SIZE = 100
VGM_RANDOM_MAX_CONSECUTIVE_UNPLAYABLE = 5
# Music info countdown: refresh interval and bounded join on stop
VGM_INFO_TICK_SECONDS = 1.0
VGM_INFO_TICKER_JOIN_TIMEOUT = 1.5


class VgmPlayer:
    """Handles VGM playback logic, header parsing, and callbacks.

    Socket management and process execution are handled by the Emulation facade.
    """

    def __init__(
        self,
        mame_exe,
        mame_dir,
        vgmplay_exe,
        vgmlua_script,
        rom_paths,
        vgm_info_callback=None,
        vgm_stopped_callback=None,
        max_vgm_duration=MAX_PLAYBACK_SECONDS,
    ):
        self.mame_exe = mame_exe
        self.mame_dir = mame_dir
        self.vgmplay_exe = vgmplay_exe
        self.lua_script = vgmlua_script
        self.rom_paths = rom_paths
        self._vgm_info_callback = vgm_info_callback
        self._vgm_stopped_callback = vgm_stopped_callback
        self.max_vgm_duration = max_vgm_duration

        self.playvgm = False
        self.playintrovgm = False
        self.playrandomvgm = False
        self._vgm_stopped_notified = False

        # music info countdown ("<title> -MM:ss (<dB> dB)")
        self._vgm_title = None
        self._planned_seconds = 0
        self._level_db = None
        self._info_ticker = None
        self._info_ticker_stop = None

    @property
    def vgm_info_callback(self):
        return self._vgm_info_callback

    @vgm_info_callback.setter
    def vgm_info_callback(self, value):
        self._vgm_info_callback = value

    @property
    def vgm_stopped_callback(self):
        return self._vgm_stopped_callback

    @vgm_stopped_callback.setter
    def vgm_stopped_callback(self, value):
        self._vgm_stopped_callback = value

    def _vgm_process_env(self, vgm_port_env):
        """Pass the port captured for this listener only to the MAME process."""
        env = os.environ.copy()
        port = _parse_vgmplay_port(vgm_port_env)
        if port is None:
            env.pop('VGMPLAY_PORT', None)
        else:
            env['VGMPLAY_PORT'] = str(port)
        return env

    def _notify_vgm_info(self, message):
        """Forward a VGM info message to the Kodi integration layer."""
        if self.vgm_info_callback:
            try:
                self.vgm_info_callback(message)
            except Exception as error:
                log(f'UMSA Emu: VGM info callback failed: {error}', level='warning')

    def vgm_status(self, remaining_seconds):
        """Music info line for the current track."""
        return format_vgm_status(self._vgm_title, remaining_seconds, self._level_db)

    def on_lua_log(self, text):
        """Lua log frame listener: keep the last ``eff_db`` of ``LEVEL_ADJ``."""
        level_db = parse_lua_level_db(text)
        if level_db is not None:
            self._level_db = level_db

    def start_info_ticker(self, clock=time.monotonic):
        """Count the music info down once per second until stopped.

        Started when vgmplay.lua connected, i.e. when playback begins. Does
        nothing for playbacks without a title (intro VGM).
        """
        self.stop_info_ticker()
        if not self._vgm_title:
            return
        stop = Event()
        started = clock()
        planned = self._planned_seconds

        def tick():
            while True:
                remaining = planned - (clock() - started)
                self._notify_vgm_info(self.vgm_status(remaining))
                if remaining <= 0 or stop.wait(VGM_INFO_TICK_SECONDS):
                    return

        self._info_ticker_stop = stop
        self._info_ticker = Thread(target=tick, name='vgm-info-ticker', daemon=True)
        self._info_ticker.start()

    def stop_info_ticker(self):
        """Stop the music info countdown (bounded join)."""
        ticker, stop = self._info_ticker, self._info_ticker_stop
        self._info_ticker = self._info_ticker_stop = None
        if stop:
            stop.set()
        if ticker and ticker.is_alive():
            ticker.join(VGM_INFO_TICKER_JOIN_TIMEOUT)

    def _notify_vgm_stopped(self):
        """Forward the end of a VGM playback to the Kodi integration layer.

        The callback is delivered at most once per playback: the playback
        owner and the playback worker can both reach the end of a track, and
        the Kodi layer must only be told once that the VGM stopped.
        """
        if self._vgm_stopped_notified:
            return
        self._vgm_stopped_notified = True
        if self.vgm_stopped_callback:
            try:
                self.vgm_stopped_callback()
            except Exception as error:
                log(f'UMSA Emu: VGM stopped callback failed: {error}', level='warning')

    def begin_vgm_playback(self):
        """Mark the start of a new playback.

        Clears the one-shot guard of the stopped callback so the next
        playback reports its end again.
        """
        self._vgm_stopped_notified = False

    def prepare_vgm_run(self, emurun, vgm, sec2run=90, intro=False, plan=None, info=None,
                        vgm_port_env=None, title=None):
        """Prepare emurun dict for VGM playback.

        Args:
            emurun: Emulation run state dict (will be updated)
            vgm: VGM identifier string
            sec2run: Seconds to run (fallback if plan not provided)
            intro: Whether this is an intro VGM
            plan: Optional PlaybackPlan object
            info: Optional music info title (``format_vgm_title``)
            vgm_port_env: VGMPLAY_PORT value for the process environment
            title: Music info title without the stop notification of ``info``
                (random playback); defaults to ``info``

        Returns:
            Tuple of (vgm_args, env_dict) for process execution
        """
        self.begin_vgm_playback()
        self.playvgm = True
        self.playintrovgm = intro
        actual_sec = min(
            plan.seconds_to_run if plan else sec2run,
            self.max_vgm_duration,
        )
        self._vgm_title = title or info
        self._planned_seconds = int(actual_sec)
        self._level_db = None
        if self._vgm_title:
            self._notify_vgm_info(self.vgm_status(self._planned_seconds))
        vgm_args = ['-videodriver', 'dummy', '-video', 'none', '-nojoystick', '-nowriteconfig',
            '-seconds_to_run', str(int(actual_sec)), '-autoboot_script', self.lua_script,
            '-volume', '1', 'vgmplay', '-quik', vgm]
        emurun.update({
            'args': vgm_args,
            'emu_exe': self.vgmplay_exe or self.mame_exe,
            'emulation_start': 0,
            'working_dir': self.mame_dir,
            'env': self._vgm_process_env(vgm_port_env),
        })
        return vgm_args, emurun['env']

    def play_random_vgm_thread(self, emurun, ggdb=None, textinfo=None, db_path=None, sleep=None,
                               find_roms_func=None, run_func=None):
        """Play random vgm until ordered to stop playing.

        Candidates are fetched from the database in batches and kept in an
        in-memory queue; a new batch is requested only when the queue runs
        out. Filesystem and archive checks stay in this player. After
        ``VGM_RANDOM_MAX_CONSECUTIVE_UNPLAYABLE`` candidates in a row cannot
        start playback, random playback stops.

        Args:
            emurun: Emulation run state dict
            ggdb: Database object with get_random_vgm_batch method
            textinfo: Optional Kodi text control for display
            db_path: Database path
            sleep: Optional sleep callback
            find_roms_func: Function to find ROMs (emurun, rom_paths) -> None
            run_func: Function to run a single VGM track (vgm, sleep, close_server, plan, info, vgm_port_env)
        """
        self.playrandomvgm = True
        candidates = deque()
        consecutive_unplayable = 0

        def note_unplayable(message):
            """Log an unusable candidate and report whether to stop playback."""
            nonlocal consecutive_unplayable
            log(message, level='warning')
            consecutive_unplayable += 1
            if consecutive_unplayable >= VGM_RANDOM_MAX_CONSECUTIVE_UNPLAYABLE:
                log(
                    'UMSA Emu: play random vgm - stopping after '
                    f'{VGM_RANDOM_MAX_CONSECUTIVE_UNPLAYABLE} consecutive '
                    'unplayable candidates',
                    level='warning')
                return True
            return False

        try:
            while self.playrandomvgm:
                if not ggdb:
                    break
                if not candidates:
                    candidates.extend(
                        ggdb.get_random_vgm_batch(db_path, VGM_RANDOM_BATCH_SIZE))
                    if not candidates:
                        log(
                            'UMSA Emu: play random vgm - no candidates in '
                            'database batch, stopping',
                            level='warning')
                        break
                random_vgm = candidates.popleft()
                emurun['swl_name'] = 'vgmplay'
                emurun['set_name'] = random_vgm['name']
                if find_roms_func:
                    find_roms_func(emurun, self.rom_paths)
                else:
                    from umsa_core.rom_finder import find_roms
                    find_roms(emurun, self.rom_paths)
                if not emurun['zips']:
                    if note_unplayable(
                            f"UMSA Emu: play random vgm - {random_vgm['name']}.zip not found"):
                        break
                    continue
                vgm_zipfile = emurun['zips'][0]
                try:
                    with ZipFile(vgm_zipfile) as archive:
                        vgm_tracklist = archive.namelist()
                except (BadZipFile, OSError) as error:
                    if note_unplayable(
                            f'UMSA Emu: play random vgm - unreadable '
                            f'{random_vgm["name"]}.zip: {error}'):
                        break
                    continue
                if not vgm_tracklist:
                    if note_unplayable(
                            f'UMSA Emu: play random vgm - no tracks in '
                            f'{random_vgm["name"]}.zip'):
                        break
                    continue
                random_track = randint(1, len(vgm_tracklist))
                play_vgm = f'{random_vgm["name"]}:{random_track:03d}'
                # Parse header and calculate playback plan
                from umsa_core.vgm_header import (
                    calculate_playback_plan,
                    parse_vgm_header,
                )
                header = parse_vgm_header(
                    vgm_zipfile,
                    vgm_tracklist[random_track - 1],
                    logger=log,
                )
                plan = calculate_playback_plan(
                    header, max_seconds=self.max_vgm_duration)
                log(
                    f'UMSA Emu: VGM PLAN: {play_vgm} | {plan.reason} \n'
                    f'UMSA Emu: VGM total={header.total_seconds:.1f}s loop={header.loop_seconds:.1f}s \n'
                    f'UMSA Emu: VGM intro={header.intro_seconds:.1f}s -> run={plan.seconds_to_run:.1f}s reps={plan.loop_repetitions} \n',
                    level='debug')
                vgm_title = format_vgm_title(
                    vgm_tracklist[random_track - 1], random_vgm["gamename"])
                vgm_nice = format_vgm_status(
                    vgm_title, min(plan.seconds_to_run, self.max_vgm_duration))
                self._notify_vgm_info(vgm_nice)
                if textinfo:
                    try:
                        textinfo.setLabel(vgm_nice)
                    except Exception as error:
                        log(f'UMSA Emu: VGM label update failed: {error}', level='debug')
                consecutive_unplayable = 0
                if run_func:
                    run_func(play_vgm, sleep=sleep, close_server=False, plan=plan,
                             title=vgm_title)
        finally:
            self.playrandomvgm = False
            self._notify_vgm_stopped()

    def play_random_vgm(self, ggdb=None, textinfo=None, db_path=None, sleep=None,
                        emurun=None, find_roms_func=None, run_func=None):
        """Start random VGM playback in a thread."""
        if self.playvgm:
            return
        self.begin_vgm_playback()
        self.rvgm_thread = Thread(target=self.play_random_vgm_thread,
            args=(emurun, ggdb, textinfo, db_path, sleep),
            kwargs={'find_roms_func': find_roms_func, 'run_func': run_func})
        self.rvgm_thread.start()

    def play_vgm(self, vgm, sec2run=90, sleep=None, intro=False, info=None, plan=None,
                 emurun=None, run_func=None, vgm_port_env=None):
        """Start VGM playback in a thread.

        The worker is ``_play_vgm_thread_impl``. Every argument is handed
        over as a keyword so the forwarding stays correct when the
        implementation signature changes.

        Args:
            vgm: VGM identifier string
            sec2run: Seconds to run (fallback if plan not provided)
            sleep: Optional sleep callback
            intro: Whether this is an intro VGM
            info: Optional info message for callback
            plan: Optional PlaybackPlan object
            emurun: Emulation run state dict
            run_func: Function running the track
                (vgm, sleep, close_server, plan, info, vgm_port_env)
            vgm_port_env: VGMPLAY_PORT value for the process environment
        """
        if self.playvgm:
            return
        port_str = str(vgm_port_env) if vgm_port_env is not None else None
        self.begin_vgm_playback()
        self.playvgm = True
        self.pvgm_thread = Thread(target=self._play_vgm_thread_impl,
            kwargs={
                'emurun': emurun,
                'vgm': vgm,
                'sec2run': sec2run,
                'sleep': sleep,
                'intro': intro,
                'info': info,
                'plan': plan,
                'vgm_port_env': port_str,
                'run_func': run_func,
            })
        try:
            self.pvgm_thread.start()
        except Exception:
            self.playvgm = False
            raise

    def _play_vgm_thread_impl(self, emurun, vgm, sec2run, sleep, intro, info, plan, vgm_port_env, run_func):
        """Internal implementation of VGM playback thread.

        Prepares the run, hands the track over to ``run_func`` and always
        resets the playback state afterwards, also when the playback fails.
        """
        port_str = str(vgm_port_env) if vgm_port_env is not None else None
        try:
            self.prepare_vgm_run(emurun, vgm, sec2run, intro=intro, plan=plan,
                                 info=info, vgm_port_env=port_str)
            if run_func:
                run_func(vgm, sleep=sleep, close_server=True, plan=plan, info=info,
                         vgm_port_env=port_str)
        finally:
            self.playvgm = False
            if info:
                self._notify_vgm_stopped()
