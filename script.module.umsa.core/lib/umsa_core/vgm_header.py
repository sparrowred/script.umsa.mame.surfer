"""VGM header parser and playback plan (duration in seconds, fade-out)."""

import gzip
import math
import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from zipfile import BadZipFile, ZipFile


@dataclass
class VGMHeader:
    """Parsed and validated VGM header metadata.

    Attributes:
        loop_only: The track loops and its intro is shorter than
            ``LOOP_ONLY_INTRO_THRESHOLD``.
        header_valid: The header could be parsed.
        header_sane: The header passed the sanity checks.
        rejection_reason: Why the header is not valid or not sane.
        member_name: Track file name, for the log.
        volume_modifier: Signed byte at 0x7C (VGM 1.60+).
        header_gain_factor: ``2 ** (volume_modifier / 32)``.
        header_gain_db: ``20 * log10(header_gain_factor)``.
        extra_header_present: The extra header offset at 0xBC is not 0.
        has_chip_volumes: The extra header has chip volume entries.
    """
    total_seconds: float
    loop_seconds: float
    intro_seconds: float
    has_loop: bool
    loop_only: bool
    header_valid: bool
    header_sane: bool
    rejection_reason: str
    sample_rate: int
    total_samples: int
    loop_offset: int
    loop_samples: int
    member_name: str
    volume_modifier: int
    header_gain_factor: float
    header_gain_db: float
    extra_header_present: bool
    has_chip_volumes: bool


@dataclass
class PlaybackPlan:
    """Playback plan computed from a header.

    Attributes:
        seconds_to_run: Playback duration in seconds (MAME
            ``-seconds_to_run``, see :func:`mame_seconds_to_run`).
        loop_repetitions: Planned loop iterations.
        reason: Explanation for the log.
        header_based: The duration comes from the header.
        fallback_used: The header was invalid; a fixed duration is used.
        header: The source header.
        fade_out: The playback is cut inside the music and fades out.
    """
    seconds_to_run: float
    loop_repetitions: int
    reason: str
    header_based: bool
    fallback_used: bool
    header: VGMHeader
    fade_out: bool = True


MAX_PLAYBACK_SECONDS = 180           # Default ceiling (setting vgm_max_duration, 20-300 s)
HEADER_REJECTION_FALLBACK = 120      # Seconds for invalid headers
FADE_OUT_SECONDS = 3.0               # Fade-out of a playback that is cut
LOOP_ONLY_INTRO_THRESHOLD = 0.5      # Seconds
SANITY_MAX_DURATION = 600            # Seconds
SANITY_MAX_SAMPLE_RATE = 100000
SANITY_MIN_SAMPLE_RATE = 1000

def _invalid_header(member: str, reason: str) -> VGMHeader:
    """Return an invalid :class:`VGMHeader` with ``reason``."""
    return VGMHeader(
        total_seconds=0, loop_seconds=0, intro_seconds=0,
        has_loop=False, loop_only=False,
        header_valid=False, header_sane=False,
        rejection_reason=reason,
        sample_rate=0, total_samples=0, loop_offset=0, loop_samples=0,
        member_name=member,
        volume_modifier=0,
        header_gain_factor=1.0,
        header_gain_db=0.0,
        extra_header_present=False,
        has_chip_volumes=False
    )


