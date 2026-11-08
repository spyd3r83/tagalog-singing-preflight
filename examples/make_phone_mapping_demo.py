"""Prepare original synthetic review decisions and token-mapping fixtures."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    """Create synthetic mapping fixtures, optionally with native note spans."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--native-notes", action="store_true",
                        help="Use illustrative en_ tokens and a note plan.")
    args = parser.parse_args()
    draft = subprocess.run(
        [sys.executable, "-m", "tagalog_singing_preflight", "review-draft",
         "data/tagalog-benchmark-v1.json", "dev-05",
         "examples/lexicon-demo.tsv", "--source-label", "synthetic-demo",
         "--data-license", "MIT"],
        cwd=ROOT, capture_output=True, check=True, timeout=30)
    review = json.loads(draft.stdout)
    review["review"].update(
        status="approved", reviewer_id="synthetic-demo",
        reviewed_at="2026-11-07",
        pronunciation_notes="Generated mock decisions for tooling only.")
    for occurrence in review["occurrences"]:
        occurrence["annotation"]["proposed_ipa_tokens"] = ["ˈdemo", "ʔ"]
    mapping = {
        "schema_version": 1, "mapping_id": "synthetic-demo",
        "target_model": "synthetic-token-model-v1",
        "rules": {"ˈdemo": ["T_STRESS", "T_DEMO"], "ʔ": ["T_GLOTTAL"]},
    }
    fixtures = {
        "review.json": review, "mapping.json": mapping,
        "vocabulary.json": ["T_STRESS", "T_DEMO", "T_GLOTTAL"],
    }
    if args.native_notes:
        mapping["target_model"] = "soulx-synthetic-contract-v1"
        mapping["rules"] = {"ˈdemo": ["en_S", "en_AH0"], "ʔ": ["en_B"]}
        fixtures["vocabulary.json"] = json.loads(
            (ROOT / "examples/soulx-example-phoneset.json").read_text("utf-8"))
        fixtures["note-plan.json"] = {
            "schema_version": 1,
            "notes": [
                {"occurrence_index": index, "token_start": 0, "token_end": 3,
                 "duration": "0.5", "note_pitch": 60, "note_type": 2}
                for index in range(len(review["occurrences"]))
            ],
        }
    args.destination.mkdir()
    for filename, value in fixtures.items():
        with (args.destination / filename).open(
                "x", encoding="utf-8", newline="\n") as target:
            json.dump(value, target, ensure_ascii=False, indent=2)
            target.write("\n")
    print("Created synthetic mapping fixtures with generated mock decisions.")


if __name__ == "__main__":
    main()
