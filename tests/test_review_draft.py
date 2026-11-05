"""Exercise the development-phrase handoff without language or audio claims."""

from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tagalog_singing_preflight import review_draft


ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "tagalog-benchmark-v1.json"
LEXICON = ROOT / "examples" / "lexicon-demo.tsv"


class ReviewDraftTest(unittest.TestCase):

    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.item = next(item for item in self.manifest["items"]
                         if item["id"] == "dev-05")

    def draft(self, item_id="dev-05", lexicon_path=LEXICON):
        return review_draft.prepare_draft(
            self.manifest, item_id, lexicon_path,
            source_label="original-demo", data_license="MIT")

    def test_context_preserves_candidates_and_keeps_decisions_unset(self):
        # Invented test tokens; these are not Tagalog pronunciations.
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "invented.tsv"
            path.write_text("Ako’y\tA\nAko’y\tB\nay\tC\n", encoding="utf-8")
            original = copy.deepcopy(self.manifest)
            before = path.read_bytes()
            report = self.draft(lexicon_path=path)
            self.assertEqual(self.draft(lexicon_path=path), report)
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.manifest, original)
        self.assertEqual(report["benchmark_id"], self.manifest["benchmark_id"])
        self.assertEqual(report["item_id"], "dev-05")
        self.assertEqual(report["split"], "development")
        self.assertEqual(report["original_text"], self.item["text"])
        self.assertEqual(report["focus"], self.item["focus"])
        self.assertEqual(report["source_declaration"],
                         {"label": "original-demo", "data_license": "MIT"})
        first, second, *_ = report["occurrences"]
        self.assertEqual((first["text"], first["start"], first["end"]),
                         ("Ako’y", 0, 5))
        self.assertEqual(first["status"], "multiple_candidates")
        self.assertEqual([c["tokens"] for c in first["candidates"]],
                         [["A"], ["B"]])
        self.assertEqual(second["status"], "missing")
        self.assertEqual(report["occurrence_counts"], {
            "single_candidate": 1, "multiple_candidates": 1, "missing": 4})
        for occurrence in report["occurrences"]:
            self.assertEqual(occurrence["annotation"], {
                "selected_source_row": None, "proposed_ipa_tokens": None,
                "notes": None})

    def test_previous_review_does_not_approve_the_new_draft(self):
        self.item["review"] = {
            "status": "approved", "reviewer_id": "synthetic-reviewer",
            "reviewed_at": "2026-11-05", "pronunciation_notes": "Fixture only."}
        draft = self.draft()
        self.assertEqual(draft["review"], {
            "status": "pending", "reviewer_id": None, "reviewed_at": None,
            "pronunciation_notes": None})
        for flag in ("permissions_verified", "native_review_verified",
                     "pronunciation_assessed", "model_phone_mapping_assessed"):
            self.assertIs(draft[flag], False)
        self.assertEqual(self.item["review"]["status"], "approved")

    def test_held_out_and_unknown_ids_are_rejected_before_lexicon_read(self):
        held_id = next(item["id"] for item in self.manifest["items"]
                       if item["split"] == "held_out")
        with tempfile.TemporaryDirectory() as tmp:
            absent = pathlib.Path(tmp) / "absent.tsv"
            with self.assertRaisesRegex(ValueError, "development"):
                self.draft(held_id, absent)
            with self.assertRaisesRegex(ValueError, "absent-item"):
                self.draft("absent-item", absent)

    def test_invalid_manifest_cannot_produce_a_draft(self):
        self.manifest["items"].append(copy.deepcopy(self.item))
        with self.assertRaises(ValueError):
            self.draft()

    def test_cli_creates_a_pending_draft_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "review.json"
            command = [
                sys.executable, "-m", "tagalog_singing_preflight",
                "review-draft", str(MANIFEST), "dev-05", str(LEXICON),
                "--source-label", "synthetic-demo", "--data-license", "MIT",
                "--output", str(output),
            ]
            first = subprocess.run(command, cwd=ROOT, capture_output=True,
                                   timeout=20, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            saved = output.read_bytes()
            draft = json.loads(saved)
            self.assertEqual(draft["review"]["status"], "pending")
            self.assertEqual(draft["original_text"], self.item["text"])
            self.assertEqual(draft["occurrence_counts"]["missing"], 6)
            retry = subprocess.run(command, cwd=ROOT, capture_output=True,
                                   timeout=20, check=False)
            self.assertEqual(retry.returncode, 2)
            self.assertEqual(output.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
