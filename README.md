# script.umsa.mame.surfer
Kodi Add-on: A frontend for MAME with the UMSA twist

What's the difference to all the other frontends?

This frontend uses the information from https://umsa.info which shows all ports, conversions, remakes and sometimes clones and homebrews which are documented in MAME for the same software.

![screenshot1](https://github.com/sparrowred/script.umsa.mame.surfer/raw/master/resources/screenshot1.png)
![screenshot2](https://github.com/sparrowred/script.umsa.mame.surfer/raw/master/resources/screenshot2.png)

Warning: Software is still in development, expect some bugs and some not so well working features.

Features:
- Tries to choose the best machine for an entry from a MAME softwarelist.
- Simple support for different emulators which includes chd and zip extraction.
- Filter options for softwarelists, categories, number of players and years.
- Lists for softwarelists, sources, categories, publishers, years and play status.
- Saves snapshots directly to the softwarelist directory.
- Support for ProgettoSnaps artwork files and also a second artwork directory.
- Supports all different MAME support files.
- Implements a http://replay.marpirc.net/ replayer and a Youtube video search.

What you need:
- A working MAME installation, see https://mamedev.org
- The Kodi mediacenter, see https://kodi.tv
- Some MAME artwork files from http://www.progettosnaps.net
  (Otherwise you will only see text, most important are the cabinets.)
- Some MAME support files like https://www.arcade-history.com and https://mameinfo.mameworld.info. You can see an overview here: http://www.progettosnaps.net/support/

How to install:
1. Download https://github.com/sparrowred/script.umsa.mame.surfer/archive/master.zip.
2. Start Kodi, go to Settings (the icon on top in the middle), System, Add-ons and activate "Unknown sources".
3. Go back to main menu, choose Add-ons and look for "Install from zip file". Search for your downloaded file and select it.
4. Now the UMSA MAME surfer icon should appear, start it.
5. The Settings will pop up, try to configure what you can.
   (Artwork: at the moment only unzipped images, like cabinets/cabinets/snes.png, are supported.)
6. Finally the Add-on should start, download the UMSA database and scan your artwork and support files.

Or just clone this repository to your Kodi addons directory and activate it in Kodi.

Optional: Go to Settings, Interface, Skin and Fonts, set to Arial based and it will also show Kanjis. You need to set the Settings level at least to Standard.

Usage:
- Move around in all 4 directions.
- The enter button starts the emulation.
- The context button (key c) opens context menus or lists.

See also:
https://github.com/sparrowred/screensaver.picture.slideshow, a fork of a Kodi Screensaver with support for UMSA MAME surfer.
