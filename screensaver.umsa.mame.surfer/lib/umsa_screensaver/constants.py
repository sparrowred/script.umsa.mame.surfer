"""Shared constants of the UMSA screensaver add-on.

Pure data only, no Kodi imports: the module can be imported by unit tests
without a Kodi runtime and stays free of side effects.
"""

# Action codes (keyboard/remote)
ACTION_PLAY_NEXTITEM = (14, 112)
ACTION_MOVEMENT_RIGHT = (2,)
ACTION_CONTEXT = (117,)
ACTION_VOLUME_UP = 88
ACTION_VOLUME_DOWN = 89
ACTION_STOP = 13

# Control ids of umsa_saver.xml
INFO_LABEL = 102
INFO_DETAIL = 108
PIC_MACHINE = 105
PIC_4TO3 = 104
PIC_3TO4 = 106
PIC_1TO1 = 107
IMAGE = [1, 2]
BACKG = [5, 6]
CROSS_BACKGROUND = 109

# Window properties (UMSA.Screensaver.* is shared with the frontend)
WINDOW_ID = 10000
MODE_PROPERTY = "UMSA.Screensaver.Mode"
RUNNING_PROPERTY = "UMSA.Screensaver.Running"
EMULATOR_RUNNING_PROPERTY = "UMSA.Emulator.Running"

# Screensaver modes
MODE_NONE = 'no'
MODE_VIDEOS = 'videos'
MODE_CROSS = 'cross'
MODE_SLIDE = 'slide'
MODE_WALL = 'wall'
MODE_EMU = 'emu'

# Artwork types shown per mode
ART_TYPES_BY_MODE = {
    MODE_VIDEOS: ['videosnaps'],
    MODE_CROSS: ['covers', 'flyers'],
    MODE_SLIDE: ["covers", "flyers", "cabinets", "cpanel", "marquees"],
    MODE_WALL: ['snap'],
}

# 16:9 reference aspect ratio
AR_NORM = 1.7777
