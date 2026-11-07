"""Command-line entry point for offline singing-input preflight checks."""

from __future__ import annotations

import argparse
import decimal
import json
import pathlib
import sys

from tagalog_singing_preflight import audit
from tagalog_singing_preflight import benchmark
from tagalog_singing_preflight import lexicon
from tagalog_singing_preflight import listening
from tagalog_singing_preflight import phone_mapping
from tagalog_singing_preflight import responses
from tagalog_singing_preflight import review_draft
from tagalog_singing_preflight import soulx
from tagalog_singing_preflight import text
from tagalog_singing_preflight import voicing


MAX_JSON_BYTES = 32 * 1024 * 1024


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON input contains a duplicate object member.")
        result[key] = value
    return result


def _load_json(path: pathlib.Path, *, unique_keys: bool = False) -> object:
    with path.open("rb") as source:
        encoded = source.read(MAX_JSON_BYTES + 1)
    if len(encoded) > MAX_JSON_BYTES:
        raise ValueError(f"JSON input exceeds {MAX_JSON_BYTES} bytes.")
    try:
        return json.loads(
            encoded.decode("utf-8-sig"), parse_float=decimal.Decimal,
            object_pairs_hook=_unique_json_object if unique_keys else None)
    except RecursionError as error:
        raise ValueError("JSON input is nested too deeply.") from error


