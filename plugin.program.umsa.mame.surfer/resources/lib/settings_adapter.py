"""Settings adapter for UMSA (GUI-side, Kodi-free).

The frontend has no settings of its own: every value comes from the UMSA
settings owned by the Core add-on (``umsa_core.SharedSettings``). This module
derives the values the GUI and the emulation need from them. It does not
import any ``xbmc*`` module so it can be tested outside Kodi.
"""

import os
from dataclasses import dataclass

from umsa_core import SharedSettings, load_batocera_mapping
from umsa_core.settings import resolve_chdman, resolve_mame_setup


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
