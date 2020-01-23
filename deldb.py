import os, sys, re
import xbmc, xbmcaddon

folder = xbmc.translatePath(
        'special://profile/addon_data/script.umsa.mame.surfer/'
)

os.remove( os.path.join( folder, 'umsa.db') )
os.remove( os.path.join( folder, 'dat.db') )
os.remove( os.path.join( folder, 'artwork.db') )

# TODO xbmc popup with done msg
