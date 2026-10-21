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


def configure_emulator(gui, emu_info=None, reconfigure=False):
    """Dialog to configure emulators."""

    if not emu_info:
        emu_info = {'name': '', 'exe': '', 'dir': '', 'zip': 0, 'mode': gui.emulation_start}
    else:
        emu_info = dict(emu_info)
    # file
    emu_info['exe'] = gui.dialog.browse(
        1, 'Emulator executable', 'files', defaultt=emu_info['exe'])
    if not emu_info['exe']:
        gui.dialog.notification('Configure Emulator', 'no executable selected',
            xbmcgui.NOTIFICATION_ERROR, 3000, False)
        return
    # dir
    default = emu_info['dir']
    if not default:
        default, emu_file = os.path.split(emu_info['exe'])
        emu_name = os.path.splitext(emu_file)[0]
    emu_info['dir'] = gui.dialog.browse(0, 'Working directory', 'files', defaultt=default)
    if not emu_info['dir']:
        xbmc.executebuiltin('XBMC.Notification(no working dir selected,,2500)')
        return
    # zip/chd
    emu_info['zip'] = gui.dialog.select(
        'Extract?', ['Extract zip/chd', 'Start with zip/chd'], preselect=emu_info['zip'])
    # mode
    emu_info['mode'] = gui.dialog.select(
        'Emulator start', ["Normal", "Watch", "Fallback"], preselect=emu_info['mode'])
    # name
    default = emu_info['name']
    if not default:
        default = emu_name
    emu_info['name'] = gui.dialog.input('Name of emulator', default)
    if not emu_info['name']:
        xbmc.executebuiltin('XBMC.Notification(no name entered,,2500)')
        return
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
        rand_version = randint(178, 218)
        all_marps = marp_search(version=rand_version)
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
            if ret:
                dl_file = all_marps[ret]['download']
                set_name = all_marps[ret]['set_name']
            else:
                return

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
    except Exception:
        pass


def notify_final_launch(gui, notif_text, emu_name, mode):
    """Tell the user that the emulator stopped."""

    try:
        if mode != 'no':
            gui.emu_dialog.update(
                90, f"{notif_text}\nScreensaver active. Press a button to escape!")
        else:
            gui.emu_dialog.close()
            gui.dialog.notification(f'{emu_name} stopped', f'{notif_text}',
                                    xbmcgui.NOTIFICATION_INFO, 3000, False)
    except Exception:
        pass
