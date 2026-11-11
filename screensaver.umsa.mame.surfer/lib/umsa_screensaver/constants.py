"""Shared constants of the UMSA screensaver add-on.

Pure data only, no Kodi imports: the module can be imported by unit tests
without a Kodi runtime and stays free of side effects.
"""

from umsa_core.window_properties import (  # noqa: F401 - re-exported names
    EMULATOR_RUNNING_PROPERTY,
    SCREENSAVER_MODE_PROPERTY,
    SCREENSAVER_RUNNING_PROPERTY,
    SHARED_WINDOW_ID,
)

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

# Window properties shared with the frontend and the Kodi adapter; the names
# are defined once in umsa_core.window_properties
WINDOW_ID = SHARED_WINDOW_ID
MODE_PROPERTY = SCREENSAVER_MODE_PROPERTY
RUNNING_PROPERTY = SCREENSAVER_RUNNING_PROPERTY

# Kodi stops a woken Python screensaver 15 s later through this alarm
# (SCRIPT_ALARM / SCRIPT_TIMEOUT in Kodi's ApplicationPowerHandling.cpp)
KODI_SCREENSAVER_STOP_ALARM = "sssssscreensaver"

# Screensaver modes
MODE_VIDEOS = 'videos'
MODE_CROSS = 'cross'
MODE_SLIDE = 'slide'
MODE_WALL = 'wall'

# Artwork types shown per mode
ART_TYPES_BY_MODE = {
    MODE_VIDEOS: ['videosnaps'],
    MODE_CROSS: ['covers', 'flyers'],
    MODE_SLIDE: ["covers", "flyers", "cabinets", "cpanel", "marquees"],
    MODE_WALL: ['snap'],
}

# 16:9 reference aspect ratio
AR_NORM = 1.7777
