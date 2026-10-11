"""Kodi-managed screensaver entry point."""

import sys

import xbmcaddon

addon = xbmcaddon.Addon('screensaver.umsa.mame.surfer')
sys.path.insert(0, addon.getAddonInfo('path') + '/lib')

from umsa_screensaver.entry import run_automatic

if __name__ == "__main__":
    run_automatic()
