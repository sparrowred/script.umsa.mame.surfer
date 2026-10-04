# UMSA MAME Surfer - Agent Interaction Guide

This document describes how LLM agents should interact with the **UMSA (Universal MAME Selection Application)** Kodi addon. Use this guide to understand menu structures, available actions, and control flows.

**Key Architecture:**
- Kodi XML-based GUI with numbered control IDs
- SQLite database (`umsa.db`) for game metadata, artwork, and statistics
- JSON-RPC API on port 8080 for external communication
- Multi-layered screensaver system with various visual modes

---

## Main Menu Structure

The primary menu (MAIN_MENU, control ID 4901) presents these options:

| Menu Item | ID | Purpose | Actions |
|-----------|----|----|---------|
| **Show all / Series / Source / SWL** | M_ALL (61) / M_SERIES (3) / M_SOURCE (65) / M_SWL (66) | Browse games by categorization | Enter/Right to populate gamelist |
| **Media** | M_MEDIA (4) | Access videos, manuals, music, YouTube, replays | Opens media browser dialog |
| **Emulator (MAME)** | M_MACHINE (21) | Select machine/emulator | Shows available emulators |
| **Search** | M_SEARCH_NEW (51) | Text-based game search | Keyboard input, returns filtered list |
| **Filter** | M_FILTER (7) | Apply category filters | Context-toggle on/off, or open filter UI |
| **Screensaver** | M_SSAVER (82) | Launch visual screensaver modes | Menu selection for: videos, artwork cross, slide, wall, MARP, VGM |
| **Update** | M_UPD (81) | Refresh database/artwork/DAT files | Dialog for: db / dat / art / exo / gb64 |
| **Settings** | M_ASETTINGS (86) | Open addon configuration | Opens settings.xml |
| **Exit** | M_EXIT (9) | Close the addon | Saves state and closes |

---

## Game Selection & Navigation

**Primary Control Hierarchy:**
```
SOFTWARE_BUTTON (ID 4000)     [Main software carousel]
  ↓
SYSTEM_WRAPLIST (ID 4005)     [Machine variants with cabinet images]
  ↓
SET_LIST (ID 4003)            [Individual game sets/versions]
```

**Navigation Actions:**
- **Left/Right on SOFTWARE_BUTTON**: Cycle through history of last 10 selected games
- **Up/Down on SOFTWARE_BUTTON**: Display available artwork for current game
- **Context (Menu) on SOFTWARE_BUTTON**: Open main menu
- **Left/Right on SYSTEM_WRAPLIST**: Switch between machine variants
- **Up/Down on SYSTEM_WRAPLIST**: Cycle artwork for selected machine
- **Left/Right on SET_LIST**: Switch between game sets within a machine
- **Up/Down on SET_LIST**: Display artwork for selected set

---

## Gamelist Modes

When viewing games (GAME_LIST, ID 4007), the following modes determine what's displayed:

| Mode | ID | Content | Sort Options |
|------|----|---------| -------------|
| **Show all** | M_ALL (61) | All games for selected software | name, year, publisher |
| **Maker/Publisher** | M_MAKER (62) | Games by publisher | name, year, publisher |
| **Category** | M_CAT (63) | Games by type | name, year, publisher |
| **Year** | M_YEAR (64) | Games by release year | ±0, ±1, ±2 |
| **Players** | M_PLAYERS (90) | Games by player count | name, year, publisher |
| **Softwarelist** | M_SWL (66) | Non-MAME software list items | all swls, connected swls |
| **Source** | M_SOURCE (65) | MAME ROM source directory | name, year, publisher |
| **Recommended** | M_REC (67) | Games from DAT file recommendations | (no sort) |
| **Play Status** | M_PLAYSTAT (83) | By playtime metrics | time_played, last_played, play_count |
| **Search** | M_SEARCH / M_SEARCH_NEW (5/51) | Search results | new search |
| **Last Screensaver** | M_LSSAVER (84) | Previously used in screensaver | name, year, publisher |
| **All Emulators** | M_ALLEMUS (22) | List all configured emulators | (no sort) |
| **Machines** | M_MACHINE (21) | Machines for current SWL | name, year, publisher |

**Gamelist Actions:**
- **Enter**: Select game or apply filter option
- **Context**: Toggle filter on/off for current list
- **Up/Down**: Load/display artwork for highlighted game

