"""Settings adapter for UMSA (GUI-side, Kodi-free).

Bridges the Kodi add-on settings to typed objects used by the GUI.  Shared
settings are represented by the existing `umsa_core.SharedSettings` dataclass;
GUI-only and computed emulation settings are described here.  This module does
not import any `xbmc*` module so it can be imported and tested outside Kodi.
"""

import os
from dataclasses import dataclass

from umsa_core import SharedSettings, load_batocera_mapping

EMULATION_START = {'Normal': 0, 'Watch': 1, 'Fallback': 2}


@dataclass
class GUISettings:
    """Settings owned by plugin.program.umsa.mame.surfer."""

    pref_country: str
    temp_dir: str
    pdfviewer: str
    chdman_exe: str
    terminal: str
    emulation_start: int
    playvideo: bool | None

    @classmethod
    def from_kodi(cls, addon, core_mame_exe: str, platform: str) -> 'GUISettings':
        chdman = addon.getSetting('chdman')
        if chdman == "":
            mame_path = os.path.split(core_mame_exe)[0]
            if 'linux' in platform:
                chdman_file = os.path.join(mame_path, 'chdman')
            else:
                chdman_file = os.path.join(mame_path, 'chdman.exe')
            if os.path.isfile(chdman_file):
                chdman = chdman_file

        emulation_start = EMULATION_START[addon.getSetting('emulation_start')]

        if addon.getSetting('play_video') == 'true':
            playvideo = True
        else:
            playvideo = None

        return cls(
            pref_country=addon.getSetting('pref_country'),
            temp_dir=addon.getSetting('temp_path'),
            pdfviewer=addon.getSetting('pdfviewer'),
            chdman_exe=chdman,
            terminal=addon.getSetting('terminal'),
            emulation_start=emulation_start,
            playvideo=playvideo,
        )


@dataclass
class EmulationSettings:
    """Computed emulation settings."""

    nonmame: dict
    cab_path: str
    batomame: dict

    @classmethod
    def from_core(cls, core: SharedSettings, resource_path: str) -> 'EmulationSettings':
        return cls(
            nonmame={
                'exodos': core.exodos,
                'gb64': core.gb64,
                'whdload': core.whdload,
            },
            cab_path=os.path.join(core.progetto, 'cabinets/cabinets'),
            batomame=load_batocera_mapping(
                os.path.join(resource_path, 'batocera-dir-struct-map.txt')
            ),
        )


def load_all_settings(core: SharedSettings, addon, resource_path: str, platform: str):
    """Load GUI + emulation settings from Kodi for an already-read core."""
    gui = GUISettings.from_kodi(addon, core.mame, platform)
    emu = EmulationSettings.from_core(core, resource_path)
    return gui, emu
