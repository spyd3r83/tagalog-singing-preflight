"""Exercise explicit native note export with original synthetic decisions."""

from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tagalog_singing_preflight import review_draft
from tagalog_singing_preflight import soulx_export


ROOT = pathlib.Path(__file__).resolve().parents[1]


class SoulxExportTest(unittest.TestCase):

    def setUp(self):
        self.manifest = json.loads(
            (ROOT / "data/tagalog-benchmark-v1.json").read_text("utf-8"))
        self.lexicon = ROOT / "examples/lexicon-demo.tsv"
        self.terms = {"source_label": "synthetic-demo", "data_license": "MIT"}
        self.review = review_draft.prepare_draft(
            self.manifest, "dev-05", self.lexicon, **self.terms)
        self.review["review"].update(
            status="approved", reviewer_id="synthetic-demo",
            reviewed_at="2026-11-08", pronunciation_notes="Fixture only.")
        for occurrence in self.review["occurrences"]:
            occurrence["annotation"]["proposed_ipa_tokens"] = ["ˈdemo", "ʔ"]
        self.mapping = {
            "schema_version": 1, "mapping_id": "synthetic",
            "target_model": "synthetic-v1",
            "rules": {"ˈdemo": ["en_S", "en_AH0"], "ʔ": ["en_B"]},
        }
        self.vocabulary = json.loads(
            (ROOT / "examples/soulx-example-phoneset.json").read_text("utf-8"))
        self.plan = {"schema_version": 1, "notes": [
            {"occurrence_index": index, "token_start": 0, "token_end": 3,
             "duration": "0.5", "note_pitch": 60, "note_type": 2}
            for index in range(6)
        ]}

    def export(self, expected_frames=150):
        return soulx_export.export_review(
            self.manifest, "dev-05", self.lexicon, self.review, self.mapping,
            self.vocabulary, self.plan, expected_frames=expected_frames,
            **self.terms)

    def test_split_occurrence_preserves_order_and_original_assignments(self):
        first = self.plan["notes"][0]
        second = dict(first, token_start=1, duration="0.25")
        first.update(token_end=1, duration="0.25")
        self.plan["notes"].insert(1, second)
        original = copy.deepcopy((self.review, self.mapping, self.plan))
        result = self.export()
        self.assertEqual(result["metadata"]["phoneme"].split()[:3],
                         ["en_S", "en_AH0-B", "en_S-AH0-B"])
        self.assertEqual(result["metadata"]["text"],
                         self.review["original_text"])
        self.assertEqual(result["note_assignments"], self.plan["notes"])
        self.assertEqual(result["audit"]["status"], "pass")
        self.assertFalse(result["native_processor_executed"])
        self.assertFalse(result["native_review_verified"])
        self.assertEqual((self.review, self.mapping, self.plan), original)

    def test_coverage_rejects_gaps_overlap_reordering_and_missing_tail(self):
        valid = copy.deepcopy(self.plan)
        invalid_plans = []
        for field, value in (("token_start", 1), ("token_end", 4),
                             ("occurrence_index", 1), ("token_start", False)):
            candidate = copy.deepcopy(valid)
            candidate["notes"][0][field] = value
            invalid_plans.append(candidate)
        missing_tail = copy.deepcopy(valid)
        missing_tail["notes"].pop()
        invalid_plans.append(missing_tail)
        repeated = copy.deepcopy(valid)
        repeated["notes"].insert(1, copy.deepcopy(repeated["notes"][0]))
        invalid_plans.append(repeated)
        reordered = copy.deepcopy(valid)
        reordered["notes"][0:2] = reversed(reordered["notes"][0:2])
        invalid_plans.append(reordered)
        for plan in invalid_plans:
            with self.subTest(plan=plan):
                self.plan = plan
                with self.assertRaises(ValueError):
                    self.export()

    def test_encoding_and_native_audit_refuse_unsafe_content(self):
        for token in ("T_OTHER", "en_S-AH0", "en_", "<SP>", "<BOW>"):
            with self.subTest(token=token):
                self.mapping["rules"]["ˈdemo"] = [token, "en_AH0"]
                self.vocabulary.append(token)
                with self.assertRaises(ValueError):
                    self.export()
        self.mapping["rules"]["ˈdemo"] = ["en_S", "en_AH0"]
        self.vocabulary.remove("<SEP>")
        with self.assertRaisesRegex(ValueError, "UNKNOWN_NATIVE_PHONEMES"):
            self.export()

    def test_frame_capacity_and_changed_review_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "NATIVE_FRAME_TOTAL"):
            self.export(149)
        for note in self.plan["notes"]:
            note["duration"] = "0.04"
        with self.assertRaisesRegex(ValueError, "NATIVE_ALIGNMENT_CAPACITY"):
            self.export(12)
        self.review["occurrences"][0]["end"] += 1
        with self.assertRaisesRegex(ValueError, "occurrences"):
            self.export()

    def test_cli_demo_and_invalid_plan_create_no_partial_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo = pathlib.Path(tmp) / "native-demo"
            made = subprocess.run(
                [sys.executable, "examples/make_phone_mapping_demo.py",
                 str(demo), "--native-notes"], cwd=ROOT, capture_output=True,
                timeout=30, check=False)
            self.assertEqual(made.returncode, 0, made.stderr)
            command = [
                sys.executable, "-m", "tagalog_singing_preflight",
                "soulx-export", "data/tagalog-benchmark-v1.json", "dev-05",
                "examples/lexicon-demo.tsv", str(demo / "review.json"),
                str(demo / "mapping.json"), str(demo / "vocabulary.json"),
                str(demo / "note-plan.json"),
                "--source-label", "synthetic-demo",
                "--data-license", "MIT", "--expected-frames", "150",
            ]
            source_files = list(demo.glob("*.json"))
            before = {path: path.read_bytes() for path in source_files}
            result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                    timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["metadata"]["phoneme"].split(),
                             ["en_S-AH0-B"] * 6)
            self.assertEqual(report["audit"]["timing"]["expected_frames"], 150)
            self.assertEqual({path: path.read_bytes() for path in source_files},
                             before)
            plan = json.loads((demo / "note-plan.json").read_text("utf-8"))
            plan["notes"][0]["token_start"] = 1
            (demo / "note-plan.json").write_text(
                json.dumps(plan), encoding="utf-8")
            output = demo / "refused.json"
            refused = subprocess.run([*command, "--output", str(output)],
                                     cwd=ROOT, capture_output=True, timeout=20,
                                     check=False)
            self.assertEqual(refused.returncode, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