---

## Artwork & Media System

### Image Sources

**Left Side Images** (snap, titles, howto, logo, bosses, ends, gameover, scores, select, versus, warning)
- From ProgettoSnaps database (external artwork library)
- Local MAME snapshots from configured snapshot directory
- Aspect ratio: 1:1 (square), 3:4 (vertical), or display-dependent

**Right Side Images** (cabinets, cpanel, flyers, marquees, media, cabdevs, pcb, artpreview, covers, projectmess_covers)
- Cabinet artwork, control panels, promotional materials
- Aspect ratio: 16:9 (widescreen) or display-dependent

### Media Access (M_MEDIA Menu)

| Media Type | Format | Source | Action |
|-----------|--------|--------|--------|
| **Videos** | MP4 | Database/artwork folder | Select to play in Kodi |
| **Manuals** | PDF | Configured path | Select to open PDF viewer |
| **VGM Music** | from vgmplay ZIP | Database reference | Select track, plays via vgmplay.lua |
| **YouTube Videos** | Web link | Database (searchable) | Select label "- Youtube" to search online |
| **MARP Replays** | ZIP input files | Online database | Select replay, downloads and plays with MAME |

**Media Retrieval Methods:**
```python
ggdb.get_further_media(software_id)  # Returns YouTube & MARP links
ggdb.get_random_art(art_types)       # Random artwork for screensaver
```

---

## Filter System

**Filter Categories:**
1. Softwarelists (SWL names)
2. Game Categories (genres/types)
3. Machine Categories (machine types)
4. Players (player counts)
5. Years (release years)
6. Load/Save Filter (save named filter sets)

**Filter Workflow:**
1. Menu → Filter
2. Select Filter Category
3. Edit Active/Inactive lists (FILTER_CONTENT_LIST_ACTIVE / INACTIVE)
4. Action via FILTER_OPTIONS: `all` / `none` / `invert`
5. Return to game lists (filter applied to all queries)

**Key Controls:**
- FILTER_CATEGORY_LIST (ID 4008): Select category
- FILTER_CONTENT_LIST_ACTIVE (ID 4088): Currently selected filters
- FILTER_CONTENT_LIST_INACTIVE (ID 4089): Available filters to add
- FILTER_OPTIONS (ID 4116): Select all/none/invert

**Database Methods:**
```python
ggdb.define_filter(filter_lists)           # Apply filter, returns count
ggdb.get_all_dbentries(category_name)      # Get category options
```

---

## Screensaver Modes

Access via Menu → Screensaver, or `play_saver(mode, art_types)` method.

### Mode: Videos
**Control ID:** `running = 'videos'`

Plays random video snippets from database in a playlist.

| Action | Key | Behavior |
|--------|-----|----------|
| Next Video | Right / Next Button (14, 112) | Load next video to playlist |
| Show Game | Context (117) | Stop video, load game into main UI, close screensaver |
| Volume Up | Plus (88) | Adjust volume, screensaver continues |
| Volume Down | Minus (89) | Adjust volume, screensaver continues |
| Any Other Key | - | Stop screensaver |

**Technical Details:**
- Stores software_id in video ListItem `votes` field for retrieval
- Player class monitors `onPlayBackStarted` and `onPlayBackEnded` events
- Shows game title/genre during video playback (fade in/out timing)
- Displays: machine pic (Trailer tag), left pic/snap (Director tag)

**Info Display:**
- INFO_LABEL (ID 102): Game title
- INFO_DETAIL (ID 108): Year, maker
- PIC_MACHINE (ID 105): Machine/cabinet image
- PIC_1TO1 (ID 107): Left-side snapshot (1:1 aspect)

---

### Mode: Crossover
**Control ID:** `running = 'cross'`

Randomly positioned artwork images overlay the screen, creating a "crossover" effect.

| Action | Key | Behavior |
|--------|-----|----------|
| Volume Up | Plus (88) | Adjust volume, continue (if VGM playing) |
| Volume Down | Minus (89) | Adjust volume, continue (if VGM playing) |
| Next Song | Right / Next (14, 112) | Skip VGM track (if playing) |
| Stop VGM | X (13) | Stop music, continue crossover |
| Any Other Key | - | Deactivate screensaver |

