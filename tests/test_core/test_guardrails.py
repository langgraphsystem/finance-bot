"""Tests for guardrails refusal detection."""

from src.core.guardrails import REFUSAL_MESSAGE, _is_refusal


def test_refusal_detected_russian():
    """Russian refusal message should be detected."""
    assert _is_refusal("Я финансовый помощник") is True


def test_refusal_detected_full_message():
    """Full default refusal message should be detected."""
    assert _is_refusal(REFUSAL_MESSAGE) is True


def test_non_refusal_passed():
    """Normal financial response should NOT be a refusal."""
    assert _is_refusal("Записал расход 50 на дизель") is False


def test_english_refusal_cant_help():
    """English 'I can't help with that' should be detected."""
    assert _is_refusal("I can't help with that") is True


def test_english_refusal_cannot_help():
    """English 'I cannot help with that' should be detected."""
    assert _is_refusal("I cannot help with that") is True


def test_english_refusal_sorry():
    """English 'Sorry, I can't' should be detected."""
    assert _is_refusal("Sorry, I can't do that for you") is True


def test_refusal_case_insensitive():
    """Refusal detection should be case-insensitive."""
    assert _is_refusal("ФИНАНСОВЫЙ ПОМОЩНИК") is True
    assert _is_refusal("i CAN'T HELP WITH THAT") is True


def test_empty_string_not_refusal():
    """Empty string should not be detected as refusal."""
    assert _is_refusal("") is False


def test_unrelated_text_not_refusal():
    """Completely unrelated text should not trigger refusal."""
    assert _is_refusal("Погода сегодня хорошая") is False
