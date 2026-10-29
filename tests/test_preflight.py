"""Regression tests for public metadata contracts using original synthetic data."""

from __future__ import annotations

import copy
import decimal
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tagalog_singing_preflight import audit
from tagalog_singing_preflight import phonemes
from tagalog_singing_preflight import text
from tagalog_singing_preflight import timing
from tagalog_singing_preflight import voicing


ROOT = pathlib.Path(__file__).resolve().parents[1]


def example_plan() -> dict:
    return json.loads((ROOT / "examples" / "valid-plan.json").read_text(
        encoding="utf-8"))


def track(values: list, rate: object = 50, origin: object = "0") -> dict:
    return {"frame_rate_hz": rate, "origin_seconds": origin, "values": values}


class TextTest(unittest.TestCase):

    def test_original_diacritics_and_whitespace_survive(self):
        original = "  Si Ana’y a\u0301awit.  "
        result = text.normalize_hint(original)
        self.assertEqual(result["original"], original)
        self.assertEqual(result["nfc"], "  Si Ana’y áawit.  ")
        self.assertEqual(result["frontend_hint"], "  Si Ana'y áawit.  ")
        self.assertFalse(result["pronunciation_assessed"])

    def test_glottal_and_quote_marks_are_not_conflated(self):
        result = text.normalize_hint("‘Ana’ ʔa aʼa")
        self.assertEqual(result["frontend_hint"], "‘Ana’ ʔa aʼa")
        self.assertEqual(result["apostrophe_hint_indices"], [])
        self.assertTrue(any(w["code"] == "GLOTTAL_SYMBOL_PRESERVED"
                            for w in result["warnings"]))

    def test_empty_or_nontext_is_rejected(self):
        for value in ("", "  ", None, ["word"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                text.normalize_hint(value)


class TimingTest(unittest.TestCase):

    def test_sum_before_floor_loses_a_frame_but_exact_allocation_does_not(self):
        result = timing.allocate_frames(["0.1"] * 7, 50, 35)
        self.assertEqual(result["legacy_float_floor_total_frames"], 35)
        # Use the familiar decimal-sum loss at a clock where it crosses a frame.
        result = timing.allocate_frames(["0.1"] * 10, 50, 50)
        self.assertEqual(result["legacy_float_floor_total_frames"], 49)
        self.assertEqual(result["exact_sum_floor_total_frames"], 50)
        self.assertEqual(result["total_frames"], 50)
        self.assertEqual(sum(result["group_frames"]), 50)

    def test_cumulative_rounding_preserves_total(self):
        result = timing.allocate_frames(["0.03", "0.03", "0.04"], 50, 5)
        self.assertEqual(result["group_frames"], [2, 1, 2])
        self.assertEqual(result["boundaries_frames"], [0, 2, 3, 5])

    def test_per_group_float_floor_is_a_separate_diagnostic(self):
        result = timing.allocate_frames(["0.58", "0.42"], 50, 50)
        self.assertEqual(result["total_frames"], 50)
        self.assertEqual(result["legacy_float_floor_total_frames"], 50)
        self.assertEqual(result["legacy_per_group_float_floor_total_frames"], 49)

    def test_invalid_numbers_do_not_become_silence_or_frames(self):
        for value in ("NaN", "Infinity", "-0.1", True, None, "not-a-number"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                timing.allocate_frames([value])
        for rate in (0, -50, "NaN", False):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                timing.allocate_frames(["0.2"], rate)

    def test_explicit_expected_clock_is_checked(self):
        self.assertFalse(timing.allocate_frames(["0.2"], 50, 11)[
            "expected_frames_match"])
        with self.assertRaises(ValueError):
            timing.allocate_frames(["0.2"], 50, True)


class PhonemesTest(unittest.TestCase):

    def test_unknown_phone_has_group_location_without_fallback(self):
        result = phonemes.check_vocabulary(["A T", "fil_Q"], ["A", "T"])
        self.assertEqual(result["unknown_tokens"], [
            {"group_index": 1, "token": "fil_Q"}])
        self.assertFalse(result["tokens_supported_by_declared_vocabulary"])
        self.assertFalse(result["pronunciation_assessed"])

    def test_groups_are_not_split_into_duration_units(self):
        result = phonemes.check_vocabulary(["A T", "O"], ["A", "T", "O"])
        self.assertEqual(result["group_count"], 2)
        self.assertEqual(result["token_count"], 3)

    def test_invalid_vocabulary_rejected(self):
        with self.assertRaises(ValueError):
            phonemes.check_vocabulary(["A"], ["A B"])


class VoicingTest(unittest.TestCase):

    def test_mask_diagnostic_preserves_source_intervals(self):
        result = voicing.compare_voicing(
            track([0, 200, 200, 0, 220, 220]),
            track([0, 200, 0, 0, 220, 0]))
        self.assertEqual(result["mismatched_voicing_frames"], 2)
        self.assertEqual(result["mismatch_intervals"][0], {
            "start_frame": 2, "end_frame_exclusive": 3,
            "start_seconds": "0.04", "end_seconds_exclusive": "0.06"})
        self.assertTrue(result["both_voiced_pitch_values_equal"])
        self.assertFalse(result["pronunciation_assessed"])

    def test_clock_origin_length_must_match(self):
        for other in (track([200], 100), track([200], origin="0.02"),
                      track([200, 0])):
            with self.subTest(other=other), self.assertRaises(ValueError):
                voicing.compare_voicing(track([200]), other)

    def test_empty_or_invalid_f0_is_rejected(self):
        for values in ([], [float("nan")], [-1], [True]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                voicing.compare_voicing(track(values), track(values))

    def test_no_common_pitch_evidence_is_null(self):
        result = voicing.compare_voicing(track([0]), track([0]))
        self.assertIsNone(result["both_voiced_pitch_values_equal"])


class AuditTest(unittest.TestCase):

    def test_valid_plan_passes_without_mutation_or_diction_claim(self):
        plan = example_plan()
        original = copy.deepcopy(plan)
        report = audit.audit_plan(plan)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(plan, original)
        self.assertIn("unassessed", report["assessment_limit"])

    def test_legacy_backend_loss_fails_and_corrected_mode_passes(self):
        plan = example_plan()
        plan.update(phoneme_groups=["A"] * 10,
                    durations_seconds=["0.1"] * 10,
                    timing_mode="legacy_sum_float_floor")
        failed = audit.audit_plan(plan)
        self.assertEqual(failed["status"], "fail")
        self.assertIn("BACKEND_FRAME_TOTAL", [e["code"] for e in failed["errors"]])
        plan["timing_mode"] = "cumulative_half_up"
        self.assertEqual(audit.audit_plan(plan)["status"], "pass")

    def test_missing_expected_count_or_wrong_schema_is_rejected(self):
        for value in (None, True, 50.0, 0):
            plan = example_plan()
            plan["expected_frames"] = value
            self.assertEqual(audit.audit_plan(plan)["status"], "fail")
        plan = example_plan()
        plan["schema_version"] = decimal.Decimal("1.0")
        self.assertEqual(audit.audit_plan(plan)["status"], "fail")

    def test_group_count_unknown_token_and_zero_frame_are_errors(self):
        for change in ({"phoneme_groups": ["A"]},
                       {"vocabulary": ["A"]},
                       {"durations_seconds": ["0.001", "0.219", "0.2", "0.58"]}):
            plan = example_plan()
            plan.update(change)
            self.assertEqual(audit.audit_plan(plan)["status"], "fail")

    def test_f0_must_share_plan_rate_and_frame_count(self):
        plan = example_plan()
        plan["guide_f0"] = track([200] * 50, rate="50.0")
        plan["conditioning_f0"] = track([200] * 50)
        self.assertEqual(audit.audit_plan(plan)["status"], "pass")
        plan["conditioning_f0"]["values"][3] = 0
        self.assertEqual(audit.audit_plan(plan)["status"], "fail")
        del plan["conditioning_f0"]
        self.assertIn("F0_PAIR", [e["code"] for e in audit.audit_plan(plan)["errors"]])


class CommandLineTest(unittest.TestCase):

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "tagalog_singing_preflight",
                               *arguments], cwd=ROOT, capture_output=True,
                              encoding="utf-8", timeout=15, check=False)

    def test_real_valid_and_mismatch_commands(self):
        valid = self.run_cli("audit", "examples/valid-plan.json")
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["status"], "pass")
        legacy = self.run_cli("audit", "examples/float-floor-plan.json")
        self.assertEqual(legacy.returncode, 1, legacy.stderr)
        self.assertEqual(json.loads(legacy.stdout)["timing"][
            "legacy_float_floor_total_frames"], 49)
        mismatch = self.run_cli("voicing", "examples/guide-f0.json",
                                "examples/conditioning-f0.json")
        self.assertEqual(mismatch.returncode, 1, mismatch.stderr)
        self.assertEqual(json.loads(mismatch.stdout)["voicing"][
            "mismatched_voicing_frames"], 2)

    def test_report_creation_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "report.json"
            first = self.run_cli("text", "Si Ana’y áawit.", "--output", str(output))
            self.assertEqual(first.returncode, 0, first.stderr)
            preserved = output.read_bytes()
            second = self.run_cli("text", "Different text", "--output", str(output))
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output.read_bytes(), preserved)

    def test_malformed_input_returns_json_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            malformed = pathlib.Path(temporary) / "bad.json"
            malformed.write_text("{broken", encoding="utf-8")
            result = self.run_cli("audit", str(malformed))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stderr)["status"], "error")


if __name__ == "__main__":
    unittest.main()
