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


class ReviewCheckTest(unittest.TestCase):

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.manifest["items"][0]["text"] = "Za\u0301 ng."
        self.lexicon = self.root / "synthetic.tsv"
        self.lexicon.write_text("Zá\tA\nZá\tˈB\n", encoding="utf-8")
        self.terms = {"source_label": "synthetic-v1", "data_license": "MIT"}
        self.draft = review_draft.prepare_draft(
            self.manifest, "dev-01", self.lexicon, **self.terms)

    def check(self, draft):
        return review_draft.check_draft(
            self.manifest, "dev-01", self.lexicon, draft, **self.terms)

    def approved(self):
        edited = copy.deepcopy(self.draft)
        edited["review"].update(
            status="approved", reviewer_id="fixture-only",
            reviewed_at="2026-11-06", pronunciation_notes="Synthetic record.")
        edited["occurrences"][0]["annotation"]["selected_source_row"] = 2
        edited["occurrences"][1]["annotation"].update(
            proposed_ipa_tokens=["ʔ", "a\u0301"], notes="Synthetic tokens.")
        return edited

    def test_approved_extracts_selected_and_supplied_tokens_in_context(self):
        edited = self.approved()
        before = copy.deepcopy(edited)
        report = self.check(edited)
        self.assertEqual(report["declared_review_status"], "approved")
        self.assertEqual(report["resolved_count"], 2)
        self.assertEqual(report["unresolved_count"], 0)
        self.assertEqual(report["resolved_occurrences"], [
            {"text": "Za\u0301", "start": 0, "end": 3,
             "ipa_tokens": ["ˈB"], "selected_source_row": 2},
            {"text": "ng", "start": 4, "end": 6,
             "ipa_tokens": ["ʔ", "a\u0301"], "selected_source_row": None},
        ])
        self.assertEqual(edited, before)
        self.assertFalse(report["native_review_verified"])
        self.assertNotIn("fixture-only", json.dumps(report))
        self.assertNotIn("Synthetic tokens.", json.dumps(report))

    def test_partial_decisions_do_not_export_pronunciations(self):
        edited = self.approved()
        edited["occurrences"][1]["annotation"]["proposed_ipa_tokens"] = None
        with self.assertRaises(ValueError):
            self.check(edited)
        edited["review"]["status"] = "needs_revision"
        report = self.check(edited)
        self.assertEqual(report["resolved_count"], 1)
        self.assertEqual(report["unresolved_count"], 1)
        self.assertEqual(report["resolved_occurrences"], [])
        self.assertEqual(self.check(self.draft)["declared_review_status"],
                         "pending")

    def test_rejects_changes_to_generated_context(self):
        for field, value in (
                ("original_text", "Zá ng."), ("item_id", "dev-02"),
                ("schema_version", True), ("permissions_verified", 0)):
            with self.subTest(field=field):
                edited = self.approved()
                edited[field] = value
                with self.assertRaises(ValueError):
                    self.check(edited)
        for field, value in (("end", 2), ("start", False), ("candidates", [])):
            with self.subTest(occurrence_field=field):
                edited = self.approved()
                edited["occurrences"][0][field] = value
                with self.assertRaises(ValueError):
                    self.check(edited)
        self.lexicon.write_text("Zá\tA\nZá\tˈC\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.check(self.approved())

    def test_rejects_conflicting_choices_and_invalid_values(self):
        for changes in (
                {"selected_source_row": True}, {"selected_source_row": 8},
                {"proposed_ipa_tokens": ["A"]}, {"notes": 7}):
            with self.subTest(changes=changes):
                edited = self.approved()
                edited["occurrences"][0]["annotation"].update(changes)
                with self.assertRaises(ValueError):
                    self.check(edited)
        for tokens in ([], ["a b"], ["a\x00"], ["a" * 1025]):
            with self.subTest(tokens=tokens):
                edited = self.approved()
                annotation = edited["occurrences"][1]["annotation"]
                annotation["proposed_ipa_tokens"] = tokens
                with self.assertRaises(ValueError):
                    self.check(edited)

    def test_cli_validates_edited_file_and_rejects_duplicate_keys(self):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        edited = self.root / "edited.json"
        original = json.dumps(self.approved()).encode("utf-8")
        edited.write_bytes(original)
        command = [
            sys.executable, "-m", "tagalog_singing_preflight", "review-check",
            str(manifest), "dev-01", str(self.lexicon), str(edited),
            "--source-label", "synthetic-v1", "--data-license", "MIT",
        ]
        valid = subprocess.run(command, cwd=ROOT, capture_output=True,
                               timeout=20, check=False)
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["resolved_count"], 2)
        self.assertEqual(edited.read_bytes(), original)
        edited.write_bytes(b'{"schema_version": 1,' + original[1:])
        report = self.root / "report.json"
        invalid = subprocess.run([*command, "--output", str(report)], cwd=ROOT,
                                 capture_output=True, timeout=20, check=False)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn(b"duplicate object member", invalid.stderr)
        self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
