"""Audit native SoulX-Singer SVS metadata without loading its model.

Contract reference: Soul-AILab/SoulX-Singer at UPSTREAM_COMMIT,
soulxsinger/utils/data_processor.py and soulxsinger/models/soulxsinger.py.
This is an original diagnostic implementation, not a tensor processor or G2P.
"""

from __future__ import annotations

import decimal

from tagalog_singing_preflight import audit
from tagalog_singing_preflight import phonemes
from tagalog_singing_preflight import timing
from tagalog_singing_preflight import voicing


UPSTREAM_COMMIT = "81aeb3ae772c70093c3de74dc23c92d983801ae4"
UPSTREAM_URL = (
    "https://github.com/Soul-AILab/SoulX-Singer/blob/"
    + UPSTREAM_COMMIT + "/soulxsinger/utils/data_processor.py"
)
_FIELDS = ("phoneme", "duration", "note_pitch", "note_type")


def _metadata_groups(metadata: object) -> dict[str, list[str]]:
    """Read a native object or the upstream singleton-list envelope."""
    if isinstance(metadata, list) and len(metadata) == 1:
        metadata = metadata[0]
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object or a list of one object.")
    groups = {}
    for field in _FIELDS:
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{field} must be a nonempty native metadata string.")
        groups[field] = value.split()
    if len({len(values) for values in groups.values()}) != 1:
        raise ValueError(
            "phoneme, duration, note_pitch and note_type counts differ.")
    if len(groups["phoneme"]) > timing.MAX_GROUPS:
        raise ValueError(f"metadata exceeds {timing.MAX_GROUPS} note groups.")
    f0 = metadata.get("f0", "")
    if not isinstance(f0, str):
        raise ValueError("f0 must be a whitespace-delimited string.")
    groups["f0"] = f0.split()
    if len(groups["f0"]) > voicing.MAX_F0_FRAMES:
        raise ValueError(f"f0 exceeds {voicing.MAX_F0_FRAMES} frames.")
    return groups


def _embedding_values(values: list[str], field: str) -> list[int]:
    """Refuse indices outside SoulX's 256-entry note embeddings."""
    try:
        result = [int(value) for value in values]
    except ValueError as error:
        raise ValueError(f"{field} must contain integers.") from error
    if any(not 0 <= value <= 255 for value in result):
        raise ValueError(f"{field} must contain integers between 0 and 255.")
    return result


def _native_groups(
    groups: dict, durations: list[decimal.Decimal]
) -> list[dict]:
    """Account for native pause replacement and consecutive pause merging."""
    pitches = _embedding_values(groups["note_pitch"], "note_pitch")
    types = _embedding_values(groups["note_type"], "note_type")
    merged = []
    for index, original in enumerate(groups["phoneme"]):
        phone = original.replace("<AP>", "<SP>")
        note_type = 1 if phone == "<SP>" else types[index]
        if (merged and phone == merged[-1]["phoneme"] == "<SP>"
                and pitches[index] == merged[-1]["note_pitch"]):
            merged[-1]["native_duration"] += float(durations[index])
            merged[-1]["source_groups"].append(index)
        else:
            merged.append({
                "phoneme": phone, "native_duration": float(durations[index]),
                "note_pitch": pitches[index], "note_type": note_type,
                "source_groups": [index],
            })
    return merged


