"""Emulator configuration and MARP replay handling.

The dialogs for a new or existing emulator and the replay download live here;
starting the emulator itself stays in ``gui.py`` because it is the dispatcher
between MAME, the Kodi retroplayer and the MARP replayer.
"""

import os
from random import choice, randint

import xbmc
import xbmcgui
from umsa_core.support import marp_search

from .constants import TEXTLIST


def get_diff_emulator(gui):
    """Get different emulator"""

    emus = gui.ggdb.get_emulators()
    if emus:
        emu_names = ['Configure new emulator']
        for i in emus:
            emu_names.append(i['name'])
        ret = gui.dialog.select('Emulators', emu_names)
        if ret == -1:
            return
        if ret == 0:
            gui.configure_emulator()
        else:
            if gui.actset['swl_name'] == "mame":
                gui.ggdb.connect_emulator(
                    emus[ret - 1]['id'], source=gui.actset['source'])
            else:
                gui.ggdb.connect_emulator(
                    emus[ret - 1]['id'], swl_name=gui.actset['swl_name'])
            gui.run_emulator(emus[ret - 1])
    else:
        gui.configure_emulator()


EXTRACT_OPTIONS = ('Extract zip/chd', 'Start with zip/chd')
START_MODES = ('Normal', 'Watch', 'Fallback')


def _option_label(options, index):
    """Label of a stored option index; out-of-range values show the first."""

    return options[index] if isinstance(index, int) and 0 <= index < len(options) else options[0]


def _emulator_menu(emu_info, save_label):
    """Entries of the emulator field menu with the current values."""

    return [
        f"Executable: {emu_info['exe']}",
        f"Working directory: {emu_info['dir']}",
        f"Extract: {_option_label(EXTRACT_OPTIONS, emu_info['zip'])}",
        f"Start mode: {_option_label(START_MODES, emu_info['mode'])}",
        f"Name: {emu_info['name']}",
        save_label,
    ]


def _edit_emulator_field(gui, emu_info, field):
    """Edit one field; a cancelled dialog keeps the current value.

    Kodi's browse dialog returns the preset path on cancel, so a browse
    result equal to the preset simply keeps the value.
    """

    if field == 0:
        exe = gui.dialog.browse(1, 'Emulator executable', 'files', defaultt=emu_info['exe'])
        if exe:
            emu_info['exe'] = exe
    elif field == 1:
        default = emu_info['dir'] or os.path.dirname(emu_info['exe'])
        work_dir = gui.dialog.browse(0, 'Working directory', 'files', defaultt=default)
        if work_dir:
            emu_info['dir'] = work_dir
    elif field == 2:
        ret = gui.dialog.select('Extract?', list(EXTRACT_OPTIONS), preselect=emu_info['zip'])
        if ret > -1:
            emu_info['zip'] = ret
    elif field == 3:
        ret = gui.dialog.select('Emulator start', list(START_MODES), preselect=emu_info['mode'])
        if ret > -1:
            emu_info['mode'] = ret
    elif field == 4:
        name = gui.dialog.input('Name of emulator', emu_info['name'])
        if name:
            emu_info['name'] = name


def configure_emulator(gui, emu_info=None, reconfigure=False):
    """Dialog to configure emulators.

    A new emulator starts with the executable (cancel ends the dialog);
    working directory and name are derived from it. Then a field menu shows
    every value: a field dialog that is cancelled keeps the value, cancelling
    the menu itself ends without saving - no dialog follows a cancel.
    """

    if not emu_info:
        exe = gui.dialog.browse(1, 'Emulator executable', 'files', defaultt='')
        if not exe:
            gui.dialog.notification('Configure Emulator', 'no executable selected',
                xbmcgui.NOTIFICATION_ERROR, 3000, False)
            return
        emu_info = {
            'name': os.path.splitext(os.path.basename(exe))[0],
            'exe': exe,
            'dir': os.path.dirname(exe),
            'zip': 0,
            'mode': gui.emulation_start,
        }
    else:
        emu_info = dict(emu_info)

    save_label = 'Save' if reconfigure else 'Save and start'
    save_index = 5
    selected = save_index
    while True:
        selected = gui.dialog.select(
            f"Emulator {emu_info['name']}".strip(),
            _emulator_menu(emu_info, save_label), preselect=selected)
        if selected == -1:
            gui.dialog.notification('Configure Emulator', 'cancelled, nothing saved',
                xbmcgui.NOTIFICATION_INFO, 2500, False)
            return
        if selected == save_index:
            if emu_info['exe'] and emu_info['dir'] and emu_info['name']:
                break
            gui.dialog.notification('Configure Emulator', 'executable, directory and name needed',
                xbmcgui.NOTIFICATION_ERROR, 3000, False)
            continue
        _edit_emulator_field(gui, emu_info, selected)
    # stored option indexes stay valid even when an old entry held -1
    emu_info['zip'] = emu_info['zip'] if emu_info['zip'] in (0, 1) else 0
    emu_info['mode'] = emu_info['mode'] if emu_info['mode'] in (0, 1, 2) else 0
    # save to db
    if gui.actset['swl_name'] == "mame":
        gui.ggdb.save_emulator(emu_info, reconfigure, source=gui.actset['source'])
    else:
        gui.ggdb.save_emulator(emu_info, reconfigure, swl_name=gui.actset['swl_name'])
    # run
    if not reconfigure:
        gui.run_emulator(emu_info)


