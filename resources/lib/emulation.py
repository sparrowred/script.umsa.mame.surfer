# -*- coding: utf-8 -*-
"""Module for general emulation handling."""

import os
import socket
import gzip
import struct
import zlib
from platform import platform
from select import select as select_wait
from time import sleep as time_sleep
from zipfile import ZipFile, BadZipfile
from random import randint
from threading import Event, Thread
from subprocess import PIPE, Popen, run as subrun, check_output, CalledProcessError
from utilities import log
from vgm_header import parse_vgm_header, calculate_playback_plan, PlaybackPlan

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
# Lua level name -> utilities.log level name (see utilities.log/set_log).
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
    from vgm_header import parse_vgm_header
    header = parse_vgm_header(zip_path, member)
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
    except IOError:
        pass
    if fobj:
        for line in fobj.readlines():
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

class Emulation:
    """Emulation handling class.

    Needed:
        - temp dir          in other_emus saved as emurun.folder; for extracting roms/chds
        - mame ini          for parsing mame ini file used TODO
        - mame dir
        - mame exe          to start mame emulation, for vgmplay
        - chdman exe        extract chd
        - TODO settings path     for lua script in vgmplay
    """

    def __init__(self, temp_dir='.', mame_ini_file=None, mame_dir='.', mame_exe=None,
                    chdman_exe=None, vgmlua_script=None, monitor_self=None, nonmame={},
                    terminal='', vgmplay_exe=''):
        self.percent = 0 # chd convert
        self.playvgm = False
        self.playintrovgm = False
        self.playrandomvgm = False
        self.mame_exe = mame_exe
        self.mame_dir = mame_dir
        self.chdman_exe = chdman_exe
        self.process = None
        self.temp_dir = temp_dir
        self.emurun = {}
        self.lua_socket = None
        self.lua_server = None
        self.lua_log_thread = None
        self.lua_log_stop = None
        self.vgm_port_env = None
        self.lua_script = vgmlua_script
        self.monitor = monitor_self
        self.nonmame = nonmame
        self.terminal = terminal
        self.vgmplay_exe = vgmplay_exe
        print(f"vgmplay_exe ----{vgmplay_exe}------")
        print(f"self.vgmplay_exe ----{self.vgmplay_exe}------")

        if mame_ini_file:
            self.mame_ini = parse_mame_ini(mame_ini_file)
            # set snap directory
            if 'snapshot_directory' in self.mame_ini:
                self.mame_ini['snapshot_directory'] = os.path.join(
                    mame_dir, self.mame_ini['snapshot_directory'])
            else:
                self.mame_ini['snapshot_directory'] = ''

    def run(self):
        """Run the emulator."""

        # create args
        # TODO why can args be str? emrun['args'] should always be a list > fix everywhere
        args = []
        log(f"UMSA Emulation: run args type: {type(self.emurun['args'])}, args: {self.emurun['args']}", level='debug')
        if isinstance(self.emurun['args'], list):
            args = [self.emurun['emu_exe']]+self.emurun['args']
        elif isinstance(self.emurun['args'], str):
            args = [self.emurun['emu_exe'], self.emurun['args']]
        else:
            log(f"UMSA Emulation, run: unknown type for args = {type(self.emurun['args'])}", level='warning')
        log(f"UMSA Emulation args: {args}", level='debug')
        popen_env = {}
        if 'env' in self.emurun:
            popen_env['env'] = self.emurun['env']
        # run executable depending on emulation start
        if self.emurun['emulation_start'] == 1: # Watch
            self.process = Popen(
                args, stdout=PIPE, stderr=PIPE, cwd=self.emurun['working_dir'],
                **popen_env)
        elif self.emurun['emulation_start'] == 0: # Normal
            self.process = Popen(
                args, cwd=self.emurun['working_dir'], **popen_env)
        elif self.emurun['emulation_start'] == 2: # Fallback
            # TODO make os.system a daemon thread so it does not stop the script?
            # TODO use subprocess.run?
            self.process = None
            # Supermodel needs to be started in it's directory
            #run = "cd {} && ".format(self.emurun['working_dir'])
            run = ''
            # escape parameters with double quotes
            for i in args:
                run += '"{}" '.format(i)
            #os.system(run)
            torun = [self.terminal, '-e', run]
            log(f'UMSA Emulation run {torun}', level='debug')
            subrun(torun)


    def after_run(self):
        """Clean up after emulation run."""

        if 'symlink' in self.emurun and self.emurun['symlink']:
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

    def play_vgm_thread(self, vgm, sec2run=90, sleep=None, intro=False, close_server=True, plan=None):
        """Play vgm."""

        log(f"UMSA emu: play_vgm_thread, vgmplay_exe: {self.vgmplay_exe}")
        self.playvgm = True
        self.playintrovgm = intro
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
        log(f"UMSA emu: vgmplay_exe = {self.vgmplay_exe}")
        log(f"UMSA Emu: check if vgmplay_exe is selected: {self.emurun['emu_exe']}", level='debug') 
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
        if close_server:
            self._close_vgm_sockets()
        else:
            self._close_accepted_conn()

    def _vgm_process_env(self):
        """Pass the port captured for this listener only to the MAME process."""
        env = os.environ.copy()
        if self.vgm_port_env is None:
            env.pop('VGMPLAY_PORT', None)
        else:
            env['VGMPLAY_PORT'] = self.vgm_port_env
        return env

    def play_random_vgm_thread(self, ggdb=None, textinfo=None, db_path=None, sleep=None):
        """Play random vgm until ordered to stop playing.

            TODO check if all threads are closed at the end
        """

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
                header = parse_vgm_header(vgm_zipfile, vgm_tracklist[random_track - 1])
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
                minutes, seconds = divmod(int(header.total_seconds), 60)
                vgm_nice = f'Song "{vgm_tracklist[random_track-1][:-4].title()}" from "{random_vgm["gamename"]}" {minutes}:{seconds:02d} ({plan.reason})'
                # TODO check if screenserver running then set vgm info
                if self.monitor and self.monitor.saver.running != "no":
                    try:
                        self.monitor.saver.getControl(4100).setLabel(vgm_nice)
                    except Exception:
                        pass
                if textinfo:
                    try:
                        textinfo.setLabel(vgm_nice)
                    except Exception:
                        pass
                self.play_vgm_thread(play_vgm, sleep=sleep, close_server=False, plan=plan)
        finally:
            self._close_vgm_sockets()
            self.playrandomvgm = False

    def play_random_vgm(self, ggdb=None, textinfo=None, db_path=None, sleep=None):

        self.rvgm_thread = Thread(target=self.play_random_vgm_thread,
            args=(ggdb, textinfo, db_path, sleep))
        self.rvgm_thread.start()

    def play_vgm(self, vgm, sec2run=90, sleep=None, intro=False):

        if intro and self.playvgm:
            return  # no intro play when a vgm already plays
        self._start_vgm_server()
        self.pvgm_thread = Thread(target=self.play_vgm_thread,
            args=(vgm, sec2run, sleep, intro))
        self.pvgm_thread.start()

    def find_nonmame_roms(self, exodos_shell=''):
        """Search for files from other sources than MAME."""

        zips, chds = [], []
        filename = ''
        ret_val = True

        if self.emurun['swl_name'] == 'exodos':
            # TODO check PLATFORM!
            log(f'UMSA Emu: Platform: {PLATFORM}', level='debug')
            log(f'UMSA Emu: - eXoDOS arg: "{exodos_shell}"', level='debug')
            log(f'UMSA Emu: - emurun: {self.emurun}', level='debug')
            #if 'Linux' in PLATFORM or 'macOS' in PLATFORM:
            #    dosext = '.sh'
            #else:
            #    dosext = '.bat'
            dosext = '.bat'
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
            log("UMSA Emu - whdload: {self.emurun['description']}", level='debug')
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
            ret_val = False

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
        for path in self.mame_ini['rompath']:
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
            # TODO also check the files
            #self.emurun['extractcd'] = chd_name+file_ext
            return ""
        os.mkdir(self.emurun['folder'])
        log("UMSA Emu: create process", level='debug')
        proc = Popen(
            [self.chdman_exe, 'extractcd', '-i', self.emurun['chds'][0], '-o',
             os.path.join(self.emurun['folder'], chd_name+file_ext)],
            stdout=PIPE, stderr=PIPE)
        # routine to show progress in kodi
        self.percent = 0
        log("UMSA Emu: checking process", level='debug')
        while proc.returncode is None:
            # TODO check 34 again
            chdman_progress = proc.stderr.read(34)
            rpos = str(chdman_progress)[::-1].find('%') # reversed str
            if rpos > -1:
                pos = len(chdman_progress)-rpos-1
                try:
                    self.percent = int(float(chdman_progress[pos-4:pos]))
                except ValueError:
                    pass
            # Kodi
            update_dialog(dialog, self.percent, 'extracting chd: {}'.format(self.percent))
            if dialog and dialog.iscanceled():
                return "canceled..."
            proc.poll()
            # Kodi: use xbmc.sleep
            if sleep:
                sleep(250)
            else:
                time_sleep(250)
        log(f"UMSA Emu extract_rom: chd extract: RC = {proc.returncode}", level='debug')
        if proc.returncode == 0:
            self.emurun['extractcd'] = chd_name+file_ext
            return ""
        os.rmdir(self.emurun['folder'])
        return "Error: chdman process was unsuccessfull."

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
            if len(zfiles) == 2 and self.emurun['swl_name'] in EXTENSIONS.keys():
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
            if self.emurun['swl_name'] in EXTENSIONS.keys():
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
            params.extend(['-run=dc', '-image={}'.format(image)])
        # arcade
        else:
            # call -listroms to find parameter for -run=
            section = ''
            found = False
            try:
                listroms = check_output([self.emurun['emu_exe'], '-listroms'])
            except CalledProcessError:
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
                    '-run={0}'.format(section.lower()),
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
            ret_val = self.find_nonmame_roms()
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
