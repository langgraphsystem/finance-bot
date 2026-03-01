"""Tests for LLM translation pipeline quality in src/skills/_i18n.py."""

import json
from unittest.mock import AsyncMock, patch

from src.skills._i18n import _TRANSLATION_CACHE, ensure_translations

# ── Helpers ──────────────────────────────────────────────────────────────────

_TEST_NAMESPACE = "_test_tq"
_TEST_LANG = "fr"

_ENGLISH_STRINGS = {
    "en": {
        "greeting": "Hello, {name}!",
        "count_msg": "You have {count} items worth {amount}.",
        "bold_msg": "<b>Important</b>: check your <i>inbox</i>.",
        "code_msg": "Run <code>pip install</code> to start.",
        "simple": "Good morning.",
    }
}

_LLM_PATCH = "src.core.llm.clients.generate_text"


def _cache_key(lang: str = _TEST_LANG) -> str:
    return f"{_TEST_NAMESPACE}:{lang}"


def _cleanup_cache(*langs: str) -> None:
    for lang in langs or [_TEST_LANG]:
        _TRANSLATION_CACHE.pop(f"{_TEST_NAMESPACE}:{lang}", None)


def _mock_redis(get_return=None, get_side_effect=None):
    """Create a mock Redis object with configurable .get() behaviour."""
    mock = AsyncMock()
    if get_side_effect is not None:
        mock.get = AsyncMock(side_effect=get_side_effect)
    else:
        mock.get = AsyncMock(return_value=get_return)
    mock.set = AsyncMock()
    return mock


# ── Tests ────────────────────────────────────────────────────────────────────


async def test_placeholder_preservation():
    """Translated values must keep {name}, {count}, {amount} placeholders."""
    translated_json = json.dumps({
        "greeting": "Bonjour, {name} !",
        "count_msg": "Vous avez {count} articles d'une valeur de {amount}.",
        "bold_msg": "<b>Important</b> : vérifiez votre <i>boîte de réception</i>.",
        "code_msg": "Exécutez <code>pip install</code> pour commencer.",
        "simple": "Bonjour.",
    })

    mock_redis = _mock_redis(get_return=None)
    try:
        with (
            patch("src.core.db.redis", mock_redis),
            patch(_LLM_PATCH, new_callable=AsyncMock, return_value=translated_json),
        ):
            await ensure_translations(_TEST_NAMESPACE, _ENGLISH_STRINGS, _TEST_LANG)

        cached = _TRANSLATION_CACHE.get(_cache_key())
        assert cached is not None, "Translation must be cached"
        assert "{name}" in cached["greeting"]
        assert "{count}" in cached["count_msg"]
        assert "{amount}" in cached["count_msg"]
    finally:
        _cleanup_cache()


async def test_html_tags_preservation():
    """HTML tags <b>, <i>, <code> must survive in cached translations."""
    translated_json = json.dumps({
        "greeting": "Bonjour, {name} !",
        "count_msg": "Vous avez {count} articles d'une valeur de {amount}.",
        "bold_msg": "<b>Important</b> : vérifiez votre <i>boîte</i>.",
        "code_msg": "Exécutez <code>pip install</code> pour démarrer.",
        "simple": "Bonjour.",
    })

    mock_redis = _mock_redis(get_return=None)
    try:
        with (
            patch("src.core.db.redis", mock_redis),
            patch(_LLM_PATCH, new_callable=AsyncMock, return_value=translated_json),
        ):
            await ensure_translations(_TEST_NAMESPACE, _ENGLISH_STRINGS, _TEST_LANG)

        cached = _TRANSLATION_CACHE.get(_cache_key())
        assert cached is not None
        assert "<b>" in cached["bold_msg"] and "</b>" in cached["bold_msg"]
        assert "<i>" in cached["bold_msg"] and "</i>" in cached["bold_msg"]
        assert "<code>" in cached["code_msg"] and "</code>" in cached["code_msg"]
    finally:
        _cleanup_cache()


async def test_all_keys_present_after_translation():
    """Translated dict must have the same keys as English source."""
    en_keys = set(_ENGLISH_STRINGS["en"].keys())
    translated_json = json.dumps({
        "greeting": "Bonjour, {name} !",
        "count_msg": "Vous avez {count} articles.",
        "bold_msg": "<b>Important</b>.",
        "code_msg": "<code>pip install</code>.",
        "simple": "Bonjour.",
    })

    mock_redis = _mock_redis(get_return=None)
    try:
        with (
            patch("src.core.db.redis", mock_redis),
            patch(_LLM_PATCH, new_callable=AsyncMock, return_value=translated_json),
        ):
            await ensure_translations(_TEST_NAMESPACE, _ENGLISH_STRINGS, _TEST_LANG)

        cached = _TRANSLATION_CACHE.get(_cache_key())
        assert cached is not None
        assert set(cached.keys()) == en_keys
    finally:
        _cleanup_cache()


