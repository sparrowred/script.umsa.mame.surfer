# -*- coding: utf-8 -*-
"""add-on start up"""

import os
import sys
import xbmc
import xbmcaddon

xbmc.log("UMSA MAME surfer: startup - sys.argv: {}".format(sys.argv))

FOLDER = xbmc.translatePath('special://profile/addon_data/script.umsa.mame.surfer/')

if len(sys.argv) == 1:
    # TODO: check what we really need from these infos
    __addon__ = xbmcaddon.Addon()
    __addonid__ = __addon__.getAddonInfo('id')
    __cwd__ = __addon__.getAddonInfo('path')
    __language__ = __addon__.getLocalizedString
    __resource__ = xbmc.translatePath(os.path.join(__cwd__, 'resources', 'lib'))
    # shared resources
    addonPath = ''
    addon = xbmcaddon.Addon(id='script.umsa.mame.surfer')
    addonPath = addon.getAddonInfo('path')
    BASE_RESOURCE_PATH = os.path.join(addonPath, "resources")
    sys.path.append(os.path.join(BASE_RESOURCE_PATH, "lib"))
    # start script
    import gui
elif sys.argv[1] == "del_db":
    try:
        os.remove(os.path.join(FOLDER, 'umsa.db'))
        os.remove(os.path.join(FOLDER, 'dat.db'))
        os.remove(os.path.join(FOLDER, 'artwork.db'))
    except FileNotFoundError:
        pass
elif sys.argv[1] == "del_status":
    try:
        os.remove(os.path.join(FOLDER, 'status.db'))
    except FileNotFoundError:
        pass
else:
    xbmc.log("UMSA MAME surfer: unknown arguments")
xbmc.log("UMSA MAME surfer: stopped")
