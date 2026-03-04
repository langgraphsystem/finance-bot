"""Tests for shared text utilities: fuzzy matching, normalization, dedup."""

from src.core.text_utils import deduplicate_texts, fuzzy_find, is_similar, normalize_text

# --- normalize_text ---


def test_normalize_text_basic():
    assert normalize_text("  Hello   World  ") == "hello world"


def test_normalize_text_empty():
    assert normalize_text("") == ""


def test_normalize_text_tabs_newlines():
    assert normalize_text("foo\t\nbar") == "foo bar"


# --- is_similar ---


def test_is_similar_exact():
    assert is_similar("coffee", "coffee")


def test_is_similar_case_insensitive():
    assert is_similar("Coffee", "coffee")


def test_is_similar_substring():
    assert is_similar("coffee", "morning coffee at cafe")


def test_is_similar_high_ratio():
    assert is_similar("Groceries", "Grocery")


def test_is_similar_different():
    assert not is_similar("coffee", "basketball")


def test_is_similar_empty():
    assert not is_similar("", "hello")
    assert not is_similar("hello", "")


def test_is_similar_custom_threshold():
    assert is_similar("cat", "bat", threshold=0.5)
    assert not is_similar("cat", "bat", threshold=0.9)


# --- deduplicate_texts ---


def test_deduplicate_exact():
    items = ["coffee", "coffee", "tea"]
    assert deduplicate_texts(items) == ["coffee", "tea"]


def test_deduplicate_near():
    items = ["Bought coffee at Starbucks", "bought coffee at starbucks", "went to gym"]
    result = deduplicate_texts(items)
    assert len(result) == 2
    assert "went to gym" in result


def test_deduplicate_empty():
    assert deduplicate_texts([]) == []


# --- fuzzy_find ---


def test_fuzzy_find_exact():
    candidates = ["Food", "Transport", "Shopping"]
    assert fuzzy_find("Food", candidates) == "Food"


def test_fuzzy_find_case():
    candidates = ["Food", "Transport", "Shopping"]
    assert fuzzy_find("food", candidates) == "Food"


def test_fuzzy_find_partial():
    candidates = ["Groceries", "Transport", "Shopping"]
    assert fuzzy_find("grocery", candidates) == "Groceries"


def test_fuzzy_find_substring():
    candidates = ["Morning coffee", "Evening tea", "Lunch"]
    assert fuzzy_find("coffee", candidates) == "Morning coffee"


def test_fuzzy_find_no_match():
    candidates = ["Food", "Transport"]
    assert fuzzy_find("basketball", candidates) is None


def test_fuzzy_find_empty_query():
    assert fuzzy_find("", ["a", "b"]) is None


def test_fuzzy_find_empty_candidates():
    assert fuzzy_find("food", []) is None
