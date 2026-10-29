"""Combine small mechanical checks with explicit, machine-readable limits."""

from __future__ import annotations

import decimal

from tagalog_singing_preflight import phonemes
from tagalog_singing_preflight import text
from tagalog_singing_preflight import timing
from tagalog_singing_preflight import voicing


LIMIT = (
    "Mechanical metadata checks only. Pronunciation, stress, singer identity "
    "and musical quality are unassessed."
)


def audit_plan(plan: dict) -> dict:
    """Check a caller-supplied plan without changing its text or metadata.

    Required fields: text, phoneme_groups, vocabulary, durations_seconds,
    frame_rate_hz, expected_frames and timing_mode. Optional guide_f0 and
    conditioning_f0 must be supplied together on the same declared grid.
    """
    report = {"schema_version": 1, "status": "fail", "errors": [],
              "warnings": [], "assessment_limit": LIMIT}
    if not isinstance(plan, dict):
        report["errors"].append({"code": "INVALID_PLAN",
                                 "message": "Plan must be a JSON object."})
        return report
    if type(plan.get("schema_version")) is not int or plan["schema_version"] != 1:
        report["errors"].append({"code": "SCHEMA_VERSION",
                                 "message": "schema_version must be 1."})
    try:
        report["text"] = text.normalize_hint(plan.get("text"))
        report["warnings"].extend(report["text"]["warnings"])
    except ValueError as error:
        report["errors"].append({"code": "TEXT", "message": str(error)})
    try:
        result = phonemes.check_vocabulary(
            plan.get("phoneme_groups"), plan.get("vocabulary"))
        report["phonemes"] = result
        if result["unknown_tokens"]:
            report["errors"].append({
                "code": "UNKNOWN_PHONEMES",
                "message": "Declared vocabulary does not contain all supplied tokens.",
                "unknown_tokens": result["unknown_tokens"],
            })
    except ValueError as error:
        report["errors"].append({"code": "PHONEMES", "message": str(error)})
    try:
        if "expected_frames" not in plan:
            raise ValueError("expected_frames is required.")
        if type(plan["expected_frames"]) is not int or plan["expected_frames"] <= 0:
            raise ValueError("expected_frames must be a positive integer.")
        mode = plan.get("timing_mode")
        if mode not in ("cumulative_half_up", "legacy_sum_float_floor"):
            raise ValueError(
                "timing_mode must be cumulative_half_up or legacy_sum_float_floor.")
        result = timing.allocate_frames(
            plan.get("durations_seconds"), plan.get("frame_rate_hz"),
            plan["expected_frames"])
        report["timing"] = result
        if not result["expected_frames_match"]:
            report["errors"].append({
                "code": "FRAME_TOTAL",
                "message": "Allocated frame total differs from expected_frames.",
            })
        groups = plan.get("phoneme_groups")
        if isinstance(groups, list) and len(groups) != len(result["group_frames"]):
            report["errors"].append({
                "code": "GROUP_COUNT",
                "message": "Each phoneme group must have one duration.",
            })
        if result["zero_frame_groups"]:
            report["errors"].append({
                "code": "ZERO_FRAME_GROUPS",
                "message": "A supplied group receives zero frames at this clock.",
                "group_indices": result["zero_frame_groups"],
            })
        legacy = result["legacy_float_floor_total_frames"]
        exact_floor = result["exact_sum_floor_total_frames"]
        if legacy != exact_floor:
            report["warnings"].append({
                "code": "LEGACY_FLOAT_FLOOR_DIFFERENCE",
                "message": "Binary-float sum/floor differs from exact decimal floor.",
                "legacy_frames": legacy, "exact_floor_frames": exact_floor,
            })
        result["selected_timing_mode"] = mode
        selected_frames = (result["total_frames"] if mode == "cumulative_half_up"
                           else legacy)
        result["selected_total_frames"] = selected_frames
        if selected_frames != plan["expected_frames"]:
            report["errors"].append({
                "code": "BACKEND_FRAME_TOTAL",
                "message": "Selected backend timing mode misses expected_frames.",
                "selected_total_frames": selected_frames,
            })
    except ValueError as error:
        report["errors"].append({"code": "TIMING", "message": str(error)})
    has_guide = "guide_f0" in plan
    has_conditioning = "conditioning_f0" in plan
    if has_guide != has_conditioning:
        report["errors"].append({
            "code": "F0_PAIR", "message": "Supply both F0 tracks or neither.",
        })
    elif has_guide:
        try:
            result = voicing.compare_voicing(
                plan["guide_f0"], plan["conditioning_f0"])
            report["voicing"] = result
            if not result["voicing_masks_match"]:
                report["errors"].append({
                    "code": "VOICING_MISMATCH",
                    "message": "Declared aligned tracks have different voicing masks.",
                })
            timing_rate = report.get("timing", {}).get("frame_rate_hz")
            if (result["frames"] != plan.get("expected_frames")
                    or (timing_rate is not None and decimal.Decimal(
                        result["frame_rate_hz"]) != decimal.Decimal(timing_rate))):
                report["errors"].append({
                    "code": "F0_PLAN_CLOCK",
                    "message": "F0 clock or frame count differs from plan timing.",
                })
        except ValueError as error:
            report["errors"].append({"code": "F0", "message": str(error)})
    if not report["errors"]:
        report["status"] = "pass"
    return report
