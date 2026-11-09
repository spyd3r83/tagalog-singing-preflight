"""Compare bounded content-note metadata with supplied native CPU results.

This module has no tensor dependency and does not execute the native processor.
The optional examples.compare_soulx_cpu runner supplies actual tensor results.
"""

from __future__ import annotations

from tagalog_singing_preflight import soulx


FIELDS = ("phoneme", "note_pitch", "note_type", "mel2note")
LIMIT = (
    "Compares retained phone IDs/tokens, note fields and alignment frame "
    "count. "
    "Zero alignment indices are reported, not repaired or accepted as correct "
    "assignments. Checkpoint compatibility, pronunciation and audio quality "
    "remain unassessed."
)


def _vector(processed: dict, field: str) -> list[int]:
    value = processed.get(field)
    if (not isinstance(value, list) or len(value) != 1
            or not isinstance(value[0], list)
            or any(type(item) is not int for item in value[0])):
        raise ValueError(f"Native {field} must be one batch of integer values.")
    return value[0]


def compare_processed(
    metadata: object,
    vocabulary: list[str],
    processed: dict,
    expected_frames: int,
    sample_rate: int = 24000,
    hop_size: int = 480,
) -> dict:
    """Compare native list results without claiming how they were produced.

    Args:
        metadata: Native content-note object from soulx-export, without F0.
        vocabulary: Ordered phoneset used by the native processor.
        processed: Native phoneme, note_pitch, note_type and mel2note arrays,
            converted to nested Python lists with a single batch.
        expected_frames: Required positive alignment frame count.
        sample_rate: Native sample rate in samples per second.
        hop_size: Native samples per frame.

    Returns:
        Mechanical comparisons, retained arrays and alignment counters. A pass
        does not establish correct alignment assignments or model behavior.
        Execution remains unverified until the actual runner records it.

    Raises:
        ValueError: Metadata audit fails, input contains rests or F0, or native
            arrays are not single batches of integers.
    """
    checked = soulx.audit_metadata(metadata, vocabulary, expected_frames,
                                    sample_rate, hop_size)
    if checked["status"] != "pass":
        codes = ", ".join(error["code"] for error in checked["errors"])
        raise ValueError(f"Native metadata audit failed: {codes}.")
    if not isinstance(metadata, dict) or metadata.get("f0", ""):
        raise ValueError("Comparison needs a content-note object without F0.")
    if not isinstance(processed, dict):
        raise ValueError("Native results must be an object.")
    tokens = ["<PAD>"]
    pitches = [0]
    types = [1]
    for phone, pitch, note_type in zip(
            metadata["phoneme"].split(), metadata["note_pitch"].split(),
            metadata["note_type"].split()):
        if (phone in {"<PAD>", "<BOW>", "<EOW>", "<SEP>", "<SP>"}
                or "<AP>" in phone):
            raise ValueError("Comparison supports exported content notes only.")
        content = (["en_" + part for part in phone[3:].split("-")]
                   + ["<SEP>"] if phone.startswith("en_") else [phone])
        group = ["<BOW>", *content, "<EOW>"]
        tokens.extend(group)
        pitches.extend([int(pitch)] * len(group))
        types.extend([int(note_type)] * len(group))
    phone_ids = {token: index for index, token in enumerate(vocabulary)}
    expected_ids = [phone_ids[token] for token in tokens]
    actual = {field: _vector(processed, field) for field in FIELDS}
    actual_tokens = [vocabulary[value] if 0 <= value < len(vocabulary)
                     else None for value in actual["phoneme"]]
    alignment = actual["mel2note"]
    checks = {
        "phoneme_ids_match": actual["phoneme"] == expected_ids,
        "phoneme_tokens_match": actual_tokens == tokens,
        "note_pitch_match": actual["note_pitch"] == pitches,
        "note_type_match": actual["note_type"] == types,
        "alignment_clock_matches": len(alignment) == expected_frames,
        "alignment_indices_in_bounds": all(
            0 <= value < len(actual["phoneme"]) for value in alignment),
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "assessment_limit": LIMIT, "checks": checks, "audit": checked,
        "expected_token_count": len(tokens),
        "retained": {**actual, "phoneme_tokens": actual_tokens},
        "alignment": {
            "expected_frames": expected_frames, "frames": len(alignment),
            "zero_index_frames": alignment.count(0),
            "positive_index_frames": sum(value > 0 for value in alignment),
        },
        "native_processor_executed": False,
        "alignment_assignment_verified": False,
        "model_runtime_verified": False, "pronunciation_assessed": False,
        "native_review_verified": False,
    }
