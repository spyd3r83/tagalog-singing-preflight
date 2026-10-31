# Tagalog Singing Preflight

Catch mechanical input errors before a singing-synthesis run: unsupported phoneme tokens, lost timing frames, and incompatible voicing guides. This small, offline Python library grew from Tagalog singing experiments. Its timing and voicing checks are language-independent.

It preserves the original text and reports what it can check. A passing report does **not** establish correct pronunciation, stress, singer identity, or musical quality. This is not a singing model or a Tagalog language pack.

The project's long-term goal is a singing system with SoulX-like control and fluent Tagalog delivery, including newly supplied lyrics. The current tools are the first step. [ROADMAP.md](ROADMAP.md) tracks the path through model integration, pronunciation, permitted singing data, adaptation experiments, and listening evaluation. Contributions can advance any of those areas; they are not limited to preflight checks.

## Run it

Python 3.10 or later is required. There are no runtime dependencies, accounts, or model downloads. From a checkout:

```sh
git clone https://github.com/spyd3r83/tagalog-singing-preflight.git
cd tagalog-singing-preflight
python -m tagalog_singing_preflight audit examples/valid-plan.json
python -m unittest discover -s tests -v
```

The audit command returns JSON with `"status": "pass"` and exits with code 0. To preserve a report, add `--output report.json`; an existing file is never overwritten. Inputs are read without modification.

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

## Check native SoulX metadata

The `soulx` command checks the native SVS metadata format without loading a model:

```sh
python -m tagalog_singing_preflight soulx examples/soulx-metadata.json examples/soulx-example-phoneset.json --expected-frames 50
python -m tagalog_singing_preflight soulx examples/soulx-short-f0.json examples/soulx-example-phoneset.json --expected-frames 50
```

The first example passes with exit code 0. The second exits with code 1 because its F0 track is shorter than the note metadata. The example phoneset is an illustrative subset. For real inputs, supply the receiving frontend's actual `phone_set.json`; a declared vocabulary does not verify checkpoint compatibility.

A note can also have matching duration and F0 counts while its expanded phones cannot fit the native alignment loop:

```sh
python -m tagalog_singing_preflight soulx examples/soulx-insufficient-capacity.json examples/soulx-example-phoneset.json --expected-frames 2
```

This original synthetic example exits with code 1 and `NATIVE_ALIGNMENT_CAPACITY`. Its two-frame note expands to three content positions, including the English separator. The pinned native processor stops assigning notes at that point and leaves both alignment frames at zero. The report identifies that note and any later source groups skipped by the same early stop.

