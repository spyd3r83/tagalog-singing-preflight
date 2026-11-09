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

## Look up supplied pronunciation candidates

The offline `lexicon` command looks up every occurrence in a caller-supplied pronunciation TSV and keeps all distinct candidates. It identifies missing and ambiguous spellings without selecting a reading, predicting stress, or mapping IPA to SoulX phones. Supply the resource/version label and its **data** terms separately from any software license. These are declarations; the command does not verify permissions or native-language accuracy.

Run the original synthetic demonstration:

```sh
python -m tagalog_singing_preflight lexicon examples/lexicon-demo.tsv "zaya zana absent" --source-label synthetic-demo --data-license MIT
```

The report contains one occurrence with a single candidate, one with two candidates, and one missing occurrence. The fixture's spellings and IPA sequences are invented test material, not Tagalog annotations. Exit code 0 and `status: pass` mean the lookup completed, even with missing or ambiguous results. Malformed input or file errors exit with code 2. `--output new-report.json` creates a new report and refuses overwrite; source files remain unchanged. Reports contain the supplied text and matching resource entries, so apply their privacy and data terms before sharing them.

Use UTF-8 TSV with no header: one `word<TAB>space-separated IPA` pair per row, and additional rows for alternative pronunciations. Empty rows and a UTF-8 BOM are accepted. Each key must be a single joined unit. Keys use NFC normalization and exact case; accents, apostrophes and hyphens remain distinct. Canonically equivalent candidate token sequences are deduplicated, retaining the first supplied tokens, their first `source_row`, and the combined `row_count`. Stress marks, glottals, affricates and combining modifiers inside tokens remain intact. IPA tokens are opaque supplied labels; they are not validated phonetics.

Occurrences retain their original spelling and Python Unicode code-point `start` and exclusive `end` offsets. The conservative scanner keeps letters, combining marks, numbers, ASCII/curly apostrophes, and the hyphen characters U+002D/U+2010/U+2011 together. Other punctuation separates units. Initial or terminal apostrophes remain part of the lookup key, including quotation-like marks; they are never silently removed. Thus `puso'`, `puso`, `pag-ibig`, and `ng` require their own exact keys. This is a mechanical lookup policy, not a Tagalog word or syllable tokenizer; the existing `text` hints are not applied to keys.

Bounds are 32 MiB and 200,000 nonempty TSV rows, 256 characters per key, 1,024 characters per pronunciation, 32 distinct candidates per normalized key, and 16,000 input characters with at most 1,024 occurrences. Token separators must be ASCII spaces; extra TSV columns, whitespace-containing keys and control characters are refused. The library entry point is `lexicon.lookup_text(text, lexicon_path, source_label=..., data_license=...)` from `tagalog_singing_preflight.lexicon`, with a `pathlib.Path` for the local file.

