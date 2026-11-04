"""Offline lookup regressions using invented labels and opaque test tokens."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tagalog_singing_preflight import lexicon
from tagalog_singing_preflight import text


ROOT = pathlib.Path(__file__).resolve().parents[1]


class LexiconTest(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = pathlib.Path(temporary.name)
        self.source = self.directory / "synthetic.tsv"
        self.write_tsv("zaya\tz a j a\n")

    def write_tsv(self, value: str) -> None:
        self.source.write_bytes(value.encode("utf-8"))

    def lookup(self, value: str = "zaya", **declarations) -> dict:
        return lexicon.lookup_text(
            value, self.source,
            source_label=declarations.get("source_label", "synthetic-v1"),
            data_license=declarations.get("data_license", "MIT"))

    def test_all_candidates_preserve_stress_glottals_and_atomic_tokens(self):
        self.write_tsv("zana\tˈz a n a\nzana\tz a ˈn a ʔ\n"
                       "zaya\tkʰ ã d͡ʒ\nzaya\t[opaque]\n")
        result = self.lookup("zana zaya missing")
        self.assertEqual(result["occurrence_counts"], {
            "single_candidate": 0, "multiple_candidates": 2, "missing": 1})
        self.assertEqual(result["occurrences"][0]["candidates"], [
            {"tokens": ["ˈz", "a", "n", "a"],
             "source_row": 1, "row_count": 1},
            {"tokens": ["z", "a", "ˈn", "a", "ʔ"],
             "source_row": 2, "row_count": 1}])
        self.assertEqual(result["occurrences"][1]["candidates"], [
            {"tokens": ["kʰ", "ã", "d͡ʒ"],
             "source_row": 3, "row_count": 1},
            {"tokens": ["[opaque]"], "source_row": 4, "row_count": 1}])
        self.assertEqual(result["occurrences"][2]["candidates"], [])

    def test_nfc_duplicates_keep_first_tokens_source_row_and_count(self):
        self.write_tsv("\nza\u0301\tˈz a\u0303 ʔ\n"
                       "zá\tˈz ã ʔ\nzá\tz a ˈʔ\n")
        result = self.lookup("zá")
        self.assertEqual(result["lexicon_row_count"], 3)
        self.assertEqual(result["lexicon_key_count"], 1)
        self.assertEqual(result["occurrences"][0]["candidates"], [
            {"tokens": ["ˈz", "a\u0303", "ʔ"],
             "source_row": 2, "row_count": 2},
            {"tokens": ["z", "a", "ˈʔ"],
             "source_row": 4, "row_count": 1}])

    def test_original_codepoint_offsets_survive_nfc_and_repeated_words(self):
        self.write_tsv("zá\tz a\n")
        original = "🎵 za\u0301! zá za\u0301"
        result = self.lookup(original)
        self.assertEqual(result["original_text"], original)
        self.assertEqual(result["offset_unit"], "Python Unicode code points")
        self.assertTrue(result["end_offset_exclusive"])
        self.assertEqual(
            [(item["text"], item["start"], item["end"], item["lookup_key"])
             for item in result["occurrences"]],
            [("za\u0301", 2, 5, "zá"), ("zá", 7, 9, "zá"),
             ("za\u0301", 10, 13, "zá")])
        for item in result["occurrences"]:
            self.assertEqual(original[item["start"]:item["end"]],
                             item["text"])

    def test_case_and_lexical_diacritics_are_not_guessed(self):
        self.write_tsv("zaya\tz a\nzáya\tz ˈa\n")
        result = self.lookup("zaya Zaya záya zàya za\u0301ya")
        self.assertTrue(result["case_sensitive"])
        self.assertEqual(result["key_normalization"], "NFC")
        self.assertEqual([item["status"] for item in result["occurrences"]],
                         ["single_candidate", "missing", "single_candidate",
                          "missing", "single_candidate"])

    def test_text_apostrophe_hint_does_not_change_lookup(self):
        self.write_tsv("za'ya\tz a\n")
        original = "za’ya za'ya"
        self.assertEqual(text.normalize_hint(original)["frontend_hint"],
                         "za'ya za'ya")
        result = self.lookup(original)
        self.assertEqual([item["text"] for item in result["occurrences"]],
                         ["za’ya", "za'ya"])
        self.assertEqual([item["status"] for item in result["occurrences"]],
                         ["missing", "single_candidate"])

    def test_initial_final_and_modifier_apostrophes_stay_in_whole_units(self):
        self.write_tsv("za\tz a\n'za\tʔ z a\n")
        units = ["'za", "za'", "‘za’", "ʼza", "zaʼ", "zaʔ"]
        result = self.lookup(" ".join(units))
        self.assertEqual([item["text"] for item in result["occurrences"]],
                         units)
        self.assertEqual([item["status"] for item in result["occurrences"]],
                         ["single_candidate"] + ["missing"] * 5)

    def test_hyphen_and_number_units_are_not_split_or_rewritten(self):
        self.write_tsv("za\tz a\nya\tj a\nza-ya\tz a j a\n")
        units = ["za-ya", "za‐ya", "za‑ya", "za1", "1za", "123"]
        result = self.lookup(" ".join(units))
        self.assertEqual([item["text"] for item in result["occurrences"]],
                         units)
        self.assertEqual([item["status"] for item in result["occurrences"]],
                         ["single_candidate"] + ["missing"] * 5)

    def test_ng_needs_an_explicit_whole_word_entry(self):
        self.write_tsv("n\tn\ng\tɡ\n")
        missing = self.lookup("ng")
        self.assertEqual(missing["occurrences"][0]["status"], "missing")
        self.write_tsv("ng\t[caller-supplied]\n")
        found = self.lookup("ng")
        self.assertEqual(found["occurrences"][0]["candidates"][0]["tokens"],
                         ["[caller-supplied]"])

    def test_bom_crlf_and_blank_rows_keep_physical_source_rows(self):
        self.source.write_bytes(
            b"\xef\xbb\xbf\r\nzaya\tz a\r\n\r\nzaya\tz a\r\n")
        original = self.source.read_bytes()
        result = self.lookup()
        self.assertEqual(result["lexicon_row_count"], 2)
        self.assertEqual(result["occurrences"][0]["candidates"], [
            {"tokens": ["z", "a"], "source_row": 2, "row_count": 2}])
        self.assertEqual(self.source.read_bytes(), original)

    def test_declarations_are_claims_and_assessment_flags_remain_false(self):
        result = self.lookup(source_label="Synthetic revision 2",
                             data_license="Caller-declared terms")
        self.assertEqual(result["source_declaration"], {
            "label": "Synthetic revision 2",
            "data_license": "Caller-declared terms"})
        for flag in ("permissions_verified", "native_review_verified",
                     "pronunciation_assessed", "model_phone_mapping_assessed"):
            self.assertIs(result[flag], False)
        self.assertIn("not contextual pronunciation",
                      result["assessment_limit"])
        self.assertIn("No candidate is selected", result["assessment_limit"])

    def test_both_source_and_data_license_declarations_are_required(self):
        for field in ("source_label", "data_license"):
            for value in (None, 1, "", "  ", "x\n", "x\t", "x\u2066",
                          "x" * 513):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, field):
                        self.lookup(**{field: value})
        with self.assertRaises(TypeError):
            lexicon.lookup_text("zaya", self.source)

    def test_nontext_blank_and_no_word_inputs_are_rejected(self):
        for value in (None, 42, [], "", " \t\n", "...", "---", "'''",
                      "\u0301"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.lookup(value)

    def test_malformed_rows_fail_with_the_physical_row(self):
        malformed = [
            "missing-tab", "zaya\tz a\textra", "\tz a", "zaya\t",
            "zaya\t   ", "two words\tz a", "zaya,\tz a", "---\tz a",
            "zaya\tz\u00a0a", "zaya\tz\v a", "zaya\tz\u200ba",
        ]
        for row in malformed:
            with self.subTest(row=row):
                self.write_tsv("\nzaya\tz a\n" + row + "\n")
                with self.assertRaisesRegex(ValueError, "row 3"):
                    self.lookup()

    def test_empty_and_non_utf8_lexicons_fail(self):
        for encoded in (b"", b"\n\r\n", b"\xef\xbb\xbf", b"\xff"):
            with self.subTest(encoded=encoded):
                self.source.write_bytes(encoded)
                with self.assertRaises((ValueError, UnicodeError)):
                    self.lookup()

    def test_missing_lexicon_reports_io_failure(self):
        with self.assertRaises(OSError):
            lexicon.lookup_text(
                "zaya", self.directory / "absent.tsv",
                source_label="synthetic-v1", data_license="MIT")

    def test_byte_limit_accepts_exact_size_and_rejects_one_extra_byte(self):
        encoded = self.source.read_bytes()
        with mock.patch.object(lexicon, "MAX_TSV_BYTES", len(encoded)):
            self.assertEqual(self.lookup()["lexicon_row_count"], 1)
            self.source.write_bytes(encoded + b"\n")
            with self.assertRaisesRegex(ValueError, "bytes"):
                self.lookup()

    def test_row_limit_counts_duplicate_rows_but_ignores_empty_lines(self):
        with mock.patch.object(lexicon, "MAX_ROWS", 1):
            self.write_tsv("\n\nzaya\tz a\n\n")
            self.assertEqual(self.lookup()["lexicon_row_count"], 1)
            self.write_tsv("zaya\tz a\nzaya\tz a\n")
            with self.assertRaisesRegex(ValueError, "nonempty rows"):
                self.lookup()

    def test_text_and_occurrence_limits_have_an_inclusive_boundary(self):
        with mock.patch.object(lexicon, "MAX_TEXT_CHARACTERS", 4):
            self.assertEqual(self.lookup("zaya")["original_text"], "zaya")
            with self.assertRaises(ValueError):
                self.lookup("zayaa")
        with mock.patch.object(lexicon, "MAX_OCCURRENCES", 2):
            self.assertEqual(len(self.lookup("zaya zaya")["occurrences"]), 2)
            with self.assertRaises(ValueError):
                self.lookup("zaya zaya zaya")

    def test_word_and_ipa_bounds_reject_oversized_fields(self):
        with mock.patch.object(lexicon, "MAX_WORD_CHARACTERS", 4):
            self.assertEqual(self.lookup()["lexicon_key_count"], 1)
            self.write_tsv("zayaa\tz a\n")
            with self.assertRaisesRegex(ValueError, "row 1"):
                self.lookup()
        with mock.patch.object(lexicon, "MAX_IPA_CHARACTERS", 3):
            self.write_tsv("zaya\tz a\n")
            self.assertEqual(self.lookup()["lexicon_key_count"], 1)
            self.write_tsv("zaya\tz aa\n")
            with self.assertRaisesRegex(ValueError, "row 1"):
                self.lookup()

    def test_variant_bound_counts_distinct_candidates_after_nfc(self):
        with mock.patch.object(lexicon, "MAX_VARIANTS", 2):
            self.write_tsv("zaya\ta\u0303\nzaya\tã\nzaya\tʔ\n")
            self.assertEqual(
                len(self.lookup()["occurrences"][0]["candidates"]), 2)
            self.write_tsv("zaya\tã\nzaya\tʔ\nzaya\tˈa\n")
            with self.assertRaisesRegex(ValueError, "distinct candidates"):
                self.lookup()


class LexiconCommandLineTest(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = pathlib.Path(temporary.name)
        self.source = self.directory / "synthetic.tsv"
        self.source.write_bytes("zá\tˈz a ʔ\n".encode("utf-8"))

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-S", "-m", "tagalog_singing_preflight",
             "lexicon", str(self.source), "zá absent", "--source-label",
             "synthetic-v1", "--data-license", "MIT", *arguments],
            cwd=ROOT, capture_output=True, timeout=15, check=False,
            env={**os.environ, "PYTHONIOENCODING": "cp1252"})

    def test_utf8_stdout_works_with_a_windows_legacy_encoding(self):
        original = self.source.read_bytes()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        self.assertIn("ˈz".encode("utf-8"), result.stdout)
        report = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(report["occurrence_counts"], {
            "single_candidate": 1, "multiple_candidates": 0, "missing": 1})
        self.assertFalse(report["pronunciation_assessed"])
        self.assertEqual(self.source.read_bytes(), original)

    def test_output_is_exclusive_utf8_and_preserves_source(self):
        target = self.directory / "report.json"
        original = self.source.read_bytes()
        result = self.run_cli("--output", str(target))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        saved = target.read_bytes()
        self.assertIn("ˈz".encode("utf-8"), saved)
        self.assertEqual(json.loads(saved)["original_text"], "zá absent")
        result = self.run_cli("--output", str(target))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["status"], "error")
        self.assertEqual(target.read_bytes(), saved)
        self.assertEqual(self.source.read_bytes(), original)

    def test_output_cannot_overwrite_its_lexicon(self):
        original = self.source.read_bytes()
        result = self.run_cli("--output", str(self.source))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.source.read_bytes(), original)

    def test_bad_inputs_leave_no_report_and_return_json_errors(self):
        target = self.directory / "report.json"
        for encoded in (b"bad-row\n", b"\xff", b""):
            with self.subTest(encoded=encoded):
                self.source.write_bytes(encoded)
                result = self.run_cli("--output", str(target))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(json.loads(result.stderr)["status"], "error")
                self.assertFalse(target.exists())
                self.assertEqual(self.source.read_bytes(), encoded)

    def test_cli_requires_source_and_data_license_options(self):
        for options in ([], ["--source-label", "synthetic-v1"],
                        ["--data-license", "MIT"]):
            with self.subTest(options=options):
                result = subprocess.run(
                    [sys.executable, "-S", "-m", "tagalog_singing_preflight",
                     "lexicon", str(self.source), "zá", *options],
                    cwd=ROOT, capture_output=True, timeout=15, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