def audit_metadata(
    metadata: object,
    vocabulary: list[str],
    expected_frames: int,
    sample_rate: int = 24000,
    hop_size: int = 480,
) -> dict:
    """Check native strings against a phoneset and expected frame count.

    Args:
        metadata: Native object or singleton-list envelope. Required strings are
            phoneme, duration, note_pitch and note_type. Optional f0 is also a
            whitespace-delimited string. Other fields are left untouched.
        vocabulary: Token list from the receiving frontend's phone_set.json.
            This declaration does not prove checkpoint embedding compatibility.
        expected_frames: Positive frame count required by the intended output.
        sample_rate: Receiving processor sample rate, in samples per second.
        hop_size: Receiving processor samples per frame. This diagnostic profile
            supports integer frame rates only.

    Returns:
        A JSON-compatible report. A pass checks the listed mechanical contracts;
        it does not execute the processor, generate audio or assess diction.
        The metadata and vocabulary are never modified.
    """
    report = {
        "schema_version": 1, "status": "fail", "errors": [], "warnings": [],
        "assessment_limit": audit.LIMIT + (
            " Native tensor alignment, checkpoint compatibility and audio are "
            "not evaluated; input metadata is not repaired."),
        "upstream_commit": UPSTREAM_COMMIT, "contract_source": UPSTREAM_URL,
    }
    try:
        if (type(expected_frames) is not int or not 0 < expected_frames
                <= voicing.MAX_F0_FRAMES):
            raise ValueError(
                "expected_frames must be an integer from 1 to "
                f"{voicing.MAX_F0_FRAMES}.")
        if (type(sample_rate) is not int or not 0 < sample_rate <= 1_000_000
                or type(hop_size) is not int or not 0 < hop_size <= sample_rate
                or sample_rate % hop_size):
            raise ValueError(
                "sample_rate/hop_size must define a positive integer rate; "
                "sample_rate must not exceed 1000000.")
        rate = sample_rate // hop_size
        groups = _metadata_groups(metadata)
        durations = [timing.number(value, f"duration[{index}]")
                     for index, value in enumerate(groups["duration"])]
        if any(not value for value in durations):
            raise ValueError("Every native note duration must be positive.")
        native = _native_groups(groups, durations)
        expanded_groups = []
        for group in native:
            phone = group["phoneme"]
            if phone.startswith("en_"):
                expanded = ["en_" + value for value in phone[3:].split("-")]
                expanded.append("<SEP>")
            else:
                expanded = [phone]
            expanded_groups.append(" ".join(["<BOW>", *expanded, "<EOW>"]))
        expanded_groups[0] = "<PAD> " + expanded_groups[0]
        checked = phonemes.check_vocabulary(expanded_groups, vocabulary)
        report["phonemes"] = {
            "input_groups": len(groups["phoneme"]),
            "native_groups_after_pause_merge": len(native),
            "expanded_token_count": checked["token_count"],
            "unknown_tokens": [
                {"source_group_indices": ([] if item["token"] == "<PAD>" else
                    native[item["group_index"]]["source_groups"]),
                 "token": item["token"]}
                for item in checked["unknown_tokens"]],
            "pronunciation_assessed": False,
        }
        if checked["unknown_tokens"]:
            report["errors"].append({
                "code": "UNKNOWN_NATIVE_PHONEMES",
                "message": "Expanded native tokens are absent from phoneset.",
            })
        if any("<AP>" in phone for phone in groups["phoneme"]):
            report["warnings"].append({
                "code": "NATIVE_AP_TO_SP",
                "message": "The native frontend replaces <AP> with <SP>.",
            })
        if len(native) != len(groups["phoneme"]):
            report["warnings"].append({
                "code": "NATIVE_PAUSE_MERGE",
                "message": (
                    "Native processing merges adjacent equal-pitch pauses."),
            })
        allocation = timing.allocate_frames(groups["duration"], rate,
                                            expected_frames)
        # Match the referenced native processor's operation order, including
        # float additions within merged pauses. This does not change its clock.
        native_frames = int(sum(group["native_duration"] for group in native)
                            * sample_rate / hop_size)
        report["timing"] = {
            "sample_rate": sample_rate, "hop_size": hop_size,
            "frame_rate_hz": rate, "expected_frames": expected_frames,
            "exact_allocated_frames": allocation["total_frames"],
            "native_float_floor_frames": native_frames,
            "exact_total_seconds": allocation["total_seconds"],
        }
        if (allocation["total_frames"] != expected_frames
                or native_frames != expected_frames):
            report["errors"].append({
                "code": "NATIVE_FRAME_TOTAL",
                "message": (
                    "Exact allocation or native total misses expected_frames."),
            })
        if allocation["zero_frame_groups"]:
            report["errors"].append({
                "code": "ZERO_FRAME_GROUPS",
                "message": "Some input notes receive no frames at this clock.",
                "source_group_indices": allocation["zero_frame_groups"],
            })
        if groups["f0"]:
            for index, value in enumerate(groups["f0"]):
                timing.number(value, f"f0[{index}]")
            final_frames = min(native_frames, len(groups["f0"]))
            report["f0"] = {
                "supplied_frames": len(groups["f0"]),
                "native_retained_frames": final_frames,
                "native_truncates_f0": len(groups["f0"]) > native_frames,
                "native_truncates_metadata": native_frames > len(groups["f0"]),
            }
            if (len(groups["f0"]) != native_frames
                    or final_frames != expected_frames):
                report["errors"].append({
                    "code": "NATIVE_F0_TRUNCATION",
                    "message": (
                        "Native processing truncates F0 or metadata to the "
                        "shorter clock."),
                })
        else:
            report["warnings"].append({
                "code": "NO_F0",
                "message": "No F0 supplied; melody control is not established.",
            })
    except ValueError as error:
        report["errors"].append({
            "code": "NATIVE_CONTRACT", "message": str(error)})
    if not report["errors"]:
        report["status"] = "pass"
    return report
