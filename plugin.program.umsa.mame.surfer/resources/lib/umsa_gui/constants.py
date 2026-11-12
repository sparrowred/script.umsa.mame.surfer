"""Control IDs, action codes and menu codes of the UMSA frontend.

The values are part of the contract with the Estuary skin XML and with the
screensaver add-on. They must not change: ``gui.py`` re-exports them so the
historic public names keep working.
"""

# DAT display category of the driver WIP, defined once in Core
from umsa_core.dat_parser import DRIVER_WIP as _DRIVER_WIP

# shared with the screensaver and the Kodi adapter; defined once in Core
from umsa_core.window_properties import EMULATOR_RUNNING_PROPERTY  # noqa: F401

# Action codes
# See guilib/Key.h
ACTION_CANCEL_DIALOG = (9, 10, 51, 92, 110)
ACTION_PLAYFULLSCREEN = (12, 79, 227)
ACTION_MOVEMENT_LEFT = (1,)
ACTION_MOVEMENT_RIGHT = (2,)
ACTION_MOVEMENT_UP = (3,)
ACTION_MOVEMENT_DOWN = (4,)
ACTION_MOVEMENT = (1, 2, 3, 4, 5, 6, 159, 160)
ACTION_INFO = (11,)
ACTION_PLAY_NEXTITEM = (14, 112)
ACTION_SOUND_VOLUME = (88, 89)
ACTION_CONTEXT = (117,)
ACTION_ENTER = (7,)
# movement in a vertical list: up/down, page up/down, mouse wheel,
# scroll up/down (analog trigger), next/previous letter
ACTION_LIST_SCROLL = (3, 4, 5, 6, 104, 105, 111, 112, 159, 160)
# sent by GamelistSettle via the builtin Action(noop)
ACTION_NOOP = (999,)

# seconds without list movement before the gamelist entry is (re)loaded
GAMELIST_SETTLE_DELAY = 0.3
# an onAction callback starting less than this many seconds after the previous
# handler ended was queued while that handler ran (held key) and is dropped
ACTION_BACKLOG_THRESHOLD = 0.02

# ControlIds
SERIES_LABEL = 2301
COMPILATION_LABEL = 2302
MEDIA_LABEL = 2303
VIDEO_LABEL = 2005
SOFTWARE_BUTTON = 4000
MAIN_MENU = 4901
GROUP_GAME_LIST = 407
GROUP_FILTER = 408
TEXTLIST = 4033
# keys of the TEXTLIST entries that are no DAT text (ListItem property 'key');
# the 'no info' entry stands for a missing DAT text and opens no text viewer
TEXTLIST_KEY_PROPERTY = 'key'
TEXTLIST_KEY_NO_INFO = 'no_info'
TEXTLIST_KEY_EMU_OUTPUT = 'emu_output'
# placeholder in TEXTLIST_ORDER for DAT categories not listed by name (free
# "- XYZ -" headings of a DAT, e.g. 'Tips/Tricks'); they sort alphabetically
TEXTLIST_OTHER_CATEGORIES = None
# fixed order of the DAT categories in TEXTLIST ('Emulator output' is appended
# after an emulator run by emulator_setup.add_or_update_emu_output)
TEXTLIST_ORDER = (
    'History',
    'Info',
    'MInfo',
    'Sysinfo',
    'eXoDOS',
    'GameBase64',
    'Story',
    'Gameplay',
    'Start',
    'Setup',
    'Play Inst.',
    'Score',
    'Command',
    TEXTLIST_OTHER_CATEGORIES,
    'WIP',
    'others',
    _DRIVER_WIP,
)
# DAT categories never shown in TEXTLIST ('Rec' has its own menu entry)
TEXTLIST_HIDDEN = ('Contribute', 'Rec')
IMAGE_RIGHT = 2232
IMAGE_BIG_LIST = 2233
IMAGE_LIST = 2223
LEFT_IMAGE_HORI = 2222
LEFT_IMAGE_VERT = 2221
SET_LIST = 4003
SYSTEM_BORDER = 2405
SYSTEM_WRAPLIST = 4005
MACHINE_PLUS = 4210
MACHINE_COUNT = 4211
MACHINE_SEP1 = 2406
MACHINE_SEP2 = 2407
MACHINE_SEP3 = 2408
LISTMODE_MENU = 4902
# TODO rename GAME_LIST to LISTMODE
GAME_LIST = 4007
GAME_LIST_BG = 4107
GAME_LIST_LABEL = 4117
GAME_LIST_LABEL_ID = 4217
GAME_LIST_OPTIONS = 4118
GAME_LIST_SORT = 4119
GAME_LIST_IMAGE = 4115
GAME_LIST_TEXT = 4114
FILTER_CATEGORY_LIST = 4008
FILTER_CONTENT_LIST_ACTIVE = 4088
FILTER_CONTENT_LIST_INACTIVE = 4089
FILTER_LIST_BG = 4108
FILTER_LABEL = 4109
FILTER_LABEL2 = 4110
FILTER_OPTIONS = 4116
MUSIC_INFO = 4100
LABEL_STATUS = 4101
SHADOW_MACHINE = 4201
SHADOW_SET = 4202
SHADOW_DAT = 4203

