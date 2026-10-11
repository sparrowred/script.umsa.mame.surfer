"""Kodi-independent shared functionality for UMSA add-ons."""

from .data_paths import CoreDataPaths
from .logging import log, set_log
from .persistence import (
    load_filter,
    load_lastsaver,
    load_software_list,
    save_filter,
    save_software_list,
)
from .process import ProcessLaunchError, ProcessRunner, ProcessState, ProcessStatus
from .settings import SharedSettings
from .sqlite import connect_sqlite
from .vgm_header import (
    PlaybackPlan,
    VGMHeader,
    calculate_playback_plan,
    parse_vgm_header,
)

__all__ = [
    "CoreDataPaths",
    "PlaybackPlan",
    "ProcessLaunchError",
    "ProcessRunner",
    "ProcessState",
    "ProcessStatus",
    "SharedSettings",
    "VGMHeader",
    "calculate_playback_plan",
    "connect_sqlite",
    "load_filter",
    "load_lastsaver",
    "load_software_list",
    "log",
    "parse_vgm_header",
    "save_filter",
    "save_software_list",
    "set_log",
]
