"""Audit benchmark structure without verifying language or reviewers."""

from __future__ import annotations

import datetime
import re
import unicodedata


MAX_ITEMS = 10_000
MAX_TEXT_CHARS = 4096
FOCUS_TAGS = (
    "lexical_stress", "glottal_stop", "velar_nasal", "vowel_sequence",
    "contraction", "connected_phrase", "sustained_vowel",
)
SPLITS = ("development", "held_out")
REVIEW_STATUSES = ("pending", "approved", "needs_revision")
LIMIT = (
    "Manifest structure and declared records only. Native reviewer competence, "
    "pronunciation, singing quality, text originality, licensing and model "
    "training contamination are not verified. Public held-out items are not "
    "secret or guaranteed unseen."
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_REVIEW_FIELDS = (
    "status", "reviewer_id", "reviewed_at", "pronunciation_notes",
)


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(
            f"{field} must be 1-64 ASCII letters, digits, underscores, dots "
            "or hyphens, beginning with a letter or digit.")
    return value


def _text_key(value: object) -> str:
    if (not isinstance(value, str) or not value.strip()
            or len(value) > MAX_TEXT_CHARS):
        raise ValueError(f"text must contain 1-{MAX_TEXT_CHARS} characters.")
    normalized = unicodedata.normalize(
        "NFC", unicodedata.normalize("NFC", value).casefold())
    key = "".join(character for character in normalized
                  if not character.isspace()
                  and not unicodedata.category(character).startswith("P"))
    if not key:
        raise ValueError("text must contain more than punctuation/whitespace.")
    return key


def _review_status(review: object) -> str:
    if not isinstance(review, dict) or any(
            field not in review for field in _REVIEW_FIELDS):
        raise ValueError("review must contain all four review fields.")
    status = review["status"]
    if not isinstance(status, str) or status not in REVIEW_STATUSES:
        raise ValueError("review.status must be a declared review status.")
    if status == "pending":
        if any(review[field] is not None for field in _REVIEW_FIELDS[1:]):
            raise ValueError("Pending review record fields must be null.")
        return status
    _identifier(review["reviewer_id"], "review.reviewer_id")
    date = review["reviewed_at"]
    if not isinstance(date, str):
        raise ValueError("review.reviewed_at must be YYYY-MM-DD.")
    try:
        parsed = datetime.date.fromisoformat(date)
    except ValueError as error:
        raise ValueError("review.reviewed_at must be YYYY-MM-DD.") from error
    if parsed.isoformat() != date:
        raise ValueError("review.reviewed_at must be YYYY-MM-DD.")
    notes = review["pronunciation_notes"]
    if (not isinstance(notes, str) or not notes.strip()
            or len(notes) > MAX_TEXT_CHARS):
        raise ValueError(
            "Reviewed pronunciation_notes must be a nonempty bounded string.")
    return status


def _item_fields(item: object) -> tuple[str, str, str, list[str], str]:
    if not isinstance(item, dict):
        raise ValueError("Each item must be an object.")
    identifier = _identifier(item.get("id"), "id")
    split = item.get("split")
    if not isinstance(split, str) or split not in SPLITS:
        raise ValueError("split must be development or held_out.")
    key = _text_key(item.get("text"))
    focus = item.get("focus")
    if (not isinstance(focus, list) or not focus or len(focus) > len(FOCUS_TAGS)
            or any(not isinstance(tag, str) or tag not in FOCUS_TAGS
                   for tag in focus) or len(set(focus)) != len(focus)):
        raise ValueError("focus must contain unique supported focus tags.")
    return identifier, split, key, focus, _review_status(item.get("review"))


def audit_manifest(manifest: object) -> dict:
    """Return bounded manifest diagnostics without changing the caller's data.

    A pass validates records and the documented cross-split text comparison;
    it does not certify native review, pronunciation or evaluation readiness.
    """
    report = {
        "schema_version": 1, "status": "fail", "errors": [], "warnings": [],
        "assessment_limit": LIMIT, "native_review_verified": False,
        "split_counts": dict.fromkeys(SPLITS, 0),
        "focus_counts": dict.fromkeys(FOCUS_TAGS, 0),
        "review_counts": dict.fromkeys(REVIEW_STATUSES, 0),
        "pending_item_ids": [], "needs_revision_item_ids": [],
    }
    try:
        if not isinstance(manifest, dict):
            raise ValueError("Manifest must be an object.")
        if (type(manifest.get("schema_version")) is not int
                or manifest["schema_version"] != 1):
            raise ValueError("schema_version must be integer 1.")
        report["benchmark_id"] = _identifier(
            manifest.get("benchmark_id"), "benchmark_id")
        if (manifest.get("language") != "tl"
                or manifest.get("text_origin") != "original_authored"
                or manifest.get("license") != "MIT"):
            raise ValueError(
                "This profile requires language tl, text_origin "
                "original_authored and license MIT as declared metadata.")
        items = manifest.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
            raise ValueError(f"items must contain 1-{MAX_ITEMS} records.")
    except ValueError as error:
        report["errors"].append({"code": "MANIFEST", "message": str(error)})
        return report

    report["item_count"] = len(items)
    identifiers = {}
    text_splits = {}
    for index, item in enumerate(items):
        try:
            identifier, split, key, focus, review = _item_fields(item)
        except ValueError as error:
            report["errors"].append({
                "code": "ITEM", "item_index": index, "message": str(error)})
            continue
        if identifier in identifiers:
            report["errors"].append({
                "code": "DUPLICATE_ID", "item_index": index,
                "first_item_index": identifiers[identifier],
                "item_id": identifier,
            })
        else:
            identifiers[identifier] = index
        by_split = text_splits.setdefault(key, {})
        for other_split, other_id in by_split.items():
            if other_split != split:
                report["errors"].append({
                    "code": "SPLIT_OVERLAP", "item_index": index,
                    "item_ids": [other_id, identifier],
                    "message": "Normalized text appears in both splits.",
                })
        by_split.setdefault(split, identifier)
        report["split_counts"][split] += 1
        report["review_counts"][review] += 1
        for tag in focus:
            report["focus_counts"][tag] += 1
        if review in ("pending", "needs_revision"):
            report[f"{review}_item_ids"].append(identifier)
    if not all(report["split_counts"].values()):
        report["errors"].append({
            "code": "MISSING_SPLIT",
            "message": "Both development and held_out need valid records.",
        })
    for status in ("pending", "needs_revision"):
        if report["review_counts"][status]:
            report["warnings"].append({
                "code": "NATIVE_REVIEW_" + status.upper(),
                "item_ids": report[f"{status}_item_ids"],
                "message": "Declared review status does not verify language.",
            })
    if not report["errors"]:
        report["status"] = "pass"
    return report
