"""Native SVS checks with original synthetic fixtures, without a model."""

from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tagalog_singing_preflight import soulx


ROOT = pathlib.Path(__file__).resolve().parents[1]


def example_metadata() -> dict:
    return json.loads((ROOT / "examples/soulx-metadata.json").read_text(
        encoding="utf-8"))


def example_phoneset() -> list[str]:
    return json.loads((ROOT / "examples/soulx-example-phoneset.json").read_text(
        encoding="utf-8"))


def error_codes(report: dict) -> list[str]:
    return [error["code"] for error in report["errors"]]


class NativeMetadataTest(unittest.TestCase):

    def test_expands_english_note_groups_without_mutating_inputs(self):
        metadata = example_metadata()
        phoneset = example_phoneset()
        original = copy.deepcopy((metadata, phoneset))
        report = soulx.audit_metadata(metadata, phoneset, 50)
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual((metadata, phoneset), original)
        self.assertEqual(report["phonemes"]["expanded_token_count"], 11)
        self.assertEqual(report["timing"]["native_float_floor_frames"], 50)
        self.assertEqual(report["f0"]["native_retained_frames"], 50)
        self.assertFalse(report["phonemes"]["pronunciation_assessed"])

    def test_structural_and_expanded_tokens_use_actual_declared_phoneset(self):
        report = soulx.audit_metadata(example_metadata(), ["en_S-AH0"], 50)
        self.assertIn("UNKNOWN_NATIVE_PHONEMES", error_codes(report))
        unknown = report["phonemes"]["unknown_tokens"]
        self.assertIn({"source_group_indices": [], "token": "<PAD>"}, unknown)
        self.assertIn({"source_group_indices": [0], "token": "en_AH0"}, unknown)
        self.assertIn({"source_group_indices": [0], "token": "<SEP>"}, unknown)

    def test_f0_shorter_and_longer_than_native_clock_fail_explicitly(self):
        for count in (49, 51):
            with self.subTest(count=count):
                metadata = example_metadata()
                metadata["f0"] = " ".join(["200"] * count)
                report = soulx.audit_metadata(metadata, example_phoneset(), 50)
                self.assertIn("NATIVE_F0_TRUNCATION", error_codes(report))
                self.assertEqual(
                    report["f0"]["native_retained_frames"], min(50, count))
                self.assertEqual(
                    report["f0"]["native_truncates_f0"], count > 50)
                self.assertEqual(
                    report["f0"]["native_truncates_metadata"], count < 50)

    def test_native_float_floor_failure_is_not_hidden_by_exact_allocator(self):
        metadata = {
            "phoneme": " ".join(["en_S"] * 10),
            "duration": " ".join(["0.1"] * 10),
            "note_pitch": " ".join(["60"] * 10),
            "note_type": " ".join(["2"] * 10),
            "f0": " ".join(["200"] * 50),
        }
        report = soulx.audit_metadata(metadata, example_phoneset(), 50)
        self.assertEqual(report["timing"]["exact_allocated_frames"], 50)
        self.assertEqual(report["timing"]["native_float_floor_frames"], 49)
        self.assertIn("NATIVE_FRAME_TOTAL", error_codes(report))
        self.assertIn("NATIVE_F0_TRUNCATION", error_codes(report))

    def test_pause_replacement_and_merging_are_included_in_native_clock(self):
        metadata = {"phoneme": "<AP> <SP> en_S", "duration": "0.1 0.1 0.8",
                    "note_pitch": "0 0 60", "note_type": "0 2 2"}
        report = soulx.audit_metadata(metadata, example_phoneset(), 50)
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(
            report["phonemes"]["native_groups_after_pause_merge"], 2)
        warnings = [warning["code"] for warning in report["warnings"]]
        self.assertIn("NATIVE_AP_TO_SP", warnings)
        self.assertIn("NATIVE_PAUSE_MERGE", warnings)
        self.assertIn("NO_F0", warnings)

    def test_singleton_envelope_is_supported_but_batches_are_not_implicit(self):
        self.assertEqual(soulx.audit_metadata(
            [example_metadata()], example_phoneset(), 50)["status"], "pass")
        for metadata in ([], [example_metadata(), example_metadata()], "bad"):
            with self.subTest(metadata=metadata):
                self.assertIn("NATIVE_CONTRACT", error_codes(
                    soulx.audit_metadata(metadata, example_phoneset(), 50)))

    def test_invalid_native_fields_do_not_reach_a_model(self):
        changes = [
            {"duration": "0.4"}, {"duration": "NaN 0.6"},
            {"duration": "0 1"}, {"note_pitch": "60 256"},
            {"note_type": "-1 2"}, {"note_type": "2 nope"},
            {"phoneme": ["en_S", "en_B"]}, {"f0": [200] * 50},
            {"f0": "NaN"}, {"f0": "-1"},
        ]
        for change in changes:
            with self.subTest(change=change):
                metadata = example_metadata()
                metadata.update(change)
                self.assertIn("NATIVE_CONTRACT", error_codes(
                    soulx.audit_metadata(metadata, example_phoneset(), 50)))

    def test_expected_clock_and_supported_profile_are_strict(self):
        for expected in (True, 0, -1, 1.0, 1_000_001):
            with self.subTest(expected=expected):
                self.assertIn("NATIVE_CONTRACT", error_codes(
                    soulx.audit_metadata(
                        example_metadata(), example_phoneset(), expected)))
        for rate, hop in ((True, 480), (24000, 0), (22050, 480)):
            with self.subTest(rate=rate, hop=hop):
                self.assertIn("NATIVE_CONTRACT", error_codes(
                    soulx.audit_metadata(
                        example_metadata(), example_phoneset(), 50, rate, hop)))

    def test_zero_frame_note_is_refused(self):
        metadata = example_metadata()
        metadata["duration"] = "0.001 0.999"
        report = soulx.audit_metadata(metadata, example_phoneset(), 50)
        self.assertIn("ZERO_FRAME_GROUPS", error_codes(report))


class NativeCommandLineTest(unittest.TestCase):

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "tagalog_singing_preflight", "soulx",
             "examples/soulx-metadata.json",
             "examples/soulx-example-phoneset.json",
             *arguments], cwd=ROOT, capture_output=True, encoding="utf-8",
            timeout=15, check=False)

    def test_native_command_passes_and_mismatched_expected_count_fails(self):
        passed = self.run_cli("--expected-frames", "50")
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(json.loads(passed.stdout)["status"], "pass")
        failed = self.run_cli("--expected-frames", "51")
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertIn(
            "NATIVE_FRAME_TOTAL", error_codes(json.loads(failed.stdout)))

    def test_native_report_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "report.json"
            arguments = ("--expected-frames", "50", "--output", str(output))
            first = self.run_cli(*arguments)
            self.assertEqual(first.returncode, 0, first.stderr)
            original = output.read_bytes()
            second = self.run_cli(*arguments)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output.read_bytes(), original)

    def test_runnable_short_f0_fixture_reports_native_truncation(self):
        result = subprocess.run(
            [sys.executable, "-m", "tagalog_singing_preflight", "soulx",
             "examples/soulx-short-f0.json",
             "examples/soulx-example-phoneset.json", "--expected-frames", "50"],
            cwd=ROOT, capture_output=True, encoding="utf-8", timeout=15,
            check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn("NATIVE_F0_TRUNCATION", error_codes(report))
        self.assertEqual(report["f0"]["native_retained_frames"], 3)


if __name__ == "__main__":
    unittest.main()