**Technical Details:**
- Creates ControlImage elements dynamically
- Positions: random x (0-1280), y (0-720)
- Sizes based on aspect ratio (Vertical, Horizontal, NotScaled)
- Maintains list of up to 60 images (oldest removed as new ones added)
- Uses artwork types: covers, flyers, cabinets, cpanel, marquees

**Info Display:**
- INFO_LABEL (ID 102): Current game name
- INFO_DETAIL (ID 108): Year, maker
- PIC_MACHINE (ID 105): Machine/cabinet image

---

### Mode: Slide
**Control ID:** `running = 'slide'`

Smooth transitions between artwork images (two-image fade effect).

| Action | Key | Behavior |
|--------|-----|----------|
| Volume Up | Plus (88) | Adjust volume, continue (if VGM playing) |
| Volume Down | Minus (89) | Adjust volume, continue (if VGM playing) |
| Next Song | Right / Next (14, 112) | Skip VGM track (if playing) |
| Stop VGM | X (13) | Stop music, continue slide show |
| Any Other Key | - | Deactivate screensaver |

**Technical Details:**
- Alternates between two image controls (IMAGE[0], IMAGE[1]) via fade animation
- Background images (BACKG[0], BACKG[1]) fade concurrently
- Aspect ratio: artwork NOT scaled (covers, flyers, cabinets, cpanel, marquees)
- Timing: configured via `ssaver_time` setting (seconds per image)

**Info Display:**
- INFO_LABEL (ID 102): Current game name
- INFO_DETAIL (ID 108): Year, maker
- PIC_MACHINE (ID 105): Machine/cabinet image

---

### Mode: Wall
**Control ID:** `running = 'wall'`

Grid of images that fill in random positions (like a puzzle).

| Action | Key | Behavior |
|--------|-----|----------|
| Volume Up | Plus (88) | Adjust volume, continue (if VGM playing) |
| Volume Down | Minus (89) | Adjust volume, continue (if VGM playing) |
| Next Song | Right / Next (14, 112) | Skip VGM track (if playing) |
| Stop VGM | X (13) | Stop music, continue wall |
| Any Other Key | - | Deactivate screensaver |

**Technical Details:**
- Dynamically creates grid of ControlImage elements (`wall['mesh']`)
- Dimensions calculated from settings:
  - Rows: `srows` to `srows_b` (snapshots) or `trows` to `trows_b` (titles)
  - Image width/height based on screen aspect ratio
  - Vertical images auto-sized with `vert_width` / `vert_x` offset
- Fill algorithm:
  1. Shuffle position list
  2. Pop random position from list
  3. Set image at that position
  4. Free spaces cycle random images (percentage-based)
- Uses artwork type: snap (or titles if configured)

**Settings:**
```python
ssaver_wall = {
    'srows': int,      # Min rows for snapshots
    'srows_b': int,    # Max rows for snapshots
    'trows': int,      # Min rows for titles
    'trows_b': int,    # Max rows for titles
    'free': int,       # Percentage of free spaces
    'titles': str      # "Snapshots" / "Titles" / "Random"
}
```

**Info Display:**
- INFO_LABEL (ID 102): Current game name
- INFO_DETAIL (ID 108): Year, maker
- PIC_MACHINE (ID 105): Machine/cabinet image
- Wall mesh positions updated dynamically

---

### Mode: MARP Replays (Dialog-based)
**Control ID:** Not screensaver (`running = 'no'`), but special dialog

Displays MAME emulation replay competition replays (M.A.M.E. Arcade Racing Productions).

**Access:** Menu → Screensaver → "Astonish me with a MARP replay" (random) or via `marp_replayer()` function

**Features:**
- Searches online MARP database for ranked replays
- Filters by version (random between 178-218)
- Displays: player name, rank, percentage, points
- Downloads `.inp` file and plays with MAME in "playback" mode

**Return Action:**
- After replay finishes or user presses cancel, returns to main UI

---

### Mode: VGM Music
**Control ID:** Not screensaver, integrated control

Plays random Video Game Music from MAME arcade sound tracks via `vgmplay.lua` script.

**Access:** Menu → Screensaver → "Play random Video Game Music"

**Features:**
- Plays via Lua script bridge to vgmplay emulator
- Sends commands: `volume_up`, `volume_down`, `exit`
- Stores flag: `playrandomvgm` (True when active)
- Shows MUSIC_INFO label (ID 4100) with player info

**Return Action:**
- Stop key (X) or any other action returns to main UI

