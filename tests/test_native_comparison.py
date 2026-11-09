"""Test comparison boundaries without installing the optional native runtime."""

from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tagalog_singing_preflight import native_comparison


ROOT = pathlib.Path(__file__).resolve().parents[1]


class NativeComparisonTest(unittest.TestCase):

    def setUp(self):
        self.vocabulary = json.loads(
            (ROOT / "examples/soulx-example-phoneset.json").read_text("utf-8"))
        self.metadata = {
            "text": "Original synthetic fixture.",
            "phoneme": "en_S-AH0-B", "duration": "0.5",
            "note_pitch": "60", "note_type": "2",
        }
        self.actual = {
            "phoneme": [[0, 1, 5, 6, 7, 3, 2]],
            "note_pitch": [[0, 60, 60, 60, 60, 60, 60]],
            "note_type": [[1, 2, 2, 2, 2, 2, 2]],
            "mel2note": [[1] + [2, 3, 4, 5] * 5 + [0, 0, 0, 6]],
        }

    def compare(self):
        return native_comparison.compare_processed(
            self.metadata, self.vocabulary, self.actual, 25)

    def test_retained_fields_and_zeros_have_separate_meanings(self):
        original = copy.deepcopy((self.metadata, self.vocabulary, self.actual))
        report = self.compare()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["expected_token_count"], 7)
        self.assertEqual(report["alignment"]["zero_index_frames"], 3)
        self.assertEqual(report["alignment"]["positive_index_frames"], 22)
        self.assertFalse(report["native_processor_executed"])
        self.assertFalse(report["alignment_assignment_verified"])
        self.assertFalse(report["pronunciation_assessed"])
        self.assertEqual((self.metadata, self.vocabulary, self.actual),
                         original)

    def test_changed_native_fields_and_clock_fail_the_comparison(self):
        original = copy.deepcopy(self.actual)
        for field, expected_check in (
                ("phoneme", "phoneme_ids_match"),
                ("note_pitch", "note_pitch_match"),
                ("note_type", "note_type_match")):
            with self.subTest(field=field):
                self.actual = copy.deepcopy(original)
                self.actual[field][0][1] += 1
                report = self.compare()
                self.assertEqual(report["status"], "fail")
                self.assertFalse(report["checks"][expected_check])
        self.actual = copy.deepcopy(original)
        self.actual["mel2note"][0].pop()
        self.assertFalse(self.compare()["checks"]["alignment_clock_matches"])
        self.actual = copy.deepcopy(original)
        self.actual["mel2note"][0][0] = 7
        self.assertFalse(
            self.compare()["checks"]["alignment_indices_in_bounds"])

    def test_invalid_batch_and_failed_metadata_audit_are_refused(self):
        self.actual["phoneme"] = [[False]]
        with self.assertRaisesRegex(ValueError, "integer values"):
            self.compare()
        self.metadata["duration"] = "0.01"
        with self.assertRaisesRegex(ValueError, "NATIVE_ALIGNMENT_CAPACITY"):
            self.compare()

    def test_cli_rejects_changed_source_before_import_or_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            source = directory / "soulxsinger/utils/data_processor.py"
            source.parent.mkdir(parents=True)
            source.write_text("raise RuntimeError('must not import')\n",
                              encoding="utf-8")
            exported = directory / "export.json"
            exported.write_text(json.dumps({"metadata": self.metadata}),
                                encoding="utf-8")
            output = directory / "comparison.json"
            result = subprocess.run(
                [sys.executable, "-m", "examples.compare_soulx_cpu",
                 str(exported), "examples/soulx-example-phoneset.json",
                 "--upstream", str(directory), "--expected-frames", "25",
                 "--output", str(output)], cwd=ROOT, capture_output=True,
                timeout=20, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"differs from the pinned source", result.stderr)
            self.assertNotIn(b"must not import", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