def marp_replayer(gui, dl_file=None, set_name=None, random=None):
    """Start MAME with a MARP Replay input file

    Random replay with no argument
    """

    if not dl_file:
        rand_version = randint(178, 289)
        all_marps = marp_search(version=rand_version)
        if not all_marps:
            gui.dialog.notification(
                "MARP", f"no replays found for version {rand_version}")
            return
        if random:
            marp_rand = choice(all_marps)
            dl_file = marp_rand['download']
            set_name = marp_rand['set_name']
        else:
            marp_list = []
            for i in all_marps:
                marp_list.append("{}[CR] {}: {} ({}, {})".format(
                    i['gamename'], i['player'], i['rank'], i['percentage'], i['points']))
            ret = gui.dialog.select(
                f"Select MARP {rand_version} replay:", marp_list, useDetails=True)
            # select() returns -1 on cancel; index 0 is a valid choice
            if ret < 0:
                return
            dl_file = all_marps[ret]['download']
            set_name = all_marps[ret]['set_name']

    gui.run_emulator({
        'name': "MARP Replay", 'exe': "marp", 'set_name': set_name, 'marp_dl': dl_file})


def add_or_update_emu_output(gui, out, err, exit_code, cmd_args):
    """Show the emulator output in the text list of the skin."""

    no_emu_out = True
    try:
        for i in range(gui.getControl(TEXTLIST).size()):
            if gui.getControl(TEXTLIST).getListItem(i).getLabel() == 'Emulator output':
                no_emu_out = False
                emu_out_item = gui.getControl(TEXTLIST).getListItem(i)
                break
    except Exception:
        return
    if no_emu_out and (out or err):
        try:
            emu_out_item = xbmcgui.ListItem()
            emu_out_item.setLabel('Emulator output')
            gui.getControl(TEXTLIST).addItem(emu_out_item)
        except Exception:
            return
    try:
        cmd_str = ' '.join(cmd_args) if cmd_args else ''
        emu_out_item.setProperty(
            'text', f'cmd: {cmd_str}\nerr {exit_code}: {err}\nout: {out}')
        gui.getControl(TEXTLIST).selectItem(gui.getControl(TEXTLIST).size() - 1)
    except Exception as error:
        xbmc.log(
            f'UMSA gui: could not update emulator output: {error}',
            xbmc.LOGDEBUG)


def notify_final_launch(gui, notif_text, emu_name, mode):
    """Tell the user that the emulator stopped."""

    if mode != 'no':
        try:
            gui.emu_dialog.update(
                90, f"{notif_text}\nScreensaver active. Press a button to escape!")
        except Exception as error:
            xbmc.log(
                f'UMSA gui: could not update emulator dialog: {error}',
                xbmc.LOGWARNING)
    else:
        try:
            gui.emu_dialog.close()
        except Exception as error:
            xbmc.log(
                f'UMSA gui: could not close emulator dialog: {error}',
                xbmc.LOGWARNING)
        try:
            gui.dialog.notification(f'{emu_name} stopped', f'{notif_text}',
                                    xbmcgui.NOTIFICATION_INFO, 3000, False)
        except Exception as error:
            xbmc.log(
                f'UMSA gui: could not show final launch notification: {error}',
                xbmc.LOGWARNING)
