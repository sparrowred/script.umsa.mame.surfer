"""Screensaver settings model.

The add-on settings are read in one place and exposed twice: as typed
dataclasses for the new modules and as the legacy dictionary the Kodi
window code still uses (``Saver.settings``).
"""

from dataclasses import dataclass
from random import choice

from .constants import AR_NORM

SETTING_TIME = 'ssaver_time'
SETTING_INFO = 'ssaver_info'
SETTING_VIDEOS = 'ssaver_videos'
SETTING_SLIDE = 'ssaver_slide'
SETTING_WALL = 'ssaver_wall'
SETTING_CROSS = 'ssaver_cross'
SETTING_TROWS = 'ssaver_trows'
SETTING_TROWS_B = 'ssaver_trows_b'
SETTING_SROWS = 'ssaver_srows'
SETTING_SROWS_B = 'ssaver_srows_b'
SETTING_FREE = 'ssaver_free'
SETTING_TITLES = 'ssaver_titles'

WALL_TITLES = "Titles"
WALL_RANDOM = "Random"


@dataclass(frozen=True)
class WallSettings:
    """Wall mode layout options."""

    trows: int = 0
    trows_b: int = 0
    srows: int = 0
    srows_b: int = 0
    free: int = 0
    titles: str = ''

    def as_dict(self):
        """Return the legacy dictionary representation."""

        return {
            'trows': self.trows,
            'trows_b': self.trows_b,
            'srows': self.srows,
            'srows_b': self.srows_b,
            'free': self.free,
            'titles': self.titles,
        }


@dataclass(frozen=True)
class ScreensaverSettings:
    """All settings the screensaver needs."""

    own_artwork: str = ''
    progettosnaps: str = ''
    ar_norm: float = AR_NORM
    ar_x: float = 1.0
    time: int = 0
    info: bool = False
    types: tuple = ()
    wall: WallSettings = WallSettings()

    @classmethod
    def from_addon(cls, addon, core_settings):
        """Build the settings from the Kodi add-on and the Core settings.

        ``addon`` is the ``xbmcaddon.Addon`` of the screensaver add-on and
        ``core_settings`` the shared Core settings object.
        """

        types = []
        if addon.getSetting(SETTING_VIDEOS) == 'true':
            types.append('videos')
        if addon.getSetting(SETTING_SLIDE) == 'true':
            types.append('slide')
        if addon.getSetting(SETTING_WALL) == 'true':
            types.append('wall')
        if addon.getSetting(SETTING_CROSS) == 'true':
            types.append('cross')

        wall = WallSettings(
            trows=int(addon.getSetting(SETTING_TROWS)),
            trows_b=int(addon.getSetting(SETTING_TROWS_B)),
            srows=int(addon.getSetting(SETTING_SROWS)),
            srows_b=int(addon.getSetting(SETTING_SROWS_B)),
            free=int(addon.getSetting(SETTING_FREE)),
            titles=addon.getSetting(SETTING_TITLES),
        )

        return cls(
            own_artwork=core_settings.own_artwork,
            progettosnaps=core_settings.progettosnaps,
            ar_x=core_settings.aspect_ratio_factor,
            time=int(addon.getSetting(SETTING_TIME)),
            info=addon.getSetting(SETTING_INFO) == 'true',
            types=tuple(types),
            wall=wall,
        )

    def as_legacy_dict(self):
        """Return the dictionary the Kodi window code expects.

        The result keeps the historical keys (``ar_norm``, ``ar_x``,
        ``time``, ``info``, ``type``, ``wall``); ``type`` is a mutable
        list because the monitor removes and re-appends ``videos`` while
        audio is playing.
        """

        return {
            'ar_norm': self.ar_norm,
            'ar_x': self.ar_x,
            'time': self.time,
            'info': self.info,
            'type': list(self.types),
            'wall': self.wall.as_dict(),
        }


def choose_mode(types, chooser=choice):
    """Return a randomly chosen mode of ``types``.

    An empty list raises ``IndexError``, exactly like ``random.choice``;
    the caller checks the list before asking for a mode.
    """

    return chooser(types)