async def test_malformed_llm_output_no_crash():
    """Invalid JSON from LLM must not raise; cache must NOT be populated."""
    mock_redis = _mock_redis(get_return=None)
    try:
        with (
            patch("src.core.db.redis", mock_redis),
            patch(
                _LLM_PATCH,
                new_callable=AsyncMock,
                return_value="This is not valid JSON at all {{{",
            ),
        ):
            # Must not raise
            await ensure_translations(_TEST_NAMESPACE, _ENGLISH_STRINGS, _TEST_LANG)

        assert _cache_key() not in _TRANSLATION_CACHE
    finally:
        _cleanup_cache()


async def test_markdown_fence_stripping():
    """LLM output wrapped in ```json ... ``` fences must be parsed correctly."""
    inner = json.dumps({
        "greeting": "Hallo, {name}!",
        "count_msg": "{count} Artikel, {amount} Wert.",
        "bold_msg": "<b>Wichtig</b>.",
        "code_msg": "<code>pip install</code>.",
        "simple": "Guten Morgen.",
    })
    fenced = f"```json\n{inner}\n```"

    mock_redis = _mock_redis(get_return=None)
    try:
        with (
            patch("src.core.db.redis", mock_redis),
            patch(_LLM_PATCH, new_callable=AsyncMock, return_value=fenced),
        ):
            await ensure_translations(_TEST_NAMESPACE, _ENGLISH_STRINGS, "de")

        cached = _TRANSLATION_CACHE.get(_cache_key("de"))
        assert cached is not None, "Fenced JSON should be parsed"
        assert cached["greeting"] == "Hallo, {name}!"
    finally:
        _cleanup_cache("de")


async def test_redis_cache_hit_skips_llm():
    """When Redis already has cached translations, generate_text must NOT be called."""
    cached_data = json.dumps({"greeting": "Bonjour, {name} !", "simple": "Bonjour."})
    mock_redis = _mock_redis(get_return=cached_data)

    try:
        with (
            patch("src.core.db.redis", mock_redis),
            patch(_LLM_PATCH, new_callable=AsyncMock) as mock_llm,
        ):
            await ensure_translations(_TEST_NAMESPACE, _ENGLISH_STRINGS, _TEST_LANG)
            mock_llm.assert_not_called()

        # Cache should still be populated from Redis hit
        cached = _TRANSLATION_CACHE.get(_cache_key())
        assert cached is not None
        assert cached["greeting"] == "Bonjour, {name} !"
    finally:
        _cleanup_cache()


async def test_static_language_skip():
    """Static languages (en, ru, es) must skip both Redis and LLM entirely."""
    mock_redis = _mock_redis()
    with (
        patch("src.core.db.redis", mock_redis),
        patch(_LLM_PATCH, new_callable=AsyncMock) as mock_llm,
    ):
        await ensure_translations(_TEST_NAMESPACE, _ENGLISH_STRINGS, "ru")
        mock_llm.assert_not_called()
        mock_redis.get.assert_not_called()


async def test_empty_english_strings_skip():
    """When English source dict is empty, generate_text must not be called."""
    mock_redis = _mock_redis(get_return=None)
    try:
        with (
            patch("src.core.db.redis", mock_redis),
            patch(_LLM_PATCH, new_callable=AsyncMock) as mock_llm,
        ):
            await ensure_translations(_TEST_NAMESPACE, {"en": {}}, _TEST_LANG)
            mock_llm.assert_not_called()

        assert _cache_key() not in _TRANSLATION_CACHE
    finally:
        _cleanup_cache()


async def test_non_dict_response_ignored():
    """If LLM returns a JSON array instead of a dict, cache must not be populated."""
    mock_redis = _mock_redis(get_return=None)
    try:
        with (
            patch("src.core.db.redis", mock_redis),
            patch(
                _LLM_PATCH,
                new_callable=AsyncMock,
                return_value='["not", "a", "dict"]',
            ),
        ):
            await ensure_translations(_TEST_NAMESPACE, _ENGLISH_STRINGS, _TEST_LANG)

        assert _cache_key() not in _TRANSLATION_CACHE
    finally:
        _cleanup_cache()


async def test_redis_unavailable_returns_gracefully():
    """If Redis raises on .get(), function must return without crashing."""
    try:
        mock_redis = _mock_redis(get_side_effect=ConnectionError("Redis down"))
        with (
            patch("src.core.db.redis", mock_redis),
            patch(_LLM_PATCH, new_callable=AsyncMock) as mock_llm,
        ):
            # Must not raise
            await ensure_translations(_TEST_NAMESPACE, _ENGLISH_STRINGS, _TEST_LANG)
            # LLM should NOT be called because function returns early on Redis failure
            mock_llm.assert_not_called()

        assert _cache_key() not in _TRANSLATION_CACHE
    finally:
        _cleanup_cache()
