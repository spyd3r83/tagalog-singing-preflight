"""Benchmark record contracts with original synthetic text and no audio."""

from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tagalog_singing_preflight import benchmark


ROOT = pathlib.Path(__file__).resolve().parents[1]


def sample_manifest() -> dict:
    review = {"status": "pending", "reviewer_id": None,
              "reviewed_at": None, "pronunciation_notes": None}
    return {
        "schema_version": 1, "benchmark_id": "original-test-v1",
        "language": "tl", "text_origin": "original_authored", "license": "MIT",
        "items": [
            {"id": "dev-01", "split": "development", "text": "Si Ana’y aawit.",
             "focus": ["contraction", "connected_phrase"],
             "review": copy.deepcopy(review)},
            {"id": "held-01", "split": "held_out", "text": "May bagong araw.",
             "focus": ["vowel_sequence"], "review": copy.deepcopy(review)},
        ],
    }


def error_codes(report: dict) -> list[str]:
    return [error["code"] for error in report["errors"]]


class BenchmarkTest(unittest.TestCase):

    def test_bundled_manifest_preserves_pending_review_and_split_contract(self):
        source = (ROOT / "data/tagalog-benchmark-v1.json").read_bytes()
        report = benchmark.audit_manifest(json.loads(source))
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["item_count"], 16)
        self.assertEqual(report["split_counts"],
                         {"development": 8, "held_out": 8})
        self.assertEqual(report["review_counts"],
                         {"pending": 16, "approved": 0, "needs_revision": 0})
        self.assertTrue(all(report["focus_counts"].values()))
        self.assertFalse(report["native_review_verified"])
        self.assertEqual(source, (
            ROOT / "data/tagalog-benchmark-v1.json").read_bytes())

    def test_pending_manifest_passes_without_mutation_or_review_claim(self):
        manifest = sample_manifest()
        original = copy.deepcopy(manifest)
        report = benchmark.audit_manifest(manifest)
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(manifest, original)
        self.assertEqual(report["split_counts"],
                         {"development": 1, "held_out": 1})
        self.assertEqual(report["review_counts"]["pending"], 2)
        self.assertEqual(report["focus_counts"]["connected_phrase"], 1)
        self.assertEqual(report["focus_counts"]["glottal_stop"], 0)
        self.assertEqual(report["pending_item_ids"], ["dev-01", "held-01"])
        self.assertFalse(report["native_review_verified"])
        self.assertEqual(report["warnings"][0]["code"],
                         "NATIVE_REVIEW_PENDING")

    def test_case_punctuation_spaces_and_apostrophes_cannot_cross_splits(self):
        for text in ("SI ANA'Y AAWIT!", "si ana’y aawit", "Si-Ana’y aawit?",
                     "  Si\tAna’y\naawit.  "):
            with self.subTest(text=text):
                manifest = sample_manifest()
                manifest["items"][1]["text"] = text
                report = benchmark.audit_manifest(manifest)
                self.assertIn("SPLIT_OVERLAP", error_codes(report))
                self.assertEqual(report["errors"][0]["item_ids"],
                                 ["dev-01", "held-01"])

    def test_nfc_equivalence_is_detected_but_diacritics_remain_distinct(self):
        manifest = sample_manifest()
        manifest["items"][0]["text"] = "Áawit tayo."
        manifest["items"][1]["text"] = "A\u0301AWIT tayo!"
        self.assertIn("SPLIT_OVERLAP", error_codes(
            benchmark.audit_manifest(manifest)))
        manifest["items"][0]["text"] = "Búkas ang pinto."
        manifest["items"][1]["text"] = "Bukás ang pinto."
        self.assertEqual(benchmark.audit_manifest(manifest)["status"], "pass")

    def test_same_split_text_repeat_is_not_cross_split_overlap(self):
        manifest = sample_manifest()
        repeated = copy.deepcopy(manifest["items"][0])
        repeated["id"] = "dev-02"
        manifest["items"].append(repeated)
        self.assertEqual(benchmark.audit_manifest(manifest)["status"], "pass")

    def test_duplicate_identifier_and_missing_split_are_errors(self):
        manifest = sample_manifest()
        manifest["items"][1]["id"] = "dev-01"
        self.assertIn("DUPLICATE_ID", error_codes(
            benchmark.audit_manifest(manifest)))
        manifest["items"][1]["id"] = "dev-02"
        manifest["items"][1]["split"] = "development"
        self.assertIn("MISSING_SPLIT", error_codes(
            benchmark.audit_manifest(manifest)))

    def test_reviewed_records_remain_declared_unverified_records(self):
        manifest = sample_manifest()
        for item, status in zip(manifest["items"],
                                ("approved", "needs_revision")):
            item["review"] = {
                "status": status, "reviewer_id": "reviewer-01",
                "reviewed_at": "2026-10-31",
                "pronunciation_notes": "Synthetic record for contract testing.",
            }
        report = benchmark.audit_manifest(manifest)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["review_counts"],
                         {"pending": 0, "approved": 1, "needs_revision": 1})
        self.assertFalse(report["native_review_verified"])
        self.assertEqual(report["needs_revision_item_ids"], ["held-01"])
        self.assertIn("NATIVE_REVIEW_NEEDS_REVISION",
                      [warning["code"] for warning in report["warnings"]])

    def test_incomplete_or_malformed_review_records_fail(self):
        base = {"status": "approved", "reviewer_id": "reviewer-01",
                "reviewed_at": "2026-10-31", "pronunciation_notes": "Checked."}
        changes = [
            {"reviewer_id": None}, {"reviewer_id": ""},
            {"reviewed_at": "2026-02-30"}, {"reviewed_at": "20261031"},
            {"reviewed_at": "2026-1-01"}, {"reviewed_at": 20261031},
            {"pronunciation_notes": " "}, {"pronunciation_notes": False},
            {"status": []}, {"status": "unknown"}, {"status": "pending"},
        ]
        for change in changes:
            with self.subTest(change=change):
                manifest = sample_manifest()
                manifest["items"][0]["review"] = {**base, **change}
                self.assertIn("ITEM", error_codes(
                    benchmark.audit_manifest(manifest)))
        manifest = sample_manifest()
        del manifest["items"][0]["review"]["reviewer_id"]
        self.assertIn("ITEM", error_codes(
            benchmark.audit_manifest(manifest)))

    def test_invalid_header_items_and_bounds_fail_without_type_errors(self):
        for change in ({"schema_version": True}, {"schema_version": 1.0},
                       {"benchmark_id": "bad id"}, {"language": "en"},
                       {"text_origin": "unknown"}, {"license": None},
                       {"items": []}, {"items": "wrong"}):
            with self.subTest(change=change):
                self.assertIn("MANIFEST", error_codes(
                    benchmark.audit_manifest({**sample_manifest(), **change})))
        for manifest in (None, [], True):
            self.assertIn("MANIFEST", error_codes(
                benchmark.audit_manifest(manifest)))
        manifest = sample_manifest()
        manifest["items"] *= benchmark.MAX_ITEMS
        self.assertIn("MANIFEST", error_codes(
            benchmark.audit_manifest(manifest)))

    def test_invalid_item_fields_and_text_limits_fail(self):
        changes = [
            {"id": ""}, {"id": "x" * 65}, {"split": []},
            {"text": "..."}, {"text": " "}, {"text": False},
            {"text": "x" * (benchmark.MAX_TEXT_CHARS + 1)},
            {"focus": "contraction"}, {"focus": []}, {"focus": [{}]},
            {"focus": ["unknown"]}, {"focus": ["contraction"] * 2},
        ]
        for change in changes:
            with self.subTest(change=change):
                manifest = sample_manifest()
                manifest["items"][0].update(change)
                self.assertIn("ITEM", error_codes(
                    benchmark.audit_manifest(manifest)))


