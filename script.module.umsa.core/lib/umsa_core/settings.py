"""Typed access to the shared UMSA Core settings."""

from dataclasses import dataclass

ASPECT_RATIOS = {
    "16:9": 1.7777,
    "16:10": 1.6,
    "5:4": 1.25,
    "4:3": 1.3333,
}
DEFAULT_ASPECT_RATIO = "16:9"

# Filter category names shown in the UI - must match database/persistence keys
FILTER_CATEGORIES = [
    "Softwarelists", "Game Categories", "Machine Categories", "Players",
    "Years", "----------", "Load Filter", "Save Filter"
]


@dataclass(frozen=True)
class SharedSettings:
    """Values of the settings owned by the ``script.module.umsa.core`` add-on."""

    mame: str = ""
    mameini: str = ""
    mamedir: str = ""
    progettosnaps: str = ""
    own_artwork: str = ""
    vgmplay: str = ""
    datdir: str = ""
    exodos: str = ""
    gb64: str = ""
    whdload: str = ""
    aspectratio: str = DEFAULT_ASPECT_RATIO
    ssaver_musicinfo: str = "true"

    @property
    def musicinfo_enabled(self) -> bool:
        """Return whether the screensaver should display music info."""

        return self.ssaver_musicinfo == "true"

    @property
    def aspect_ratio_factor(self) -> float:
        """Return the horizontal/vertical factor for the configured aspect ratio."""

        return ASPECT_RATIOS.get(
            self.aspectratio, ASPECT_RATIOS[DEFAULT_ASPECT_RATIO]
        )
