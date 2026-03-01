"""Tests for RTL (Arabic, Hebrew) and Asian (Chinese, Japanese, Korean) i18n support."""

from datetime import UTC, datetime

from src.skills._i18n import (
    _24H_LANGUAGES,
    _MONTH_ABBR,
    _TRANSLATION_CACHE,
    LANG_NAMES,
    fmt_date,
    fmt_time,
    lang_instruction,
    t_cached,
)

# Base datetime used across all tests: 2026-03-15 14:30 UTC
DT = datetime(2026, 3, 15, 14, 30, tzinfo=UTC)


# ── RTL tests: Arabic ────────────────────────────────────────────────────────


def test_fmt_date_arabic():
    """Arabic month name is used and output is in 24h format."""
    result = fmt_date(DT, "ar")
    assert "مارس" in result
    assert "14:30" in result


def test_fmt_time_arabic():
    """Arabic time uses 24h format."""
    result = fmt_time(DT, "ar")
    assert result == "14:30"


def test_arabic_months_complete():
    """_MONTH_ABBR['ar'] has exactly 12 non-empty entries."""
    months = _MONTH_ABBR["ar"]
    assert len(months) == 12
    for m in months:
        assert isinstance(m, str) and len(m) > 0


def test_lang_instruction_arabic():
    """lang_instruction('ar') returns instruction containing 'Arabic'."""
    result = lang_instruction("ar")
    assert "Arabic" in result
    assert "IMPORTANT" in result


def test_t_cached_arabic_from_cache():
    """Populate _TRANSLATION_CACHE and verify Arabic string is returned."""
    strings = {"en": {"greeting": "Hello"}}
    cache_key = "test_ar_ns:ar"
    try:
        _TRANSLATION_CACHE[cache_key] = {"greeting": "مرحبا"}
        result = t_cached(strings, "greeting", "ar", namespace="test_ar_ns")
        assert result == "مرحبا"
    finally:
        _TRANSLATION_CACHE.pop(cache_key, None)


def test_fmt_date_arabic_specific_months():
    """March in Arabic is specifically 'مارس'."""
    result = fmt_date(DT, "ar")
    # DT is March 15 — month index 2 → _MONTH_ABBR["ar"][2]
    assert _MONTH_ABBR["ar"][2] == "مارس"
    assert "مارس" in result


# ── RTL tests: Hebrew ─────────────────────────────────────────────────────────


def test_fmt_date_hebrew_fallback():
    """Hebrew (he) is not in _MONTH_ABBR, so fmt_date falls back to English."""
    result = fmt_date(DT, "he")
    # English fallback uses strftime %b → "Mar"
    assert "Mar" in result


def test_lang_instruction_hebrew_uses_code():
    """Hebrew (he) is not in LANG_NAMES, so falls back to raw code 'he'."""
    assert "he" not in LANG_NAMES
    result = lang_instruction("he")
    assert "he" in result
    assert "IMPORTANT" in result


# ── Asian language tests: Chinese ─────────────────────────────────────────────


def test_fmt_date_chinese():
    """Chinese month format uses '3月' for March."""
    result = fmt_date(DT, "zh")
    assert "3月" in result
    assert "14:30" in result


def test_fmt_time_chinese_24h():
    """Chinese time uses 24h format."""
    result = fmt_time(DT, "zh")
    assert result == "14:30"


def test_chinese_months_complete():
    """_MONTH_ABBR['zh'] has exactly 12 entries."""
    months = _MONTH_ABBR["zh"]
    assert len(months) == 12
    for i, m in enumerate(months, 1):
        assert m == f"{i}月"


# ── Asian language tests: Japanese ────────────────────────────────────────────


def test_fmt_date_japanese():
    """Japanese month format uses '3月' for March."""
    result = fmt_date(DT, "ja")
    assert "3月" in result
    assert "14:30" in result


def test_fmt_date_japanese_tokyo_tz():
    """Japanese date with Asia/Tokyo timezone — UTC+9 shifts 14:30 to 23:30."""
    result = fmt_date(DT, "ja", timezone="Asia/Tokyo")
    assert "23:30" in result
    assert "3月" in result


def test_japanese_months_complete():
    """_MONTH_ABBR['ja'] has exactly 12 entries."""
    months = _MONTH_ABBR["ja"]
    assert len(months) == 12
    for i, m in enumerate(months, 1):
        assert m == f"{i}月"


# ── Asian language tests: Korean ──────────────────────────────────────────────


def test_fmt_date_korean():
    """Korean month format uses '12월' for December."""
    dt_dec = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
    result = fmt_date(dt_dec, "ko")
    assert "12월" in result


def test_korean_months_complete():
    """_MONTH_ABBR['ko'] has exactly 12 entries."""
    months = _MONTH_ABBR["ko"]
    assert len(months) == 12
    for i, m in enumerate(months, 1):
        assert m == f"{i}월"


# ── Cross-cutting tests ──────────────────────────────────────────────────────


def test_all_asian_languages_24h():
    """Chinese, Japanese, and Korean are all in _24H_LANGUAGES."""
    for lang in ("zh", "ja", "ko"):
        assert lang in _24H_LANGUAGES, f"{lang} should be in _24H_LANGUAGES"


def test_t_cached_cjk_strings():
    """Cache lookup works with CJK characters for zh, ja, ko."""
    strings = {"en": {"welcome": "Welcome"}}
    translations = {
        "zh": "欢迎",
        "ja": "ようこそ",
        "ko": "환영합니다",
    }
    try:
        for lang, translated in translations.items():
            cache_key = f"test_cjk_ns:{lang}"
            _TRANSLATION_CACHE[cache_key] = {"welcome": translated}

        for lang, expected in translations.items():
            result = t_cached(strings, "welcome", lang, namespace="test_cjk_ns")
            assert result == expected, f"Expected '{expected}' for {lang}, got '{result}'"
    finally:
        for lang in translations:
            _TRANSLATION_CACHE.pop(f"test_cjk_ns:{lang}", None)
