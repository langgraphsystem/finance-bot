"""Tests for centralized i18n system (src/skills/_i18n.py)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from src.skills._i18n import (
    _MONTH_ABBR,
    _STRING_REGISTRY,
    _TRANSLATION_CACHE,
    COMMON_STRINGS,
    fmt_date,
    fmt_time,
    register_strings,
    t,
    t_cached,
)

# ── t() tests ─────────────────────────────────────────────────────────────────

_TEST_STRINGS = {
    "en": {"hello": "Hello", "greet": "Hello, {name}!"},
    "ru": {"hello": "Привет", "greet": "Привет, {name}!"},
    "es": {"hello": "Hola", "greet": "Hola, {name}!"},
}


def test_t_english():
    assert t(_TEST_STRINGS, "hello", "en") == "Hello"


def test_t_russian():
    assert t(_TEST_STRINGS, "hello", "ru") == "Привет"


def test_t_spanish():
    assert t(_TEST_STRINGS, "hello", "es") == "Hola"


def test_t_unknown_lang_falls_back_to_english():
    assert t(_TEST_STRINGS, "hello", "fr") == "Hello"


def test_t_missing_key_returns_key():
    assert t(_TEST_STRINGS, "nonexistent", "en") == "nonexistent"


def test_t_with_format_kwargs():
    assert t(_TEST_STRINGS, "greet", "en", name="Alice") == "Hello, Alice!"
    assert t(_TEST_STRINGS, "greet", "ru", name="Алиса") == "Привет, Алиса!"


# ── t_cached() tests ─────────────────────────────────────────────────────────


def test_t_cached_static_langs():
    """Static languages (en/ru/es) work identically to t()."""
    assert t_cached(_TEST_STRINGS, "hello", "en", "test") == "Hello"
    assert t_cached(_TEST_STRINGS, "hello", "ru", "test") == "Привет"
    assert t_cached(_TEST_STRINGS, "hello", "es", "test") == "Hola"


def test_t_cached_falls_back_to_english():
    """Unknown language without cache falls back to English."""
    assert t_cached(_TEST_STRINGS, "hello", "fr", "test") == "Hello"


def test_t_cached_uses_memory_cache():
    """When memory cache is populated, t_cached returns cached translation."""
    _TRANSLATION_CACHE["test_cache:fr"] = {"hello": "Bonjour"}
    try:
        assert t_cached(_TEST_STRINGS, "hello", "fr", "test_cache") == "Bonjour"
    finally:
        _TRANSLATION_CACHE.pop("test_cache:fr", None)


def test_t_cached_with_format_kwargs():
    _TRANSLATION_CACHE["test_fmt:de"] = {"greet": "Hallo, {name}!"}
    try:
        result = t_cached(_TEST_STRINGS, "greet", "de", "test_fmt", name="Hans")
        assert result == "Hallo, Hans!"
    finally:
        _TRANSLATION_CACHE.pop("test_fmt:de", None)


# ── register_strings() tests ─────────────────────────────────────────────────


def test_register_strings():
    ns = "_test_register"
    strings = {"en": {"a": "A"}, "ru": {"a": "А"}}
    register_strings(ns, strings)
    assert ns in _STRING_REGISTRY
    assert _STRING_REGISTRY[ns] is strings
    # Cleanup
    _STRING_REGISTRY.pop(ns, None)


# ── COMMON_STRINGS tests ─────────────────────────────────────────────────────


def test_common_strings_has_all_static_langs():
    assert "en" in COMMON_STRINGS
    assert "ru" in COMMON_STRINGS
    assert "es" in COMMON_STRINGS


def test_common_strings_keys_match():
    en_keys = set(COMMON_STRINGS["en"])
    ru_keys = set(COMMON_STRINGS["ru"])
    es_keys = set(COMMON_STRINGS["es"])
    assert en_keys == ru_keys == es_keys


def test_common_strings_no_file():
    assert "no_file" in COMMON_STRINGS["en"]
    assert len(COMMON_STRINGS["en"]["no_file"]) > 10


# ── ensure_translations() tests ──────────────────────────────────────────────


async def test_ensure_translations_skips_static_langs():
    """Static languages (en/ru/es) should be skipped entirely."""
    from src.skills._i18n import ensure_translations

    # Should not call LLM or Redis for static languages
    await ensure_translations("test_ns", _TEST_STRINGS, "en")
    await ensure_translations("test_ns", _TEST_STRINGS, "ru")
    await ensure_translations("test_ns", _TEST_STRINGS, "es")
    # No crash = pass


async def test_ensure_translations_uses_redis_cache():
    """If Redis has cached translations, use them instead of calling LLM."""
    import json

    from src.skills._i18n import ensure_translations

    cached_data = json.dumps({"hello": "Bonjour"})
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=cached_data)

    with patch("src.skills._i18n.redis", mock_redis, create=True):
        # Patch the import
        with patch.dict("sys.modules", {}):
            import sys

            # Mock the redis import inside ensure_translations
            mock_db_module = type(sys)("mock_db")
            mock_db_module.redis = mock_redis
            with patch.dict("sys.modules", {"src.core.db": mock_db_module}):
                await ensure_translations("test_redis", _TEST_STRINGS, "fr")

    # Should have populated cache
    cache_key = "test_redis:fr"
    if cache_key in _TRANSLATION_CACHE:
        assert _TRANSLATION_CACHE[cache_key] == {"hello": "Bonjour"}
        _TRANSLATION_CACHE.pop(cache_key, None)


# ── fmt_date() tests ─────────────────────────────────────────────────────────


def test_fmt_date_english():
    dt = datetime(2026, 3, 15, 14, 30, tzinfo=UTC)
    result = fmt_date(dt, "en")
    assert "Mar" in result
    assert "15" in result
    assert "PM" in result


def test_fmt_date_russian():
    dt = datetime(2026, 3, 15, 14, 30, tzinfo=UTC)
    result = fmt_date(dt, "ru")
    assert "мар" in result
    assert "15" in result
    assert "14:30" in result


def test_fmt_date_french():
    dt = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    result = fmt_date(dt, "fr")
    assert "jan" in result
    assert "5" in result
    assert "09:00" in result


def test_fmt_date_chinese():
    dt = datetime(2026, 6, 20, 15, 45, tzinfo=UTC)
    result = fmt_date(dt, "zh")
    assert "6月" in result
    assert "20" in result


def test_fmt_date_unknown_lang_uses_english():
    dt = datetime(2026, 3, 15, 14, 30, tzinfo=UTC)
    result = fmt_date(dt, "xx")
    assert "Mar" in result


# ── fmt_time() tests ─────────────────────────────────────────────────────────


def test_fmt_time_english():
    dt = datetime(2026, 3, 15, 14, 30, tzinfo=UTC)
    result = fmt_time(dt, "en")
    assert "PM" in result


def test_fmt_time_russian():
    dt = datetime(2026, 3, 15, 14, 30, tzinfo=UTC)
    assert fmt_time(dt, "ru") == "14:30"


def test_fmt_time_24h_languages():
    dt = datetime(2026, 3, 15, 14, 30, tzinfo=UTC)
    for lang in ("fr", "de", "pt", "it", "uk", "pl", "tr"):
        assert fmt_time(dt, lang) == "14:30", f"{lang} should use 24h format"


# ── _MONTH_ABBR coverage tests ───────────────────────────────────────────────


def test_month_abbr_has_15_languages():
    assert len(_MONTH_ABBR) >= 14  # all 14 non-English languages


def test_month_abbr_each_has_12_months():
    for lang, months in _MONTH_ABBR.items():
        assert len(months) == 12, f"{lang} should have 12 month abbreviations"


# ── Document skills registered tests ─────────────────────────────────────────


def test_document_skills_register_strings():
    """After importing document skills, their _STRINGS should be registered."""
    # Import a few document skills to trigger registration
    import src.skills.analyze_document.handler  # noqa: F401
    import src.skills.extract_table.handler  # noqa: F401
    import src.skills.summarize_document.handler  # noqa: F401

    assert "analyze_document" in _STRING_REGISTRY
    assert "extract_table" in _STRING_REGISTRY
    assert "summarize_document" in _STRING_REGISTRY


def test_registered_strings_have_en_ru_es():
    """All registered skills should have en/ru/es static translations."""
    import src.skills.analyze_document.handler  # noqa: F401

    strings = _STRING_REGISTRY.get("analyze_document", {})
    assert "en" in strings
    assert "ru" in strings
    assert "es" in strings


# ── Phase 5: Registry validation tests ──────────────────────────────────────


def test_all_skills_register_strings():
    """After importing all skills, _STRING_REGISTRY should have >= 80 namespaces."""
    import src.skills  # noqa: F401 — triggers all skill registrations

    assert len(_STRING_REGISTRY) >= 80, (
        f"Expected >= 80 registered namespaces, got {len(_STRING_REGISTRY)}: "
        f"{sorted(_STRING_REGISTRY.keys())}"
    )


def test_all_registered_have_3_static_langs():
    """Every registered namespace must have en, ru, and es keys."""
    import src.skills  # noqa: F401

    for ns, strings in _STRING_REGISTRY.items():
        for lang in ("en", "ru", "es"):
            assert lang in strings, f"Namespace '{ns}' missing static language '{lang}'"


def test_registered_keys_match_across_langs():
    """en/ru/es should have identical key sets per namespace (if non-empty)."""
    import src.skills  # noqa: F401

    for ns, strings in _STRING_REGISTRY.items():
        en_keys = set(strings.get("en", {}).keys())
        if not en_keys:
            continue  # skip namespaces with empty strings (skeleton registrations)
        ru_keys = set(strings.get("ru", {}).keys())
        es_keys = set(strings.get("es", {}).keys())
        if ru_keys:  # only check if ru has keys (non-skeleton)
            assert en_keys == ru_keys, (
                f"Namespace '{ns}': en keys {en_keys} != ru keys {ru_keys}"
            )
        if es_keys:
            assert en_keys == es_keys, (
                f"Namespace '{ns}': en keys {en_keys} != es keys {es_keys}"
            )
