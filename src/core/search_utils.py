"""Shared text search utilities for word-level ILIKE matching."""

import re

from sqlalchemy import and_

# Short stop words to drop from search queries (RU + EN)
_STOP_WORDS = {
    "and", "or", "the", "for", "in", "on", "at", "to", "of", "is", "it", "my",
    "и", "или", "для", "на", "за", "от", "про", "в", "с", "по", "к", "у", "о", "об",
    "мои", "мой", "моя", "моё", "мне", "меня",
}


def split_search_words(text: str, min_len: int = 2) -> list[str]:
    """Split search text into meaningful words, dropping stop words.

    >>> split_search_words("сухур и ифтар")
    ['сухур', 'ифтар']
    >>> split_search_words("delete notes for January")
    ['delete', 'notes', 'january']
    """
    return [
        w
        for w in re.findall(r"[а-яёa-z0-9]+", text.lower())
        if w not in _STOP_WORDS and len(w) >= min_len
    ]


def ilike_all_words(column, words: list[str]):
    """Build AND condition: column ILIKE '%word1%' AND column ILIKE '%word2%' ...

    Each word must be present in the column for the row to match.
    """
    return and_(*(column.ilike(f"%{w}%") for w in words))
