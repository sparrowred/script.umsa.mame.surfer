"""Typed access to the UMSA settings (owned by ``script.module.umsa.core``).

All settings of the UMSA add-ons live in the Core add-on; the frontend has no
settings of its own. ``SharedSettings.from_raw`` turns the raw Kodi strings into
typed values. The resolve helpers derive the effective MAME paths from optional
settings. Kodi-free: callers pass the ``getSetting`` function and file checks.
"""

import os
from dataclasses import dataclass, fields

ASPECT_RATIOS = {
    "16:9": 1.7777,
    "16:10": 1.6,
    "5:4": 1.25,
    "4:3": 1.3333,
}
DEFAULT_ASPECT_RATIO = "16:9"

# emulation_start values (settings.xml integer list)
EMULATION_START_NORMAL = 0
EMULATION_START_WATCH = 1
EMULATION_START_FALLBACK = 2
EMULATION_START_MODES = (
    EMULATION_START_NORMAL, EMULATION_START_WATCH, EMULATION_START_FALLBACK)

DEFAULT_VGM_PORT = 22713
COUNTRIES = ("USA", "Europe", "Japan")

# Filter category names shown in the UI - must match the status.db filter mappings
FILTER_CATEGORIES = [
    "Softwarelists", "Game Categories", "Machine Categories", "Players",
    "Years", "----------", "Load Filter", "Save Filter"
]


@dataclass(frozen=True)
class SharedSettings:
    """Values of the settings in ``script.module.umsa.core/resources/settings.xml``.

    Field names are the setting ids. Paths stay unresolved here: an empty
    optional path means "derive it" (see ``resolve_mame_setup``,
    ``resolve_chdman``; the Kodi adapter fills an empty ``rom_temp_dir``).
    """

    # Emulators
    mame_exe: str = ""
    mame_ini: str = ""
    mame_working_dir: str = ""
    chdman_exe: str = ""
    emulation_start: int = EMULATION_START_NORMAL
    terminal: str = ""
    exodos_dir: str = ""
    gb64_dir: str = ""
    whdload_dir: str = ""
    # Media
    progettosnaps_dir: str = ""
    own_artwork_dir: str = ""
    support_files_dir: str = ""
    vgmplay_exe: str = ""
    vgm_port: int = DEFAULT_VGM_PORT
    show_music_info: bool = True
    vgm_show_machine_list: bool = False
    vgm_max_duration: int = 180
    vgm_intro_duration: int = 0
    # Frontend
    pref_country: str = "USA"
    auto_play_videos: bool = False
    rom_temp_dir: str = ""
    rom_cache: bool = False
    batocera_layout: bool = True
    pdf_viewer: str = ""
    aspect_ratio: str = DEFAULT_ASPECT_RATIO

    @classmethod
    def from_raw(cls, get):
        """Build the settings from ``get(setting_id) -> str`` (Kodi getSetting).

        Empty or invalid values fall back to the field default, so a fresh
        profile or a hand-edited settings file never raises here.
        """

        defaults = cls()
        values = {}
        for field in fields(cls):
            raw = get(field.name)
            raw = raw.strip() if isinstance(raw, str) else raw
            default = getattr(defaults, field.name)
            if isinstance(default, bool):
                values[field.name] = (
                    default if raw in (None, "") else raw == "true")
            elif isinstance(default, int):
                try:
                    values[field.name] = int(raw)
                except (TypeError, ValueError):
                    values[field.name] = default
            else:
                values[field.name] = raw if raw else default

        if values["emulation_start"] not in EMULATION_START_MODES:
            values["emulation_start"] = defaults.emulation_start
        if not 1024 <= values["vgm_port"] <= 65535:
            values["vgm_port"] = defaults.vgm_port
        if not 20 <= values["vgm_max_duration"] <= 300:
            values["vgm_max_duration"] = defaults.vgm_max_duration
        if not 0 <= values["vgm_intro_duration"] <= 30:
            values["vgm_intro_duration"] = defaults.vgm_intro_duration
        if values["pref_country"] not in COUNTRIES:
            values["pref_country"] = defaults.pref_country
        if values["aspect_ratio"] not in ASPECT_RATIOS:
            values["aspect_ratio"] = defaults.aspect_ratio
        return cls(**values)

    @property
    def nonmame(self) -> dict:
        """Roots of the non-MAME collections, keyed like the database expects."""

        return {
            "exodos": self.exodos_dir,
            "gb64": self.gb64_dir,
            "whdload": self.whdload_dir,
        }

    @property
    def aspect_ratio_factor(self) -> float:
        """Return the horizontal/vertical factor for the configured aspect ratio."""

        return ASPECT_RATIOS.get(
            self.aspect_ratio, ASPECT_RATIOS[DEFAULT_ASPECT_RATIO]
        )


def _is_windows(platform):
    return platform.lower().startswith(("win", "nt"))


def resolve_mame_setup(mame_exe, mame_ini="", working_dir="", *,
                       platform, home, isfile=os.path.isfile):
    """Return ``(mame_ini, working_dir)`` MAME is started with.

    A configured value always wins. Otherwise:
    1. ``mame.ini`` next to the executable (portable install, the usual case
       on Windows) -> the executable folder is the working directory;
    2. on Linux/macOS ``~/.mame/mame.ini`` (distribution packages) -> ``~/.mame``;
    3. no ini found -> no ini, the executable folder is the working directory.
    """

    exe_dir = os.path.dirname(mame_exe) if mame_exe else ""
    found_ini, found_dir = "", exe_dir
    candidate = os.path.join(exe_dir, "mame.ini") if exe_dir else ""
    if candidate and isfile(candidate):
        found_ini = candidate
    elif not _is_windows(platform) and home:
        dot_mame = os.path.join(home, ".mame")
        candidate = os.path.join(dot_mame, "mame.ini")
        if isfile(candidate):
            found_ini, found_dir = candidate, dot_mame

    ini = mame_ini or found_ini
    if working_dir:
        cwd = working_dir
    elif mame_ini:
        cwd = os.path.dirname(mame_ini)
    else:
        cwd = found_dir
    return ini, cwd


def resolve_chdman(chdman_exe, mame_exe, *, platform, isfile=os.path.isfile):
    """Return the chdman executable: configured, else next to MAME, else ''."""

    if chdman_exe:
        return chdman_exe
    if not mame_exe:
        return ""
    name = "chdman.exe" if _is_windows(platform) else "chdman"
    candidate = os.path.join(os.path.dirname(mame_exe), name)
    return candidate if isfile(candidate) else ""
