# Toward fluent Tagalog singing

Build a singing system that can render newly supplied Tagalog lyrics with natural pronunciation and musical phrasing, while retaining useful voice, note and timing control comparable to SoulX. This is the project goal. The released preflight tools establish mechanical input checks; fluent Tagalog synthesis remains unproved.

This file is the maintained project roadmap. Use pull requests and their validation results for implementation evidence. Keep the existing offline commands working as the project grows.

## Starting evidence

The initial release checks text preservation, phoneme vocabulary, timing and aligned voicing masks. Its documented integration results exposed a lost timing frame and mismatched voicing masks. These checks help diagnose inputs; they do not establish pronunciation or audible improvement.

The native SoulX metadata audit adds checks tied to a specific upstream source revision, with original runnable fixtures. It does not execute SoulX's tensor processor or model. Comparing its predictions with the native processor remains an integration task before claiming runtime equivalence.

Upstream [SoulX-Singer](https://github.com/Soul-AILab/SoulX-Singer/tree/81aeb3ae772c70093c3de74dc23c92d983801ae4) documents Mandarin, English and Cantonese training coverage. That coverage does not establish Tagalog support. Singing voice conversion (SVC) carries content from a sung recording; singing voice synthesis (SVS) must create the supplied words from its conditioning inputs. Evaluate both routes separately.

The [SoulX paper, section 3.3.1](https://arxiv.org/html/2602.07803v1) reports an intelligibility problem when rewritten lyrics retain the old melody's F0 conditioning, with better results from score-conditioned editing in its evaluated languages. This is a useful experiment design for Tagalog, whose outcome remains untested here.

## Priorities and completion evidence

| Priority | Work | Evidence needed to complete the increment |
| --- | --- | --- |
| 1 | Integrate with the native SoulX metadata contract | Audit original synthetic inputs against a pinned upstream processor, with runnable examples for valid inputs, unsupported phones, lost frames and incompatible F0 lengths. State exactly which inputs were inspected and whether the model itself ran. |
| 2 | Establish a Tagalog pronunciation benchmark | Create original, human-checked phrases covering stress contrasts, glottal stops, vowel sequences, contractions, consonant transitions and syllable-to-note alignment. Keep a held-out set separate from development examples. Record the reviewers and remaining disagreements. |
| 3 | Compare useful inference baselines | Use recordings and voices permitted for the intended use. Compare a clear sung-guide SVC baseline with new-lyrics SVS under score conditioning and under old-contour F0 conditioning. Preserve exact settings and listen to the same held-out phrases. |
| 4 | Prepare permitted singing data | Extend the resource catalog with evidence for recording, lyric, performer, training, conversion and redistribution permissions as applicable. Validate manifests and annotation alignment without bundling restricted material. Speech and lexicons can support a frontend; measure singing outcomes separately. |
| 5 | Prove an adaptation path | Verify an executable training path, model and data permissions, compute needs and recovery before proposing a bounded experiment. Compare a compatible existing Tagalog singing model or adaptation of another maintained system when that is more practical. Do not assume the SoulX inference release includes fine-tuning support. |
| 6 | Demonstrate useful musical performance | Progress from held-out phrases to a complete original or permitted song. Inspect lyrics, pronunciation, stress, phrasing, pitch, timing, voice consistency and audible artifacts in the actual output. Publish only material permitted for release. |

Work on the next useful unblocked increment. A model experiment can wait for data, compute or approval while tests, frontend work, evaluation tooling or source verification continue. A documentation-only update should resolve a concrete uncertainty or make an existing result reproducible.

## Define quality before comparing audio

Before generating a benchmark, record its intended use, baseline, held-out items, inference settings and acceptance criteria. The proposed evaluation dimensions are word intelligibility, natural Tagalog pronunciation and lexical stress, musical phrasing, pitch and timing fidelity, voice consistency, and artifacts. Report these dimensions separately so one score cannot conceal a serious defect.

Use native Tagalog listeners for language judgments and listeners able to assess the musical task. Give reviewers the exact audio version, use blinded comparisons where practical, and record disagreement and coverage limits. Set numerical thresholds before the experiment; this roadmap establishes no measured thresholds or passing audio result. ASR transcripts and objective pitch measurements can assist diagnosis but cannot establish fluency or natural singing on their own.

## Data and execution boundaries

[data/catalog.json](data/catalog.json) is a resource index, not a cleared combined training corpus. For example, [LIEE](https://github.com/julieraptor/LIEE-Filipino-Singing-Corpus-for-Singing-Voice-Synthesis#terms-and-conditions) distinguishes permitted synthesis uses from prohibited voice-changer uses. [tiny-tagalog-dataset](https://github.com/UtaUtaUtau/tiny-tagalog-dataset) separates its data terms from its code license. Verify the exact proposed use rather than treating public availability as permission.

Keep private recordings, third-party song lyrics, credentials, internal project records and restricted weights or datasets out of public examples and commits. Use original synthetic fixtures for tooling. New paid compute, external uploads of private material, and use of a person's voice need the applicable authority before execution; local preparation and public-source research can continue independently.

## Continue maintenance

Inspect current code, upstream changes, open pull requests, CI and the latest evidence before selecting work. Prefer one small tested contribution over duplicated implementations or cosmetic churn. Each substantive contribution should explain the problem, observed result, remaining limit and next useful step in its pull request. Update this roadmap when a milestone or the evidence changes; do not infer progress from a daily run alone.