class BenchmarkCommandLineTest(unittest.TestCase):

    def run_cli(
        self, path: pathlib.Path, *arguments: str
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "tagalog_singing_preflight", "benchmark",
             str(path), *arguments], cwd=ROOT, capture_output=True,
            encoding="utf-8", timeout=15, check=False)

    def test_valid_pending_cli_and_exclusive_report_preserve_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / "manifest.json"
            target = pathlib.Path(temporary) / "report.json"
            source.write_text(json.dumps(sample_manifest()), encoding="utf-8")
            original = source.read_bytes()
            result = self.run_cli(source, "--output", str(target))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(target.read_text(
                encoding="utf-8"))["native_review_verified"])
            preserved = target.read_bytes()
            result = self.run_cli(source, "--output", str(target))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(target.read_bytes(), preserved)
            self.assertEqual(source.read_bytes(), original)

    def test_contract_failures_are_one_and_json_io_failures_are_two(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / "manifest.json"
            source.write_text('{"schema_version": true}', encoding="utf-8")
            result = self.run_cli(source)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "fail")
            source.write_text("{broken", encoding="utf-8")
            result = self.run_cli(source)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stderr)["status"], "error")
            self.assertEqual(
                self.run_cli(source.parent / "absent").returncode, 2)


if __name__ == "__main__":
    unittest.main()