---

## Action Codes (Keyboard/Controller Mappings)

```python
ACTION_CANCEL_DIALOG = (9, 10, 51, 92, 110)  # ESC, Back, etc
ACTION_PLAYFULLSCREEN = (12, 79, 227)         # TAB, etc
ACTION_MOVEMENT_LEFT = (1,)                   # Left arrow
ACTION_MOVEMENT_RIGHT = (2,)                  # Right arrow
ACTION_MOVEMENT_UP = (3,)                     # Up arrow
ACTION_MOVEMENT_DOWN = (4,)                   # Down arrow
ACTION_INFO = (11,)                           # Info key
ACTION_PLAY_NEXTITEM = (14, 112)              # Next track / right shoulder
ACTION_SOUND_VOLUME = (88, 89)                # Plus/Minus keys
ACTION_CONTEXT = (117,)                       # Context menu (right-click)
ACTION_ENTER = (7,)                           # Enter/Select

# Screensaver-specific
ACTION_STOP_VGM = (13,)                       # X key (stop)
```

---

## Control IDs Reference

### Main Interface
```python
SOFTWARE_BUTTON = 4000           # Main carousel for game selection
GAME_LIST = 4007                 # Game selection list
GAME_LIST_LABEL = 4117           # Label above game list
GAME_LIST_LABEL_ID = 4217        # Hidden label storing list mode ID
GAME_LIST_OPTIONS = 4118         # Sort/filter options
GAME_LIST_SORT = 4119            # Filter toggle (on/off)
SYSTEM_WRAPLIST = 4005           # Machine variants (horizontal wrap)
SET_LIST = 4003                  # Game sets (vertical list)
MAIN_MENU = 4901                 # Main menu
LISTMODE_MENU = 4902             # Submenu for list modes
```

### Filter System
```python
FILTER_CATEGORY_LIST = 4008      # Filter category selector
FILTER_CONTENT_LIST_ACTIVE = 4088   # Currently selected filters
FILTER_CONTENT_LIST_INACTIVE = 4089 # Available filters
FILTER_LABEL = 4109              # Category name label
FILTER_LABEL2 = 4110             # Filter set name label
FILTER_OPTIONS = 4116            # all / none / invert buttons
```

### Artwork Display
```python
IMAGE_BIG_LIST = 2233            # Right-side artwork list
IMAGE_LIST = 2223                # Left-side artwork list
IMAGE = [1, 2]                   # Slide mode image controls
LEFT_IMAGE_HORI = 2222           # Horizontal aspect image
LEFT_IMAGE_VERT = 2221           # Vertical aspect image
PIC_MACHINE = 105                # Screensaver: machine image
PIC_4TO3 = 104                   # Screensaver: 4:3 aspect image
PIC_3TO4 = 106                   # Screensaver: 3:4 aspect image
PIC_1TO1 = 107                   # Screensaver: 1:1 aspect image
BACKG = [5, 6]                   # Screensaver: background controls
```

### Info Display
```python
TEXTLIST = 4033                  # Info/DAT text display
LABEL_STATUS = 4101              # Status label (playtime, machine count)
MUSIC_INFO = 4100                # VGM player info display
INFO_LABEL = 102                 # Screensaver: title label
INFO_DETAIL = 108                # Screensaver: detail label (year, maker)
```

### Machine Display
```python
SYSTEM_BORDER = 2405             # Border around machine icons
MACHINE_SEP1 = 2406              # Machine separator 1
MACHINE_SEP2 = 2407              # Machine separator 2
MACHINE_SEP3 = 2408              # Machine separator 3
MACHINE_PLUS = 4210              # "+" indicator for >4 machines
SHADOW_MACHINE = 4201            # Shadow indicator
SHADOW_SET = 4202                # Shadow indicator
SHADOW_DAT = 4203                # Shadow indicator
```

---

## Emulator Management

### Emulator Types

| Emulator | ID | Purpose | Notes |
|----------|----|---------| ------|
| **MAME** | `exe: "mame"` | Primary emulator for arcade/SWL | Fully integrated, supports MARP |
| **Kodi Retroplayer** | `exe: "kodi"` | Kodi's built-in emulation | Uses Batocera mapping for ROM paths |
| **eXoDOS** | `exe: "exodos"` / `exe: "exodos_alt"` | DOS game launcher | Standard or alternate shell |
| **MARP** | `exe: "marp"` | Replay playback | Downloads `.inp`, plays with MAME |
| **Custom** | `exe: <user-defined>` | User-configured emulator | Via configure dialog |