The format follows [WikiPron's documented output](https://github.com/CUNY-CL/wikipron/blob/d282e848a211ea31cfd730f0ced8bc8cdab9e83d/README.md#output), but no third-party dictionary is bundled or downloaded. Its [stock broad and narrow scrape settings](https://github.com/CUNY-CL/wikipron/blob/d282e848a211ea31cfd730f0ced8bc8cdab9e83d/data/scrape/lib/scrape.py#L249-L263) both remove stress and syllable boundaries; choosing narrow does not restore them. Stock extraction also [excludes hyphenated and digit-containing words](https://github.com/CUNY-CL/wikipron/blob/d282e848a211ea31cfd730f0ced8bc8cdab9e83d/src/wikipron/scrape.py#L31-L44). Check the exact snapshot's data terms and coverage. Even one dictionary candidate does not establish the intended sentence meaning, singing realization, or correct pronunciation.

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

## Prepare a phrase for pronunciation review

Use `review-draft` to give a reviewer one development phrase in context. The draft includes the original text, proposed focus tags, and supplied pronunciation candidates. Occurrence offsets count Python Unicode code points and use an exclusive end. The command checks the benchmark manifest, rejects held-out items, and starts each draft with a pending review.

```sh
python -m tagalog_singing_preflight review-draft data/tagalog-benchmark-v1.json dev-05 examples/lexicon-demo.tsv --source-label synthetic-demo --data-license MIT --output review-dev-05.json
```

The invented dictionary in this example matches none of the six occurrences in `dev-05`. To surface candidates, supply a local TSV you may use for review, with its resource/version label and data terms as described under [pronunciation lookup](#look-up-supplied-pronunciation-candidates). Even a single candidate leaves the annotation blank.

For manual review, copy the chosen candidate's `source_row` into `selected_source_row`, or enter a list of supplied tokens in `proposed_ipa_tokens`. Use `notes` for unresolved readings or context, such as the intended meaning, stress, or glottal stops. Keep edited drafts with their applicable data terms. Generated files can contain restricted text or dictionary entries.

Exit code 0 means the draft was prepared. Invalid inputs, a held-out item, or an existing output file exit with code 2.

### Check an edited pronunciation review

Use the same manifest, item ID, lexicon, and declared data terms used to create the draft. Make edits only inside `review` and each occurrence's `annotation`. The checker rebuilds the generated context from those inputs and rejects changes to fields such as the original text, offsets, candidate tokens, or source rows.

```sh
python -m tagalog_singing_preflight review-check data/tagalog-benchmark-v1.json dev-05 examples/lexicon-demo.tsv review-dev-05.json --source-label synthetic-demo --data-license MIT
```

An unedited example reports `declared_review_status: "pending"`, six unresolved occurrences, and an empty `resolved_occurrences` list. Set `review.status` to `needs_revision` to return partial decisions, or to `approved` once every occurrence has one decision. Both require the opaque reviewer ID, review date, and pronunciation notes described in the benchmark contract. Each proposed token must contain no whitespace or control characters. The token list, counted with single spaces between tokens, has a 1,024-character limit. Per-occurrence notes may be null or nonblank text of up to 4,096 characters.

An approved review with every decision present returns the selected or supplied tokens in text order, with original offsets. Pending and needs-revision records return counts without exporting tokens for mapping. The report omits reviewer identifiers and notes. A pass establishes consistency with the supplied sources and record format. Reviewer identity, native pronunciation, data permission, model compatibility, and singing quality remain unassessed.

Success exits with code 0. Invalid records, duplicate fields in the edited JSON, or file errors exit with code 2. Inputs are read-only and optional `--output` creates a new file.

## Map reviewed IPA to declared model tokens

Use `phone-map` to apply a caller-supplied mapping profile to one complete review marked `approved`. The command first checks the review against its original manifest and lexicon. It then maps each IPA token explicitly and checks every profile target against the supplied model vocabulary. The output preserves word order, IPA spellings, original text, and Unicode offsets.

Run the original synthetic demonstration from a checkout:

```sh
python examples/make_phone_mapping_demo.py ../tagalog-mapping-demo
python -m tagalog_singing_preflight phone-map data/tagalog-benchmark-v1.json dev-05 examples/lexicon-demo.tsv ../tagalog-mapping-demo/review.json ../tagalog-mapping-demo/mapping.json ../tagalog-mapping-demo/vocabulary.json --source-label synthetic-demo --data-license MIT
```

The generator creates a new directory containing generated mock decisions, an invented mapping profile, and an invented vocabulary. Its six occurrences each receive the same two synthetic IPA labels. The mapping expands them to 18 target tokens in total. This demonstrates the adapter mechanics. Native Tagalog review and singing quality remain unassessed.

A profile contains exactly these four fields:

```json
{
  "schema_version": 1,
  "mapping_id": "synthetic-demo",
  "target_model": "synthetic-token-model-v1",
  "rules": {
    "ˈdemo": ["T_STRESS", "T_DEMO"],
    "ʔ": ["T_GLOTTAL"]
  }
}
```

Rules match the exact Unicode spelling and case of an entire IPA token. Stress marks attached to a token and glottal symbols therefore need explicit rules. Canonically equivalent spellings also require their exact supplied keys. Each rule must emit at least one token. A missing rule, empty expansion, unsupported target, stale review, or incomplete approval causes an error. All profile rules are checked, including unused rules.

The vocabulary is a JSON list of single tokens from the receiving frontend. For example, the synthetic vocabulary contains `["T_STRESS", "T_DEMO", "T_GLOTTAL"]`. `target_model` records the caller's model/version label. Vocabulary membership and that label leave checkpoint compatibility and linguistic equivalence unverified. Keep the profile and its applicable terms with the source review. Reports include the phrase and mapped tokens, so preserve any restrictions on those inputs when sharing results.

Limits are 10,000 rules, 1,024 characters per source token, 16 targets per rule, 256 characters per target token, and 100,000 expanded tokens per report. Tokens must be nonempty and contain no whitespace or controls. Mapping ID and target-model labels allow up to 512 characters. The CLI accepts up to 32 MiB per JSON input and rejects duplicate fields in the review or mapping profile. Success exits with code 0. Invalid records and file errors exit with code 2. Optional `--output` creates a new report, and source files are read without modification.

The Python entry point is `phone_mapping.map_review(manifest, item_id, lexicon_path, edited_review, mapping, vocabulary, source_label=..., data_license=...)`. Its per-occurrence target lists can feed the explicit note-plan exporter below. A usable linguistic mapping and syllable-to-note alignment still require separate evidence for the receiving frontend.

## Export mapped tokens with a note plan

Use `soulx-export` to turn an explicit token-to-note plan into native SoulX metadata. It repeats the original review and mapping checks, then requires every mapped target token to appear exactly once in order. The command accepts the original source inputs, rather than trusting a standalone mapping report.

Run the original synthetic demonstration in a new directory:

```sh
python examples/make_phone_mapping_demo.py ../tagalog-native-demo --native-notes
python -m tagalog_singing_preflight soulx-export data/tagalog-benchmark-v1.json dev-05 examples/lexicon-demo.tsv ../tagalog-native-demo/review.json ../tagalog-native-demo/mapping.json ../tagalog-native-demo/vocabulary.json ../tagalog-native-demo/note-plan.json --source-label synthetic-demo --data-license MIT --expected-frames 150 --output ../tagalog-native-demo/export.json
```

This variant creates mock review decisions, an illustrative English-token mapping and phoneset, and `note-plan.json`. Each of six occurrences maps to `["en_S", "en_AH0", "en_B"]` and receives one 0.5-second note. The report's `metadata.phoneme` contains six `en_S-AH0-B` groups. Its three seconds produce 150 frames at the default 24,000 Hz sample rate and 480-sample hop. These invented labels do not pronounce the Tagalog phrase.

A note plan contains exactly `schema_version` (integer 1) and a nonempty `notes` list. For example, its first record is:

```json
{
  "schema_version": 1,
  "notes": [
    {
      "occurrence_index": 0,
      "token_start": 0,
      "token_end": 3,
      "duration": "0.5",
      "note_pitch": 60,
      "note_type": 2
    }
  ]
}
```

The demonstration's complete plan also contains occurrences 1 through 5. Each record has exactly those six fields. Occurrence indices are zero-based, and `[token_start, token_end)` selects a nonempty span in that occurrence's mapped `target_tokens`. Notes must cover every occurrence contiguously and in order, without gaps, overlap, duplication, or omitted final tokens. One occurrence may be split across successive notes. The caller supplies this alignment; automatic syllable detection, rests, and repeated-token melisma are outside this slice.

Durations are positive decimal strings in seconds. Pitch and type are integers from 0 through 255, matching the pinned native embedding bounds; the range alone does not establish musically meaningful settings. A note can contain one target token directly, or multiple `en_` tokens whose nonempty suffixes contain no hyphens. The latter serialize as `en_A-B` and expand to the supplied tokens plus native `<SEP>`. Mixed or non-English multi-token groups, ambiguous `en_` tokens, and content targets `<PAD>`, `<BOW>`, `<EOW>`, `<SEP>`, `<SP>`, or `<AP>` are refused. Native `<AP>` substitution within a token is also refused.

Before returning metadata, the exporter runs the [pinned SoulX audit](#check-native-soulx-metadata) with the required `--expected-frames` and optional `--sample-rate` and `--hop-size`. That audit checks the expanded vocabulary, including inserted structural tokens, frame totals, and native pre-assignment capacity. Audit failure refuses the export and includes its error codes. No F0 is inferred or supplied. The [pinned processor](https://github.com/Soul-AILab/SoulX-Singer/blob/81aeb3ae772c70093c3de74dc23c92d983801ae4/soulxsinger/utils/data_processor.py) accepts absent F0; melody control still needs runtime and audio evidence.

The report includes the native `metadata` object (`text`, `phoneme`, `duration`, `note_pitch`, `note_type`), original note assignments, the audit, and its upstream commit. Extract `metadata` for a native consumer; the report itself is not the native input object. `native_processor_executed`, `model_runtime_verified`, `pronunciation_assessed`, and `native_review_verified` remain `false`. A pass establishes these source-derived mechanical checks, without executing tensor processing, a checkpoint, or audio evaluation.

The Python entry point is `soulx_export.export_review(manifest, item_id, lexicon_path, edited_review, mapping, vocabulary, note_plan, source_label=..., data_license=..., expected_frames=..., sample_rate=24000, hop_size=480)`. Plans allow up to 100,000 notes; the existing mapping and numeric bounds also apply. The CLI rejects duplicate note-plan fields and accepts up to 32 MiB per JSON input. Success exits with code 0; invalid records, native audit failures, and file errors exit with code 2. Inputs remain unchanged. Optional `--output` creates a new report and refuses overwrite.

### Compare with the native processor on CPU

The optional checkout example runs that saved export through the actual pinned `DataProcessor`, then compares retained phone IDs and tokens, note pitch and type, and the alignment frame count. Use an existing trusted SoulX checkout at the [pinned revision](https://github.com/Soul-AILab/SoulX-Singer/tree/81aeb3ae772c70093c3de74dc23c92d983801ae4) and a Python environment with its required PyTorch, NumPy, and torchaudio libraries already installed. Replace `/path/to/SoulX-Singer` with that checkout's root:

```sh
python -m examples.compare_soulx_cpu ../tagalog-native-demo/export.json ../tagalog-native-demo/vocabulary.json --upstream /path/to/SoulX-Singer --expected-frames 150 --output ../tagalog-native-demo/native-comparison.json
```

The runner verifies `data_processor.py` against SHA-256 `14baf4c7784cea85bd58f0c29bd504d3ae46809931c0d40b16183a39581290cb` before importing it. Other checkout files and installed dependencies are caller-supplied and must also be trusted. The runner imports the native libraries, forces processor tensors to CPU, disables bytecode writes during upstream imports, and passes a copied metadata object without a WAV path. It downloads nothing, loads no weights, and invokes no model or audio generation. The package's ordinary runtime and regression suite retain no tensor dependency.

On 9 November 2026, the synthetic six-note export retained all 37 expected phone positions, including structural tokens, and all note pitch/type values. Its CPU alignment contained 150 frames: 132 had positive indices and 18 had index zero. The observed environment was Python 3.11.9, PyTorch and torchaudio 2.6.0+cu124, and NumPy 1.26.4. The CUDA-built libraries still executed this processor on CPU.

A comparison pass covers the listed field, index-bound, and clock checks. The report includes the retained arrays and `zero_index_frames`; zero slots do not fail this bounded comparison or establish correct assignment. `alignment_assignment_verified`, `model_runtime_verified`, `pronunciation_assessed`, and `native_review_verified` remain `false`. The comparison records `native_processor_executed: true` separately from the unchanged export report. Native tensor preprocessing is now observed for this synthetic case; complete alignment, checkpoint behavior, Tagalog pronunciation, and musical quality remain unassessed.

The comparison reruns the metadata audit and supports exported content notes without F0, using the same default clocks as `soulx-export`. Optional clock flags are `--sample-rate` and `--hop-size`. Inputs remain unchanged, and `--output` refuses overwrite. Exit codes are 0 for matching compared fields, 1 for a native-result difference, and 2 for invalid inputs, a changed processor source, missing native dependencies, or file/runtime errors. Ordinary CI tests the comparison and refusal behavior with synthetic list results; the actual upstream execution is an optional local integration check.

## Prepare a local listening comparison

The `listening` command prepares randomized A/B trials from two sets of supplied WAV clips. It creates anonymous filenames and a blank response sheet, with the condition mapping kept outside the listener folder. It does not synthesize audio, recruit listeners, or evaluate their responses.

This runnable demonstration generates four original **tones**, not sung versions of the phrases. Use a new directory for each run:

```sh
python examples/make_listening_demo.py ../tagalog-listening-demo
python -m tagalog_singing_preflight listening data/tagalog-benchmark-v1.json ../tagalog-listening-demo/plan.json ../tagalog-listening-demo/packet --seed 17
```

The resulting `packet/listener/` contains `trials.json`, `responses.csv`, and two WAVs per trial. New packets use format version 2: a fresh random `packet_id` appears in the listener JSON, operator key, and every CSV row. Retain those identifiers when entering responses. The JSON pairs A/B files with the intended text; open the WAVs in a local player and record `A`, `B`, `tie`, or `cannot_assess` in the CSV's `preference` column. Notes are optional. Keep `packet/operator-key.json` with the operator: it contains the seed, source paths, condition descriptions, item IDs, and audio identity records. Source filenames and non-audio WAV chunks are excluded from the listener files. Audible differences can still reveal a condition; this is not a guarantee of blinding.

For real comparisons, replace the demo's plan and tones with permitted clips. The plan declares version 1, an experiment ID, the matching benchmark ID, a split, two conditions, a permission note, and clips. Each condition has `id`, `mode` (`svc`, `svs`, or fixture-only `synthetic`), and a description recording the model, settings, and guide or score used. Each clip has `item_id`, `condition_id`, and a path relative to the plan directory. Select the same nonempty subset from one benchmark split for both conditions. Absolute paths, paths escaping that directory, missing partners, and duplicate pairs are refused. The permission note records your stated basis for local listening; the tool does not verify recording, lyric, or voice-use rights. Keep private plans, audio, keys, and completed responses out of public commits.

The builder reads the complete declared PCM payload and rejects empty, truncated, or unsupported WAVs. It supports ordinary RIFF PCM with one or two channels, 16/24/32-bit samples, 8–96 kHz sample rates, and clips up to 60 seconds. Each pair must have the same format and frame count. Limits are 64 pairs, 32 MiB per input WAV, and 256 MiB of input WAVs in total. New WAV containers preserve the supplied PCM samples and clock; there is no normalization, trimming, or resampling. Matching clocks do not establish matched loudness or a fair acoustic comparison.

Choose one judgment per pass with `--attribute pronunciation` (the default), `phrasing`, or `artifacts`. Use a new packet and seed for each listener session, and keep the mapping from listeners. The same inputs, seed, and Python runtime reproduce the trial assignment and PCM audio; each version 2 creation still receives a new packet ID. IDs use [Python's random UUID4](https://docs.python.org/3.10/library/uuid.html#uuid.uuid4) and contain no source path or condition label. Showing the intended text means these trials do not measure unprompted word intelligibility. Native Tagalog review, listener suitability, controlled playback levels, prospective criteria, and disagreement analysis remain the experimenter's responsibility. Pending text reviews remain explicitly unverified.

The separation of judgments and randomized presentation is informed by [ITU-R BS.1534-3, Annex 1, sections 3, 5.3, and 6](https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1534-3-201510-I!!PDF-E.pdf). This exploratory tool does not implement MUSHRA's reference, anchor, assessor-training, or scoring protocol and makes no conformance claim. Packet creation establishes preparation, not pronunciation, musical quality, or fluency.

Success exits with code 0 and a JSON report. Invalid plans, audio, arguments, or file operations exit with code 2. Existing output directories are refused, including empty ones; inputs are unchanged. If writing fails after directory creation, a partial packet may remain and must not be used as complete. The Python entry point is `listening.prepare_packet(manifest, plan, audio_root, output_dir, seed, attribute="pronunciation", packet_version=2)`. Use `--packet-version 1` or `packet_version=1` only when a legacy three-column form is needed. Existing version 1 packets remain readable and are not migrated. The benchmark and input-plan contracts remain version 1; packet format versions are separate.

## Tally a listener's responses

The `responses` command maps recorded A/B choices back to their declared conditions for one packet, listener, split, and attribute. It reports counts and coverage, with ties and `cannot_assess` entries kept separate. It does not select a winner or establish language quality.

After preparing the tone packet above, generate a separate mock CSV using its actual packet and trial identifiers, then tally it:

```sh
python examples/make_listening_demo.py ../tagalog-listening-demo/synthetic-responses.csv --responses-for ../tagalog-listening-demo/packet
python -m tagalog_singing_preflight responses ../tagalog-listening-demo/packet ../tagalog-listening-demo/synthetic-responses.csv --listener-id synthetic-demo --output ../tagalog-listening-demo/summary.json
```

The two generated entries are one mock A choice and one mock `cannot_assess` entry; no listener supplied them. With seed 17, A maps to `tone-high`, and the second entry remains `cannot_assess`. For real records, use the completed `listener/responses.csv` from that listener's original packet and an opaque listener identifier. Version 2 requires matching packet IDs in the key, listener JSON, and every present CSV row, including rows with blank preferences. A response sheet from a different packet is refused even when its trial IDs, seed, and audio are otherwise identical.

`response_packet_id_matches` is `true` only for a nonempty version 2 CSV whose row IDs all match the packet. It is `null` for a header-only CSV or a legacy version 1 packet. Version 1 has no packet identifier, so same-trial-ID sheets can still be mixed up; the report warns about that limit. Keep original CSV-to-packet associations intact for both versions. These checks detect accidental mixups when identifiers remain intact; they do not authenticate the key, respondent, or audio actually heard. `response_packet_binding_verified` remains `false`. The separate `audio_matches_key` check compares each current anonymous WAV's SHA-256 with the supplied key.

Blank preferences and missing response rows are reported separately. `responses_complete` means every trial has a nonblank permitted response, including `cannot_assess`; it does not mean every trial received a preference. An empty response sheet passes the file checks with zero answers. `status: "pass"` establishes valid records and the documented byte comparison. Native reviewer competence, actual listening, recording permissions, and response provenance remain unverified. No human judgments have been collected for the bundled phrases.

Keep the exact CSV header for the packet version, with each trial appearing at most once:

| Packet version | CSV header |
| --- | --- |
| 2, the default | `packet_id,trial_id,preference,notes` |
| 1, legacy | `trial_id,preference,notes` |

Preferences are exactly `A`, `B`, `tie`, `cannot_assess`, or blank. Mixed packet versions, missing or mismatched version 2 identifiers, duplicate or unknown trials, duplicate headers, extra or missing columns, malformed quoting, and other preference values are refused. UTF-8 with or without a BOM is supported. Limits are 64 trials, 1 MiB for the CSV, and 4,096 characters per notes field. Notes are validated but excluded from the report; keep the source records privately for review. Success exits with code 0; invalid inputs or file operations exit with code 2. `--output` creates a new report and refuses overwrite. Inputs are unchanged.

The Python entry point is `responses.summarize_packet(packet_dir, responses_path, listener_id)`. Treat its counts as a descriptive record from one session. It provides no population statistics, quality threshold, native-language certification, or pooled comparison across listeners. Obtain suitable native Tagalog listeners, permitted sung clips, reviewed text, and prospective acceptance criteria before drawing conclusions about singing performance.

## Evidence and limits

The regression suite covers Unicode preservation, unknown tokens, frame allocation, malformed numeric inputs, shared F0 clocks, mismatch intervals, CLI failures, and refusal to overwrite reports. Public examples use original synthetic text and contours.

A private integration check found a 7.50-second input becoming 374 rather than 375 frames under binary-float sum/floor. The allocator returned 375. A separate check found 159 voicing-mask differences across 475 frames, despite equal pitch values on all 172 jointly voiced frames. These results demonstrate metadata diagnostics, not improved audio or native-language correctness. Private source material is not included.

Supported here: text preservation, declared-vocabulary checks, timing allocation/audit, aligned voicing-mask comparison, the documented native SoulX metadata audit, supplied pronunciation lookup, explicit token mapping and content-note export, benchmark validation, development review drafts and checks, local randomized listening-packet preparation, and descriptive response tallies. Applying corrected inputs through a model runtime remains experimental. Not implemented: automatic G2P/IPA, stress prediction, model-language expansion, training, synthesis, conversion, audio repair, or statistical analysis of listener populations.

## Resource catalog and contributions

[data/catalog.json](data/catalog.json) contains original metadata and primary links for 11 resources, separating singing corpora, speech, lexicons/G2P, a speech model, and YouTube research leads. No third-party data or weights are bundled. The catalog records verification dates, limitations, and distinct permissions; it is not a cleared training corpus.

For example, the [LIEE corpus](https://github.com/julieraptor/LIEE-Filipino-Singing-Corpus-for-Singing-Voice-Synthesis) permits specified singing-synthesis uses but prohibits voice-conversion uses and raw redistribution. The [tiny Tagalog dataset](https://github.com/UtaUtaUtau/tiny-tagalog-dataset) uses CC BY-NC 4.0 for data, separately from its MIT code. Some other resources have unresolved or conflicting terms. Public YouTube availability and attribution do not establish training or voice-use permission. Recheck the source terms for your intended use.

Useful contributions include a minimal failing JSON example, a tested adapter with its exact frontend vocabulary, or a primary-source catalog correction. Use original synthetic fixtures; do not attach private recordings, song lyrics, credentials, or unlicensed datasets. A Tagalog-capable model would require separately cleared data, aligned annotations, compatible architecture, and native-speaker evaluation. This package does not provide that model.

Original package code, documentation, and catalog metadata are [MIT licensed](LICENSE). Linked resources retain their own terms. Implementation references: [Python Decimal](https://docs.python.org/3.11/library/decimal.html), [Unicode normalization](https://docs.python.org/3.11/library/unicodedata.html), and [Python packaging](https://packaging.python.org/en/latest/tutorials/packaging-projects/).
