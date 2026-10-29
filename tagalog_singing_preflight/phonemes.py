"""Check caller-declared model tokens without inventing phoneme mappings."""

from __future__ import annotations

from tagalog_singing_preflight import timing


def check_vocabulary(groups: list[str], vocabulary: list[str]) -> dict:
    """Check whitespace-delimited tokens in each supplied timing group.

    A group may contain one or more tokens. Group boundaries are preserved;
    the caller must provide the vocabulary used by its receiving model.
    """
    if (not isinstance(groups, list) or not groups
            or len(groups) > timing.MAX_GROUPS
            or any(not isinstance(group, str) or not group.strip()
                   for group in groups)):
        raise ValueError("phoneme_groups must be a nonempty list of strings.")
    if (not isinstance(vocabulary, list) or not vocabulary
            or len(vocabulary) > 1_000_000
            or any(not isinstance(token, str) or not token
                   or len(token.split()) != 1 for token in vocabulary)):
        raise ValueError("vocabulary must contain nonempty single-token strings.")
    declared = set(vocabulary)
    unknown = []
    token_count = 0
    for index, group in enumerate(groups):
        tokens = group.split()
        token_count += len(tokens)
        for token in tokens:
            if token not in declared:
                unknown.append({"group_index": index, "token": token})
    return {
        "group_count": len(groups),
        "token_count": token_count,
        "declared_vocabulary_size": len(declared),
        "unknown_tokens": unknown,
        "tokens_supported_by_declared_vocabulary": not unknown,
        "pronunciation_assessed": False,
    }