### Configuration Dialog

**Access:** Menu → Emulator → "Choose a different emulator" → "Configure new emulator"

**Steps:**
1. Select executable path (browse file dialog)
2. Set working directory
3. Choose extraction mode: "Extract zip/chd" or "Start with zip/chd"
4. Define startup mode: "Normal" / "Watch" / "Fallback"
5. Enter emulator name
6. Save to database

**Emulator Connection:**
- MAME: Linked to source ROMs (e.g., `source='arcade'`)
- SWL: Linked to software list (e.g., `swl_name='c64'`)
- Custom: Can support multiple game types

### Database Methods
```python
ggdb.get_emulators(source=None, swl_name=None)      # Get emulators
ggdb.save_emulator(emu_info, reconfigure, ...)      # Save config
ggdb.delete_emulator(emu_id)                        # Remove emulator
ggdb.delete_emulator_connection(emu_conn_id)        # Unlink emulator
ggdb.connect_emulator(emu_id, source=None, swl_name=None)  # Link emulator
```

---

## Update Operations

Access via Menu → Update, then select operation:

| Operation | Python Call | Duration | Purpose |
|-----------|-------------|----------|---------|
| **Update Database** | `update('db')` | ~30-60 sec | Download latest UMSA.db from umsa.info |
| **Scan DAT Files** | `update('dat')` | ~5-30 min | Index game history, info metadata |
| **Scan Artwork** | `update('art')` | ~10-60 min | Scan ProgettoSnaps directories |
| **Scan eXoDOS** | `update('exo')` | ~5-15 min | Index eXoDOS game data |
| **Scan GB64** | `update('gb64')` | ~5-15 min | Index GameBase64 data |

**Technical:**
- Database operations run in background threads
- Progress dialog displays current file/status
- Runs asynchronously (non-blocking)

---

## Database Query API

### Game Data Retrieval
```python
# By software/machine
get_by_software(software_id)
get_by_swl(swl_name, software_id)
get_by_maker(maker_id, software_id)
get_by_cat(category_id, software_id)
get_by_year(year, software_id)
get_by_players(nplayers, software_id)

# Search & metadata
get_searchresults(search_string)               # Full-text search
get_random_id()                                # Get random game
search_single(gamename)                        # Find specific game
get_series(software_id)                        # Games in series
get_machines(swl_name, machine_name)           # Machines for SWL
get_machine_name(machine_id)                   # Machine info

# Artwork
get_artwork_by_software_id(software_id, art_type)  # Specific artwork
get_random_art(art_types)                      # Random artwork (screensaver)
get_art_types()                                # Available artwork types

# Media & Links
get_further_media(software_id)                 # YouTube, MARP links
get_last_played(stat_type)                     # Play statistics

# Emulators
get_emulators(source=None, swl_name=None)
get_emulator(emu_id=None, emu_conn_id=None)

# Filter operations
define_filter(filter_lists)                    # Apply filter, returns count
get_all_dbentries(category_name)               # List category items

# Status tracking
write_status_after_play(software_id, playtime_seconds)
make_time_nice(seconds)                        # Format playtime
```

---

## Common Workflows

### Starting a Game
1. Navigate SOFTWARE_BUTTON (carousel left/right)
2. Press Context (Menu) to open MAIN_MENU
3. Select menu item (e.g., M_ALL) to populate GAME_LIST
4. Browse GAME_LIST with up/down
5. Press Enter to select game
6. Emulator launched via `run_emulator()` method

### Searching for a Game
1. Menu → Search (M_SEARCH_NEW)
2. Enter search text via keyboard
3. GAME_LIST populated with results
4. Select result to navigate to that game (adds to history)

### Applying Filters
1. Menu → Filter (M_FILTER)
2. Select FILTER_CATEGORY_LIST item (e.g., "Game Categories")
3. Move between FILTER_CONTENT_LIST_ACTIVE and FILTER_CONTENT_LIST_INACTIVE
4. Press Enter to toggle items between lists
5. Return to game lists (filter auto-applied to all queries)

