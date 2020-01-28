# -*- coding: utf-8 -*-
"""Delete UMSA MAME surfer database files from Kodi userdata folder

TODO
 - xbmc popup with done message
 - get folder from Kodi
"""

import os
import xbmc

FOLDER = xbmc.translatePath('special://profile/addon_data/script.umsa.mame.surfer/')
try:
    os.remove(os.path.join(FOLDER, 'umsa.db'))
    os.remove(os.path.join(FOLDER, 'dat.db'))
    os.remove(os.path.join(FOLDER, 'artwork.db'))
except FileNotFoundError:
    pass