# kind of the list shown in GAME_LIST (UMSA.gamelist_kind): the handlers
# dispatch on it, never on the visible list title
KIND_SOFTWARE = 'software'
KIND_SELECT = 'select'
KIND_MACHINES = 'machines'
KIND_EMULATORS = 'emulators'
KIND_MEDIA = 'media'

# GAME_LIST entries carry their id in label2, optionally as '<what>::<id>'
ENTRY_ACTION = 'action'
ENTRY_SEARCH = 'search'
ACTION_START_MAME = 'mame'
ACTION_START_KODI = 'kodi'
ACTION_START_EXODOS = 'exodos'
ACTION_START_EXODOS_ALT = 'exodos_alt'
ACTION_CHOOSE_EMULATOR = 'choose_emulator'
SEARCH_YOUTUBE = 'youtube'
SEARCH_MARP = 'marp'

# keys of the GAME_LIST_OPTIONS / FILTER_OPTIONS entries (label2)
OPTION_NEW_SEARCH = 'new search'
OPTIONS_PLAY_STATUS = ('time_played', 'last_played', 'play_count')
OPTIONS_ORDER = ('name', 'year', 'publisher')
FILTER_OPTION_ALL = 'all'
FILTER_OPTION_NONE = 'none'
FILTER_OPTION_INVERT = 'invert'

# keys of the filter category list entries that are no category (label2)
FILTER_KEY_LOAD = 'load_filter'
FILTER_KEY_SAVE = 'save_filter'

# menu
M_MACHINE = 21
M_ALLEMUS = 22
M_SERIES = 3
M_MEDIA = 4
M_SEARCH = 5
M_SEARCH_NEW = 51
M_ALL = 61
M_MAKER = 62
M_CAT = 63
M_YEAR = 64
M_SOURCE = 65
M_SWL = 66
M_REC = 67
M_FILTER = 7
M_UPD = 81
M_SSAVER = 82
M_PLAYSTAT = 83
M_LSSAVER = 84
M_ASETTINGS = 86
M_EXIT = 9
M_PLAYERS = 90

# xbmc.sleep times in ms
WAIT_PLAYER = 500
WAIT_GUI = 100

# order of listmode submenu for select
SUBMENU_ORDER = {
    M_ALL: 0, M_SERIES: 1, M_MAKER: 2, M_CAT: 3, M_REC: 4, M_YEAR: 5, M_PLAYERS: 6,
    M_SWL: 7, M_SOURCE: 7, M_SSAVER: 8, M_PLAYSTAT: 9
}

# public filter category labels in writer/file order
FILTER_CATEGORY_KEYS = (
    "Softwarelists",
    "Game Categories",
    "Machine Categories",
    "Years",
    "Players",
)
