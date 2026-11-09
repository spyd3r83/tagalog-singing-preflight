"""Optionally compare an export with the actual pinned SoulX CPU processor.

Run as python -m examples.compare_soulx_cpu from a checkout. The caller supplies
an existing upstream checkout and its installed dependencies. No downloads,
weights, waveform inputs, model inference or GPU work are performed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import pathlib
import platform
import sys
import tempfile

from tagalog_singing_preflight import __main__ as cli
from tagalog_singing_preflight import native_comparison
from tagalog_singing_preflight import soulx


PROCESSOR_SHA256 = (
    "14baf4c7784cea85bd58f0c29bd504d3ae46809931c0d40b16183a39581290cb"
)


def run_comparison(
    export: object,
    vocabulary: list[str],
    upstream: pathlib.Path,
    expected_frames: int,
    sample_rate: int = 24000,
    hop_size: int = 480,
) -> dict:
    """Run an unchanged local processor on copied content-note metadata.

    The source digest binds this check to soulx.UPSTREAM_COMMIT. Imported native
    dependencies and the caller's local checkout must also be trusted. No native
    package or dependency is copied into this repository.
    """
    if not isinstance(export, dict) or not isinstance(export.get("metadata"),
                                                    dict):
        raise ValueError("Input must be a soulx-export report with metadata.")
    metadata = export["metadata"]
    # Reject unsupported metadata before importing optional tensor libraries.
    checked = soulx.audit_metadata(metadata, vocabulary, expected_frames,
                                    sample_rate, hop_size)
    if checked["status"] != "pass":
        raise ValueError("Export metadata does not pass the native audit: "
                         + ", ".join(x["code"] for x in checked["errors"]))
    if metadata.get("f0", "") or any(
            phone in {"<PAD>", "<BOW>", "<EOW>", "<SEP>", "<SP>"}
            or "<AP>" in phone for phone in metadata["phoneme"].split()):
        raise ValueError("Comparison supports content notes without F0 only.")
    source = upstream / "soulxsinger/utils/data_processor.py"
    if hashlib.sha256(source.read_bytes()).hexdigest() != PROCESSOR_SHA256:
        raise ValueError("Local data_processor.py differs from the pinned "
                         "source; it was not imported.")
    spec = importlib.util.spec_from_file_location("soulx_cpu_processor", source)
    module = importlib.util.module_from_spec(spec)
    bytecode_setting = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(upstream))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
        sys.dont_write_bytecode = bytecode_setting
    # Give the native constructor a file with the exact validated phoneset.
    with tempfile.TemporaryDirectory() as tmp:
        phoneset = pathlib.Path(tmp) / "phoneset.json"
        phoneset.write_text(json.dumps(vocabulary), encoding="utf-8")
        processor = module.DataProcessor(hop_size, sample_rate, str(phoneset),
                                         device="cpu")
        item = processor.process(copy.deepcopy(metadata))
    vectors = {}
    for field in native_comparison.FIELDS:
        if item[field].device.type != "cpu":
            raise ValueError(f"Native {field} was not returned on CPU.")
        vectors[field] = item[field].tolist()
    report = native_comparison.compare_processed(
        metadata, vocabulary, vectors, expected_frames, sample_rate, hop_size)
    report["checks"]["f0_absence_preserved"] = item["f0"] is None
    report["status"] = ("pass" if all(report["checks"].values()) else "fail")
    report.update({
        "native_processor_executed": True,
        "upstream_commit": soulx.UPSTREAM_COMMIT,
        "processor_sha256": PROCESSOR_SHA256,
        "runtime": {"python": platform.python_version(), "device": "cpu",
                    **{name: sys.modules[name].__version__
                       for name in ("torch", "numpy", "torchaudio")}},
    })
    return report


def main(argv: list[str] | None = None) -> int:
    """Exit 1 for differences or 2 for unusable inputs; create a new report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=pathlib.Path)
    parser.add_argument("phoneset", type=pathlib.Path)
    parser.add_argument("--upstream", type=pathlib.Path, required=True)
    parser.add_argument("--expected-frames", type=int, required=True)
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--hop-size", type=int, default=480)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        report = run_comparison(
            cli._load_json(args.export, unique_keys=True),
            cli._load_json(args.phoneset), args.upstream, args.expected_frames,
            args.sample_rate, args.hop_size)
        encoded = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8",
                                  newline="\n") as target:
                target.write(encoded)
        else:
            sys.stdout.write(encoded)
        return 0 if report["status"] == "pass" else 1
    except (OSError, UnicodeError, ValueError, ImportError,
            RuntimeError) as error:
        sys.stderr.write(json.dumps({"status": "error", "error": str(error)})
                         + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