### Playing Media
1. Select game (populates M_MEDIA with available media)
2. Menu → Media (M_MEDIA)
3. Choose:
   - Videos (MP4) → plays in Kodi player
   - Manuals (PDF) → opens PDF viewer
   - Music (VGM) → plays via vgmplay.lua
   - YouTube → opens online search
   - Replays (MARP) → downloads and plays with MAME
4. Return to main UI when finished

### Starting a Screensaver
1. Menu → Screensaver (M_SSAVER)
2. Select mode:
   - "I wanna see random videos"
   - "Make me the artwork crossover"
   - "Just slide one after another"
   - "Gimme da wall, now"
   - "Astonish me with a MARP replay"
   - "Play random Video Game Music"
3. Screensaver runs until user input (mode-specific controls)

### Updating Database
1. Menu → Update (M_UPD)
2. Select operation
3. Progress dialog shows status
4. Operation runs in background

---

## Settings & Configuration

Key settings to understand for agent interactions:

```python
# Paths & Emulation
mame_exe              # MAME executable path
mame_dir              # MAME working directory
mamedir               # Alternative MAME directory reference
mameini               # MAME configuration file path
chdman_exe            # CHD disk creator utility
temp_path             # Temporary directory for ROM extraction
datdir                # DAT files directory

# Artwork & Display
progetto              # ProgettoSnaps main path
otherart              # Additional artwork path
aspectratio           # Screen aspect: 16:9, 16:10, 5:4, 4:3
cab_path              # Cabinet artwork path (calculated)

# Features
pref_country          # Preferred country for game sorting
pdfviewer             # PDF viewer application
terminal              # Terminal emulator (for output)
emulation_start       # Start mode: Normal(0), Watch(1), Fallback(2)

# Non-MAME Systems
exodos                # eXoDOS path
gb64                  # GameBase64 path
whdload               # WHDLoad Amiga path

# Screensaver
play_video            # Auto-play videos: true/false
ssaver_time           # Seconds per image (int)
ssaver_info           # Show info labels: true/false
ssaver_musicinfo      # Music info display mode
ssaver_videos         # Enable video mode: true/false
ssaver_slide          # Enable slide mode: true/false
ssaver_wall           # Enable wall mode: true/false
ssaver_cross          # Enable crossover mode: true/false
ssaver_titles         # "Snapshots" / "Titles" / "Random"
ssaver_trows          # Title rows min/max
ssaver_srows          # Snapshot rows min/max
ssaver_free           # Free space percentage (0-100)
```

---

## JSON-RPC API (Port 8080)

For external tools interacting with Kodi/UMSA:

```
http://localhost:8080/jsonrpc
```

### Useful Methods
```python
# GUI operations
GUI.GetProperties              # Get active window/dialog state
GUI.SetProperty(property, value)

# Input/Control
Input.ExecuteAction(action)    # Send keyboard/remote actions
# Actions: 7=Enter, 9=Back, 117=Context, 1=Left, 2=Right, 3=Up, 4=Down

# Playback
Player.GetProperties           # Check video/audio playback status
Player.PlayPause
Player.Stop

# File System
Files.GetDirectory(directory)  # Browse file system
```

---

## Important Constants

### Game Database Fields
```python
set_info = {
    'id': int,                 # Unique software ID
    'name': str,               # Set name (arcade/emulator internal)
    'gamename': str,           # Display name (full title)
    'detail': str,             # Variant info (revision, country)
    'year': str,               # Release year
    'publisher': str,          # Developer/Publisher
    'category': str,           # Game type/genre
    'nplayers': str,           # Player count
    'swl_name': str,           # Software list (mame, c64, etc)
    'machine_name': str,       # Emulator machine
    'machine_label': str,      # Display label for machine
    'source': str,             # ROM source directory (MAME)
    'clone': int,              # Parent ID if clone (0 if parent)
    'is_machine': bool,        # Is actual machine vs game
    'display_rotation': int,   # Screen rotation (0, 90, 270)
    'display_type': str,       # Screen type (lcd, standard)
    'last_played': dict,       # {play_count, time_played, last_nice}
    'right_pics': [],          # Artwork list (right side)
    'left_pics': [],           # Artwork list (left side)
    'localsnaps': [],          # Local MAME snapshots
}

artwork_item = {
    'id': int,                 # Software ID
    'type': str,               # snap, titles, cabinets, etc
    'name': str,               # Base filename
    'path': int,               # 0=other_artwork, 1=progetto
    'extension': str,          # png, jpg, etc
    'swl_name': str,           # Software list
    'gamename': str,           # Display name
    'year': str,               # Release year
    'maker': str,              # Publisher
    's_id': int,               # Software ID (for playlists)
    'filename': str,           # Full path (for special cases)
    'left_pic': str,           # Left-side image path (optional)
}
```

