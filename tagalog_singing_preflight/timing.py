"""Allocate a declared frame clock without binary-float floor loss."""

from __future__ import annotations

import decimal


MAX_GROUPS = 100_000


def number(value: object, name: str, maximum: str = "1000000000") -> decimal.Decimal:
    """Read a bounded finite decimal without accepting booleans as numbers."""
    if isinstance(value, bool) or not isinstance(
        value, (str, int, float, decimal.Decimal)
    ):
        raise ValueError(f"{name} must be a decimal number.")
    try:
        result = decimal.Decimal(str(value))
    except decimal.InvalidOperation as error:
        raise ValueError(f"{name} must be a decimal number.") from error
    if not result.is_finite() or not 0 <= result <= decimal.Decimal(maximum):
        raise ValueError(f"{name} must be finite and between 0 and {maximum}.")
    if result.as_tuple().exponent < -18:
        raise ValueError(f"{name} supports at most 18 fractional decimal places.")
    return result


def allocate_frames(
    durations_seconds: list[object],
    frame_rate_hz: object = 50,
    expected_frames: int | None = None,
) -> dict:
    """Return exact-decimal cumulative half-up allocation and legacy diagnostics.

    Zero-frame groups are reported rather than silently stretched. The caller
    decides whether such a group is usable by its model.
    """
    if not isinstance(durations_seconds, list) or not durations_seconds:
        raise ValueError("durations_seconds must be a nonempty list.")
    if len(durations_seconds) > MAX_GROUPS:
        raise ValueError(f"durations_seconds exceeds {MAX_GROUPS} groups.")
    rate = number(frame_rate_hz, "frame_rate_hz", "1000000")
    if not rate:
        raise ValueError("frame_rate_hz must be positive.")
    if expected_frames is not None and (
        isinstance(expected_frames, bool)
        or not isinstance(expected_frames, int)
        or expected_frames <= 0
    ):
        raise ValueError("expected_frames must be a positive integer.")
    values = [number(value, f"duration[{index}]")
              for index, value in enumerate(durations_seconds)]
    # Bounds above limit accepted numbers to 28 significant decimal places.
    # Sixty-four digits cover the maximum list length and decimal rate product.
    with decimal.localcontext() as context:
        context.prec = 64
        cumulative = decimal.Decimal(0)
        boundaries = [0]
        legacy_frames = []
        discrepancies = []
        for index, value in enumerate(values):
            cumulative += value
            boundary = int((cumulative * rate).to_integral_value(
                rounding=decimal.ROUND_HALF_UP))
            boundaries.append(boundary)
            exact_floor = int((value * rate).to_integral_value(
                rounding=decimal.ROUND_FLOOR))
            float_floor = int(float(value) * float(rate))
            legacy_frames.append(float_floor)
            if float_floor != exact_floor:
                discrepancies.append({
                    "group_index": index,
                    "duration_seconds": str(value),
                    "legacy_float_floor_frames": float_floor,
                    "decimal_floor_frames": exact_floor,
                })
        if not cumulative:
            raise ValueError("Total duration must be positive.")
        frames = [end - start for start, end in zip(
            boundaries[:-1], boundaries[1:])]
        return {
            "rounding": "cumulative-half-up",
            "frame_rate_hz": str(rate),
            "total_seconds": str(cumulative),
            "group_frames": frames,
            "boundaries_frames": boundaries,
            "total_frames": boundaries[-1],
            "expected_frames": expected_frames,
            "expected_frames_match": (
                expected_frames is None or boundaries[-1] == expected_frames),
            "zero_frame_groups": [i for i, value in enumerate(frames) if not value],
            "legacy_float_floor_total_frames": int(
                sum(float(value) for value in values) * float(rate)),
            "exact_sum_floor_total_frames": int(
                (cumulative * rate).to_integral_value(
                    rounding=decimal.ROUND_FLOOR)),
            "legacy_per_group_float_floor_total_frames": sum(legacy_frames),
            "legacy_float_floor_discrepancies": discrepancies,
        }
