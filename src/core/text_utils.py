"""Shared text utilities: fuzzy matching, normalization, deduplication."""

from difflib import SequenceMatcher

SIMILARITY_THRESHOLD = 0.75


def normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, strip."""
    return " ".join(text.lower().strip().split())


def is_similar(a: str, b: str, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """Check if two texts are near-duplicates.

    Uses containment check first (fast path), then SequenceMatcher ratio.
    """
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def deduplicate_texts(
    items: list[str],
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[str]:
    """Remove near-duplicate strings, keeping first occurrence."""
    unique: list[str] = []
    for item in items:
        if not any(is_similar(item, u, threshold) for u in unique):
            unique.append(item)
    return unique


def fuzzy_find(
    query: str,
    candidates: list[str],
    threshold: float = 0.6,
) -> str | None:
    """Find the best fuzzy match for query among candidates.

    Returns the best match above threshold, or None.
    """
    query_n = normalize_text(query)
    if not query_n:
        return None

    best_score = 0.0
    best_match: str | None = None
    for candidate in candidates:
        cand_n = normalize_text(candidate)
        if not cand_n:
            continue
        if query_n == cand_n:
            return candidate
        if query_n in cand_n or cand_n in query_n:
            score = 0.9
        else:
            score = SequenceMatcher(None, query_n, cand_n).ratio()
        if score > best_score and score >= threshold:
            best_score = score
            best_match = candidate
    return best_match
