"""Exercise listening packets using original synthetic PCM, never songs."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import wave

from tagalog_singing_preflight import listening


ROOT = pathlib.Path(__file__).resolve().parents[1]


def sample_manifest() -> dict:
    items = []
    for identifier, split, text in (
            ("dev-01", "development", "Si Ana’y aawit."),
            ("dev-02", "development", "May bagong araw."),
            ("dev-03", "development", "Dahan-dahan ang bangka."),
            ("held-01", "held_out", "Bukas ang maliit na pinto.")):
        items.append({
            "id": identifier, "split": split, "text": text,
            "focus": ["connected_phrase"],
            "review": {"status": "pending", "reviewer_id": None,
                       "reviewed_at": None, "pronunciation_notes": None},
        })
    return {
        "schema_version": 1, "benchmark_id": "packet-test-v1",
        "language": "tl", "text_origin": "original_authored", "license": "MIT",
        "items": items,
    }


def wave_bytes(
    channels: int = 1, width: int = 2, rate: int = 24000,
    frames: int = 240, value: int = 100,
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        sample = value.to_bytes(width, byteorder="little", signed=True)
        output.writeframes(sample * channels * frames)
    return buffer.getvalue()


def with_metadata(encoded: bytes) -> bytes:
    # A valid LIST chunk models source/condition information to remove.
    metadata = b"INFOsource-secret-condition-baseline\x00"
    chunk = b"LIST" + struct.pack("<I", len(metadata)) + metadata
    chunk += b"\x00" * (len(metadata) % 2)
    modified = encoded[:36] + chunk + encoded[36:]
    return modified[:4] + struct.pack("<I", len(modified) - 8) + modified[8:]


class _ListeningFixture:

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.output = self.root / "packet"
        self.manifest = sample_manifest()
        self.plan = {
            "schema_version": 1, "experiment_id": "secret-experiment",
            "benchmark_id": "packet-test-v1", "split": "development",
            "permission_note": "Original synthetic PCM made for this test.",
            "conditions": [
                {"id": "secret-baseline", "mode": "synthetic",
                 "description": "Original low constant PCM fixture."},
                {"id": "secret-candidate", "mode": "synthetic",
                 "description": "Original different constant PCM fixture."},
            ], "clips": [],
        }
        for item in self.manifest["items"]:
            for index, condition in enumerate(self.plan["conditions"]):
                path = f"{item['id']}-{condition['id']}.wav"
                (self.root / path).write_bytes(with_metadata(
                    wave_bytes(value=100 + index)))
                if item["split"] == "development":
                    self.plan["clips"].append({
                        "item_id": item["id"], "condition_id": condition["id"],
                        "path": path,
                    })

    def prepare(self, **kwargs) -> dict:
        return listening.prepare_packet(
            kwargs.get("manifest", self.manifest),
            kwargs.get("plan", self.plan), self.root,
            kwargs.get("output", self.output), kwargs.get("seed", 17),
            kwargs.get("attribute", "pronunciation"))

    def assert_rejected(self, **kwargs):
        with self.assertRaises((ValueError, OSError)):
            self.prepare(**kwargs)
        self.assertFalse(self.output.exists())

    def packet_files(self, path: pathlib.Path) -> dict:
        return {str(file.relative_to(path)): file.read_bytes()
                for file in path.rglob("*") if file.is_file()}


class ListeningTest(_ListeningFixture, unittest.TestCase):

    def test_packet_preserves_pcm_and_separates_operator_identity(self):
        original = copy.deepcopy((self.manifest, self.plan))
        sources = {path.name: path.read_bytes()
                   for path in self.root.glob("*.wav")}
        report = self.prepare()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["trial_count"], 3)
        self.assertFalse(report["native_review_verified"])
        self.assertFalse(report["permission_verified"])
        self.assertIn("NATIVE_REVIEW_PENDING", report["warnings"])
        listener = self.output / "listener"
        trials = json.loads((listener / "trials.json").read_text("utf-8"))
        key = json.loads((self.output / "operator-key.json").read_text("utf-8"))
        listener_bytes = b"".join(self.packet_files(listener).values())
        for forbidden in (b"secret", b"dev-01", b"development", b'"seed"',
                          b'"review"', b'"source_path"', b"LIST"):
            self.assertNotIn(forbidden, listener_bytes)
        self.assertEqual(key["seed"], 17)
        self.assertEqual(len(trials["trials"]), 3)
        for trial, mapping in zip(trials["trials"], key["trials"]):
            self.assertEqual(trial["trial_id"], mapping["trial_id"])
            self.assertEqual(mapping["review"]["status"], "pending")
            for label in ("A", "B"):
                version = mapping["versions"][label]
                target = listener / trial[label]
                with wave.open(str(target), "rb") as output:
                    pcm = output.readframes(output.getnframes() + 1)
                    self.assertEqual(output.getnframes(), 240)
                    self.assertEqual(output.getframerate(), 24000)
                self.assertEqual(hashlib.sha256(pcm).hexdigest(),
                                 version["pcm_sha256"])
                with wave.open(io.BytesIO(sources[version["source_path"]]),
                               "rb") as source:
                    self.assertEqual(pcm, source.readframes(241))
                self.assertEqual(
                    hashlib.sha256(target.read_bytes()).hexdigest(),
                    version["output_sha256"])
        self.assertEqual((self.manifest, self.plan), original)
        self.assertEqual(sources, {
            path.name: path.read_bytes() for path in self.root.glob("*.wav")})

    def test_single_attribute_and_empty_response_rows(self):
        self.prepare(attribute="phrasing")
        listener = self.output / "listener"
        trials = json.loads((listener / "trials.json").read_text("utf-8"))
        self.assertEqual(trials["attribute"], "phrasing")
        self.assertIn("musical phrasing", trials["question"])
        with (listener / "responses.csv").open(
                encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["preference"] == row["notes"] == ""
                            for row in rows))
        self.assertEqual(set(rows[0]), {"trial_id", "preference", "notes"})

    def test_seed_reproduces_packet_and_other_seeds_change_mapping(self):
        self.prepare()
        other = self.root / "repeat"
        self.prepare(output=other)
        self.assertEqual(self.packet_files(self.output),
                         self.packet_files(other))
        variants = set()
        for seed in range(4):
            target = self.root / f"seed-{seed}"
            self.prepare(output=target, seed=seed)
            key = json.loads((target / "operator-key.json").read_text("utf-8"))
            variants.add(tuple((trial["item_id"],
                                trial["versions"]["A"]["condition_id"])
                               for trial in key["trials"]))
        self.assertGreater(len(variants), 1)

    def test_held_out_subset_and_declared_revision_remain_unverified(self):
        self.plan["split"] = "held_out"
        self.plan["clips"] = [{
            "item_id": "held-01", "condition_id": condition["id"],
            "path": f"held-01-{condition['id']}.wav",
        } for condition in self.plan["conditions"]]
        self.manifest["items"][-1]["review"] = {
            "status": "needs_revision", "reviewer_id": "declared-01",
            "reviewed_at": "2026-11-01", "pronunciation_notes": "Test record.",
        }
        report = self.prepare()
        self.assertEqual(report["trial_count"], 1)
        self.assertIn("NATIVE_REVIEW_NEEDS_REVISION", report["warnings"])
        self.assertFalse(report["native_review_verified"])

    def test_existing_output_and_inputs_are_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("Preserve existing work.", encoding="utf-8")
        original = sentinel.read_bytes()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(sentinel.read_bytes(), original)
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_invalid_headers_manifest_seed_and_attribute_create_no_output(self):
        for change in ({"schema_version": True}, {"benchmark_id": "wrong"},
                       {"split": []}, {"conditions": []},
                       {"permission_note": " "}, {"experiment_id": "bad id"}):
            with self.subTest(change=change):
                self.assert_rejected(plan={**self.plan, **change})
        for seed in (True, -1, 2 ** 63, 1.0, None):
            with self.subTest(seed=seed):
                self.assert_rejected(seed=seed)
        self.assert_rejected(attribute="quality")
        self.assert_rejected(manifest={})

    def test_duplicate_missing_unknown_and_wrong_split_pairs_fail(self):
        clips = self.plan["clips"]
        variants = [clips[:-1], clips + [clips[0]], [],
                    [{**clips[0], "item_id": "held-01"}, *clips[1:]],
                    [{**clips[0], "condition_id": "unknown"}, *clips[1:]]]
        for variant in variants:
            with self.subTest(variant=variant):
                self.assert_rejected(plan={**self.plan, "clips": variant})

    def test_absolute_and_traversing_clip_paths_fail(self):
        for path in ("../outside.wav", str(self.root / "outside.wav"),
                     "C:/outside.wav", "missing.wav"):
            with self.subTest(path=path):
                plan = copy.deepcopy(self.plan)
                plan["clips"][0]["path"] = path
                self.assert_rejected(plan=plan)

    def test_symlink_escape_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            outside = pathlib.Path(temporary) / "outside.wav"
            outside.write_bytes(wave_bytes())
            link = self.root / "link.wav"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("Symlink creation unavailable to this account.")
            self.plan["clips"][0]["path"] = "link.wav"
            self.assert_rejected()

    def test_mismatched_pair_clock_or_format_fails(self):
        path = self.root / self.plan["clips"][0]["path"]
        for parameters in ({"frames": 239}, {"rate": 22050},
                           {"width": 3}, {"channels": 2}):
            with self.subTest(parameters=parameters):
                path.write_bytes(wave_bytes(**parameters))
                self.assert_rejected()

    def test_truncated_partial_empty_and_unsupported_wav_fail(self):
        path = self.root / self.plan["clips"][0]["path"]
        original = wave_bytes()
        partial = original[:4] + struct.pack("<I", len(original) - 9)
        partial += original[8:40] + struct.pack("<I", 479) + original[44:-1]
        float_format = bytearray(original)
        struct.pack_into("<H", float_format, 20, 3)
        variants = (original[:-20], partial, wave_bytes(frames=0),
                    bytes(float_format), b"not WAV", wave_bytes(width=1),
                    wave_bytes(rate=7999), wave_bytes(channels=3))
        for encoded in variants:
            with self.subTest(size=len(encoded)):
                path.write_bytes(encoded)
                self.assert_rejected()

    def test_supported_pcm_widths_and_silence_are_preserved(self):
        for width in (2, 3, 4):
            for clip in self.plan["clips"]:
                (self.root / clip["path"]).write_bytes(
                    wave_bytes(channels=2, width=width, value=0))
            target = self.root / f"width-{width}"
            self.prepare(output=target)
            with wave.open(str(target / "listener/trial-001-A.wav"), "rb") as f:
                self.assertEqual(f.getsampwidth(), width)
                self.assertEqual(f.getnchannels(), 2)
                self.assertEqual(f.readframes(241), b"\x00" * (240 * width * 2))

    def test_resource_bounds_are_enforced_before_output(self):
        with mock.patch.object(listening, "MAX_TRIALS", 2):
            self.assert_rejected()
        with mock.patch.object(listening, "MAX_WAV_BYTES", 128):
            self.assert_rejected()
        with mock.patch.object(listening, "MAX_TOTAL_BYTES", 1024):
            self.assert_rejected()
        with mock.patch.object(listening, "MAX_SECONDS", 0):
            self.assert_rejected()

    def test_write_failure_reports_retained_partial_directory(self):
        with mock.patch.object(listening, "_write_json",
                               side_effect=OSError("simulated disk failure")):
            with self.assertRaisesRegex(OSError, "partial output remains"):
                self.prepare()
        self.assertTrue((self.output / "listener").is_dir())
        self.assertFalse((self.output / "operator-key.json").exists())


class ListeningCommandLineTest(_ListeningFixture, unittest.TestCase):

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess:
        manifest = self.root / "manifest.json"
        plan = self.root / "plan.json"
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        plan.write_text(json.dumps(self.plan), encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-S", "-m", "tagalog_singing_preflight",
             "listening", str(manifest), str(plan), str(self.output),
             *arguments],
            cwd=ROOT, capture_output=True, encoding="utf-8", timeout=15,
            check=False)

    def test_cli_success_existing_directory_and_invalid_inputs(self):
        result = self.run_cli("--seed", "23", "--attribute", "artifacts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["attribute"], "artifacts")
        again = self.run_cli("--seed", "23")
        self.assertEqual(again.returncode, 2)
        self.assertIn("already exists", again.stderr)

    def test_cli_contract_error_and_required_seed_are_two(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())
        self.plan["clips"].pop()
        result = self.run_cli("--seed", "0")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["status"], "error")
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
