"""Apply explicit IPA-to-model rules to a checked development review."""

from __future__ import annotations

import pathlib
import unicodedata

from tagalog_singing_preflight import phonemes
from tagalog_singing_preflight import review_draft


MAX_RULES = 10_000
MAX_TARGETS_PER_RULE = 16
MAX_OUTPUT_TOKENS = 100_000
LIMIT = (
    "Explicit mapping and declared-vocabulary membership checked. Native "
    "reviewer identity, linguistic equivalence, permissions, model runtime "
    "compatibility and singing quality remain unassessed."
)


def _token(value: object, limit: int, field: str) -> None:
    if (not isinstance(value, str) or not value or len(value) > limit
            or any(c.isspace() or unicodedata.category(c)[0] == "C"
                   for c in value)):
        raise ValueError(f"{field} must be a nonempty token of at most "
                         f"{limit} characters without whitespace or controls.")


def _validate_mapping(mapping: object, vocabulary: object) -> dict:
    """Check the complete profile and every declared target token."""
    fields = {"schema_version", "mapping_id", "target_model", "rules"}
    if not isinstance(mapping, dict) or mapping.keys() != fields:
        raise ValueError("Mapping must contain exactly the four profile "
                         "fields.")
    if (type(mapping["schema_version"]) is not int
            or mapping["schema_version"] != 1):
        raise ValueError("Mapping schema_version must be integer 1.")
    for field in ("mapping_id", "target_model"):
        value = mapping[field]
        if (not isinstance(value, str) or not value.strip() or len(value) > 512
                or any(unicodedata.category(c)[0] == "C" for c in value)):
            raise ValueError(f"{field} must be nonblank text of at most 512 "
                             "characters without controls.")
    rules = mapping["rules"]
    if not isinstance(rules, dict) or not 1 <= len(rules) <= MAX_RULES:
        raise ValueError(f"rules must contain between 1 and {MAX_RULES} "
                         "entries.")
    groups = []
    for source, targets in rules.items():
        _token(source, 1024, "Rule source")
        if (not isinstance(targets, list)
                or not 1 <= len(targets) <= MAX_TARGETS_PER_RULE):
            raise ValueError(f"Rule {source!r} needs between 1 and "
                             f"{MAX_TARGETS_PER_RULE} target tokens.")
        for target in targets:
            _token(target, 256, f"Rule {source!r} target")
        groups.append(" ".join(targets))

    if (not isinstance(vocabulary, list) or not vocabulary
            or len(vocabulary) > 1_000_000):
        raise ValueError("vocabulary must contain 1-1000000 single tokens.")
    for token in vocabulary:
        if (not isinstance(token, str) or not token
                or any(c.isspace() or unicodedata.category(c)[0] == "C"
                       for c in token)):
            raise ValueError("vocabulary entries must be nonempty tokens "
                             "without whitespace or controls.")
    checked = phonemes.check_vocabulary(groups, vocabulary)
    if not checked["tokens_supported_by_declared_vocabulary"]:
        unknown = checked["unknown_tokens"][0]
        source = list(rules)[unknown["group_index"]]
        raise ValueError(f"Rule {source!r} target {unknown['token']!r} is "
                         "absent from the declared vocabulary.")
    return rules


def map_review(
    manifest: object,
    item_id: str,
    lexicon_path: pathlib.Path,
    edited_review: object,
    mapping: object,
    vocabulary: object,
    *,
    source_label: str,
    data_license: str,
) -> dict:
    """Map a complete declared-approved review through exact supplied rules.

    Source tokens match by their exact Unicode spelling and case. Every rule
    must emit at least one declared target token. Inputs remain unchanged.

    Args:
        manifest: Original benchmark manifest.
        item_id: Exact development item identifier.
        lexicon_path: Local pronunciation TSV used to prepare the review.
        edited_review: Original draft with reviewer decisions filled in.
        mapping: Version 1 profile with identity, target model and token rules.
        vocabulary: Caller-supplied receiving model token list.
        source_label: Caller-declared lexicon source and version.
        data_license: Caller-declared lexicon data terms.

    Returns:
        Ordered mapped occurrences preserving original text and code-point
        offsets, plus explicit mechanical-check and assessment fields.

    Raises:
        ValueError: Review, profile or vocabulary is invalid, a source rule is
            missing, or expansion exceeds 100000 output tokens.
        OSError: The source lexicon cannot be read.
        UnicodeError: The source lexicon is not UTF-8.
    """
    reviewed = review_draft.check_draft(
        manifest, item_id, lexicon_path, edited_review,
        source_label=source_label, data_license=data_license)
    if (reviewed["declared_review_status"] != "approved"
            or reviewed["unresolved_count"]):
        raise ValueError("Mapping requires a complete review declared "
                         "approved.")
    rules = _validate_mapping(mapping, vocabulary)

    mapped = []
    total = 0
    for index, occurrence in enumerate(reviewed["resolved_occurrences"]):
        targets = []
        for token_index, token in enumerate(occurrence["ipa_tokens"]):
            if token not in rules:
                raise ValueError(f"Occurrence {index} IPA token {token_index} "
                                 f"{token!r} has no explicit mapping rule.")
            expansion = rules[token]
            if total + len(expansion) > MAX_OUTPUT_TOKENS:
                raise ValueError(f"Mapping exceeds {MAX_OUTPUT_TOKENS} "
                                 "output tokens.")
            targets.extend(expansion)
            total += len(expansion)
        mapped.append({
            "text": occurrence["text"], "start": occurrence["start"],
            "end": occurrence["end"],
            "ipa_tokens": list(occurrence["ipa_tokens"]),
            "target_tokens": targets,
        })
    report = {key: reviewed[key] for key in (
        "benchmark_id", "item_id", "original_text", "source_declaration",
        "offset_unit", "end_offset_exclusive",
    )}
    report.update({
        "schema_version": 1, "status": "pass", "assessment_limit": LIMIT,
        "mapping_id": mapping["mapping_id"],
        "target_model": mapping["target_model"],
        "mapped_occurrences": mapped, "target_token_count": total,
        "tokens_supported_by_declared_vocabulary": True,
        "native_review_verified": False, "permissions_verified": False,
        "pronunciation_assessed": False, "linguistic_mapping_assessed": False,
        "model_runtime_verified": False,
    })
    return report