def parse_vgm_header(
    zip_path: str,
    member: str,
    logger: Callable[..., None] | None = None,
) -> VGMHeader:
    """Parse and validate the VGM header of a zip member (``.vgm`` or ``.vgz``).

    Never raises: a parse failure gives ``header_valid=False``, a failed
    sanity check ``header_sane=False``.
    """
    try:
        with ZipFile(zip_path) as zobj:
            data = zobj.read(member)
        if data[:2] == b'\x1f\x8b':  # .vgz
            data = gzip.decompress(data)
        if data[0:4] != b'Vgm ' or len(data) < 0x28:
            return _invalid_header(member, "Invalid VGM magic or truncated header")
        
        rate = struct.unpack_from('<I', data, 0x24)[0] or 44100
        if rate in (60, 50):  # recording rate in Hz; VGM samples are 44100 Hz
            rate = 44100
        total = struct.unpack_from('<I', data, 0x18)[0]
        loop_off = struct.unpack_from('<I', data, 0x1c)[0]
        loop_cnt = struct.unpack_from('<I', data, 0x20)[0]
        
        # Volume modifier at 0x7C (signed byte, VGM 1.60+).
        volume_modifier = 0
        header_gain_factor = 1.0
        header_gain_db = 0.0
        if len(data) > 0x7C:
            mod_byte = data[0x7C]
            if mod_byte >= 128:
                volume_modifier = mod_byte - 256
            else:
                volume_modifier = mod_byte
            # VGM spec: -63 (0xC1) is replaced with -64 for 0.25 factor
            if volume_modifier == -63:
                volume_modifier = -64
            header_gain_factor = 2.0 ** (volume_modifier / 32.0)
            header_gain_db = 20.0 * math.log10(header_gain_factor) if header_gain_factor > 0 else -float('inf')
        
        # Extra header at 0xBC (VGM 1.70+).
        extra_header_present = False
        has_chip_volumes = False
        if len(data) > 0xBC:
            extra_offset = struct.unpack_from('<I', data, 0xBC)[0]
            if extra_offset != 0:
                extra_header_present = True
                extra_pos = 0xBC + extra_offset
                # Extra header: [size:u32][clock_offset:u32][vol_offset:u32]
                if len(data) > extra_pos + 12:
                    vol_offset = struct.unpack_from('<I', data, extra_pos + 8)[0]
                    if vol_offset != 0:
                        vol_pos = extra_pos + vol_offset
                        if len(data) > vol_pos + 1:
                            entry_count = data[vol_pos]
                            if entry_count > 0:
                                has_chip_volumes = True
        
        total_s = total / rate if rate else 0
        loop_s = loop_cnt / rate if loop_cnt and rate else 0
        intro_s = (total - loop_cnt) / rate if loop_off and loop_cnt and rate else None
        
        has_loop = bool(loop_cnt)
        intro_s = (total - loop_cnt) / rate if loop_cnt and rate else None
        loop_only = has_loop and (intro_s is not None and intro_s < LOOP_ONLY_INTRO_THRESHOLD)
        
        header = VGMHeader(
            total_seconds=round(total_s, 2),
            loop_seconds=round(loop_s, 2),
            intro_seconds=round(intro_s, 2) if intro_s is not None else 0.0,
            has_loop=has_loop,
            loop_only=loop_only,
            header_valid=True,
            header_sane=True,  # set by _validate_header
            rejection_reason="",
            sample_rate=rate,
            total_samples=total,
            loop_offset=loop_off,
            loop_samples=loop_cnt,
            member_name=member,
            volume_modifier=volume_modifier,
            header_gain_factor=header_gain_factor,
            header_gain_db=header_gain_db,
            extra_header_present=extra_header_present,
            has_chip_volumes=has_chip_volumes
        )
        
        _validate_header(header)
        return header
        
    except (BadZipFile, OSError, EOFError, struct.error, ValueError, zlib.error) as err:
        if logger is not None:
            logger(
                f'UMSA vgm_header: vgm header parse failed for {member}: {err}',
                level='debug')
        return _invalid_header(member, f"Parse error: {err}")


def _validate_header(h: VGMHeader) -> None:
    """Apply the sanity checks, setting ``header_sane`` and ``rejection_reason``."""
    if not (SANITY_MIN_SAMPLE_RATE <= h.sample_rate <= SANITY_MAX_SAMPLE_RATE):
        h.header_sane = False
        h.rejection_reason = f"Sample rate {h.sample_rate} outside [{SANITY_MIN_SAMPLE_RATE}, {SANITY_MAX_SAMPLE_RATE}]"
        return
    
    if h.total_seconds > SANITY_MAX_DURATION:
        h.header_sane = False
        h.rejection_reason = f"Total duration {h.total_seconds:.1f}s exceeds maximum {SANITY_MAX_DURATION}s"
        return
    
    if h.total_samples <= 0:
        h.header_sane = False
        h.rejection_reason = f"Total samples {h.total_samples} not positive"
        return
    
    if h.has_loop:
        if h.loop_samples <= 0:
            h.header_sane = False
            h.rejection_reason = f"Loop samples {h.loop_samples} not positive despite loop flag"
            return
        if h.loop_samples > h.total_samples:
            h.header_sane = False
            h.rejection_reason = f"Loop samples {h.loop_samples} > total samples {h.total_samples}"
            return
        if h.loop_seconds > h.total_seconds:
            h.header_sane = False
            h.rejection_reason = f"Loop duration {h.loop_seconds:.1f}s > total duration {h.total_seconds:.1f}s"
            return


