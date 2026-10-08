"""VGM Header Parser and Playback Plan Calculator.

Extracts, validates, and computes playback duration from VGM headers.
"""

import struct
import gzip
import zlib
import math
from dataclasses import dataclass
from zipfile import ZipFile, BadZipFile
from typing import Optional
from utilities import log


@dataclass
class VGMHeader:
    """Parsed and validated VGM header metadata."""
    total_seconds: float
    loop_seconds: float
    intro_seconds: float
    has_loop: bool
    loop_only: bool          # True if intro ≈ 0 and has_loop
    header_valid: bool       # Successfully parsed
    header_sane: bool        # Passes sanity checks
    rejection_reason: str    # If not header_sane
    sample_rate: int
    total_samples: int
    loop_offset: int
    loop_samples: int
    member_name: str         # Track filename for logging
    # Volume/gain fields
    volume_modifier: int     # Signed byte at 0x7C (-64 to +192)
    header_gain_factor: float  # 2^(modifier/32)
    header_gain_db: float    # 20*log10(gain)
    extra_header_present: bool  # Whether 0xBC offset != 0
    has_chip_volumes: bool   # Whether extra header has chip volume entries


@dataclass
class PlaybackPlan:
    """Computed playback plan from validated header."""
    seconds_to_run: float      # Duration to pass to MAME (-seconds_to_run)
    loop_repetitions: int      # Planned loop iterations
    reason: str                # Human-readable explanation
    header_based: bool         # True if header was primary driver
    fallback_used: bool        # True if audio fallback needed
    header: VGMHeader          # Source header for logging


# Constants
MAX_PLAYBACK_SECONDS = 60          # Hard ceiling
HEADER_REJECTION_FALLBACK = 60      # Seconds for invalid headers
LOOP_ONLY_INTRO_THRESHOLD = 0.5     # Seconds - fixed, not configurable
SANITY_MAX_DURATION = 600          # 10 minutes max total duration
SANITY_MAX_SAMPLE_RATE = 100000
SANITY_MIN_SAMPLE_RATE = 1000

# Loop-only repetition table (hardcoded)
LOOP_ONLY_REPS = [
    (10, 1),   # loop < 10s  -> 5 reps
    (20, 2),   # loop < 20s  -> 4 reps
    (40, 2),   # loop < 40s  -> 3 reps
    (float('inf'), 2),  # loop >= 40s -> 2 reps
]

def _invalid_header(member: str, reason: str) -> VGMHeader:
    """Create an invalid VGMHeader with all required fields."""
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


def parse_vgm_header(zip_path: str, member: str) -> VGMHeader:
    """Parse VGM header from zip member with full validation.
    
    Returns VGMHeader with header_valid=False on parse failure,
    header_sane=False on sanity check failure.
    """
    try:
        with ZipFile(zip_path) as zobj:
            data = zobj.read(member)
        if data[:2] == b'\x1f\x8b':  # .vgz gzip compressed
            data = gzip.decompress(data)
        if data[0:4] != b'Vgm ' or len(data) < 0x28:
            return _invalid_header(member, "Invalid VGM magic or truncated header")
        
        rate = struct.unpack_from('<I', data, 0x24)[0] or 44100
        if rate in (60, 50): # fallback for gen/sms, Hz?
            rate = 44100
        total = struct.unpack_from('<I', data, 0x18)[0]
        loop_off = struct.unpack_from('<I', data, 0x1c)[0]
        loop_cnt = struct.unpack_from('<I', data, 0x20)[0]
        
        # Parse volume modifier at 0x7C (signed byte, VGM 1.60+)
        volume_modifier = 0
        header_gain_factor = 1.0
        header_gain_db = 0.0
        if len(data) > 0x7C:
            mod_byte = data[0x7C]
            # Convert unsigned byte to signed int8 (-128 to 127)
            if mod_byte >= 128:
                volume_modifier = mod_byte - 256
            else:
                volume_modifier = mod_byte
            # VGM spec: -63 (0xC1) is replaced with -64 for 0.25 factor
            if volume_modifier == -63:
                volume_modifier = -64
            # Gain = 2^(modifier/32)
            header_gain_factor = 2.0 ** (volume_modifier / 32.0)
            header_gain_db = 20.0 * math.log10(header_gain_factor) if header_gain_factor > 0 else -float('inf')
        
        # Parse extra header at 0xBC (VGM 1.70+)
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
        
        # Calculate durations
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
            header_sane=True,  # Will be validated below
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
        
        # Sanity checks
        _validate_header(header)
        return header
        
    except (BadZipFile, OSError, EOFError, struct.error, ValueError, zlib.error) as err:
        log(f'UMSA vgm_header: vgm header parse failed for {member}: {err}', level='debug')
        return _invalid_header(member, f"Parse error: {err}")


def _validate_header(h: VGMHeader) -> None:
    """Apply sanity checks, mutating header_sane and rejection_reason."""
    # Sample rate
    if not (SANITY_MIN_SAMPLE_RATE <= h.sample_rate <= SANITY_MAX_SAMPLE_RATE):
        h.header_sane = False
        h.rejection_reason = f"Sample rate {h.sample_rate} outside [{SANITY_MIN_SAMPLE_RATE}, {SANITY_MAX_SAMPLE_RATE}]"
        return
    
    # Total duration
    if h.total_seconds > SANITY_MAX_DURATION:
        h.header_sane = False
        h.rejection_reason = f"Total duration {h.total_seconds:.1f}s exceeds maximum {SANITY_MAX_DURATION}s"
        return
    
    # Total samples must be positive
    if h.total_samples <= 0:
        h.header_sane = False
        h.rejection_reason = f"Total samples {h.total_samples} not positive"
        return
    
    # Loop validation
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


def calculate_playback_plan(header: VGMHeader, max_seconds: int = MAX_PLAYBACK_SECONDS) -> PlaybackPlan:
    """Compute planned playback duration from validated header."""
    
    if not header.header_valid or not header.header_sane:
        return PlaybackPlan(
            seconds_to_run=HEADER_REJECTION_FALLBACK,
            loop_repetitions=0,
            reason=f"Invalid/insane header -> {HEADER_REJECTION_FALLBACK}s fallback: {header.rejection_reason}",
            header_based=False,
            fallback_used=True,
            header=header
        )
    
    if not header.has_loop:
        # Non-looping: play actual duration + 2s margin
        duration = min(header.total_seconds + 2.0, max_seconds)
        return PlaybackPlan(
            seconds_to_run=duration,
            loop_repetitions=0,
            reason=f"No loop -> {duration:.1f}s (header: {header.total_seconds:.1f}s + 2s margin)",
            header_based=True,
            fallback_used=False,
            header=header
        )
    
    if header.loop_only:
        # Loop-only: repetition table
        reps = 2
        for threshold, r in LOOP_ONLY_REPS:
            if header.loop_seconds < threshold:
                reps = r
                break
        duration = min(header.loop_seconds * reps, max_seconds)
        return PlaybackPlan(
            seconds_to_run=duration,
            loop_repetitions=reps,
            reason=f"Loop-only {header.loop_seconds:.1f}s x {reps} = {duration:.1f}s",
            header_based=True,
            fallback_used=False,
            header=header
        )
    
    # Normal looping music: intro + ~3 loops, capped
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
