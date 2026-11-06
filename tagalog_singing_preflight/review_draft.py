"""Prepare and check contextual pronunciation reviews for benchmark items."""

from __future__ import annotations

import pathlib
import unicodedata

from tagalog_singing_preflight import benchmark
from tagalog_singing_preflight import lexicon


LIMIT = (
    "Draft for contextual pronunciation review. Candidate decisions and native "
    "review are pending. Permissions, model phone compatibility and singing "
    "quality remain unassessed."
)
CHECK_LIMIT = (
    "This check compares the draft with the supplied sources and validates "
    "declared review decisions. Native review, pronunciation, permissions, "
    "model phone compatibility and singing quality remain unassessed."
)


def prepare_draft(
    manifest: object,
    item_id: str,
    lexicon_path: pathlib.Path,
    *,
    source_label: str,
    data_license: str,
) -> dict:
    """Prepare blank review fields alongside the supplied IPA candidates.

    Args:
        manifest: Parsed benchmark manifest containing the development item.
        item_id: Exact manifest identifier of the development item.
        lexicon_path: Local UTF-8 pronunciation TSV.
        source_label: Caller-declared source and version of the TSV.
        data_license: Caller-declared data terms for the TSV.

    Returns:
        A draft containing the full phrase, original code-point offsets, and
        unselected candidates with source rows. Every review starts pending.

    Raises:
        ValueError: The manifest or lookup inputs are invalid, or the item ID
            does not identify a development item.
        OSError: The lexicon cannot be read.
        UnicodeError: The lexicon is not UTF-8.
    """
    audit = benchmark.audit_manifest(manifest)
    if audit["status"] != "pass":
        first_error = audit["errors"][0]["code"]
        raise ValueError(
            f"Benchmark manifest failed validation ({first_error}). "
            "Run the benchmark command for details.")

    item = next((item for item in manifest["items"] if item["id"] == item_id),
                None)
    if item is None:
        raise ValueError(f"Unknown benchmark item ID {item_id!r}.")
    if item["split"] != "development":
        raise ValueError("Review drafts require a development item. "
                         "Held-out items are reserved for evaluation.")

    lookup = lexicon.lookup_text(
        item["text"], lexicon_path, source_label=source_label,
        data_license=data_license)
    for occurrence in lookup["occurrences"]:
        occurrence["annotation"] = {
            "selected_source_row": None,
            "proposed_ipa_tokens": None,
            "notes": None,
        }

    return {
        "schema_version": 1,
        "status": "pass",
        "assessment_limit": LIMIT,
        "benchmark_id": audit["benchmark_id"],
        "item_id": item["id"],
        "split": item["split"],
        "original_text": lookup["original_text"],
        "focus": list(item["focus"]),
        "source_declaration": lookup["source_declaration"],
        "offset_unit": lookup["offset_unit"],
        "end_offset_exclusive": lookup["end_offset_exclusive"],
        "occurrence_counts": lookup["occurrence_counts"],
        "occurrences": lookup["occurrences"],
        "review": {
            "status": "pending",
            "reviewer_id": None,
            "reviewed_at": None,
            "pronunciation_notes": None,
        },
        "permissions_verified": False,
        "native_review_verified": False,
        "pronunciation_assessed": False,
        "model_phone_mapping_assessed": False,
    }


def _require_match(value: object, expected: object, field: str) -> None:
    """Compare generated values exactly, including JSON number types."""
    if type(value) is not type(expected):
        raise ValueError(f"{field} does not match the regenerated draft.")
    if isinstance(expected, dict):
        if value.keys() != expected.keys():
            raise ValueError(f"{field} has missing or extra generated fields.")
        for key, entry in expected.items():
            _require_match(value[key], entry, f"{field}.{key}")
    elif isinstance(expected, list):
        if len(value) != len(expected):
            raise ValueError(f"{field} does not match the regenerated draft.")
        for index, (actual, entry) in enumerate(zip(value, expected)):
            _require_match(actual, entry, f"{field}[{index}]")
    elif value != expected:
        raise ValueError(f"{field} does not match the regenerated draft.")


