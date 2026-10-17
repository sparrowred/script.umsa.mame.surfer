"""Kodi-independent shared functionality for UMSA add-ons."""

from .artwork import (
    IMAGE_ART_TYPES,
    LEFT_IMAGELIST,
    RIGHT_IMAGELIST,
    build_artwork_path,
    categorize_art_type,
    check_image_aspect,
    find_local_snapshots,
    get_machine_artwork_path,
    resolve_artwork_path,
    root_key_for_path,
)
from .data_paths import CoreDataPaths
from .logging import log, set_log
from .paths import load_batocera_mapping
from .persistence import (
    load_filter,
    load_lastsaver,
    load_software_list,
    save_filter,
    save_software_list,
)
from .process import ProcessLaunchError, ProcessRunner, ProcessState, ProcessStatus
from .scan_coordinator import (
    ScanBusyError,
    ScanLockContext,
    scan_coordinator,
)
from .settings import FILTER_CATEGORIES, SharedSettings
from .sqlite import connect_sqlite, connect_sqlite_readonly
from .vgm_header import (
    PlaybackPlan,
    VGMHeader,
    calculate_playback_plan,
    parse_vgm_header,
)

__all__ = [
    "FILTER_CATEGORIES",
    "IMAGE_ART_TYPES",
    "LEFT_IMAGELIST",
    "RIGHT_IMAGELIST",
    "CoreDataPaths",
    "PlaybackPlan",
    "ProcessLaunchError",
    "ProcessRunner",
    "ProcessState",
    "ProcessStatus",
    "ScanBusyError",
    "ScanLockContext",
    "SharedSettings",
    "VGMHeader",
    "build_artwork_path",
    "calculate_playback_plan",
    "categorize_art_type",
    "check_image_aspect",
    "connect_sqlite",
    "connect_sqlite_readonly",
    "find_local_snapshots",
    "get_machine_artwork_path",
    "load_batocera_mapping",
    "load_filter",
    "load_lastsaver",
    "load_software_list",
    "log",
    "parse_vgm_header",
    "resolve_artwork_path",
    "root_key_for_path",
    "save_filter",
    "save_software_list",
    "scan_coordinator",
    "set_log",
]
