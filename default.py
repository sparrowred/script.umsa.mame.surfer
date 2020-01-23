import os
import sys
#import re
import xbmc
import xbmcaddon

__addon__ = xbmcaddon.Addon()
__addonid__ = __addon__.getAddonInfo('id')
__cwd__ = __addon__.getAddonInfo('path')#py2.decode("utf-8")
__language__ = __addon__.getLocalizedString
__resource__ = xbmc.translatePath(
    os.path.join(__cwd__, 'resources', 'lib')#py2.encode("utf-8")
)#py2.decode("utf-8")

# Test
#print("### sys.argv ###")
#print(sys.argv)

# Shared resources
addonPath = ''
addon = xbmcaddon.Addon(id='script.umsa.mame.surfer')
addonPath = addon.getAddonInfo('path')

BASE_RESOURCE_PATH = os.path.join(addonPath, "resources")
sys.path.append(os.path.join(BASE_RESOURCE_PATH, "lib"))

import gui
