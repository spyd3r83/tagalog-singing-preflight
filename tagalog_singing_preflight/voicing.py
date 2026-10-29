"""Compare explicitly aligned F0 voicing masks without inferring lyrics."""

from __future__ import annotations

import decimal

from tagalog_singing_preflight import timing


MAX_F0_FRAMES = 1_000_000


def _read_track(track: dict, name: str) -> tuple:
    if not isinstance(track, dict):
        raise ValueError(f"{name} must be an object.")
    for field in ("frame_rate_hz", "origin_seconds", "values"):
        if field not in track:
            raise ValueError(f"{name}.{field} is required.")
    rate = timing.number(track["frame_rate_hz"], f"{name}.frame_rate_hz", "1000000")
    if not rate:
        raise ValueError(f"{name}.frame_rate_hz must be positive.")
    origin = timing.number(track["origin_seconds"], f"{name}.origin_seconds")
    values = track["values"]
    if (not isinstance(values, list) or not values
            or len(values) > MAX_F0_FRAMES):
        raise ValueError(f"{name}.values must contain 1 to {MAX_F0_FRAMES} frames.")
    parsed = [timing.number(value, f"{name}.values[{index}]")
              for index, value in enumerate(values)]
    return rate, origin, parsed


def compare_voicing(guide: dict, conditioning: dict) -> dict:
    """Require the same declared grid, then compare zero/nonzero F0 frames.

    Explicit zero means unvoiced. This function does not extract pitch, move
    boundaries, interpolate, or decide which recording is linguistically right.
    """
    rate, origin, guide_values = _read_track(guide, "guide")
    other_rate, other_origin, conditioning_values = _read_track(
        conditioning, "conditioning")
    if rate != other_rate:
        raise ValueError("F0 frame_rate_hz values differ; align explicitly first.")
    if origin != other_origin:
        raise ValueError("F0 origin_seconds values differ; align explicitly first.")
    if len(guide_values) != len(conditioning_values):
        raise ValueError("F0 frame counts differ; align explicitly first.")
    mismatched = [index for index, (left, right) in enumerate(
        zip(guide_values, conditioning_values)) if bool(left) != bool(right)]
    intervals = []
    for index in mismatched:
        if intervals and intervals[-1][1] == index:
            intervals[-1][1] = index + 1
        else:
            intervals.append([index, index + 1])
    with decimal.localcontext() as context:
        context.prec = 50
        spans = [{
            "start_frame": start,
            "end_frame_exclusive": end,
            "start_seconds": str(origin + decimal.Decimal(start) / rate),
            "end_seconds_exclusive": str(origin + decimal.Decimal(end) / rate),
        } for start, end in intervals]
    both_voiced = [(left, right) for left, right in zip(
        guide_values, conditioning_values) if left and right]
    return {
        "frame_rate_hz": str(rate),
        "origin_seconds": str(origin),
        "frames": len(guide_values),
        "mismatched_voicing_frames": len(mismatched),
        "voicing_masks_match": not mismatched,
        "mismatch_intervals": spans,
        "both_voiced_frames": len(both_voiced),
        "both_voiced_pitch_values_equal": (all(
            left == right for left, right in both_voiced) if both_voiced else None),
        "pronunciation_assessed": False,
        "interpretation": "A mask difference is a diagnostic, not a diction verdict.",
    }