def main(argv: list[str] | None = None) -> int:
    """Run a check; exit 1 for a failed contract, 2 for malformed input/output."""
    parser = argparse.ArgumentParser(
        description="Offline metadata checks; not a pronunciation or singing model.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    text_parser = subparsers.add_parser("text", help="Preserve text and show hints.")
    text_parser.add_argument("text")
    lexicon_parser = subparsers.add_parser(
        "lexicon", help="Look up all candidates in a caller-supplied local TSV.")
    lexicon_parser.add_argument("lexicon", type=pathlib.Path)
    lexicon_parser.add_argument("text")
    lexicon_parser.add_argument("--source-label", required=True)
    lexicon_parser.add_argument("--data-license", required=True)
    audit_parser = subparsers.add_parser("audit", help="Audit a JSON plan.")
    audit_parser.add_argument("plan", type=pathlib.Path)
    benchmark_parser = subparsers.add_parser(
        "benchmark", help="Audit an original phrase benchmark manifest.")
    benchmark_parser.add_argument("manifest", type=pathlib.Path)
    review_parser = subparsers.add_parser(
        "review-draft", help="Prepare a pronunciation review for one phrase.")
    check_parser = subparsers.add_parser(
        "review-check", help="Check an edited pronunciation review.")
    mapping_parser = subparsers.add_parser(
        "phone-map", help="Apply explicit rules to a checked review.")
    for parser_for_review in (review_parser, check_parser, mapping_parser):
        parser_for_review.add_argument("manifest", type=pathlib.Path)
        parser_for_review.add_argument("item_id")
        parser_for_review.add_argument("lexicon", type=pathlib.Path)
        parser_for_review.add_argument("--source-label", required=True)
        parser_for_review.add_argument("--data-license", required=True)
    check_parser.add_argument("review", type=pathlib.Path)
    mapping_parser.add_argument("review", type=pathlib.Path)
    mapping_parser.add_argument("mapping", type=pathlib.Path)
    mapping_parser.add_argument("vocabulary", type=pathlib.Path)
    listening_parser = subparsers.add_parser(
        "listening", help="Prepare a new local randomized listening packet.")
    listening_parser.add_argument("manifest", type=pathlib.Path)
    listening_parser.add_argument("plan", type=pathlib.Path)
    listening_parser.add_argument("output_dir", type=pathlib.Path)
    listening_parser.add_argument("--seed", type=int, required=True)
    listening_parser.add_argument("--packet-version", type=int, choices=(1, 2),
                                  default=2)
    listening_parser.add_argument(
        "--attribute", choices=list(listening.ATTRIBUTES),
        default="pronunciation")
    responses_parser = subparsers.add_parser(
        "responses", help="Tally declared responses for one local packet.")
    responses_parser.add_argument("packet", type=pathlib.Path)
    responses_parser.add_argument("csv", type=pathlib.Path)
    responses_parser.add_argument("--listener-id", required=True)
    voicing_parser = subparsers.add_parser("voicing", help="Compare aligned F0 masks.")
    voicing_parser.add_argument("guide", type=pathlib.Path)
    voicing_parser.add_argument("conditioning", type=pathlib.Path)
    soulx_parser = subparsers.add_parser(
        "soulx", help="Audit native SoulX SVS strings.")
    soulx_parser.add_argument("metadata", type=pathlib.Path)
    soulx_parser.add_argument("phoneset", type=pathlib.Path)
    soulx_parser.add_argument("--expected-frames", type=int, required=True)
    soulx_parser.add_argument("--sample-rate", type=int, default=24000)
    soulx_parser.add_argument("--hop-size", type=int, default=480)
    for subparser in (text_parser, lexicon_parser, audit_parser, benchmark_parser,
                      review_parser, check_parser, mapping_parser,
                      responses_parser, voicing_parser, soulx_parser):
        subparser.add_argument("--output", type=pathlib.Path,
                               help="Create a new JSON report; refuse overwrite.")
    args = parser.parse_args(argv)
    try:
        if args.command == "text":
            result = {"schema_version": 1, "status": "pass",
                      "assessment_limit": audit.LIMIT,
                      "text": text.normalize_hint(args.text)}
        elif args.command == "lexicon":
            result = lexicon.lookup_text(
                args.text, args.lexicon, source_label=args.source_label,
                data_license=args.data_license)
        elif args.command == "audit":
            result = audit.audit_plan(_load_json(args.plan))
        elif args.command == "benchmark":
            result = benchmark.audit_manifest(_load_json(args.manifest))
        elif args.command == "review-draft":
            result = review_draft.prepare_draft(
                _load_json(args.manifest), args.item_id, args.lexicon,
                source_label=args.source_label, data_license=args.data_license)
        elif args.command == "review-check":
            result = review_draft.check_draft(
                _load_json(args.manifest), args.item_id, args.lexicon,
                _load_json(args.review, unique_keys=True),
                source_label=args.source_label, data_license=args.data_license)
        elif args.command == "phone-map":
            result = phone_mapping.map_review(
                _load_json(args.manifest), args.item_id, args.lexicon,
                _load_json(args.review, unique_keys=True),
                _load_json(args.mapping, unique_keys=True),
                _load_json(args.vocabulary),
                source_label=args.source_label, data_license=args.data_license)
        elif args.command == "listening":
            result = listening.prepare_packet(
                _load_json(args.manifest), _load_json(args.plan),
                args.plan.parent, args.output_dir, args.seed, args.attribute,
                args.packet_version)
        elif args.command == "responses":
            result = responses.summarize_packet(
                args.packet, args.csv, args.listener_id)
        elif args.command == "soulx":
            result = soulx.audit_metadata(
                _load_json(args.metadata), _load_json(args.phoneset),
                args.expected_frames, args.sample_rate, args.hop_size)
        else:
            comparison = voicing.compare_voicing(
                _load_json(args.guide), _load_json(args.conditioning))
            result = {"schema_version": 1,
                      "status": ("pass" if comparison["voicing_masks_match"]
                                 else "fail"),
                      "assessment_limit": audit.LIMIT,
                      "voicing": comparison}
        encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if getattr(args, "output", None):
            with args.output.open("x", encoding="utf-8", newline="\n") as target:
                target.write(encoded)
        else:
            # stdout can be CP1252 on Windows. Emit JSON UTF-8 bytes when possible.
            if hasattr(sys.stdout, "buffer"):
                sys.stdout.buffer.write(encoded.encode("utf-8"))
            else:
                sys.stdout.write(encoded)
        return 0 if result["status"] == "pass" else 1
    except (OSError, UnicodeError, ValueError, decimal.InvalidOperation) as error:
        sys.stderr.write(json.dumps({"status": "error", "error": str(error)},
                                    ensure_ascii=True) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
