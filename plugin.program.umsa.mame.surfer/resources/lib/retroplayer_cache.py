"""Kodi RetroPlayer launch: find the ROM, prepare the file to play, start.

The file RetroPlayer gets follows the setting ``rom_cache``:

* software lists UMSA has to rebuild (``rom_finder.EXTENSIONS``: joined and
  renamed ROM files) and Gamebase64 archives are always extracted into the
  ROM temp folder;
* everything else is played from its original path, or - with the ROM cache
  switched on - from a copy in the cache (``umsa_core.rom_cache``).
"""

import os

import xbmc
import xbmcgui
from emulator_launcher import new_emurun
from umsa_core import ShutdownRequested
from umsa_core.rom_cache import CacheCopyCancelled, cache_archives
from umsa_core.rom_finder import EXTENSIONS, NONMAME
from umsa_gui import strings as S
from umsa_gui.strings import tr

EMULATOR_NAME = "Retroplayer"
# documentation file inside the Gamebase64 archives
GB64_INFO_FILE = 'VERSION.NFO'


def needs_extraction(swl_name):
    """True when RetroPlayer cannot play the archive of the software list."""

    return swl_name in EXTENSIONS or swl_name.startswith('gb64_')


def _close(ctx):
    ctx.stop_screensaver()
    ctx.emu_dialog.close()


def _fail(ctx, message):
    _close(ctx)
    ctx.dialog.notification(
        heading=tr(S.ERROR), message=message,
        icon=xbmcgui.NOTIFICATION_ERROR, time=7500)


def prepare_playfile(ctx):
    """Return the file RetroPlayer plays, or None when there is none.

    Fills ``ctx.emulation.emurun`` with the found ROMs; raises
    ``CacheCopyCancelled`` / ``ShutdownRequested`` from a copy into the cache.
    """

    emurun = ctx.emulation.emurun
    swl_name = emurun['swl_name']

    ctx.emu_dialog.update(10, tr(S.RUN_SEARCHING_ROMS))
    if swl_name in NONMAME:
        ctx.emulation.find_nonmame_roms()
    else:
        ctx.emulation.find_roms()
    zips = emurun.get('zips') or []
    chds = emurun.get('chds') or []
    xbmc.log(f"UMSA gui: retroplayer: zips={zips!r} chds={chds!r}", xbmc.LOGDEBUG)
    if not zips and not chds:
        return None

    if zips and needs_extraction(swl_name):
        emurun['folder'] = ctx.cache_layout.extract_dir(
            swl_name, emurun['set_name'], emurun.get('source'))
        error = ctx.emulation.extract_rom()
        if error:
            xbmc.log(f"UMSA gui: retroplayer: {error}", xbmc.LOGWARNING)
            return None
        files = sorted(
            name for name in emurun.get('extract_files') or []
            if name != GB64_INFO_FILE)
        return os.path.join(emurun['folder'], files[0]) if files else None

    if ctx.rom_cache:
        cache_archives(emurun, ctx.cache_layout, ctx.emu_dialog, ctx.wait)
        zips = emurun.get('zips') or []
        chds = emurun.get('chds') or []
    return zips[0] if zips else chds[0]


def run_retroplayer(ctx):
    """Find the ROM, prepare the file to play and start RetroPlayer."""

    try:
        ctx.emu_dialog.create(tr(S.RUN_TITLE, EMULATOR_NAME), tr(S.RUN_WARM_UP))
    except Exception as error:  # noqa: BLE001 - the dialog only shows progress
        xbmc.log(f"UMSA gui: could not create emulator progress dialog: {error}",
                 xbmc.LOGWARNING)

    # the run state other starts build in the launcher
    ctx.emulation.emurun = new_emurun(ctx.actset, ctx.ggdb, 0, '')
    try:
        playfile = prepare_playfile(ctx)
    except ShutdownRequested:
        xbmc.log("UMSA gui: retroplayer: Kodi shuts down, start stopped",
                 xbmc.LOGWARNING)
        _close(ctx)
        ctx.exit()
        return
    except CacheCopyCancelled:
        xbmc.log("UMSA gui: retroplayer: copy into the ROM cache cancelled",
                 xbmc.LOGDEBUG)
        _close(ctx)
        return
    except OSError as error:
        xbmc.log(f"UMSA gui: retroplayer: could not prepare the ROM: {error}",
                 xbmc.LOGERROR)
        _fail(ctx, str(error))
        return
    finally:
        ctx.emulation.after_run()

    if not playfile:
        _fail(ctx, tr(S.RUN_CANNOT_FIND_ROM))
        return
    xbmc.log(f"UMSA gui: retroplayer: playfile = {playfile}", xbmc.LOGDEBUG)

    game_item = xbmcgui.ListItem(playfile)
    game_item.setInfo(type='game', infoLabels={'title': ctx.actset['gamename']})
    game_tag = game_item.getGameInfoTag()
    game_tag.setTitle(ctx.actset['name'])
    game_tag.setPlatform(ctx.actset['machine_label'])
    game_tag.setGenres([ctx.actset['category']])
    game_tag.setPublisher(ctx.actset['publisher'])
    game_tag.setDeveloper(ctx.actset['publisher'])  # get dev from game entry
    game_tag.setOverview('set info from history')  # TODO
    year = ctx.actset['year']
    game_tag.setYear(int(year) if str(year).isdigit() else 0)
    if ctx.player.isPlaying():
        ctx.player.stop()
        xbmc.sleep(500)
    ctx.player.play(playfile, game_item)
    _close(ctx)
    # TODO need to exit or find out how to deinit the window and init it
    # again after the play session (as long as the player plays, the game runs)
    ctx.exit()
    # TODO update status, but how to measure playtime?
