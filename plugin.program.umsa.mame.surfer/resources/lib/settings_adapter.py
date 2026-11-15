"""Settings adapter for UMSA (GUI-side, Kodi-free).

The frontend has no settings of its own: every value comes from the UMSA
settings owned by the Core add-on (``umsa_core.SharedSettings``). This module
derives the values the GUI and the emulation need from them. It does not
import any ``xbmc*`` module so it can be tested outside Kodi.
"""

import os
from dataclasses import dataclass, field

from umsa_core import SharedSettings, load_batocera_mapping
from umsa_core.rom_cache import CacheLayout
from umsa_core.settings import resolve_chdman, resolve_mame_setup
from umsa_core.vgm_header import MAX_PLAYBACK_SECONDS


@dataclass
class EmulationSettings:
    """Effective emulator paths and computed emulation settings."""

    mame_ini: str
    mame_working_dir: str
    chdman_exe: str
    nonmame: dict
    cab_path: str
    batomame: dict

    @classmethod
    def from_core(cls, core: SharedSettings, resource_path: str, platform: str,
                  home: str = '', isfile=os.path.isfile) -> 'EmulationSettings':
        mame_ini, working_dir = resolve_mame_setup(
            core.mame_exe, core.mame_ini, core.mame_working_dir,
            platform=platform, home=home, isfile=isfile)
        return cls(
            mame_ini=mame_ini,
            mame_working_dir=working_dir,
            chdman_exe=resolve_chdman(
                core.chdman_exe, core.mame_exe, platform=platform, isfile=isfile),
            nonmame=core.nonmame,
            cab_path=os.path.join(core.progettosnaps_dir, 'cabinets/cabinets'),
            batomame=load_batocera_mapping(
                os.path.join(resource_path, 'batocera-dir-struct-map.txt')
            ),
        )


def load_all_settings(core: SharedSettings, resource_path: str, platform: str,
                      home: str = '') -> EmulationSettings:
    """Derive the emulation settings from the already-read UMSA settings."""

    return EmulationSettings.from_core(core, resource_path, platform, home=home)


@dataclass
class FrontendSettings:
    """The settings the frontend works with.

    The window keeps one object and fills it again (``apply``) after the
    settings dialog, so the workflow contexts that hold it see the new values.
    """

    mame_exe: str = ''
    mameini: str = ''
    mame_dir: str = ''
    chdman_exe: str = ''
    progettosnaps: str = ''
    own_artwork: str = ''
    aratio: str = ''
    datdir: str = ''
    vgmplay_exe: str = ''
    musicinfo: bool = False
    vgm_show_machine_list: bool = False
    vgm_max_duration: int = MAX_PLAYBACK_SECONDS
    # None: Core default
    vgm_port: object = None
    vgm_intro_duration: int = 0
    pref_country: str = ''
    temp_dir: str = ''
    pdfviewer: str = ''
    terminal: object = False
    emulation_start: int = 0
    playvideo: object = None
    nonmame: dict = field(default_factory=dict)
    cab_path: str = ''
    batomame: dict = field(default_factory=dict)
    # ROM cache: one layout for extracted sets and copies of all starts
    rom_cache: bool = False
    cache_layout: object = None
    # folder of the filter files (Core data paths)
    settings_folder: object = None

    def apply(self, core: SharedSettings, emu: EmulationSettings) -> None:
        """Take over the UMSA settings and the values derived from them."""

        self.mame_exe = core.mame_exe
        self.mameini = emu.mame_ini
        self.mame_dir = emu.mame_working_dir
        self.chdman_exe = emu.chdman_exe
        self.progettosnaps = core.progettosnaps_dir
        self.own_artwork = core.own_artwork_dir
        self.aratio = core.aspect_ratio
        self.datdir = core.support_files_dir
        self.vgmplay_exe = core.vgmplay_exe
        self.musicinfo = core.show_music_info
        self.vgm_show_machine_list = core.vgm_show_machine_list
        self.vgm_max_duration = core.vgm_max_duration
        self.vgm_port = core.vgm_port
        self.vgm_intro_duration = core.vgm_intro_duration
        self.pref_country = core.pref_country
        self.temp_dir = core.rom_temp_dir
        self.pdfviewer = core.pdf_viewer
        self.terminal = core.terminal
        self.emulation_start = core.emulation_start
        self.playvideo = True if core.auto_play_videos else None
        self.nonmame = emu.nonmame
        self.cab_path = emu.cab_path
        self.batomame = emu.batomame
        self.rom_cache = core.rom_cache
        self.cache_layout = CacheLayout(
            self.temp_dir, core.batocera_layout, self.batomame)

    def artwork_source_roots(self) -> dict:
        """Map artwork sources to their configured root directories."""

        return {
            "progettosnaps": self.progettosnaps,
            "own_artwork": self.own_artwork,
            "exodos": self.nonmame.get("exodos", ""),
            "gb64": self.nonmame.get("gb64", ""),
        }
