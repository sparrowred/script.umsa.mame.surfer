"""Artwork availability checks and mode planning of the screensaver.

Before the screensaver starts, the artwork database is asked whether the
requested mode has anything to show at all. The check runs against the
artwork database (the same source of truth the random artwork selection
uses) and never scans the filesystem: a missing or broken file is a
runtime problem and is handled by the render loop, not here.

The module is Kodi-free: it only decides which mode may run and why a
session may not start. The notifications and the lifecycle belong to the
Kodi layer.
"""

from random import choice

from .constants import (
    ART_TYPES_BY_MODE,
    MODE_CROSS,
    MODE_SLIDE,
    MODE_VIDEOS,
    MODE_WALL,
)

# The modes that show artwork instead of a video
IMAGE_MODES = (MODE_CROSS, MODE_SLIDE, MODE_WALL)

# Reasons of a start plan
REASON_OK = 'ok'
REASON_NO_MODES = 'no_modes'
REASON_NO_VIDEOS = 'no_videos'
REASON_NO_ARTWORK = 'no_artwork'


class AvailabilityError(Exception):
    """The artwork availability check itself failed.

    A broken database must never look like an empty one: the check raises
    instead of answering ``False`` so the caller can log the error and
    stop the screensaver safely.
    """


class StartPlan:
    """The result of the startup availability check.

    ``mode`` is the mode that may run (``None`` when nothing may run),
    ``reason`` tells why a session may not start and ``candidates`` holds
    the viable modes the plan was built from.
    """

    def __init__(self, mode=None, reason=REASON_OK, candidates=()):
        self.mode = mode
        self.reason = reason
        self.candidates = list(candidates)

    @property
    def ok(self):
        """Return whether the plan allows a screensaver session."""

        return self.mode is not None

    def __repr__(self):  # pragma: no cover - debugging helper
        return (
            f"StartPlan(mode={self.mode!r}, reason={self.reason!r}, "
            f"candidates={self.candidates!r})"
        )


def art_types_for_mode(mode):
    """Return the artwork types the given mode needs."""

    return list(ART_TYPES_BY_MODE.get(mode, []))


def has_artwork(ggdb, art_types):
    """Return whether the artwork database holds a row of the given types.

    Raises :class:`AvailabilityError` when the database query fails, so a
    query error is never read as "no artwork".
    """

    types = [art_type for art_type in dict.fromkeys(art_types or []) if art_type]
    if not types:
        return False
    if ggdb is None:
        raise AvailabilityError("no artwork database available")
    try:
        return bool(ggdb.has_artwork(types))
    except Exception as error:  # noqa: BLE001 - a broken database is not an empty one
        raise AvailabilityError(f"artwork availability query failed: {error}") from error


def mode_available(ggdb, mode, art_types=None):
    """Return whether the artwork database holds artwork for the mode.

    ``art_types`` overrides the artwork types of the mode (used when a
    caller asks for specific artwork types).
    """

    types = list(art_types) if art_types else art_types_for_mode(mode)
    return has_artwork(ggdb, types)


def available_modes(ggdb, modes, art_types=None):
    """Return the modes of ``modes`` whose artwork is available."""

    return [mode for mode in modes if mode_available(ggdb, mode, art_types)]


def image_fallback_modes(ggdb, configured):
    """Return the image modes usable as fallback.

    The currently configured image modes come first; when none of them has
    artwork, the remaining image modes are considered - but only the ones
    the database confirms.
    """

    configured_images = [mode for mode in configured if mode in IMAGE_MODES]
    fallback = available_modes(ggdb, configured_images)
    if fallback:
        return fallback
    others = [mode for mode in IMAGE_MODES if mode not in configured_images]
    return available_modes(ggdb, others)


def plan_start(ggdb, candidates, configured=None, chooser=choice):
    """Plan the start of an automatically selected screensaver mode.

    ``candidates`` are the modes that may be selected (the caller removes
    the video mode when audio plays), ``configured`` are the modes the
    user configured. Only modes whose artwork is available are selected.

    When the video mode is a candidate but the database holds no
    videosnap, the plan falls back to an image mode and reports the reason
    ``no_videos`` so the caller can tell the user.
    """

    candidates = [mode for mode in (candidates or []) if mode]
    configured = [mode for mode in (configured or []) if mode]
    if not candidates:
        return StartPlan(reason=REASON_NO_MODES)

    images = [mode for mode in candidates if mode in IMAGE_MODES]
    viable_images = available_modes(ggdb, images)

    if MODE_VIDEOS in candidates:
        if mode_available(ggdb, MODE_VIDEOS):
            plan = StartPlan(candidates=viable_images + [MODE_VIDEOS])
            plan.mode = chooser(plan.candidates)
            return plan
        # no videos in the database: fall back to an artwork mode
        fallback = image_fallback_modes(ggdb, configured or images)
        if not fallback:
            return StartPlan(reason=REASON_NO_ARTWORK, candidates=[])
        plan = StartPlan(reason=REASON_NO_VIDEOS, candidates=fallback)
        plan.mode = chooser(fallback)
        return plan

    if viable_images:
        plan = StartPlan(candidates=viable_images)
        plan.mode = chooser(viable_images)
        return plan
    return StartPlan(reason=REASON_NO_ARTWORK, candidates=[])


def plan_request(ggdb, requested_mode, requested_art_types=None, configured=None,
                 chooser=choice):
    """Plan the start of an explicitly requested screensaver mode.

    An explicitly requested image mode is never silently replaced by
    another one: without artwork the session does not start. The video
    mode falls back to an artwork mode, exactly like the automatic
    selection.
    """

    configured = [mode for mode in (configured or []) if mode]
    if not requested_mode:
        return StartPlan(reason=REASON_NO_MODES)

    types = list(requested_art_types) if requested_art_types else art_types_for_mode(requested_mode)
    if mode_available(ggdb, requested_mode, types):
        return StartPlan(mode=requested_mode, candidates=[requested_mode])

    if requested_mode == MODE_VIDEOS:
        fallback = image_fallback_modes(ggdb, configured)
        if not fallback:
            return StartPlan(reason=REASON_NO_ARTWORK)
        plan = StartPlan(reason=REASON_NO_VIDEOS, candidates=fallback)
        plan.mode = chooser(fallback)
        return plan
    return StartPlan(reason=REASON_NO_ARTWORK)
