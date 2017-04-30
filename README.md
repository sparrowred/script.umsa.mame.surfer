# script.umsa.mame.surfer
Kodi Add-on: A frontend for MAME with the UMSA twist

What's the difference?

This frontend uses the information from https://umsa.info which shows all
ports, conversions, remakes and sometimes clones and homebrews which are in MAME
for the same software.

Warning:
This software is in alpha status. So expect bugs, chrashes and not working features.

Features:
- Filter options for softwarelists, categories, number of players and years.
- Lists for source, softwarelists, categories, publishers, years and play status.
- Tries to choose the best machine for an entry from a softwarelist.
- Simple support for different emulators.
- Support for ProgettoSnaps artwork and datfiles.
- Moves taken snapshots from machine directory to software list directory.

Needed:
- A working MAME installation, see http://mamedev.org
- The Kodi mediacenter, see https://kodi.tv
- Some artwork from http://www.progettosnaps.net, otherwise it's so empty
- Some dat files like https://www.arcade-history.com and http://mameinfo.mameworld.info
  for additional informations

How to install:
1. Download the Add-on: https://umsa.info/umsa.mame.surfer.zip
2. Start Kodi, go to Settings (the icon on top in the middle), System,
   Add-ons and activate Unknown sources
3. Go back to main menu, Add-ons, use the icon on the top left,
   Install from zip file and choose umsa.mame.surfer.zip
4. Go back to main menu, Add-ons and you should see the UMSA MAME Surfer icon.
5. Select it and the Settings will pop up. Configure what you can.
   - ProgettoSnaps: only unzipped images like cabinets/cabinets/snes.png are supported
6. Now the Add-on will start. Have fun.

Optional: Go to Settings, Interface, Fonts and set to Arial based to get Kanjis.
You need to set the Settings level at least to Standard.

Usage:
- The enter button starts the emulation.
- In the dat section enter popups a list for Recommended, Series, Videos and Manuals.
- The context button (key c) opens a popup for different lists.
- Go up from the top for a menu which contains the Filter options.

Todo:
- Scan dat files and artwork pictures to database for faster access and startup.
- Speed up unoptimized databases statements (sometimes needs seconds).
- Add favorite lists.

See also:
https://github.com/sparrowred/screensaver.picture.slideshow, a fork of a
Kodi Screensaver with support for UMSA MAME surfer.

Contact: sparrowred16 at this gmail thing com