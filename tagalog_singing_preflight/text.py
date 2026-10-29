"""Preserve written text and provide an explicitly separate frontend hint."""

from __future__ import annotations

import unicodedata


def normalize_hint(text: str) -> dict:
    """Return NFC text and intra-word curly-apostrophe hints, never a G2P result.

    Spacing, diacritics and phonetic glottal symbols remain intact. Curly marks
    outside a letter-to-letter contraction remain intact too.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a nonempty string.")
    if len(text) > 1_000_000:
        raise ValueError("text exceeds 1000000 characters.")
    nfc = unicodedata.normalize("NFC", text)
    characters = list(nfc)
    replacements = []
    for index, character in enumerate(characters):
        if character not in ("\u2018", "\u2019") or not 0 < index < len(nfc) - 1:
            continue
        if (unicodedata.category(nfc[index - 1]).startswith("L")
                and unicodedata.category(nfc[index + 1]).startswith("L")):
            characters[index] = "'"
            replacements.append(index)
    warnings = []
    if replacements:
        warnings.append({
            "code": "CONTRACTION_HINT_ONLY",
            "message": "An ASCII apostrophe hint does not validate pronunciation.",
        })
    if any(mark in nfc for mark in ("\u02bc", "\u0294")):
        warnings.append({
            "code": "GLOTTAL_SYMBOL_PRESERVED",
            "message": "Glottal symbols need explicit receiving-model support.",
        })
    return {
        "original": text,
        "nfc": nfc,
        "frontend_hint": "".join(characters),
        "apostrophe_hint_indices": replacements,
        "warnings": warnings,
        "pronunciation_assessed": False,
    }
