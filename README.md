# Tagalog Singing Preflight

Catch mechanical input errors before a singing-synthesis run: unsupported phoneme tokens, lost timing frames, and incompatible voicing guides. This small, offline Python library grew from Tagalog singing experiments. Its timing and voicing checks are language-independent.

It preserves the original text and reports what it can check. A passing report does **not** establish correct pronunciation, stress, singer identity, or musical quality. This is not a singing model or a Tagalog language pack.

## Run it

Python 3.10 or later is required. There are no runtime dependencies, accounts, or model downloads. From a checkout:

```sh
git clone https://github.com/spyd3r83/tagalog-singing-preflight.git
cd tagalog-singing-preflight
python -m tagalog_singing_preflight audit examples/valid-plan.json
python -m unittest discover -s tests -v
```

The first command returns JSON with `"status": "pass"` and exits with code 0. To preserve a report, add `--output report.json`; an existing file is never overwritten. Inputs are read without modification.

Two examples deliberately fail:

```sh
python -m tagalog_singing_preflight audit examples/float-floor-plan.json
python -m tagalog_singing_preflight voicing examples/guide-f0.json examples/conditioning-f0.json
```

Both exit with code 1. The timing example declares ten 0.1-second groups at 50 Hz. Binary-float sum followed by floor yields 49 frames; exact-decimal cumulative rounding yields 50. Change its `timing_mode` to `cumulative_half_up` in a copy to obtain a passing plan. The voicing example reports two mismatched frames and their intervals.

Exit codes are 0 for a mechanical pass, 1 for an audit or voicing mismatch, and 2 for malformed input, invalid direct-voicing contracts, or an input/output error. Invalid fields inside a parsed audit plan are reported as audit failures. A pass can still contain warnings.

## Declare the input contract

The original short phrase and token groups below are illustrative; they are not a verified phonetic transcription.

```json
{
  "schema_version": 1,
  "text": "Sabay tayo.",
  "phoneme_groups": ["S A", "B A Y", "T A", "Y O"],
  "vocabulary": ["S", "A", "B", "Y", "T", "O"],
  "durations_seconds": ["0.18", "0.22", "0.20", "0.40"],
  "frame_rate_hz": 50,
  "expected_frames": 50,
  "timing_mode": "cumulative_half_up"
}
```

Each phoneme group has one duration. Tokens within a group are separated by whitespace. The supplied vocabulary must come from the receiving model's actual frontend; declaring a token here does not add it to a model's embeddings. Unknown tokens are rejected with group locations, without a fallback to silence.

Use decimal strings for intended durations. Allocation rounds cumulative boundaries half-up, then subtracts adjacent boundaries. Reports include group frames, total frames, zero-frame groups, and separate diagnostics for float sum/floor and per-group float floor. The audit requires a positive expected count and rejects zero-frame groups. `legacy_sum_float_floor` audits that explicitly selected legacy behavior; `cumulative_half_up` audits the new allocator.

**Integration is explicit:** use the reported `group_frames` in an adapter that accepts frame counts. Running this tool does not patch a model's timing code or make a float-based backend use the corrected allocation.

Optional `guide_f0` and `conditioning_f0` must appear together. Each has this shape:

```json
{"frame_rate_hz": 50, "origin_seconds": "0", "values": [0, 200, 200]}
```

Zero means unvoiced; positive values mean voiced. Tracks must declare the same rate, origin, and length. Within an audit plan, their rate and length must also match the plan. Mismatches produce contiguous intervals with an exclusive end. There is no automatic resampling, alignment, pitch extraction, or decision about which guide is correct.

Numeric inputs must be finite and nonnegative. Rates must be positive. The CLI limits each JSON file to 32 MiB; the library limits duration groups to 100,000 and F0 tracks to 1,000,000 frames. Decimal inputs support up to 18 fractional places. Out-of-contract values are refused.

## Library entry points

```python
from tagalog_singing_preflight import phonemes, text, timing, voicing

hint = text.normalize_hint("Si Ana’y áawit.")
allocation = timing.allocate_frames(["0.1"] * 10, 50, 50)
checked = phonemes.check_vocabulary(["A", "B A"], ["A", "B"])
# voicing.compare_voicing(guide_dict, conditioning_dict)
```

`text.normalize_hint` returns separate `original`, NFC-normalized `nfc`, and `frontend_hint` fields. The hint changes curly apostrophes between letters to ASCII apostrophes and reports those positions. Diacritics, spacing, quotation marks outside contractions, and phonetic glottal symbols are retained. This is a frontend compatibility hint, not a pronunciation repair. `audit.audit_plan(plan)` combines the checks into a versioned JSON-compatible report.

## Evidence and limits

The regression suite covers Unicode preservation, unknown tokens, frame allocation, malformed numeric inputs, shared F0 clocks, mismatch intervals, CLI failures, and refusal to overwrite reports. Public examples use original synthetic text and contours.

A private integration check found a 7.50-second input becoming 374 rather than 375 frames under binary-float sum/floor. The allocator returned 375. A separate check found 159 voicing-mask differences across 475 frames, despite equal pitch values on all 172 jointly voiced frames. These results demonstrate metadata diagnostics, not improved audio or native-language correctness. Private source material is not included.

Supported here: text preservation, declared-vocabulary checks, timing allocation/audit, and aligned voicing-mask comparison. Experimental: applying the diagnostics through a model-specific adapter. Not implemented: automatic G2P/IPA, stress prediction, model-language expansion, training, synthesis, conversion, audio repair, or listening evaluation.

## Resource catalog and contributions

[data/catalog.json](data/catalog.json) contains original metadata and primary links for 11 resources, separating singing corpora, speech, lexicons/G2P, a speech model, and YouTube research leads. No third-party data or weights are bundled. The catalog records verification dates, limitations, and distinct permissions; it is not a cleared training corpus.

For example, the [LIEE corpus](https://github.com/julieraptor/LIEE-Filipino-Singing-Corpus-for-Singing-Voice-Synthesis) permits specified singing-synthesis uses but prohibits voice-conversion uses and raw redistribution. The [tiny Tagalog dataset](https://github.com/UtaUtaUtau/tiny-tagalog-dataset) uses CC BY-NC 4.0 for data, separately from its MIT code. Some other resources have unresolved or conflicting terms. Public YouTube availability and attribution do not establish training or voice-use permission. Recheck the source terms for your intended use.

Useful contributions include a minimal failing JSON example, a tested adapter with its exact frontend vocabulary, or a primary-source catalog correction. Use original synthetic fixtures; do not attach private recordings, song lyrics, credentials, or unlicensed datasets. A Tagalog-capable model would require separately cleared data, aligned annotations, compatible architecture, and native-speaker evaluation. This package does not provide that model.

Original package code, documentation, and catalog metadata are [MIT licensed](LICENSE). Linked resources retain their own terms. Implementation references: [Python Decimal](https://docs.python.org/3.11/library/decimal.html), [Unicode normalization](https://docs.python.org/3.11/library/unicodedata.html), and [Python packaging](https://packaging.python.org/en/latest/tutorials/packaging-projects/).
