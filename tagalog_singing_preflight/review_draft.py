"""Prepare a contextual pronunciation review draft for one benchmark item."""

from __future__ import annotations

import pathlib

from tagalog_singing_preflight import benchmark
from tagalog_singing_preflight import lexicon


LIMIT = (
    "Draft for contextual pronunciation review. Candidate decisions and native "
    "review are pending. Permissions, model phone compatibility and singing "
    "quality remain unassessed."
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
        raise ValueError(f"Benchmark manifest failed validation ({first_error}). "
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
