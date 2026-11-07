"""Check explicit mappings with synthetic tokens and original text offsets."""

from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tagalog_singing_preflight import phone_mapping
from tagalog_singing_preflight import review_draft


ROOT = pathlib.Path(__file__).resolve().parents[1]


class PhoneMappingTest(unittest.TestCase):

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = pathlib.Path(directory.name)
        self.manifest = json.loads(
            (ROOT / "data/tagalog-benchmark-v1.json").read_text("utf-8"))
        self.manifest["items"][0]["text"] = "Za\u0301 ng."
        self.lexicon = self.directory / "synthetic.tsv"
        self.lexicon.write_text("Zá\tˈz a\u0303 ʔ\n", encoding="utf-8")
        self.terms = {"source_label": "synthetic-v1", "data_license": "MIT"}
        self.review = review_draft.prepare_draft(
            self.manifest, "dev-01", self.lexicon, **self.terms)
        self.review["review"].update(
            status="approved", reviewer_id="synthetic-reviewer",
            reviewed_at="2026-11-07", pronunciation_notes="Fixture only.")
        self.review["occurrences"][0]["annotation"]["selected_source_row"] = 1
        annotation = self.review["occurrences"][1]["annotation"]
        annotation["proposed_ipa_tokens"] = ["ŋ"]
        self.mapping = {
            "schema_version": 1, "mapping_id": "synthetic",
            "target_model": "synthetic-v1",
            "rules": {"ˈz": ["STRESS", "Z"], "a\u0303": ["A"],
                      "ʔ": ["GLOTTAL"], "ŋ": ["NG"]},
        }
        self.vocabulary = ["STRESS", "Z", "A", "GLOTTAL", "NG"]

    def map_review(self):
        return phone_mapping.map_review(
            self.manifest, "dev-01", self.lexicon, self.review,
            self.mapping, self.vocabulary, **self.terms)

    def test_mapping_preserves_unicode_context_and_expands_explicit_rules(self):
        original = copy.deepcopy((self.manifest, self.review, self.mapping))
        result = self.map_review()
        self.assertEqual(result["mapped_occurrences"], [
            {"text": "Za\u0301", "start": 0, "end": 3,
             "ipa_tokens": ["ˈz", "a\u0303", "ʔ"],
             "target_tokens": ["STRESS", "Z", "A", "GLOTTAL"]},
            {"text": "ng", "start": 4, "end": 6,
             "ipa_tokens": ["ŋ"], "target_tokens": ["NG"]},
        ])
        self.assertEqual(result["target_token_count"], 5)
        self.assertTrue(result["tokens_supported_by_declared_vocabulary"])
        for flag in ("native_review_verified", "permissions_verified",
                     "pronunciation_assessed", "linguistic_mapping_assessed",
                     "model_runtime_verified"):
            self.assertIs(result[flag], False)
        self.assertNotIn("synthetic-reviewer", json.dumps(result))
        self.assertEqual((self.manifest, self.review, self.mapping), original)

    def test_missing_stress_glottal_and_exact_combining_rules_are_refused(self):
        rules = copy.deepcopy(self.mapping["rules"])
        for source, replacement in (("ˈz", "z"), ("ʔ", "glottal"),
                                    ("a\u0303", "ã")):
            with self.subTest(source=source):
                self.mapping["rules"] = copy.deepcopy(rules)
                targets = self.mapping["rules"].pop(source)
                self.mapping["rules"][replacement] = targets
                with self.assertRaises(ValueError):
                    self.map_review()

    def test_pending_incomplete_and_changed_reviews_are_refused(self):
        approved = copy.deepcopy(self.review)
        for status in ("pending", "needs_revision"):
            with self.subTest(status=status):
                self.review = copy.deepcopy(approved)
                self.review["review"]["status"] = status
                if status == "pending":
                    self.review["review"].update(
                        reviewer_id=None, reviewed_at=None,
                        pronunciation_notes=None)
                with self.assertRaises(ValueError):
                    self.map_review()
        self.review = copy.deepcopy(approved)
        annotation = self.review["occurrences"][1]["annotation"]
        annotation["proposed_ipa_tokens"] = None
        with self.assertRaises(ValueError):
            self.map_review()
        self.review = copy.deepcopy(approved)
        self.review["occurrences"][0]["end"] = 2
        with self.assertRaises(ValueError):
            self.map_review()

    def test_profile_rejects_deletion_and_unknown_unused_target(self):
        rules = copy.deepcopy(self.mapping["rules"])
        for value in ([], [""], ["A B"], ["A\x00"], ["x"] * 17):
            with self.subTest(value=value):
                self.mapping["rules"] = copy.deepcopy(rules)
                self.mapping["rules"]["ˈz"] = value
                with self.assertRaises(ValueError):
                    self.map_review()
        self.mapping["rules"] = rules
        self.mapping["rules"]["unused"] = ["UNDECLARED"]
        with self.assertRaises(ValueError):
            self.map_review()
        del self.mapping["rules"]["unused"]
        self.vocabulary.append(" invalid ")
        with self.assertRaises(ValueError):
            self.map_review()

    def test_runnable_demo_cli_and_refusal_to_create_partial_mapping(self):
        demo = self.directory / "demo"
        make = subprocess.run(
            [sys.executable, "examples/make_phone_mapping_demo.py", str(demo)],
            cwd=ROOT, capture_output=True, timeout=30, check=False)
        self.assertEqual(make.returncode, 0, make.stderr)
        command = [
            sys.executable, "-m", "tagalog_singing_preflight", "phone-map",
            "data/tagalog-benchmark-v1.json", "dev-05",
            "examples/lexicon-demo.tsv", str(demo / "review.json"),
            str(demo / "mapping.json"), str(demo / "vocabulary.json"),
            "--source-label", "synthetic-demo", "--data-license", "MIT",
        ]
        result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["target_token_count"], 18)
        profile = json.loads((demo / "mapping.json").read_text("utf-8"))
        del profile["rules"]["ʔ"]
        (demo / "mapping.json").write_text(
            json.dumps(profile), encoding="utf-8")
        output = demo / "refused.json"
        invalid = subprocess.run([*command, "--output", str(output)], cwd=ROOT,
                                 capture_output=True, timeout=20, check=False)
        self.assertEqual(invalid.returncode, 2)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
