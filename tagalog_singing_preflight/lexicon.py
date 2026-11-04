"""Look up supplied pronunciation candidates without selecting a reading."""

from __future__ import annotations

import pathlib
import unicodedata


MAX_TSV_BYTES = 32 * 1024 * 1024
MAX_ROWS = 200_000
MAX_TEXT_CHARACTERS = 16_000
MAX_OCCURRENCES = 1024
MAX_WORD_CHARACTERS = 256
MAX_IPA_CHARACTERS = 1024
MAX_VARIANTS = 32
JOINERS = frozenset("'\u2018\u2019-\u2010\u2011")
LIMIT = (
    "Dictionary matches are supplied candidates, not contextual pronunciation, "
    "native review, model-compatible phones, permission verification or "
    "singing "
    "quality. No candidate is selected and no missing pronunciation is guessed."
)


def _unit_character(character: str) -> bool:
    return (unicodedata.category(character)[0] in "LMN"
            or character in JOINERS)


def _units(text: str) -> list[tuple[int, int]]:
    """Keep joined spellings intact and index the original Python string."""
    spans = []
    start = None
    for index, character in enumerate(text + " "):
        if _unit_character(character):
            if start is None:
                start = index
        elif start is not None:
            if any(unicodedata.category(c)[0] in "LN"
                   for c in text[start:index]):
                spans.append((start, index))
            start = None
    return spans


def _declaration(value: str, name: str) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 512
            or any(unicodedata.category(c)[0] == "C" for c in value)):
        raise ValueError(f"{name} must be nonblank text of at most 512 "
                         "characters "
                         "without control characters.")
    return value


def _read_lexicon(path: pathlib.Path) -> tuple[dict, int]:
    with path.open("rb") as source:
        encoded = source.read(MAX_TSV_BYTES + 1)
    if len(encoded) > MAX_TSV_BYTES:
        raise ValueError(f"Lexicon exceeds {MAX_TSV_BYTES} bytes.")
    entries = {}
    row_count = 0
    for row, line in enumerate(encoded.decode("utf-8-sig").split("\n"), 1):
        line = line.removesuffix("\r")
        if not line:
            continue
        row_count += 1
        if row_count > MAX_ROWS:
            raise ValueError(f"Lexicon exceeds {MAX_ROWS} nonempty rows.")
        columns = line.split("\t")
        if len(columns) != 2:
            raise ValueError(f"Lexicon row {row} needs exactly two TSV "
                             "columns.")
        word, ipa = columns
        if (not word or len(word) > MAX_WORD_CHARACTERS
                or _units(word) != [(0, len(word))]):
            raise ValueError(f"Lexicon row {row} needs one joined word of at "
                             f"most {MAX_WORD_CHARACTERS} characters.")
        if (not ipa.strip() or len(ipa) > MAX_IPA_CHARACTERS
                or any(unicodedata.category(c)[0] == "C" for c in ipa)):
            raise ValueError(f"Lexicon row {row} needs nonempty pronunciation "
                             f"text of at most {MAX_IPA_CHARACTERS} characters "
                             "without control characters.")
        # Split only on spaces: IPA modifiers and combining marks stay atomic.
        tokens = [token for token in ipa.split(" ") if token]
        if any(any(c.isspace() for c in token) for token in tokens):
            raise ValueError(f"Lexicon row {row} must separate tokens with "
                             "ASCII spaces.")
        key = unicodedata.normalize("NFC", word)
        identity = tuple(unicodedata.normalize("NFC", token)
                         for token in tokens)
        variants = entries.setdefault(key, {})
        if identity in variants:
            variants[identity]["row_count"] += 1
        else:
            if len(variants) >= MAX_VARIANTS:
                raise ValueError(f"Lexicon row {row} exceeds {MAX_VARIANTS} "
                                 "distinct candidates for one key.")
            variants[identity] = {"tokens": tokens, "source_row": row,
                                  "row_count": 1}
    if not entries:
        raise ValueError("Lexicon contains no pronunciation rows.")
    return entries, row_count


def lookup_text(text: str, lexicon_path: pathlib.Path, *, source_label: str,
                data_license: str) -> dict:
    """Return every supplied candidate per occurrence, preserving offsets.

    Keys use NFC and exact case. Apostrophes, accents and hyphens are retained;
    Other punctuation separates units. IPA is opaque, not validated.

    Args:
        text: Original text, at most 16000 Python characters and 1024 units.
        lexicon_path: Local UTF-8 word<TAB>space-separated-token file.
        source_label: Caller declaration identifying the resource/version.
        data_license: Caller-declared data terms, separate from code terms.

    Returns:
        A mechanical lookup report with every candidate and explicit limits.

    Raises:
        ValueError: Input is malformed or exceeds the documented bounds.
        OSError: The lexicon cannot be read.
        UnicodeError: The lexicon is not UTF-8.
    """
    source_label = _declaration(source_label, "source_label")
    data_license = _declaration(data_license, "data_license")
    if (not isinstance(text, str) or not text.strip()
            or len(text) > MAX_TEXT_CHARACTERS):
        raise ValueError("text must be nonblank and at most 16000 characters.")
    spans = _units(text)
    if not spans or len(spans) > MAX_OCCURRENCES:
        raise ValueError("text must contain between 1 and 1024 joined units.")
    entries, row_count = _read_lexicon(lexicon_path)
    occurrences = []
    counts = {"single_candidate": 0, "multiple_candidates": 0, "missing": 0}
    for start, end in spans:
        original = text[start:end]
        key = unicodedata.normalize("NFC", original)
        candidates = list(entries.get(key, {}).values())
        if not candidates:
            status = "missing"
        elif len(candidates) == 1:
            status = "single_candidate"
        else:
            status = "multiple_candidates"
        counts[status] += 1
        occurrences.append({"text": original, "start": start, "end": end,
                            "lookup_key": key, "status": status,
                            "candidates": candidates})
    return {
        "schema_version": 1, "status": "pass", "assessment_limit": LIMIT,
        "original_text": text, "key_normalization": "NFC",
        "case_sensitive": True, "offset_unit": "Python Unicode code points",
        "end_offset_exclusive": True,
        "source_declaration": {"label": source_label,
                               "data_license": data_license},
        "lexicon_row_count": row_count, "lexicon_key_count": len(entries),
        "occurrence_counts": counts, "occurrences": occurrences,
        "permissions_verified": False, "native_review_verified": False,
        "pronunciation_assessed": False, "model_phone_mapping_assessed": False,
    }