def _check_annotation(
    annotation: object, occurrence: dict, field: str,
) -> dict | None:
    """Validate an editable annotation and resolve its declared tokens."""
    if (not isinstance(annotation, dict)
            or annotation.keys() != occurrence["annotation"].keys()):
        raise ValueError(f"{field} must contain the three draft fields.")
    notes = annotation["notes"]
    if notes is not None and (
        not isinstance(notes, str) or not notes.strip()
        or len(notes) > benchmark.MAX_TEXT_CHARS
    ):
        raise ValueError(f"{field}.notes must be null or nonblank text of at "
                         f"most {benchmark.MAX_TEXT_CHARS} characters.")

    selected = annotation["selected_source_row"]
    proposed = annotation["proposed_ipa_tokens"]
    if selected is not None and proposed is not None:
        raise ValueError(f"{field} must choose one pronunciation source.")
    if selected is not None:
        if type(selected) is not int or selected < 1:
            raise ValueError(f"{field}.selected_source_row must be a positive "
                             "integer.")
        candidate = next((candidate for candidate in occurrence["candidates"]
                          if candidate["source_row"] == selected), None)
        if candidate is None:
            raise ValueError(f"{field}.selected_source_row must identify a "
                             "candidate for this occurrence.")
        tokens = candidate["tokens"]
    elif proposed is not None:
        token_field = f"{field}.proposed_ipa_tokens"
        if not isinstance(proposed, list) or not proposed:
            raise ValueError(f"{token_field} must be a nonempty token list.")
        total = len(proposed) - 1
        for token in proposed:
            if not isinstance(token, str) or not token:
                raise ValueError(f"{token_field} requires nonempty strings.")
            total += len(token)
            if total > lexicon.MAX_IPA_CHARACTERS:
                raise ValueError(f"{token_field} exceeds "
                                 f"{lexicon.MAX_IPA_CHARACTERS} characters "
                                 "including token separators.")
            if any(c.isspace() or unicodedata.category(c)[0] == "C"
                   for c in token):
                raise ValueError(f"{token_field} tokens must exclude "
                                 "whitespace and control characters.")
        tokens = proposed
    else:
        return None

    return {
        "text": occurrence["text"],
        "start": occurrence["start"],
        "end": occurrence["end"],
        "ipa_tokens": list(tokens),
        "selected_source_row": selected,
    }


def check_draft(
    manifest: object,
    item_id: str,
    lexicon_path: pathlib.Path,
    edited_review: object,
    *,
    source_label: str,
    data_license: str,
) -> dict:
    """Check a returned development review against its regenerated draft.

    Args:
        manifest: Parsed benchmark manifest containing the development item.
        item_id: Exact manifest identifier of the development item.
        lexicon_path: Local UTF-8 pronunciation TSV used for the draft.
        edited_review: Parsed draft with edits confined to review fields and
            occurrence annotations.
        source_label: Caller-declared source and version of the TSV.
        data_license: Caller-declared data terms for the TSV.

    Returns:
        A mechanical comparison report with resolution counts and the ordered
        tokens for a complete review declared approved.
    Raises:
        ValueError: The sources or returned draft are invalid or disagree.
        OSError: The lexicon cannot be read.
        UnicodeError: The lexicon is not UTF-8.
    """
    expected = prepare_draft(
        manifest, item_id, lexicon_path, source_label=source_label,
        data_license=data_license)
    if (not isinstance(edited_review, dict)
            or edited_review.keys() != expected.keys()):
        raise ValueError("Returned draft has missing or extra fields.")
    for key, value in expected.items():
        if key not in ("review", "occurrences"):
            _require_match(edited_review[key], value, key)

    review = edited_review["review"]
    if (not isinstance(review, dict)
            or review.keys() != expected["review"].keys()):
        raise ValueError("review must contain the four draft fields.")
    declared_status = benchmark.validate_review_record(review)

    occurrences = edited_review["occurrences"]
    if (not isinstance(occurrences, list)
            or len(occurrences) != len(expected["occurrences"])):
        raise ValueError("occurrences do not match the regenerated draft.")
    resolved = []
    for index, (returned, generated) in enumerate(
        zip(occurrences, expected["occurrences"])
    ):
        field = f"occurrences[{index}]"
        if (not isinstance(returned, dict)
                or returned.keys() != generated.keys()):
            raise ValueError(f"{field} has missing or extra generated fields.")
        for key, value in generated.items():
            if key != "annotation":
                _require_match(returned[key], value, f"{field}.{key}")
        result = _check_annotation(returned["annotation"], generated,
                                   f"{field}.annotation")
        if result is not None:
            resolved.append(result)
    unresolved_count = len(occurrences) - len(resolved)
    if declared_status == "approved" and unresolved_count:
        raise ValueError("An approved review must resolve every occurrence.")

    report = {
        key: expected[key]
        for key in (
            "schema_version", "status", "benchmark_id", "item_id", "split",
            "original_text", "source_declaration", "offset_unit",
            "end_offset_exclusive", "permissions_verified",
            "native_review_verified", "pronunciation_assessed",
            "model_phone_mapping_assessed",
        )
    }
    report.update(
        assessment_limit=CHECK_LIMIT,
        declared_review_status=declared_status,
        resolved_count=len(resolved),
        unresolved_count=unresolved_count,
        resolved_occurrences=resolved if declared_status == "approved" else [],
    )
    return report
