"""VGM track preparation, random track selection and the music info.

Sockets, processes and the playback threads belong to
:class:`umsa_core.emulation.Emulation`.
"""

import os
import secrets
import time
from collections import deque
from random import randint
from threading import Event, Thread
from zipfile import BadZipFile, ZipFile

from umsa_core import log
from umsa_core.game_repository import random_vgm_batch
from umsa_core.vgm_header import (
    FADE_OUT_SECONDS,
    MAX_PLAYBACK_SECONDS,
    format_vgm_status,
    format_vgm_title,
    mame_seconds_to_run,
)
from umsa_core.vgm_socket import _parse_vgmplay_port, parse_lua_level

VGM_RANDOM_BATCH_SIZE = 100
VGM_RANDOM_MAX_CONSECUTIVE_UNPLAYABLE = 5
# Music info countdown: refresh interval and bounded join on stop (seconds).
VGM_INFO_TICK_SECONDS = 1.0
VGM_INFO_TICKER_JOIN_TIMEOUT = 1.5
# Longest wait for MAME after the Lua connect: -seconds_to_run counts emulated
# time, so a slow machine may take longer; beyond this the track is stopped.
VGM_WAIT_FACTOR = 1.5
VGM_WAIT_MARGIN_SECONDS = 30.0


class VgmPlayer:
    """Prepare VGM tracks, pick random ones and keep the music info.

    ``vgm_info_callback(text)`` gets the music info line,
    ``vgm_stopped_callback()`` the end of a playback (once per playback).
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
        # Session token of the current playback (VGMPLAY_TOKEN): only the
        # MAME of this playback may connect.
        self.vgm_token = None

        self._vgm_title = None
        self._planned_seconds = 0
        self._level = None  # (gain_db, state) of the last level frame
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

    def _vgm_process_env(self, vgm_port_env, fade_seconds=None, token=None):
        """Return the environment of the MAME process.

        Sets the port of this listener, the fade-out length in seconds for
        vgmplay.lua (none: no fade) and the session token for its HELLO line
        (none: no handshake).
        """
        env = os.environ.copy()
        if token:
            env['VGMPLAY_TOKEN'] = token
        else:
            env.pop('VGMPLAY_TOKEN', None)
        port = _parse_vgmplay_port(vgm_port_env)
        if port is None:
            env.pop('VGMPLAY_PORT', None)
        else:
            env['VGMPLAY_PORT'] = str(port)
        if fade_seconds:
            env['VGMPLAY_FADE_SECONDS'] = f'{fade_seconds:g}'
        else:
            env.pop('VGMPLAY_FADE_SECONDS', None)
        return env

    def _notify_vgm_info(self, message):
        """Pass a music info line to ``vgm_info_callback``; failures are only logged."""
        if self.vgm_info_callback:
            try:
                self.vgm_info_callback(message)
            except Exception as error:
                log(f'UMSA Emu: VGM info callback failed: {error}', level='warning')

    def vgm_status(self, remaining_seconds):
        return format_vgm_status(self._vgm_title, remaining_seconds, self._level)

    def on_lua_log(self, text):
        """Keep gain and state of the last level frame of vgmplay.lua (socket thread)."""
        level = parse_lua_level(text)
        if level is not None:
            self._level = level

    def process_timeout(self):
        """Return the seconds to wait for the MAME process of the prepared track."""

        return self._planned_seconds * VGM_WAIT_FACTOR + VGM_WAIT_MARGIN_SECONDS

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
            """Send the countdown once per second until stopped or at 0."""
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
        """Call ``vgm_stopped_callback`` at most once per playback.

        The playback owner and the worker can both reach the end of a track.
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
        """Fill ``emurun`` for a VGM track and start a new session token.

        Args:
            vgm: ``<set>:<track>`` for MAME ``-quik``.
            sec2run: Seconds to run when there is no ``plan``.
            intro: The track is the intro VGM.
            plan: Optional :class:`~umsa_core.vgm_header.PlaybackPlan`.
            info: Optional music info title (``format_vgm_title``).
            vgm_port_env: ``VGMPLAY_PORT`` value for the process environment.
            title: Music info title without the stop notification of ``info``
                (random playback); default ``info``.

        Returns:
            ``(vgm_args, env)`` of the MAME process.
        """
        self.begin_vgm_playback()
        self.playvgm = True
        self.playintrovgm = intro
        actual_sec = min(
            plan.seconds_to_run if plan else sec2run,
            self.max_vgm_duration,
        )
        # A playback that ends inside the music is faded out; only a track
        # without loop that runs to its own end is not (plan.fade_out).
        fade_out = (
            plan is None
            or actual_sec < plan.seconds_to_run
            or plan.fade_out
        )
        # One token per playback: only the MAME of this playback may connect.
        self.vgm_token = secrets.token_hex(8)
        self._vgm_title = title or info
        # The info counts down from what MAME really runs.
        self._planned_seconds = mame_seconds_to_run(actual_sec)
        self._level = None
        if self._vgm_title:
            self._notify_vgm_info(self.vgm_status(self._planned_seconds))
        vgm_args = ['-videodriver', 'dummy', '-video', 'none', '-nojoystick', '-nowriteconfig',
            '-seconds_to_run', str(self._planned_seconds), '-autoboot_script', self.lua_script,
            '-volume', '1', 'vgmplay', '-quik', vgm]
        emurun.update({
            'args': vgm_args,
            'emu_exe': self.vgmplay_exe or self.mame_exe,
            'emulation_start': 0,
            'working_dir': self.mame_dir,
            'env': self._vgm_process_env(
                vgm_port_env, FADE_OUT_SECONDS if fade_out else None,
                self.vgm_token),
        })
        return vgm_args, emurun['env']

    def play_random_vgm_thread(self, emurun, textinfo=None, db_path=None,
                               find_roms_func=None, run_func=None,
                               stop_requested=None):
        """Play random VGM tracks until stopped (runs in the worker thread).

        Candidates come from umsa.db in batches. After
        ``VGM_RANDOM_MAX_CONSECUTIVE_UNPLAYABLE`` candidates in a row cannot
        play (missing or broken archive, ``run_func`` returning ``False``),
        the playback stops.

        Args:
            textinfo: Optional Kodi text control for the title.
            db_path: Core data directory; without one nothing is played.
            find_roms_func: ``(emurun, rom_paths) -> None``; default
                :func:`umsa_core.rom_finder.find_roms`.
            run_func: Plays one track ``(vgm, close_server, plan, title)``;
                ``False`` means MAME could not play it.
            stop_requested: Optional predicate; ``True`` ends the playback,
                also when the stop came before this worker started.
        """
        self.playrandomvgm = True
        candidates = deque()
        consecutive_unplayable = 0

        def keep_playing():
            if not self.playrandomvgm:
                return False
            return not (stop_requested and stop_requested())

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
            while keep_playing():
                if not db_path:
                    break
                if not candidates:
                    candidates.extend(
                        random_vgm_batch(db_path, VGM_RANDOM_BATCH_SIZE))
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
                if not keep_playing():
                    # Stopped while this track was prepared.
                    break
                started = True
                if run_func:
                    started = run_func(play_vgm, close_server=False,
                                       plan=plan, title=vgm_title)
                if started is False:
                    # A broken setup must not skip through tracks forever.
                    if note_unplayable(
                            f'UMSA Emu: play random vgm - MAME could not play {play_vgm}'):
                        break
                    continue
                consecutive_unplayable = 0
        finally:
            self.playrandomvgm = False
            self._notify_vgm_stopped()
