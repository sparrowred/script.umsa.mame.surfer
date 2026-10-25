"""GUI-side emulator launch orchestration.

Extracted from UMSA.run_emulator to separate launch workflow
from GUI lifecycle and control wiring.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from umsa_core import log
from umsa_core.emulation import CHDExtractionCancelled, CHDExtractionError


@dataclass
class LaunchCtx:
    # data
    actset: dict = None
    emu_infos: dict = None
    emulation: Any = None
    ggdb: Any = None
    emu_dialog: Any = None
    dialog: Any = None
    player: Any = None
    mame_dir: str = ''
    emulation_start: int = 0
    playvideo: bool = False

    # callbacks
    stop_screensaver: Callable[[], None] = lambda: None
    get_screensaver_mode: Callable[[], str] = lambda: 'no'
    set_emulator_running: Callable[[bool], None] = lambda flag: None
    search_snaps: Callable[[dict], Any] = lambda actset: []
    show_artwork: Callable[[str], None] = lambda kind: None
    add_or_update_emu_output: Callable[[str, str, int, list], None] = lambda out, err, code, args: None
    notify_final: Callable[[str, str, str], None] = lambda notif, name, mode: None
    sleep: Callable[[int], None] = lambda ms: None


def launch_emulator(ctx: LaunchCtx) -> None:
    """Orchestrate emulator launch (non-retroplayer paths).

    Preserves existing behavior and error/cleanup semantics.
    """
    emu_infos = ctx.emu_infos or {}

    # stop playing mame vgm
    if getattr(ctx.emulation, 'playvgm', False):
        try:
            ctx.emulation.send_vgmaction(b'exit')
        except Exception as error:
            log(
                f'UMSA gui: could not stop VGM before emulator launch: {error}',
                level='warning')
        if getattr(ctx.emulation, 'playrandomvgm', None) is not None:
            ctx.emulation.playrandomvgm = None
        ctx.sleep(500)

    # UI prep
    try:
        ctx.emu_dialog.create("Emulator: {}".format(emu_infos.get('name', '')), 'warm up...')
    except Exception as error:
        log(
            f'UMSA gui: could not create emulator progress dialog: {error}',
            level='warning')
    ctx.stop_screensaver()

    # build emurun
    ctx.emulation.emurun = {
        'emulation_start': ctx.emulation_start,
        'working_dir': ctx.mame_dir,
        'swl_name': ctx.actset.get('swl_name'),
        'set_name': ctx.actset.get('name'),
        'description': ctx.actset.get('gamename'),
        'publisher': ctx.actset.get('publisher'),
        'set_clone': ctx.ggdb.get_set_name(ctx.actset.get('clone')) if ctx.ggdb else None,
        'disks': ctx.ggdb.get_disks(ctx.actset.get('swl_name'), ctx.actset.get('name')) if ctx.ggdb else [],
    }

    # disk selection
    emurun_disks = ctx.emulation.emurun.get('disks') or []
    if emurun_disks and len(emurun_disks) > 1:
        select = []
        select_index = []
        for idx, i in enumerate(emurun_disks):
            try:
                if i['disk']:
                    select.append(i['disk'])
                    select_index.append(idx)
            except (KeyError, IndexError, TypeError) as error:
                log(
                    f'UMSA gui: skipping invalid disk row {idx}: {error}',
                    level='warning')
        if select:
            try:
                which_disk = ctx.dialog.select('Select CHD:', select)
            except Exception as error:
                log(f'UMSA gui: CHD selection failed: {error}', level='warning')
                which_disk = -1
            if which_disk > -1:
                try:
                    picked = select_index[which_disk]
                    this_disk = emurun_disks[picked]
                    emurun_disks[picked] = emurun_disks[0]
                    emurun_disks[0] = this_disk
                except (IndexError, TypeError) as error:
                    log(
                        f'UMSA gui: could not promote selected CHD: {error}',
                        level='warning')

    exe = emu_infos.get('exe', '') or ''

    # exodos
    if 'exodos' in exe:
        try:
            ctx.emu_dialog.update(10, 'searching shellscript...')
        except Exception as error:
            log(
                f'UMSA gui: could not update emulator progress: {error}',
                level='debug')
        ctx.emulation.prepare_exodos_run(emu_infos)
    # marp
    elif exe == "marp":
        try:
            ctx.emu_dialog.update(20, 'download replay...')
        except Exception as error:
            log(
                f'UMSA gui: could not update emulator progress: {error}',
                level='debug')
        ctx.emulation.prepare_marp_run(emu_infos)
    # mame
    elif exe == "mame":
        ctx.emulation.prepare_mame_run(ctx.ggdb, ctx.actset, dialog=ctx.emu_dialog)
    # other emulator
    else:
        import xbmcgui
        try:
            error = ctx.emulation.other_emulator(
                emu_infos, sleep=ctx.sleep, dialog=ctx.emu_dialog)
        except CHDExtractionCancelled:
            ctx.stop_screensaver()
            try:
                ctx.emu_dialog.close()
            except Exception as error:
                log(
                    f'UMSA gui: could not close emulator dialog after CHD '
                    f'cancellation: {error}', level='warning')
            return
        except CHDExtractionError as error:
            ctx.stop_screensaver()
            try:
                ctx.emu_dialog.close()
            except Exception as close_error:
                log(
                    f'UMSA gui: could not close emulator dialog after CHD '
                    f'error: {close_error}', level='warning')
            try:
                ctx.dialog.notification(
                    f'{emu_infos.get("name", "")} error', str(error),
                    xbmcgui.NOTIFICATION_ERROR, 3500)
            except Exception as notify_error:
                log(
                    f'UMSA gui: could not show CHD error notification: '
                    f'{notify_error}', level='warning')
            return
        except Exception as error:
            ctx.stop_screensaver()
            try:
                ctx.emu_dialog.close()
            except Exception as close_error:
                log(
                    f'UMSA gui: could not close emulator dialog after '
                    f'preparation error: {close_error}', level='warning')
            log(
                f'UMSA gui: emulator preparation failed: {error}',
                level='error')
            raise
        if not error:
            ctx.stop_screensaver()
            try:
                ctx.emu_dialog.close()
            except Exception as close_error:
                log(
                    f'UMSA gui: could not close emulator dialog after '
                    f'missing ROM: {close_error}', level='warning')
            try:
                ctx.dialog.notification(
                    f'{emu_infos.get("name", "")} error', 'rom not found',
                    xbmcgui.NOTIFICATION_ERROR, 3500)
            except Exception as notify_error:
                log(
                    f'UMSA gui: could not show missing ROM notification: '
                    f'{notify_error}', level='warning')
            return
        # multiple extracted files
        if ('extract_files' in ctx.emulation.emurun and
                len(ctx.emulation.emurun['extract_files']) > 1):
            try:
                which_file = ctx.dialog.select(
                    'Select file: ', ctx.emulation.emurun['extract_files'])
            except Exception as error:
                log(
                    f'UMSA gui: extracted file selection failed: {error}',
                    level='warning')
                which_file = -1
            if which_file > -1:
                try:
                    ctx.emulation.emurun['args'] = os.path.join(
                        ctx.emulation.emurun['folder'],
                        ctx.emulation.emurun['extract_files'][which_file]
                    )
                except (KeyError, IndexError, TypeError) as error:
                    log(
                        f'UMSA gui: could not select extracted file: {error}',
                        level='warning')

    # pause media
    try:
        if ctx.playvideo and ctx.player.isPlayingVideo():
            ctx.player.stop()
        elif ctx.player.isPlayingAudio():
            ctx.player.pause()
    except Exception as error:
        log(
            f'UMSA gui: could not pause media before emulator launch: {error}',
            level='warning')

    # execute
    try:
        ctx.emu_dialog.update(50, 'emulator running...')
    except Exception as error:
        log(
            f'UMSA gui: could not update emulator progress: {error}',
            level='debug')
    import time
    ctx.sleep(100)
    emurun = ctx.emulation.emurun
    uses_process_runner = emurun.get('emulation_start') in (0, 1)
    ctx.set_emulator_running(True)
    out = ''
    err = ''
    start = time.time()
    try:
        try:
            if uses_process_runner:
                ctx.emulation.start_managed_process(
                    capture_output=(emurun.get('emulation_start') == 1)
                )
            else:
                ctx.emulation.run()
        except OSError as error:
            log(
                f'UMSA gui: {emu_infos.get("name", "")} launch failed: {error}',
                level='error')
            try:
                ctx.emu_dialog.close()
            except Exception as close_error:
                log(
                    f'UMSA gui: could not close emulator dialog after launch '
                    f'failure: {close_error}', level='warning')
            raise
        out, err = ctx.emulation.wait_for_completion(dialog=ctx.emu_dialog, sleep=ctx.sleep)
    finally:
        ctx.set_emulator_running(False)

    end = time.time()
    try:
        ctx.emu_dialog.update(75, 'emulator stopped...')
    except Exception as error:
        log(
            f'UMSA gui: could not update emulator progress: {error}',
            level='debug')
    notif = f"Played: {ctx.ggdb.make_time_nice(end - start) if ctx.ggdb else int(end - start)}"
    ctx.stop_screensaver()
    try:
        if ctx.player.isPlayingAudio():
            ctx.player.pause()
    except Exception as error:
        log(
            f'UMSA gui: could not pause media after emulator run: {error}',
            level='warning')

    # average speed
    try:
        if "Average speed:" in out:
            rev = out[::-1]
            try:
                percent = rev[rev.find('( %') + 2:rev.find(' :deeps')][::-1]
                if percent != "100.00%":
                    notif += f" - {percent}"
            except (IndexError, ValueError) as error:
                log(
                    f'UMSA gui: could not parse emulator average speed: {error}',
                    level='debug')
    except Exception as error:
        log(
            f'UMSA gui: could not inspect emulator average speed: {error}',
            level='debug')

    # exit code + output
    exit_code = None
    if uses_process_runner:
        try:
            st = ctx.emulation.managed_process_status()
            exit_code = getattr(st, 'exit_code', None)
        except Exception as error:
            log(
                f'UMSA gui: could not read emulator exit status: {error}',
                level='warning')
            exit_code = None
    if exit_code is not None and exit_code != 0:
        try:
            cmd_args = ctx.emulation.emurun.get('args', [])
            if isinstance(cmd_args, str):
                cmd_args = [cmd_args]
            ctx.add_or_update_emu_output(out or '', err or '', int(exit_code), cmd_args)
        except Exception as error:
            log(
                f'UMSA gui: could not show emulator output: {error}',
                level='warning')
        notif += "\nerror: see bottom left"

    # finalize status
    try:
        if emu_infos.get('exe') != "marp":
            if int(end - start) > 60:
                try:
                    ctx.ggdb.write_status_after_play(ctx.actset.get('id'), int(end - start))
                except Exception as error:
                    log(
                        f'UMSA gui: could not record emulator play time: {error}',
                        level='warning')
            if emu_infos.get('exe') == "mame":
                ctx.sleep(100)
                try:
                    ctx.actset['localsnaps'] = ctx.search_snaps(ctx.actset)
                except Exception as error:
                    log(
                        f'UMSA gui: could not search snapshots after emulator '
                        f'run: {error}', level='warning')
                try:
                    ctx.show_artwork('set')
                except Exception as error:
                    log(
                        f'UMSA gui: could not show artwork after emulator run: '
                        f'{error}', level='warning')
    except Exception as error:
        log(
            f'UMSA gui: could not finalize emulator status: {error}',
            level='warning')

    # final notify
    try:
        mode = ctx.get_screensaver_mode()
        ctx.notify_final(notif, emu_infos.get('name', ''), mode)
    except Exception as error:
        log(
            f'UMSA gui: could not show final emulator notification: {error}',
            level='warning')
