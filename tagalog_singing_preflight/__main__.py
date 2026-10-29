"""Command-line entry point for offline singing-input preflight checks."""

from __future__ import annotations

import argparse
import decimal
import json
import pathlib
import sys

from tagalog_singing_preflight import audit
from tagalog_singing_preflight import soulx
from tagalog_singing_preflight import text
from tagalog_singing_preflight import voicing


MAX_JSON_BYTES = 32 * 1024 * 1024


def _load_json(path: pathlib.Path) -> object:
    with path.open("rb") as source:
        encoded = source.read(MAX_JSON_BYTES + 1)
    if len(encoded) > MAX_JSON_BYTES:
        raise ValueError(f"JSON input exceeds {MAX_JSON_BYTES} bytes.")
    return json.loads(encoded.decode("utf-8-sig"), parse_float=decimal.Decimal)


def main(argv: list[str] | None = None) -> int:
    """Run a check; exit 1 for a failed contract, 2 for malformed input/output."""
    parser = argparse.ArgumentParser(
        description="Offline metadata checks; not a pronunciation or singing model.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    text_parser = subparsers.add_parser("text", help="Preserve text and show hints.")
    text_parser.add_argument("text")
    audit_parser = subparsers.add_parser("audit", help="Audit a JSON plan.")
    audit_parser.add_argument("plan", type=pathlib.Path)
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
    for subparser in (text_parser, audit_parser, voicing_parser, soulx_parser):
        subparser.add_argument("--output", type=pathlib.Path,
                               help="Create a new JSON report; refuse overwrite.")
    args = parser.parse_args(argv)
    try:
        if args.command == "text":
            result = {"schema_version": 1, "status": "pass",
                      "assessment_limit": audit.LIMIT,
                      "text": text.normalize_hint(args.text)}
        elif args.command == "audit":
            result = audit.audit_plan(_load_json(args.plan))
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
        if args.output:
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