def mame_seconds_to_run(seconds: float) -> int:
    """Return whole seconds for MAME's ``-seconds_to_run``, never below 1.

    MAME takes an integer and treats ``0`` as "no limit": a plan below one
    second (short loops) would play for ever. Rounding up never cuts the
    plan short.
    """

    return max(1, math.ceil(seconds))


def calculate_playback_plan(header: VGMHeader, max_seconds: int = MAX_PLAYBACK_SECONDS) -> PlaybackPlan:
    """Return the playback plan of a header, capped at ``max_seconds``.

    Invalid header: ``HEADER_REJECTION_FALLBACK``; no loop: the track plus
    2 s; loop only: one loop; otherwise intro + 3 loops.
    """
    
    if not header.header_valid or not header.header_sane:
        duration = min(HEADER_REJECTION_FALLBACK, max_seconds)
        return PlaybackPlan(
            seconds_to_run=duration,
            loop_repetitions=0,
            reason=f"Invalid/insane header -> {duration}s fallback: {header.rejection_reason}",
            header_based=False,
            fallback_used=True,
            header=header
        )
    
    if not header.has_loop:
        # Non-looping: play actual duration + 2s margin. The track ends on
        # its own, only a capped one is cut and needs the fade-out.
        natural = header.total_seconds + 2.0
        duration = min(natural, max_seconds)
        return PlaybackPlan(
            seconds_to_run=duration,
            loop_repetitions=0,
            reason=f"No loop -> {duration:.1f}s (header: {header.total_seconds:.1f}s + 2s margin)",
            header_based=True,
            fallback_used=False,
            header=header,
            fade_out=natural > max_seconds,
        )
    
    if header.loop_only:
        reps = 1
        duration = min(header.loop_seconds * reps, max_seconds)
        return PlaybackPlan(
            seconds_to_run=duration,
            loop_repetitions=reps,
            reason=f"Loop-only {header.loop_seconds:.1f}s x {reps} = {duration:.1f}s",
            header_based=True,
            fallback_used=False,
            header=header
        )
    
    target = header.intro_seconds + header.loop_seconds * 3
    duration = min(target, max_seconds)
    reps = max(1, int((duration - header.intro_seconds) / header.loop_seconds))
    return PlaybackPlan(
        seconds_to_run=duration,
        loop_repetitions=reps,
        reason=f"Intro {header.intro_seconds:.1f}s + {reps} loops = {duration:.1f}s",
        header_based=True,
        fallback_used=False,
        header=header
    )


def format_vgm_title(track_filename, gamename):
    """Return the title part of the VGM music info, shared by all play modes."""

    return f'Song "{track_filename[:-4].title()}" from "{gamename}"'


# Suffix of the gain in the music info per leveling state
# (vgm_socket.LUA_LEVEL_STATES); a frozen gain needs no marker.
_LEVEL_STATE_SUFFIX = {'auto': ' auto', 'locked': '', 'manual': ' manual'}


def format_vgm_status(title, remaining_seconds, level=None):
    """Return the music info line ``<title> -MM:ss (<+gain> dB[ auto| manual])``.

    ``remaining_seconds`` counts down during playback and is clamped at 0;
    ``level`` is ``(gain_db, state)`` of the last level frame of vgmplay.lua:
    the gain UMSA puts on the track and whether the leveling still adjusts
    it (``auto``), froze it (``locked``, no marker) or the user changed it
    (``manual``).
    """

    # Round up: a fresh 180 s plan reads -03:00, not -02:59.
    remaining = max(0, math.ceil(remaining_seconds))
    minutes, seconds = divmod(remaining, 60)
    status = f'{title} -{minutes:02d}:{seconds:02d}'
    if level is not None:
        gain_db, state = level
        # A gain that rounds to zero reads +0.0, never -0.0.
        gain = round(gain_db, 1) or 0.0
        status += f' ({gain:+.1f} dB{_LEVEL_STATE_SUFFIX.get(state, "")})'
    return status