The checker accepts a metadata object or a list containing one object. Required fields are whitespace-delimited strings named `phoneme`, `duration`, `note_pitch` and `note_type`; `f0` is optional. It checks group counts, note embedding indices, pause normalization and merging, expanded English phone groups and structural tokens, native float-floor frame counts, and F0 length. Reports identify the [upstream processor revision](https://github.com/Soul-AILab/SoulX-Singer/blob/81aeb3ae772c70093c3de74dc23c92d983801ae4/soulxsinger/utils/data_processor.py) used for these rules.

The `alignment_capacity` section checks the native loop's capacity condition before assignment, using cumulative float starts and ties-to-even rounding. Its `skipped_source_group_indices` maps a detected early stop back to the supplied metadata. A fitting capacity check does not establish complete tensor alignment: overlap handling, token placement, and unassigned frames remain unassessed.

Defaults are a 24,000 Hz sample rate and 480-sample hop, giving a 50 Hz frame rate. Only positive integer frame rates are supported. `--output` creates a new report and refuses overwrite. Exit codes are 0 for pass, 1 for a failed metadata check (including invalid fields in parsed JSON), and 2 for malformed JSON, command arguments or an input/output error.

This is a source-derived diagnostic, not execution of the native tensor processor. It does not validate every tensor assignment, generate phonemes, repair metadata, load a checkpoint or assess audio. In particular, detecting a shortened F0 track prevents treating silent truncation as a complete phrase; it does not choose or create a correct pitch guide.

## Library entry points

```python
from tagalog_singing_preflight import phonemes, text, timing, voicing

hint = text.normalize_hint("Si Ana’y áawit.")
allocation = timing.allocate_frames(["0.1"] * 10, 50, 50)
checked = phonemes.check_vocabulary(["A", "B A"], ["A", "B"])
# voicing.compare_voicing(guide_dict, conditioning_dict)
```

`text.normalize_hint` returns separate `original`, NFC-normalized `nfc`, and `frontend_hint` fields. The hint changes curly apostrophes between letters to ASCII apostrophes and reports those positions. Diacritics, spacing, quotation marks outside contractions, and phonetic glottal symbols are retained. This is a frontend compatibility hint, not a pronunciation repair. `audit.audit_plan(plan)` combines the checks into a versioned JSON-compatible report.

For native metadata, use `soulx.audit_metadata(metadata, vocabulary, expected_frames, sample_rate=24000, hop_size=480)` from the `tagalog_singing_preflight.soulx` module. It returns a JSON-compatible diagnostic report and leaves the inputs unchanged.

## Prepare a Tagalog pronunciation benchmark

The [draft phrase manifest](data/tagalog-benchmark-v1.json) contains 16 original, assistant-authored phrases: eight development items and eight `held_out` items. All 16 await native Tagalog review. The focus tags are proposed review tasks, not verified pronunciation or stress labels. No recordings, phoneme transcriptions, or melodies are included.

```sh
python -m tagalog_singing_preflight benchmark data/tagalog-benchmark-v1.json
```

The command exits with code 0 because the manifest structure is valid. Its report includes `NATIVE_REVIEW_PENDING`, `native_review_verified: false`, split and focus counts, and declared review counts. This pass does not establish evaluation readiness or singing quality.

The version 1 profile requires `schema_version: 1`, a `benchmark_id`, `language: "tl"`, `text_origin: "original_authored"`, `license: "MIT"`, and an `items` array. Each item has `id`, `split`, `text`, `focus`, and `review` fields. Use `development` or `held_out` for the split. See the manifest for the seven supported focus tags and complete record shape.

Pending review records have status `pending` and null `reviewer_id`, `reviewed_at`, and `pronunciation_notes`. Records marked `approved` or `needs_revision` require an opaque reviewer identifier, a valid `YYYY-MM-DD` date, and nonblank pronunciation notes. The tool checks record completeness; it does not verify reviewer competence or the truth of an approval. Text origin and license are declarations, not independently verified permissions.

The auditor rejects duplicate item IDs, missing splits, and text shared across splits after NFC normalization and case folding, ignoring punctuation and whitespace while retaining diacritics. It leaves supplied text unchanged. This bounded comparison does not establish semantic separation or absence from model training. Both public splits are visible; `held_out` means reserved from development within a declared experiment, not secret or guaranteed unseen.

The library accepts at most 10,000 items, 4,096 Unicode characters per text or notes field, and 64-character ASCII identifiers beginning with a letter or digit. Identifiers may also contain underscores, dots, and hyphens. The CLI retains its 32 MiB input limit and exclusive `--output` creation. Exit codes are 0 for a valid contract, 1 for a parsed contract failure, and 2 for malformed JSON or input/output errors. `benchmark.audit_manifest(manifest)` exposes the same checks in Python.

The proposed stress and phrasing focus is informed by [Zuraw and Roca's study of Filipino text-setting](https://doi.org/10.1017/S0952675725000041), which found relationships between word prominence and musical note placement. The paper does not validate these phrases or supply their annotations. Native review and subsequent audio evidence remain necessary.

## Evidence and limits

The regression suite covers Unicode preservation, unknown tokens, frame allocation, malformed numeric inputs, shared F0 clocks, mismatch intervals, CLI failures, and refusal to overwrite reports. Public examples use original synthetic text and contours.

A private integration check found a 7.50-second input becoming 374 rather than 375 frames under binary-float sum/floor. The allocator returned 375. A separate check found 159 voicing-mask differences across 475 frames, despite equal pitch values on all 172 jointly voiced frames. These results demonstrate metadata diagnostics, not improved audio or native-language correctness. Private source material is not included.

Supported here: text preservation, declared-vocabulary checks, timing allocation/audit, aligned voicing-mask comparison, the documented native SoulX metadata audit, and benchmark manifest validation. Applying corrected inputs through a model runtime remains experimental. Not implemented: automatic G2P/IPA, stress prediction, model-language expansion, training, synthesis, conversion, audio repair, or listening evaluation.

## Resource catalog and contributions

[data/catalog.json](data/catalog.json) contains original metadata and primary links for 11 resources, separating singing corpora, speech, lexicons/G2P, a speech model, and YouTube research leads. No third-party data or weights are bundled. The catalog records verification dates, limitations, and distinct permissions; it is not a cleared training corpus.

For example, the [LIEE corpus](https://github.com/julieraptor/LIEE-Filipino-Singing-Corpus-for-Singing-Voice-Synthesis) permits specified singing-synthesis uses but prohibits voice-conversion uses and raw redistribution. The [tiny Tagalog dataset](https://github.com/UtaUtaUtau/tiny-tagalog-dataset) uses CC BY-NC 4.0 for data, separately from its MIT code. Some other resources have unresolved or conflicting terms. Public YouTube availability and attribution do not establish training or voice-use permission. Recheck the source terms for your intended use.

Useful contributions include a minimal failing JSON example, a tested adapter with its exact frontend vocabulary, or a primary-source catalog correction. Use original synthetic fixtures; do not attach private recordings, song lyrics, credentials, or unlicensed datasets. A Tagalog-capable model would require separately cleared data, aligned annotations, compatible architecture, and native-speaker evaluation. This package does not provide that model.

Original package code, documentation, and catalog metadata are [MIT licensed](LICENSE). Linked resources retain their own terms. Implementation references: [Python Decimal](https://docs.python.org/3.11/library/decimal.html), [Unicode normalization](https://docs.python.org/3.11/library/unicodedata.html), and [Python packaging](https://packaging.python.org/en/latest/tutorials/packaging-projects/).
