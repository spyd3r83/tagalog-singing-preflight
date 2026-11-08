"""Export checked mapped tokens through an explicit SoulX content-note plan."""

from __future__ import annotations

import pathlib

from tagalog_singing_preflight import phone_mapping
from tagalog_singing_preflight import soulx
from tagalog_singing_preflight import timing


_NOTE_FIELDS = {
    "occurrence_index", "token_start", "token_end", "duration",
    "note_pitch", "note_type",
}
_STRUCTURAL = {"<PAD>", "<BOW>", "<EOW>", "<SEP>", "<SP>", "<AP>"}
LIMIT = (
    "Explicit content-note spans and source-derived native metadata checks. "
    "Native tensor processing, checkpoint compatibility, linguistic alignment "
    "and singing quality remain unassessed."
)


def _native_phone(tokens: list[str], index: int) -> str:
    """Encode groups whose native expansion preserves the supplied tokens."""
    for token in tokens:
        if token in _STRUCTURAL or "<AP>" in token:
            raise ValueError(f"Note {index} contains a structural or rest "
                             "token.")
        if token.startswith("en_") and (
                not token[3:] or "-" in token[3:]):
            raise ValueError(f"Note {index} contains an ambiguous en_ token.")
    if len(tokens) == 1:
        return tokens[0]
    if not all(token.startswith("en_") for token in tokens):
        raise ValueError(f"Note {index} needs one token or an all-en_ group.")
    return "en_" + "-".join(token[3:] for token in tokens)


def _metadata(mapped: dict, note_plan: object) -> tuple[dict, list[dict]]:
    if (not isinstance(note_plan, dict)
            or note_plan.keys() != {"schema_version", "notes"}
            or type(note_plan["schema_version"]) is not int
            or note_plan["schema_version"] != 1):
        raise ValueError("Note plan needs exactly schema_version integer 1 "
                         "and notes.")
    notes = note_plan["notes"]
    if not isinstance(notes, list) or not 1 <= len(notes) <= timing.MAX_GROUPS:
        raise ValueError(f"notes must contain 1-{timing.MAX_GROUPS} records.")
    occurrences = mapped["mapped_occurrences"]
    occurrence_index = 0
    token_start = 0
    fields = {name: [] for name in ("phoneme", "duration", "note_pitch",
                                    "note_type")}
    assignments = []
    for index, note in enumerate(notes):
        if not isinstance(note, dict) or note.keys() != _NOTE_FIELDS:
            raise ValueError(f"Note {index} must contain the six note fields.")
        for name in ("occurrence_index", "token_start", "token_end",
                     "note_pitch", "note_type"):
            if type(note[name]) is not int:
                raise ValueError(f"Note {index} {name} must be an integer.")
        if (note["occurrence_index"] != occurrence_index
                or note["token_start"] != token_start
                or occurrence_index >= len(occurrences)):
            raise ValueError(f"Note {index} must continue the next uncovered "
                             "token in occurrence order.")
        occurrence = occurrences[occurrence_index]
        tokens = occurrence["target_tokens"]
        token_end = note["token_end"]
        if not token_start < token_end <= len(tokens):
            raise ValueError(f"Note {index} needs a nonempty bounded token "
                             "span.")
        duration = note["duration"]
        if (not isinstance(duration, str) or not duration
                or any(character.isspace() for character in duration)):
            raise ValueError(f"Note {index} duration must be a decimal string.")
        duration_value = timing.number(duration, f"Note {index} duration")
        if not duration_value:
            raise ValueError(f"Note {index} duration must be positive.")
        fields["phoneme"].append(_native_phone(tokens[token_start:token_end],
                                                index))
        fields["duration"].append(str(duration_value))
        fields["note_pitch"].append(str(note["note_pitch"]))
        fields["note_type"].append(str(note["note_type"]))
        assignments.append(dict(note))
        token_start = token_end
        if token_end == len(tokens):
            occurrence_index += 1
            token_start = 0
    if occurrence_index != len(occurrences):
        raise ValueError("Note plan leaves mapped tokens uncovered.")
    metadata = {name: " ".join(values) for name, values in fields.items()}
    metadata["text"] = mapped["original_text"]
    return metadata, assignments


def export_review(
    manifest: object,
    item_id: str,
    lexicon_path: pathlib.Path,
    edited_review: object,
    mapping: object,
    vocabulary: object,
    note_plan: object,
    *,
    source_label: str,
    data_license: str,
    expected_frames: int,
    sample_rate: int = 24000,
    hop_size: int = 480,
) -> dict:
    """Build audited native metadata from rechecked review and note spans.

    Args:
        manifest: Original benchmark manifest.
        item_id: Development item to export.
        lexicon_path: Local source pronunciation TSV.
        edited_review: Original review draft with complete declared decisions.
        mapping: Explicit IPA-to-target-token profile.
        vocabulary: Receiving frontend's declared token list.
        note_plan: Version 1 plan covering every mapped content token once.
        source_label: Caller-declared source and version of the lexicon.
        data_license: Caller-declared lexicon data terms.
        expected_frames: Required positive output frame count.
        sample_rate: Native processor sample rate.
        hop_size: Samples per frame for the native processor.

    Returns:
        Native metadata, original note assignments and the passing audit.

    Raises:
        ValueError: Sources, mapping, spans, encoding or native audit fail.
        OSError: Source lexicon cannot be read.
        UnicodeError: Source lexicon is not UTF-8.
    """
    mapped = phone_mapping.map_review(
        manifest, item_id, lexicon_path, edited_review, mapping, vocabulary,
        source_label=source_label, data_license=data_license)
    metadata, assignments = _metadata(mapped, note_plan)
    checked = soulx.audit_metadata(metadata, vocabulary, expected_frames,
                                    sample_rate, hop_size)
    if checked["status"] != "pass":
        codes = ", ".join(error["code"] for error in checked["errors"])
        raise ValueError(f"Native metadata audit failed: {codes}.")
    return {
        "schema_version": 1, "status": "pass", "assessment_limit": LIMIT,
        "benchmark_id": mapped["benchmark_id"], "item_id": mapped["item_id"],
        "mapping_id": mapped["mapping_id"],
        "target_model": mapped["target_model"],
        "source_declaration": mapped["source_declaration"],
        "metadata": metadata, "note_assignments": assignments, "audit": checked,
        "upstream_commit": soulx.UPSTREAM_COMMIT,
        "native_processor_executed": False, "model_runtime_verified": False,
        "pronunciation_assessed": False, "native_review_verified": False,
        "permissions_verified": False,
    }
