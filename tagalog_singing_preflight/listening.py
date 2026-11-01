"""Prepare local randomized comparisons without assessing singing quality."""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import pathlib
import random
import re
import struct
import wave

from tagalog_singing_preflight import benchmark


MAX_TRIALS = 64
MAX_WAV_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_SECONDS = 60
ATTRIBUTES = {
    "pronunciation": "Which version has more natural Tagalog pronunciation?",
    "phrasing": "Which version has more natural musical phrasing?",
    "artifacts": "Which version has fewer audible synthesis artifacts?",
}
LIMIT = (
    "Local comparison preparation only. No listening result, native reviewer "
    "competence, permission, pronunciation or singing quality is verified. "
    "Visible target text prevents an unprompted intelligibility measurement. "
    "Anonymous names and removed metadata do not guarantee auditory blinding. "
    "No ITU or MUSHRA conformance is claimed."
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


@dataclasses.dataclass(frozen=True)
class _Audio:
    source_path: str
    channels: int
    sample_width_bytes: int
    sample_rate_hz: int
    frame_count: int
    pcm: bytes
    input_sha256: str

    @property
    def clock(self) -> tuple[int, int, int, int]:
        return (self.channels, self.sample_width_bytes, self.sample_rate_hz,
                self.frame_count)


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a 1-64 character ASCII identifier.")
    return value


def _nonempty(value: object, field: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or len(value) > benchmark.MAX_TEXT_CHARS):
        raise ValueError(f"{field} must contain 1-4096 characters.")
    return value


def _wave_chunks(encoded: bytes) -> dict[bytes, bytes]:
    """Check RIFF chunks, including bytes hidden by a partial frame."""
    if (len(encoded) < 12 or encoded[:4] != b"RIFF"
            or encoded[8:12] != b"WAVE"
            or struct.unpack_from("<I", encoded, 4)[0] + 8 != len(encoded)):
        raise ValueError("WAV must be a complete ordinary RIFF/WAVE file.")
    chunks = {}
    offset = 12
    while offset < len(encoded):
        if offset + 8 > len(encoded):
            raise ValueError("WAV has a truncated chunk header.")
        tag, size = struct.unpack_from("<4sI", encoded, offset)
        start = offset + 8
        end = start + size
        if end > len(encoded):
            raise ValueError("WAV has a truncated chunk payload.")
        if tag in (b"fmt ", b"data"):
            if tag in chunks:
                raise ValueError("WAV must have one fmt and one data chunk.")
            chunks[tag] = encoded[start:end]
        offset = end + (size % 2)
        # wave.writeframes omits a final odd-data pad; accept that common form.
        if offset == len(encoded) + 1 and end == len(encoded):
            offset = end
    return chunks


def _read_audio(root: pathlib.Path, relative: object) -> tuple[_Audio, int]:
    name = _nonempty(relative, "clip.path")
    path = pathlib.Path(name)
    if path.is_absolute() or pathlib.PureWindowsPath(name).drive:
        raise ValueError("clip.path must be relative to the audio root.")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("clip.path must stay within the audio root.")
    with resolved.open("rb") as source:
        encoded = source.read(MAX_WAV_BYTES + 1)
    if len(encoded) > MAX_WAV_BYTES:
        raise ValueError("WAV exceeds the 32 MiB file limit.")
    chunks = _wave_chunks(encoded)
    format_chunk = chunks.get(b"fmt ", b"")
    if len(format_chunk) < 16 or b"data" not in chunks:
        raise ValueError("WAV needs complete fmt and data chunks.")
    tag, channels, rate, byte_rate, block, bits = struct.unpack_from(
        "<HHIIHH", format_chunk)
    if (tag != 1 or channels not in (1, 2) or bits not in (16, 24, 32)
            or not 8000 <= rate <= 96000):
        raise ValueError(
            "WAV requires ordinary PCM, 1-2 channels, 16/24/32 bits, "
            "and 8000-96000 Hz.")
    width = bits // 8
    if block != channels * width or byte_rate != rate * block:
        raise ValueError("WAV block alignment or byte rate is inconsistent.")
    payload = chunks[b"data"]
    if not payload or len(payload) % block:
        raise ValueError("WAV data must contain complete nonempty frames.")
    frames = len(payload) // block
    if frames > rate * MAX_SECONDS:
        raise ValueError("WAV exceeds the 60-second phrase limit.")
    try:
        with wave.open(io.BytesIO(encoded), "rb") as source:
            pcm = source.readframes(frames + 1)
            if source.getnframes() != frames or pcm != payload:
                raise ValueError(
                    "WAV declared frames do not match readable PCM.")
    except (wave.Error, EOFError, struct.error) as error:
        raise ValueError(f"Unreadable PCM WAV: {error}") from error
    return _Audio(
        path.as_posix(), channels, width, rate, frames, pcm,
        hashlib.sha256(encoded).hexdigest()), len(encoded)


def _validate_plan(manifest: object, plan: object) -> tuple[dict, dict, dict]:
    report = benchmark.audit_manifest(manifest)
    if report["status"] != "pass":
        raise ValueError("Benchmark manifest failed its contract audit.")
    if not isinstance(plan, dict):
        raise ValueError("Listening plan must be an object.")
    if (type(plan.get("schema_version")) is not int
            or plan["schema_version"] != 1):
        raise ValueError("Listening schema_version must be integer 1.")
    _identifier(plan.get("experiment_id"), "experiment_id")
    if plan.get("benchmark_id") != manifest["benchmark_id"]:
        raise ValueError("Listening benchmark_id must match the manifest.")
    if plan.get("split") not in benchmark.SPLITS:
        raise ValueError("Listening split must be development or held_out.")
    _nonempty(plan.get("permission_note"), "permission_note")
    conditions = plan.get("conditions")
    if not isinstance(conditions, list) or len(conditions) != 2:
        raise ValueError("Listening plan must declare exactly two conditions.")
    by_condition = {}
    for condition in conditions:
        if not isinstance(condition, dict):
            raise ValueError("Each condition must be an object.")
        identifier = _identifier(condition.get("id"), "condition.id")
        if (identifier in by_condition
                or condition.get("mode") not in ("svc", "svs", "synthetic")):
            raise ValueError(
                "Conditions need unique IDs and mode svc, svs or synthetic.")
        by_condition[identifier] = {
            "id": identifier, "mode": condition["mode"],
            "description": _nonempty(condition.get("description"),
                                     "condition.description"),
        }
    items = {item["id"]: item for item in manifest["items"]
             if item["split"] == plan["split"]}
    clips = plan.get("clips")
    if (not isinstance(clips, list) or not 2 <= len(clips) <= MAX_TRIALS * 2):
        raise ValueError("Listening clips must contain 1-64 complete pairs.")
    pairs = {}
    for clip in clips:
        if not isinstance(clip, dict):
            raise ValueError("Each clip must be an object.")
        item = _identifier(clip.get("item_id"), "clip.item_id")
        condition = _identifier(clip.get("condition_id"), "clip.condition_id")
        if item not in items or condition not in by_condition:
            raise ValueError(
                "Clip item or condition is outside the selected set.")
        pair = pairs.setdefault(item, {})
        if condition in pair:
            raise ValueError("Duplicate item/condition clip pair.")
        pair[condition] = _nonempty(clip.get("path"), "clip.path")
    if any(set(pair) != set(by_condition) for pair in pairs.values()):
        raise ValueError(
            "Every selected item needs a clip for both conditions.")
    return items, by_condition, pairs


def _canonical_wave(audio: _Audio) -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setnchannels(audio.channels)
        output.setsampwidth(audio.sample_width_bytes)
        output.setframerate(audio.sample_rate_hz)
        output.writeframes(audio.pcm)
    return target.getvalue()


def _write_json(path: pathlib.Path, value: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as target:
        json.dump(value, target, ensure_ascii=False, indent=2)
        target.write("\n")


def prepare_packet(
    manifest: object, plan: object, audio_root: pathlib.Path,
    output_dir: pathlib.Path, seed: int, attribute: str = "pronunciation",
) -> dict:
    """Create a new packet from complete matched PCM clips; never overwrite.

    Contracts and all source audio are validated before creating output_dir.
    A later write failure leaves the newly created partial directory for
    inspection and raises OSError. Inputs are never modified. Share only the
    listener subdirectory, under the applicable media permissions.
    """
    if type(seed) is not int or not 0 <= seed < 2 ** 63:
        raise ValueError("seed must be an integer from 0 through 2**63-1.")
    if not isinstance(attribute, str) or attribute not in ATTRIBUTES:
        raise ValueError(
            "attribute must be pronunciation, phrasing or artifacts.")
    items, conditions, pairs = _validate_plan(manifest, plan)
    root = pathlib.Path(audio_root).resolve()
    target = pathlib.Path(output_dir)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Output directory already exists: {target}")
    audio = {}
    total_bytes = 0
    for item, pair in pairs.items():
        audio[item] = {}
        for condition, path in pair.items():
            clip, size = _read_audio(root, path)
            total_bytes += size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("Listening WAV inputs exceed 256 MiB total.")
            audio[item][condition] = clip
        if len({clip.clock for clip in audio[item].values()}) != 1:
            raise ValueError(
                "Paired clips must have matching PCM clocks/formats.")
    generator = random.Random(seed)
    order = sorted(pairs)
    generator.shuffle(order)
    trials = []
    mappings = []
    target.mkdir()
    try:
        listener = target / "listener"
        listener.mkdir()
        for index, item in enumerate(order, 1):
            trial_id = f"trial-{index:03d}"
            condition_order = sorted(conditions)
            generator.shuffle(condition_order)
            trial = {"trial_id": trial_id, "text": items[item]["text"]}
            mapping = {
                "trial_id": trial_id, "item_id": item,
                "split": plan["split"],
                "review": {field: items[item]["review"][field] for field in (
                    "status", "reviewer_id", "reviewed_at",
                    "pronunciation_notes")},
                "versions": {},
            }
            for label, condition in zip(("A", "B"), condition_order):
                clip = audio[item][condition]
                filename = f"{trial_id}-{label}.wav"
                encoded = _canonical_wave(clip)
                with (listener / filename).open("xb") as output:
                    output.write(encoded)
                trial[label] = filename
                mapping["versions"][label] = {
                    "condition_id": condition, "source_path": clip.source_path,
                    "input_sha256": clip.input_sha256,
                    "output_sha256": hashlib.sha256(encoded).hexdigest(),
                    "pcm_sha256": hashlib.sha256(clip.pcm).hexdigest(),
                    "channels": clip.channels,
                    "sample_width_bytes": clip.sample_width_bytes,
                    "sample_rate_hz": clip.sample_rate_hz,
                    "frame_count": clip.frame_count,
                }
            trials.append(trial)
            mappings.append(mapping)
        _write_json(listener / "trials.json", {
            "schema_version": 1, "attribute": attribute,
            "question": ATTRIBUTES[attribute], "assessment_limit": LIMIT,
            "instructions": (
                "Listen to both complete versions in each trial, then enter A, "
                "B, tie or cannot_assess in responses.csv. Judge only the "
                "specified attribute in this pass. Note any uncertainty. "
                "Use native Tagalog listeners for language judgments. "
                "Keep playback conditions and volume consistent."),
            "native_review_verified": False, "trials": trials,
        })
        with (listener / "responses.csv").open(
                "x", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(("trial_id", "preference", "notes"))
            writer.writerows((trial["trial_id"], "", "") for trial in trials)
        _write_json(target / "operator-key.json", {
            "schema_version": 1, "experiment_id": plan["experiment_id"],
            "benchmark_id": plan["benchmark_id"], "split": plan["split"],
            "seed": seed, "attribute": attribute,
            "conditions": list(conditions.values()),
            "permission_note": plan["permission_note"],
            "permission_verified": False, "native_review_verified": False,
            "assessment_limit": LIMIT, "trials": mappings,
        })
    except (OSError, UnicodeError, ValueError, wave.Error) as error:
        raise OSError(
            f"Packet write failed; partial output remains at {target}: {error}"
        ) from error
    review_counts = dict.fromkeys(benchmark.REVIEW_STATUSES, 0)
    for item in pairs:
        review_counts[items[item]["review"]["status"]] += 1
    warnings = ["NATIVE_REVIEW_UNVERIFIED", "LISTENING_NOT_PERFORMED"]
    for status in ("pending", "needs_revision"):
        if review_counts[status]:
            warnings.append("NATIVE_REVIEW_" + status.upper())
    return {
        "schema_version": 1, "status": "pass", "trial_count": len(trials),
        "attribute": attribute, "native_review_verified": False,
        "permission_verified": False, "assessment_limit": LIMIT,
        "review_counts": review_counts, "warnings": warnings,
    }
