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
# also raised by Kodi itself when the mute changes (Application.SetMute)
ACTION_MUTE = 91

# Control ids of umsa_overlay.xml (the foreground overlay)
INFO_LABEL = 102
INFO_DETAIL = 108
PIC_MACHINE = 105
LEFT_ART = 104

# Control ids of umsa_saver.xml
IMAGE = [1, 2]
BACKG = [5, 6]

# Skin files; the main window and the foreground overlay share the resolution
SKIN_NAME = "default"
SKIN_RESOLUTION = "1080i"
SAVER_XML = "umsa_saver.xml"
OVERLAY_XML = "umsa_overlay.xml"

# Coordinate space of SKIN_RESOLUTION, used by the dynamic Python controls
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080

# Window properties (UMSA.Screensaver.* is shared with the frontend)
WINDOW_ID = 10000
MODE_PROPERTY = "UMSA.Screensaver.Mode"
RUNNING_PROPERTY = "UMSA.Screensaver.Running"
# shared with plugin.program.umsa.mame.surfer: both depend on the identical name
EMULATOR_RUNNING_PROPERTY = "UMSA.Emulator.Running"

# Kodi stops a woken Python screensaver 15 s later through this alarm
# (SCRIPT_ALARM / SCRIPT_TIMEOUT in Kodi's ApplicationPowerHandling.cpp)
KODI_SCREENSAVER_STOP_ALARM = "sssssscreensaver"

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
