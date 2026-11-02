"""Tally declared listening responses against a supplied local packet key."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import pathlib
import re

from tagalog_singing_preflight import benchmark
from tagalog_singing_preflight import listening


MAX_JSON_BYTES = 1024 * 1024
MAX_CSV_BYTES = 1024 * 1024
PREFERENCES = ("A", "B", "tie", "cannot_assess", "")
LIMIT = (
    "Single-packet declared response counts only, not a quality score or "
    "winner. Current audio bytes match the supplied operator key; key "
    "authenticity, the packet actually heard, human listening, listener "
    "competence, native review, permissions and singing quality are not "
    "verified. Version 1 CSV trial IDs do not identify their originating "
    "packet; retain each response file with its original packet."
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_TRIAL_ID = re.compile(r"trial-([0-9]{3})\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a 1-64 character ASCII identifier.")
    return value


def _packet_path(root: pathlib.Path, name: str) -> pathlib.Path:
    resolved = (root / name).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Packet files must stay within the packet directory.")
    return resolved


def _read_bytes(path: pathlib.Path, maximum: int) -> bytes:
    with path.open("rb") as source:
        encoded = source.read(maximum + 1)
    if len(encoded) > maximum:
        raise ValueError(f"Input file exceeds its {maximum}-byte limit.")
    return encoded


def _load_object(path: pathlib.Path) -> dict:
    value = json.loads(_read_bytes(path, MAX_JSON_BYTES).decode("utf-8-sig"))
    if (not isinstance(value, dict)
            or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1):
        raise ValueError("Packet JSON must be an object with schema_version 1.")
    return value


def _trial_map(value: object) -> dict[str, dict]:
    if (not isinstance(value, list)
            or not 1 <= len(value) <= listening.MAX_TRIALS):
        raise ValueError("Packet trials must contain 1-64 records.")
    result = {}
    for trial in value:
        if not isinstance(trial, dict):
            raise ValueError("Each packet trial must be an object.")
        identifier = trial.get("trial_id")
        match = _TRIAL_ID.fullmatch(identifier) if isinstance(
            identifier, str) else None
        if (match is None or not 1 <= int(match[1]) <= listening.MAX_TRIALS
                or identifier in result):
            raise ValueError("Packet trial IDs must be unique trial-001..064.")
        result[identifier] = trial
    return result


def _packet_records(key: dict, listener: dict) -> tuple[dict, dict, dict]:
    """Validate mapping fields without trusting declared approval."""
    for field in ("experiment_id", "benchmark_id"):
        _identifier(key.get(field), field)
    split = key.get("split")
    attribute = key.get("attribute")
    if not isinstance(split, str) or split not in benchmark.SPLITS:
        raise ValueError("Packet split must be development or held_out.")
    if (not isinstance(attribute, str) or attribute not in listening.ATTRIBUTES
            or attribute != listener.get("attribute")):
        raise ValueError("Packet key and listener attributes must match.")
    conditions = key.get("conditions")
    if not isinstance(conditions, list) or len(conditions) != 2:
        raise ValueError("Packet needs exactly two distinct conditions.")
    condition_modes = {}
    for condition in conditions:
        if not isinstance(condition, dict):
            raise ValueError("Each packet condition must be an object.")
        identifier = _identifier(condition.get("id"), "condition.id")
        mode = condition.get("mode")
        if (identifier in condition_modes or not isinstance(mode, str)
                or mode not in ("svc", "svs", "synthetic")):
            raise ValueError("Conditions need unique IDs and supported modes.")
        condition_modes[identifier] = mode
    mappings = _trial_map(key.get("trials"))
    trials = _trial_map(listener.get("trials"))
    if set(mappings) != set(trials):
        raise ValueError("Packet key and listener trial IDs must match.")
    items = set()
    for identifier, mapping in mappings.items():
        item = _identifier(mapping.get("item_id"), "item_id")
        if item in items or mapping.get("split") != split:
            raise ValueError("Packet item IDs must be unique in one split.")
        items.add(item)
        review = mapping.get("review")
        if (not isinstance(review, dict)
                or not isinstance(review.get("status"), str)
                or review["status"] not in benchmark.REVIEW_STATUSES):
            raise ValueError("Packet needs a supported declared review status.")
        versions = mapping.get("versions")
        if not isinstance(versions, dict) or set(versions) != {"A", "B"}:
            raise ValueError("Packet mappings must contain A and B versions.")
        mapped_conditions = set()
        for label in ("A", "B"):
            if trials[identifier].get(label) != f"{identifier}-{label}.wav":
                raise ValueError("Packet audio names must match trial IDs.")
            version = versions[label]
            if not isinstance(version, dict):
                raise ValueError("Each mapped version must be an object.")
            condition = _identifier(version.get("condition_id"),
                                    "version.condition_id")
            mapped_conditions.add(condition)
            digest = version.get("output_sha256")
            if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
                raise ValueError(
                    "Mapped audio needs a lowercase SHA-256 digest.")
        if mapped_conditions != set(condition_modes):
            raise ValueError("Each trial must map both distinct conditions.")
    return condition_modes, mappings, trials


def _verify_audio(root: pathlib.Path, mappings: dict, trials: dict) -> None:
    """Check bounded current bytes against the key, without asserting origin."""
    listener = _packet_path(root, "listener")
    total = 0
    for identifier, trial in trials.items():
        for label in ("A", "B"):
            path = _packet_path(listener, trial[label])
            encoded = _read_bytes(path, listening.MAX_WAV_BYTES)
            total += len(encoded)
            if total > listening.MAX_TOTAL_BYTES:
                raise ValueError("Packet WAV files exceed 256 MiB total.")
            expected = mappings[identifier]["versions"][label]["output_sha256"]
            if hashlib.sha256(encoded).hexdigest() != expected:
                raise ValueError(
                    f"Audio bytes do not match key for {identifier} {label}.")


def _read_responses(path: pathlib.Path, trial_ids: set[str]) -> dict[str, str]:
    """Read CSV cells; keep absent rows separate from blank preferences."""
    encoded = _read_bytes(path, MAX_CSV_BYTES).decode("utf-8-sig")
    result = {}
    try:
        reader = csv.reader(io.StringIO(encoded, newline=""), strict=True)
        if next(reader, None) != ["trial_id", "preference", "notes"]:
            raise ValueError("CSV header must be trial_id,preference,notes.")
        for index, row in enumerate(reader, 1):
            if index > listening.MAX_TRIALS or len(row) != 3:
                raise ValueError(
                    "CSV needs at most 64 rows with exactly 3 cells.")
            identifier, preference, notes = row
            if identifier not in trial_ids or identifier in result:
                raise ValueError("CSV trial IDs must be known and unique.")
            if preference not in PREFERENCES:
                raise ValueError(
                    "Preference must be A, B, tie, cannot_assess or blank.")
            if len(notes) > benchmark.MAX_TEXT_CHARS:
                raise ValueError("CSV notes must be at most 4096 characters.")
            result[identifier] = preference
    except csv.Error as error:
        raise ValueError(f"Malformed response CSV: {error}") from error
    return result


def summarize_packet(
    packet_dir: pathlib.Path, responses_path: pathlib.Path, listener_id: str,
) -> dict:
    """Return single-packet declared preference counts without modifying files.

    Args:
        packet_dir: Local v1 packet containing its key and listener directory.
        responses_path: UTF-8 response CSV retained with its original packet.
        listener_id: Caller-supplied opaque identifier, not verified identity.

    Returns:
        A JSON-compatible mechanical report. Missing and blank answers remain
        distinct; complete coverage does not establish listening or quality.

    Raises:
        ValueError: Packet, audio identity, CSV, or resource contracts fail.
        OSError: An input file cannot be read.
    """
    _identifier(listener_id, "listener_id")
    root = pathlib.Path(packet_dir).resolve()
    key = _load_object(_packet_path(root, "operator-key.json"))
    listener = _load_object(_packet_path(root, "listener/trials.json"))
    modes, mappings, trials = _packet_records(key, listener)
    _verify_audio(root, mappings, trials)
    records = _read_responses(pathlib.Path(responses_path), set(trials))
    preferences = dict.fromkeys(modes, 0)
    ties = cannot_assess = 0
    blank = []
    for identifier, preference in records.items():
        if preference in ("A", "B"):
            version = mappings[identifier]["versions"][preference]
            condition = version["condition_id"]
            preferences[condition] += 1
        elif preference == "tie":
            ties += 1
        elif preference == "cannot_assess":
            cannot_assess += 1
        else:
            blank.append(identifier)
    missing = sorted(set(trials) - set(records))
    reviews = dict.fromkeys(benchmark.REVIEW_STATUSES, 0)
    for mapping in mappings.values():
        reviews[mapping["review"]["status"]] += 1
    warnings = ["LISTENING_UNVERIFIED", "RESPONSE_PACKET_BINDING_UNVERIFIED"]
    for status in ("pending", "needs_revision"):
        if reviews[status]:
            warnings.append("NATIVE_REVIEW_" + status.upper())
    if blank or missing:
        warnings.append("RESPONSES_INCOMPLETE")
    return {
        "schema_version": 1, "status": "pass", "assessment_limit": LIMIT,
        "experiment_id": key["experiment_id"],
        "benchmark_id": key["benchmark_id"], "split": key["split"],
        "attribute": key["attribute"], "listener_id": listener_id,
        "condition_modes": modes, "condition_preferences": preferences,
        "trial_count": len(trials), "response_rows": len(records),
        "answered_trials": len(records) - len(blank),
        "ties": ties, "cannot_assess": cannot_assess,
        "blank_trial_ids": sorted(blank), "missing_row_trial_ids": missing,
        "responses_complete": not (blank or missing),
        "declared_review_counts": reviews, "audio_matches_key": True,
        "native_review_verified": False, "permission_verified": False,
        "listening_performed_verified": False,
        "response_packet_binding_verified": False, "warnings": warnings,
    }
