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
import uuid
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
                                 target, seed, packet_version=1)

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


class PacketIdentityTest(_ResponseFixture, unittest.TestCase):

    def setUp(self):
        super().setUp()
        self.legacy_packet = self.packet
        self.packet = self.root / "v2-packet"
        self.prepare_v2(self.packet)
        self.write_v2_rows([("trial-001", "A", "Synthetic response."),
                            ("trial-002", "tie", ""),
                            ("trial-003", "cannot_assess", ""),
                            ("trial-004", "", "")])

    def prepare_v2(self, target: pathlib.Path, seed: int = 17) -> dict:
        return listening.prepare_packet(self.manifest, self.plan, self.root,
                                        target, seed)

    def write_v2_rows(self, rows: list[tuple[str, str, str]]) -> None:
        with self.csv_path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.writer(target)
            writer.writerow(("packet_id", "trial_id", "preference", "notes"))
            writer.writerows((self.key()["packet_id"], *row) for row in rows)

    def test_default_v2_id_is_shared_without_claiming_provenance(self):
        key = self.key()
        listener = self.packet / "listener/trials.json"
        trials = json.loads(listener.read_text("utf-8"))
        self.assertEqual(key["schema_version"], 2)
        self.assertEqual(trials["schema_version"], 2)
        self.assertEqual(key["packet_id"], trials["packet_id"])
        parsed = uuid.UUID(key["packet_id"])
        self.assertEqual(parsed.version, 4)
        self.assertEqual(str(parsed), key["packet_id"])
        with (self.packet / "listener/responses.csv").open(
                encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["packet_id"] == key["packet_id"]
                            and row["preference"] == "" for row in rows))
        report = self.summarize()
        self.assertEqual(report["packet_version"], 2)
        self.assertEqual(report["packet_id"], key["packet_id"])
        self.assertIs(report["response_packet_id_matches"], True)
        self.assertEqual((report["answered_trials"], report["ties"],
                          report["cannot_assess"]), (3, 1, 1))
        self.assertEqual(report["blank_trial_ids"], ["trial-004"])
        for field in ("response_packet_binding_verified",
                      "listening_performed_verified", "native_review_verified",
                      "permission_verified"):
            self.assertFalse(report[field])

    def test_same_seed_keeps_assignment_and_audio_but_gets_fresh_id(self):
        other = self.root / "same-seed"
        self.prepare_v2(other)
        first_key = self.key()
        second_key = json.loads(
            (other / "operator-key.json").read_text("utf-8"))
        self.assertNotEqual(first_key["packet_id"], second_key["packet_id"])
        self.assertEqual(first_key["trials"], second_key["trials"])
        first_trials = json.loads(
            (self.packet / "listener/trials.json").read_text("utf-8"))
        second_trials = json.loads((other / "listener/trials.json").read_text(
            "utf-8"))
        self.assertEqual(first_trials["trials"], second_trials["trials"])
        for source in (self.packet / "listener").glob("*.wav"):
            self.assertEqual(source.read_bytes(),
                             (other / "listener" / source.name).read_bytes())
        with self.assertRaisesRegex(ValueError, "CSV packet_id"):
            self.summarize(other)
        different = self.root / "different-seed"
        self.prepare_v2(different, 19)
        with self.assertRaisesRegex(ValueError, "CSV packet_id"):
            self.summarize(different)

    def test_mixed_versions_missing_ids_and_key_listener_mismatch_fail(self):
        source = self.packet / "listener/trials.json"
        original = json.loads(source.read_text("utf-8"))
        for changes in ({"schema_version": 1}, {"packet_id": str(uuid.uuid4())},
                        {"packet_id": None}):
            with self.subTest(changes=changes):
                source.write_text(json.dumps({**original, **changes}),
                                  encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.summarize()
        source.write_text(json.dumps(original), encoding="utf-8")
        key = self.key()
        for identifier in (None, "", "not-a-uuid", key["packet_id"].upper(),
                           key["packet_id"].replace("-", ""),
                           "00000000-0000-1000-8000-000000000000"):
            with self.subTest(identifier=identifier):
                self.change_key({**key, "packet_id": identifier})
                with self.assertRaises(ValueError):
                    self.summarize()
        self.change_key(key)
        del key["packet_id"]
        self.change_key(key)
        with self.assertRaises(ValueError):
            self.summarize()

    def test_wrong_or_missing_row_id_fails_even_for_blank_preference(self):
        for identifier in ("", "wrong-id", str(uuid.uuid4())):
            with self.subTest(identifier=identifier):
                self.csv_path.write_text(
                    "packet_id,trial_id,preference,notes\n"
                    + identifier + ",trial-001,,\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "CSV packet_id"):
                    self.summarize()
        self.csv_path.write_text(
            "packet_id,trial_id,preference,notes\ntrial-001,A,\n",
            encoding="utf-8")
        with self.assertRaises(ValueError):
            self.summarize()

    def test_header_only_has_no_id_evidence_and_blank_rows_remain_valid(self):
        self.write_v2_rows([])
        report = self.summarize()
        self.assertIsNone(report["response_packet_id_matches"])
        self.assertEqual(report["response_rows"], 0)
        self.assertEqual(len(report["missing_row_trial_ids"]), 4)
        self.csv_path = self.packet / "listener/responses.csv"
        blank = self.summarize()
        self.assertIs(blank["response_packet_id_matches"], True)
        self.assertEqual(blank["answered_trials"], 0)
        self.assertFalse(blank["responses_complete"])

    def test_v1_and_v2_csv_headers_cannot_be_used_interchangeably(self):
        with self.assertRaisesRegex(ValueError, "CSV header"):
            self.summarize(self.legacy_packet)
        self.write_rows([("trial-001", "A", "Synthetic entry.")])
        with self.assertRaisesRegex(ValueError, "CSV header"):
            self.summarize()
        legacy = self.summarize(self.legacy_packet)
        self.assertEqual(legacy["packet_version"], 1)
        self.assertIsNone(legacy["packet_id"])
        self.assertIsNone(legacy["response_packet_id_matches"])
        self.assertFalse(legacy["response_packet_binding_verified"])

    def test_packet_version_argument_is_strict_and_creates_no_output(self):
        for version in (True, None, 0, 3, 2.0, "2"):
            with self.subTest(version=version):
                target = self.root / "invalid-version"
                with self.assertRaises(ValueError):
                    listening.prepare_packet(
                        self.manifest, self.plan, self.root, target, 17,
                        packet_version=version)
                self.assertFalse(target.exists())

    def test_cli_default_v2_and_explicit_legacy_v1_preserve_contracts(self):
        manifest = self.root / "manifest.json"
        plan = self.root / "plan.json"
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        plan.write_text(json.dumps(self.plan), encoding="utf-8")
        for version in (1, 2):
            target = self.root / f"cli-v{version}"
            command = [sys.executable, "-S", "-m", "tagalog_singing_preflight",
                       "listening", str(manifest), str(plan), str(target),
                       "--seed", "17"]
            if version == 1:
                command.extend(("--packet-version", "1"))
            prepared = subprocess.run(command, cwd=ROOT, capture_output=True,
                                      encoding="utf-8", timeout=15, check=False)
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            self.assertEqual(json.loads(prepared.stdout)["packet_version"],
                             version)
            result = subprocess.run(
                [sys.executable, "-S", "-m", "tagalog_singing_preflight",
                 "responses", str(target),
                 str(target / "listener/responses.csv"),
                 "--listener-id", "synthetic-demo"], cwd=ROOT,
                capture_output=True, encoding="utf-8", timeout=15, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["packet_version"], version)
            self.assertEqual(report["answered_trials"], 0)
            if version == 2:
                wrong = subprocess.run(
                    [sys.executable, "-S", "-m", "tagalog_singing_preflight",
                     "responses", str(target), str(self.csv_path),
                     "--listener-id", "synthetic-demo"], cwd=ROOT,
                    capture_output=True, encoding="utf-8", timeout=15,
                    check=False)
                self.assertEqual(wrong.returncode, 2)


if __name__ == "__main__":
    unittest.main()
