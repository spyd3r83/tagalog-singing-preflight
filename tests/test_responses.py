"""Exercise declared response tallies with original synthetic PCM only."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import wave

from tagalog_singing_preflight import listening
from tagalog_singing_preflight import responses


ROOT = pathlib.Path(__file__).resolve().parents[1]


class _ResponseFixture:

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        manifest = ROOT / "data/tagalog-benchmark-v1.json"
        self.manifest = json.loads(manifest.read_text(encoding="utf-8"))
        development = [item for item in self.manifest["items"]
                       if item["split"] == "development"][:4]
        self.held = next(item for item in self.manifest["items"]
                         if item["split"] == "held_out")
        self.plan = {
            "schema_version": 1, "experiment_id": "synthetic-responses",
            "benchmark_id": self.manifest["benchmark_id"],
            "split": "development", "permission_note": "Original test PCM.",
            "conditions": [
                {"id": "low", "mode": "synthetic", "description": "Test PCM."},
                {"id": "high", "mode": "synthetic", "description": "Test PCM."},
            ], "clips": [],
        }
        for item in [*development, self.held]:
            for index, condition in enumerate(self.plan["conditions"]):
                name = f"{item['id']}-{condition['id']}.wav"
                with wave.open(str(self.root / name), "wb") as output:
                    output.setparams((1, 2, 8000, 80, "NONE", "not compressed"))
                    output.writeframes((100 + index).to_bytes(2, "little") * 80)
                if item in development:
                    self.plan["clips"].append({
                        "item_id": item["id"], "condition_id": condition["id"],
                        "path": name,
                    })
        self.packet = self.root / "packet"
        self.prepare(self.packet, 17)
        self.csv_path = self.root / "answers.csv"
        self.write_rows([("trial-001", "A", "Private note omitted."),
                         ("trial-002", "tie", ""),
                         ("trial-003", "cannot_assess", ""),
                         ("trial-004", "", "")])

    def prepare(self, target: pathlib.Path, seed: int) -> None:
        listening.prepare_packet(self.manifest, self.plan, self.root,
                                 target, seed)

    def write_rows(self, rows: list[tuple[str, str, str]]) -> None:
        with self.csv_path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.writer(target)
            writer.writerow(("trial_id", "preference", "notes"))
            writer.writerows(rows)

    def summarize(self, packet: pathlib.Path | None = None) -> dict:
        return responses.summarize_packet(
            packet or self.packet, self.csv_path, "listener-test")

    def key(self) -> dict:
        path = self.packet / "operator-key.json"
        return json.loads(path.read_text("utf-8"))

    def change_key(self, key: dict) -> None:
        (self.packet / "operator-key.json").write_text(
            json.dumps(key), encoding="utf-8")


class ResponsesTest(_ResponseFixture, unittest.TestCase):

    def test_remaps_preferences_with_separate_abstentions_and_limits(self):
        report = self.summarize()
        key = self.key()
        selected = key["trials"][0]["versions"]["A"]["condition_id"]
        self.assertEqual(report["condition_preferences"][selected], 1)
        self.assertEqual(sum(report["condition_preferences"].values()), 1)
        self.assertEqual((report["trial_count"], report["response_rows"],
                          report["answered_trials"]), (4, 4, 3))
        self.assertEqual((report["ties"], report["cannot_assess"]), (1, 1))
        self.assertEqual(report["blank_trial_ids"], ["trial-004"])
        self.assertEqual(report["missing_row_trial_ids"], [])
        self.assertFalse(report["responses_complete"])
        self.assertTrue(report["audio_matches_key"])
        self.assertEqual(report["declared_review_counts"]["pending"], 4)
        for field in ("native_review_verified", "permission_verified",
                      "listening_performed_verified",
                      "response_packet_binding_verified"):
            self.assertFalse(report[field])
        serialized = json.dumps(report)
        for private in ("Private note omitted", "source_path", "reviewer_id",
                        "pronunciation_notes"):
            self.assertNotIn(private, serialized)

    def test_blank_and_missing_rows_do_not_invent_answers(self):
        self.write_rows([("trial-001", "", "")])
        report = self.summarize()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["answered_trials"], 0)
        self.assertEqual(report["blank_trial_ids"], ["trial-001"])
        self.assertEqual(report["missing_row_trial_ids"],
                         ["trial-002", "trial-003", "trial-004"])
        self.write_rows([])
        self.assertEqual(self.summarize()["response_rows"], 0)
        self.assertFalse(self.summarize()["responses_complete"])

    def test_same_condition_can_win_from_opposite_randomized_labels(self):
        labels = set()
        for seed in range(4):
            packet = self.root / f"seed-{seed}"
            self.prepare(packet, seed)
            key = json.loads((packet / "operator-key.json").read_text("utf-8"))
            rows = []
            for trial in key["trials"]:
                versions = trial["versions"].items()
                label = next(label for label, version in versions
                             if version["condition_id"] == "high")
                labels.add(label)
                rows.append((trial["trial_id"], label, "Synthetic entry."))
            self.write_rows(rows)
            report = self.summarize(packet)
            self.assertEqual(report["condition_preferences"],
                             {"high": 4, "low": 0})
            self.assertTrue(report["responses_complete"])
        self.assertEqual(labels, {"A", "B"})

    def test_v1_csv_from_another_seed_remains_unauthenticated(self):
        other = self.root / "other-session"
        self.prepare(other, 19)
        report = self.summarize(other)
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["audio_matches_key"])
        self.assertFalse(report["response_packet_binding_verified"])
        self.assertIn("originating packet", report["assessment_limit"])

    def test_held_out_declared_modes_and_review_status_stay_separate(self):
        self.plan["split"] = "held_out"
        self.plan["conditions"][0]["mode"] = "svc"
        self.plan["conditions"][1]["mode"] = "svs"
        self.plan["clips"] = [{
            "item_id": self.held["id"], "condition_id": condition["id"],
            "path": f"{self.held['id']}-{condition['id']}.wav",
        } for condition in self.plan["conditions"]]
        packet = self.root / "held-packet"
        self.prepare(packet, 0)
        self.write_rows([("trial-001", "cannot_assess", "Synthetic entry.")])
        report = self.summarize(packet)
        self.assertEqual(report["split"], "held_out")
        self.assertEqual(report["condition_modes"],
                         {"low": "svc", "high": "svs"})
        self.assertTrue(report["responses_complete"])
        self.assertEqual(sum(report["condition_preferences"].values()), 0)
        self.assertFalse(report["listening_performed_verified"])

    def test_duplicate_unknown_and_invalid_preference_rows_are_rejected(self):
        for rows in ([('trial-001', 'A', ''), ('trial-001', 'B', '')],
                     [('trial-999', 'A', '')], [('trial-001', 'a', '')],
                     [('trial-001', ' A', '')],
                     [('trial-001', 'winner', '')]):
            with self.subTest(rows=rows):
                self.write_rows(rows)
                with self.assertRaises(ValueError):
                    self.summarize()

    def test_duplicate_headers_ragged_extra_and_bad_quoting_are_rejected(self):
        for encoded in (
                "trial_id,preference,preference\ntrial-001,A,B\n",
                "trial_id,preference,notes,extra\ntrial-001,A,,x\n",
                "trial_id,preference,notes\ntrial-001,A\n",
                "trial_id,preference,notes\ntrial-001,A,,x\n",
                'trial_id,preference,notes\ntrial-001,A,"unterminated\n'):
            with self.subTest(encoded=encoded):
                self.csv_path.write_text(encoded, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.summarize()

    def test_bom_and_quoted_nonascii_notes_are_supported_but_omitted(self):
        self.csv_path.write_text(
            '\ufefftrial_id,preference,notes\r\ntrial-001,A,"á\r\nb"\r\n',
            encoding="utf-8", newline="")
        report = self.summarize()
        self.assertEqual(report["answered_trials"], 1)
        self.assertNotIn("á", json.dumps(report, ensure_ascii=False))

    def test_malformed_key_and_mismatched_listener_mappings_are_rejected(self):
        original = self.key()
        variants = []
        for field, value in (("schema_version", True), ("attribute", "quality"),
                             ("split", []), ("conditions", [])):
            variants.append({**original, field: value})
        duplicate = copy.deepcopy(original)
        duplicate["trials"][1]["trial_id"] = "trial-001"
        variants.append(duplicate)
        wrong_condition = copy.deepcopy(original)
        versions = wrong_condition["trials"][0]["versions"]
        versions["B"]["condition_id"] = versions["A"]["condition_id"]
        variants.append(wrong_condition)
        duplicate_item = copy.deepcopy(original)
        item_id = original["trials"][0]["item_id"]
        duplicate_item["trials"][1]["item_id"] = item_id
        variants.append(duplicate_item)
        bad_digest = copy.deepcopy(original)
        bad_digest["trials"][0]["versions"]["A"]["output_sha256"] = "bad"
        variants.append(bad_digest)
        for variant in variants:
            with self.subTest(variant=variant):
                self.change_key(variant)
                with self.assertRaises(ValueError):
                    self.summarize()
        self.change_key(original)
        path = self.packet / "listener/trials.json"
        trials = json.loads(path.read_text("utf-8"))
        trials["trials"].pop()
        path.write_text(json.dumps(trials), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.summarize()

    def test_unsafe_names_changed_bytes_and_missing_audio_fail(self):
        path = self.packet / "listener/trials.json"
        trials = json.loads(path.read_text("utf-8"))
        original = path.read_bytes()
        trials["trials"][0]["A"] = "../outside.wav"
        path.write_text(json.dumps(trials), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.summarize()
        path.write_bytes(original)
        audio = self.packet / "listener/trial-001-A.wav"
        source = audio.read_bytes()
        audio.write_bytes(source[:-1] + bytes([source[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, "Audio bytes do not match"):
            self.summarize()
        audio.unlink()
        with self.assertRaises(OSError):
            self.summarize()

    def test_resource_bounds_and_listener_id_are_checked(self):
        with mock.patch.object(responses, "MAX_CSV_BYTES", 5):
            with self.assertRaises(ValueError):
                self.summarize()
        with mock.patch.object(responses, "MAX_JSON_BYTES", 5):
            with self.assertRaises(ValueError):
                self.summarize()
        with mock.patch.object(listening, "MAX_WAV_BYTES", 5):
            with self.assertRaises(ValueError):
                self.summarize()
        with mock.patch.object(listening, "MAX_TOTAL_BYTES", 5):
            with self.assertRaises(ValueError):
                self.summarize()
        self.write_rows([("trial-001", "A", "x" * 4097)])
        with self.assertRaises(ValueError):
            self.summarize()
        for identifier in ("", "has space", "x" * 65, False):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    responses.summarize_packet(self.packet, self.csv_path,
                                               identifier)

    def test_summary_does_not_modify_inputs(self):
        before = {str(path.relative_to(self.root)):
                  hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in self.root.rglob("*") if path.is_file()}
        self.summarize()
        after = {str(path.relative_to(self.root)):
                 hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)


class ResponsesCommandLineTest(_ResponseFixture, unittest.TestCase):

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-S", "-m", "tagalog_singing_preflight",
             "responses", str(self.packet), str(self.csv_path), *arguments],
            cwd=ROOT,
            capture_output=True, encoding="utf-8", timeout=15, check=False)

    def test_cli_success_and_exclusive_output_creation(self):
        target = self.root / "report.json"
        result = self.run_cli("--listener-id", "synthetic-demo", "--output",
                              str(target))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(target.read_text("utf-8"))
        self.assertEqual(report["answered_trials"], 3)
        self.assertFalse(report["listening_performed_verified"])
        preserved = target.read_bytes()
        again = self.run_cli("--listener-id", "synthetic-demo", "--output",
                             str(target))
        self.assertEqual(again.returncode, 2)
        self.assertEqual(target.read_bytes(), preserved)

    def test_cli_missing_identity_bad_csv_and_stale_audio_are_two(self):
        self.assertEqual(self.run_cli().returncode, 2)
        self.write_rows([("trial-001", "wrong", "")])
        result = self.run_cli("--listener-id", "synthetic-demo")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["status"], "error")
        self.write_rows([])
        (self.packet / "listener/trial-001-A.wav").write_bytes(b"changed")
        stale = self.run_cli("--listener-id", "synthetic-demo")
        self.assertEqual(stale.returncode, 2)


if __name__ == "__main__":
    unittest.main()