### Screensaver State
```python
saver.running = 'no'           # Stopped
saver.running = 'videos'       # Playing videos
saver.running = 'cross'        # Crossover artwork
saver.running = 'slide'        # Slide show
saver.running = 'wall'         # Wall grid
saver.running = 'emu'          # After emulator run
```

---

## Key Methods for Agent Interaction

### Main GUI Class (UMSA)
```python
# Selection
select_software(software_id)
software_move(direction)        # 'left' or 'right' in history

# Game Lists
update_gamelist(menu_item_id)   # Populate game list for mode
popup_gamelist(gamelist, label, pos=0, sort=None, options=None)
gamelist_click()                # Handle selection in game list
gamelist_move()                 # Load artwork when browsing

# Menu Management
build_main_menu(select=None)
build_sublist_menu(select)
show_fulllist(what, label)

# Emulation
run_emulator(emu_infos)
configure_emulator(emu_info=None, reconfigure=False)
marp_replayer(dl_file=None, set_name=None, random=None)

# Artwork
show_artwork(howmuch='all')     # 'all', 'set', 'machine'
search_snaps(set_info)
create_artworklist()

# Filter Management
set_filter_content(cat, update=None)
gamelist_switch_filter()

# Updates
update(what)                    # 'db', 'dat', 'art', 'exo', 'gb64'
update_all()

# Utilities
exit()                          # Save state and close
choose_media()                  # Display media browser
show_rec()                      # Show recommended list
```

### Monitor Class (Screensaver Manager)
```python
play_saver(saver, art_types=None)  # Start screensaver
# saver: 'videos', 'cross', 'slide', 'wall'
# art_types: list of artwork types or None (auto-select)

play_random_vgm()              # Start VGM playback
onScreensaverDeactivated()     # Handle screensaver stop
reallyDeactivateScreensaver()  # Force cleanup
```

---

## Interaction Tips for Agents

1. **Menu Navigation**: Always check `MAIN_MENU` selected item via `getControl(MAIN_MENU).getSelectedItem().getLabel2()` to determine current context.

2. **Gamelist Population**: Different modes require different database queries. Check `GAME_LIST_LABEL_ID` to identify current mode before interpreting results.

3. **Artwork Loading**: After selecting a game, call `gamelist_move()` to load artwork properties (snaps/images).

4. **Screensaver Commands**: Screensaver modes have unique control behaviors. Check `saver.running` state before assuming action mappings.

5. **VGM Integration**: VGM playback persists through screensaver exits if `playrandomvgm == True`. Check this flag to avoid interrupting music.

6. **Filter State**: Always check `ggdb.use_filter` before assuming unfiltered results. Filter is toggleable via context menu.

7. **History Navigation**: `lastptr` and `last[]` array track game history. Use `software_move('left'/'right')` instead of direct index access.

8. **Thread Safety**: Background update operations run in separate threads. Check `scan_thread.is_alive()` before starting new update.

9. **Aspect Ratio Handling**: Call `check_image_aspect(set_info)` to get display orientation (Vertical/Horizontal/NotScaled) for proper image sizing.

10. **Database Timing**: Initial database load in `onInit()` may take several seconds. Wait for `self.ggdb` to exist before running queries.

---

## Troubleshooting Notes

- **No results in gamelist**: Check if filter is enabled (`ggdb.use_filter`). May need to load default filter.
- **Images not displaying**: Verify paths in settings (progetto, otherart). Check PIL library availability for image validation.
- **Screensaver exits immediately**: Verify screensaver mode is enabled in settings (`ssaver_videos`, `ssaver_cross`, etc).
- **VGM not playing**: Check that `vgmplay` software set exists in database and Lua script is accessible.
- **Emulator not found**: Verify executable path in settings and that working directory has write permissions.
- **MARP fails**: Check internet connection and verify MAME version is in range (178-218).

---

**Last Updated**: 2024
**Addon**: UMSA MAME Surfer (script.umsa.mame.surfer)
