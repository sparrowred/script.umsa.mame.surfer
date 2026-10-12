"""Kodi Retroplayer cache preparation and launch.

Refactored to accept a minimal context with data, services and callbacks.
"""

import os

import xbmc
import xbmcgui
import xbmcvfs
from umsa_core.emulation import NONMAME


def run_retroplayer(ctx):
    """Prepare cache folder, resolve/copy the rom and start Retroplayer."""

    ctx.emu_dialog.update(10, 'searching roms...')
    playfile = None

    # set cache folder
    if ctx.actset['swl_name'] == 'mame':
        if ctx.actset['source'] in ctx.batomame:
            ctx.emulation.emurun['folder'] = os.path.join(
                ctx.temp_dir, ctx.batomame[ctx.actset['source']] )
        else:
            ctx.emulation.emurun['folder'] = os.path.join(
                ctx.temp_dir, 'mame', 'roms')
    elif ctx.actset['swl_name'] in NONMAME:
        if ctx.actset['swl_name']+'.xml' in ctx.batomame:
            ctx.emulation.emurun['folder'] = os.path.join( 
                ctx.temp_dir, ctx.batomame[ctx.actset['swl_name']+'.xml'])
        else:
            ctx.dialog.notification(heading='error',
                message=f"{ctx.actset['swl_name']}: not found in Batocera map",
                icon=xbmcgui.NOTIFICATION_ERROR, time=7500)
            ctx.stop_screensaver()
            ctx.emu_dialog.close()
            return
        if 'gb64' in ctx.actset['swl_name']:
           ctx.emulation.emurun['folder'] = os.path.join(
               ctx.emulation.emurun['folder'],
               os.path.basename(ctx.actset['name']) )
    elif ctx.actset['swl_name']+'.xml' in ctx.batomame:
        ctx.emulation.emurun['folder'] = os.path.join(
            ctx.temp_dir, ctx.batomame[ctx.actset['swl_name']+'.xml'],
            f"{ctx.actset['swl_name']}_{ctx.actset['name']}")
    else:
        ctx.emulation.emurun['folder'] = os.path.join(
            ctx.temp_dir, 'mame', 'roms', ctx.actset['swl_name'])
    xbmc.log(f"UMSA gui: cache folder: {ctx.emulation.emurun['folder']}", xbmc.LOGDEBUG)

    # check if rom already in cache folder and set playfile
    xbmc.log("UMSA gui: check if rom in cache", xbmc.LOGDEBUG)
    if ctx.actset['swl_name'] in NONMAME:
        if os.path.exists(ctx.emulation.emurun['folder']):
            if 'gb64' in ctx.actset['swl_name']:
                dfiles = os.listdir(ctx.emulation.emurun['folder'])
                for dfile in dfiles:
                    if dfile != 'VERSION.NFO':
                        playfile = os.path.join(
                            ctx.emulation.emurun['folder'], dfile)
                        break
            else:
                playfile = os.path.join(
                    ctx.emulation.emurun['folder'],ctx.actset['name']+'.zip')
    elif ctx.actset['swl_name'] == 'mame':
        # TODO we always assume zip, not 7z, rar or what else does mame support?
        playfile = os.path.join(
            ctx.emulation.emurun['folder'], ctx.actset['name']+'.zip')
    elif ctx.actset['swl_name']+'.xml' in ctx.batomame:
        if os.path.exists(ctx.emulation.emurun['folder']):
            dfiles = os.listdir(ctx.emulation.emurun['folder'])
            if dfiles:
                playfile = os.path.join(
                    ctx.emulation.emurun['folder'], dfiles[0])
    else:
        ctx.dialog.notification(heading='error',
                                 message='check rom in cache deadend?',
                                 icon=xbmcgui.NOTIFICATION_ERROR, time=10000)
    xbmc.log(f"UMSA gui: cache build rom file: {playfile}", xbmc.LOGDEBUG)

    # we need to search for the rom in known rom paths if not in cache
    check_file = None
    if playfile:
        check_file = os.path.isfile(playfile)
    if not check_file:
        xbmc.log(f"UMSA gui: searching {ctx.actset['swl_name']} roms:", xbmc.LOGDEBUG)
        if ctx.actset['swl_name'] in NONMAME:
            ctx.emulation.find_nonmame_roms()
        else:
            # TODO: for mame use parent!
            ctx.emulation.find_roms()
        xbmc.log(f"UMSA gui: zips: {ctx.emulation.emurun['zips']}", xbmc.LOGDEBUG)
        xbmc.log(f"UMSA gui: chds: {ctx.emulation.emurun['chds']}", xbmc.LOGDEBUG)
        xbmc.log(f"UMSA gui: disks: {ctx.emulation.emurun['disks']}", xbmc.LOGDEBUG)
        # TODO check result of find_roms here
        if ctx.actset['swl_name'] == 'mame':
            if ctx.emulation.emurun['zips']:
                playfile = os.path.join(
                    ctx.emulation.emurun['folder'],
                    ctx.actset['name']+'.zip')
                xbmc.log("UMSA gui: copy rom file", xbmc.LOGDEBUG)
                if xbmcvfs.copy(
                    ctx.emulation.emurun['zips'][0], playfile):
                    xbmc.log("UMSA gui: copy successful", xbmc.LOGINFO)
                else:
                    xbmc.log("UMSA gui: copy error!!!", xbmc.LOGWARNING)
            # TODO also copy chds = ctx.emulation.emurun['disks']
        elif ctx.actset['swl_name'] in NONMAME:
            if 'gb64' in ctx.actset['swl_name']:
                ctx.emulation.extract_rom()
                if 'extract_files' in ctx.emulation.emurun:
                    for pfile in ctx.emulation.emurun['extract_files']:
                        if pfile != 'VERSION.NFO':
                            playfile = os.path.join(
                                ctx.emulation.emurun['folder'],
                                ctx.emulation.emurun['extract_files'][0])
            else:
                if ctx.emulation.emurun['zips']:
                    playfile = os.path.join(
                        ctx.emulation.emurun['folder'],
                        #ctx.actset['name']+'.zip'
                        os.path.basename(ctx.emulation.emurun['zips'][0])
                    )
                    xbmcvfs.copy(
                        ctx.emulation.emurun['zips'][0], playfile)
        elif ctx.emulation.emurun['zips']:
            ctx.emulation.extract_rom()
            if 'extract_files' in ctx.emulation.emurun:
                playfile = os.path.join(
                    ctx.emulation.emurun['folder'],
                    ctx.emulation.emurun['extract_files'][0])
        elif ctx.emulation.emurun['chds']:
            # TODO loop and copy all chds
            playfile = os.path.join(
                ctx.emulation.emurun['folder'],
                ctx.emulation.emurun['disks'][0]['disk']+'.chd')
            xbmcvfs.copy(ctx.emulation.emurun['chds'][0],playfile)
        else:
            ctx.stop_screensaver()
            ctx.emu_dialog.close()
            ctx.dialog.notification(
                heading='error', message='seems we can not find the rom?',
                icon=xbmcgui.NOTIFICATION_ERROR, time=7500)
            return

    # stop if nothing found to play
    if not playfile:
        ctx.stop_screensaver()
        ctx.emu_dialog.close()
        ctx.dialog.notification(heading='error', message='rom not found',
            icon=xbmcgui.NOTIFICATION_ERROR, time=7500)
        return
    xbmc.log(f"UMSA gui: playfile = {playfile}", xbmc.LOGDEBUG)

    # start retroplayer
    xbmc.log(f"UMSA gui: actset: {ctx.actset}", xbmc.LOGDEBUG)
    game_item = xbmcgui.ListItem(playfile)
    game_item.setInfo(type='game', infoLabels={ 'title': ctx.actset['gamename']})
    game_tag = game_item.getGameInfoTag()
    game_tag.setTitle(     ctx.actset['name'] )
    game_tag.setPlatform(  ctx.actset['machine_label'] )
    game_tag.setGenres( [  ctx.actset['category'], ] )
    game_tag.setPublisher( ctx.actset['publisher'] )
    game_tag.setDeveloper( ctx.actset['publisher'] ) # get dev from game entry
    game_tag.setOverview(  'set info from history' ) # TODO
    if ctx.actset['year'].isdigit():
        game_tag.setYear(  int(ctx.actset['year']) )
    else:
        game_tag.setYear(0)
    # TODO depends on swl, add-id is name? check log or addon
    # Sets the add-on ID of the game client executing the game.
    #game_tag.setGameClient()
    if ctx.player.isPlaying():
        ctx.player.stop()
        xbmc.sleep(500)
    ctx.player.play(playfile, game_item)
    ctx.stop_screensaver()
    ctx.emu_dialog.close()
    # TODO need to exit or found out how to deinit window and init after play session
    # but when is play over? !!! check ctx.player.isPlaying()
    # as longs is its playing the game runs!
    ctx.exit()

    # TODO update status, but how to measure playtime?
    # start thread, wait for kodi signal that retroplayer stops?
    return
