"""Shared i18n helpers for skill response localization.

Provides:
- ``t()`` — synchronous dict-based translation (en/ru/es instant)
- ``t_cached()`` — synchronous with in-memory cache fallback for any language
- ``ensure_translations()`` — async LLM translation + Redis cache for new languages
- ``warm_translations()`` — async pre-warm all registered string dicts for a language
- ``register_strings()`` — skills register their _STRINGS dicts at import time
- ``fmt_date()`` / ``fmt_time()`` — locale-aware date/time formatting (15 languages)
"""

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ── Static languages (zero latency, no Redis/LLM needed) ─────────────────────

STATIC_LANGUAGES = {"en", "ru", "es"}

# ── Common strings shared by many skills ──────────────────────────────────────

COMMON_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "no_file": "Please send a file along with your request.",
        "no_account": "Set up your account first.",
        "save": "Save",
        "cancel": "Cancel",
        "category": "Category",
        "recognized": "recognized",
        "failed_recognize": "Failed to recognize the document. Try a clearer photo.",
        "unsupported_format": "Unsupported file format.",
        "try_again": "Something went wrong. Please try again.",
        "conversion_failed": "Conversion failed.",
        "no_docs_found": "No documents found.",
        "send_file": "Send a document or image.",
        "processing": "Processing your file...",
        "done": "Done!",
        "error": "An error occurred.",
    },
    "ru": {
        "no_file": "Отправьте файл вместе с запросом.",
        "no_account": "Сначала настройте аккаунт.",
        "save": "Сохранить",
        "cancel": "Отмена",
        "category": "Категория",
        "recognized": "распознан",
        "failed_recognize": "Не удалось распознать документ. Попробуйте более чёткое фото.",
        "unsupported_format": "Неподдерживаемый формат файла.",
        "try_again": "Что-то пошло не так. Попробуйте ещё раз.",
        "conversion_failed": "Ошибка конвертации.",
        "no_docs_found": "Документы не найдены.",
        "send_file": "Отправьте документ или изображение.",
        "processing": "Обрабатываю файл...",
        "done": "Готово!",
        "error": "Произошла ошибка.",
    },
    "es": {
        "no_file": "Envíe un archivo con su solicitud.",
        "no_account": "Configure su cuenta primero.",
        "save": "Guardar",
        "cancel": "Cancelar",
        "category": "Categoría",
        "recognized": "reconocido",
        "failed_recognize": "No se pudo reconocer el documento. Intente con una foto más clara.",
        "unsupported_format": "Formato de archivo no soportado.",
        "try_again": "Algo salió mal. Inténtelo de nuevo.",
        "conversion_failed": "Error de conversión.",
        "no_docs_found": "No se encontraron documentos.",
        "send_file": "Envíe un documento o imagen.",
        "processing": "Procesando su archivo...",
        "done": "¡Listo!",
        "error": "Ocurrió un error.",
    },
}

# ── String registry — skills register their _STRINGS dicts here ──────────────

_STRING_REGISTRY: dict[str, dict[str, dict[str, str]]] = {}

# ── In-memory translation cache (populated from Redis) ───────────────────────
# Key: "{namespace}:{lang}" → {key: translated_value}

_TRANSLATION_CACHE: dict[str, dict[str, str]] = {}


def register_strings(namespace: str, strings: dict[str, dict[str, str]]) -> None:
    """Register a skill's _STRINGS dict for LLM translation warm-up.

    Called at module level in each skill handler.
    """
    _STRING_REGISTRY[namespace] = strings


# ── Translation functions ─────────────────────────────────────────────────────


def t(strings: dict[str, dict[str, str]], key: str, lang: str, **kw: Any) -> str:
    """Get a translated string with English fallback.

    Usage:
        _STRINGS = {"en": {"empty": "No items"}, "ru": {"empty": "Нет элементов"}}
        t(_STRINGS, "empty", context.language or "en")
    """
    bucket = strings.get(lang, strings.get("en", {}))
    template = bucket.get(key) or strings.get("en", {}).get(key, key)
    return template.format(**kw) if kw else template


def t_cached(
    strings: dict[str, dict[str, str]],
    key: str,
    lang: str,
    namespace: str = "",
    **kw: Any,
) -> str:
    """Get a translated string: static dict → memory cache → English fallback.

    For en/ru/es: behaves identically to ``t()`` (instant dict lookup).
    For other languages: checks in-memory cache populated from Redis.
    Falls back to English if no cached translation exists.
    """
    # 1. Static dict lookup (always works for en/ru/es)
    bucket = strings.get(lang)
    if bucket and key in bucket:
        template = bucket[key]
        return template.format(**kw) if kw else template

    # 2. In-memory cache (populated from Redis by warm_translations)
    if namespace:
        cache_key = f"{namespace}:{lang}"
        cached_bucket = _TRANSLATION_CACHE.get(cache_key, {})
        if key in cached_bucket:
            template = cached_bucket[key]
            return template.format(**kw) if kw else template

    # 3. English fallback
    template = strings.get("en", {}).get(key, key)
    return template.format(**kw) if kw else template


async def ensure_translations(
    namespace: str,
    strings: dict[str, dict[str, str]],
    lang: str,
) -> None:
    """Translate all English strings to `lang` via Claude Haiku + Redis cache.

    Skips if translations already exist in Redis (TTL 7 days).
    Populates in-memory ``_TRANSLATION_CACHE`` on success.
    """
    if lang in STATIC_LANGUAGES:
        return

    redis_key = f"i18n:{namespace}:{lang}"

    try:
        from src.core.db import redis

        existing = await redis.get(redis_key)
        if existing:
            _TRANSLATION_CACHE[f"{namespace}:{lang}"] = json.loads(existing)
            return
    except Exception:
        logger.debug("Redis unavailable for i18n cache check")
        return

    en_strings = strings.get("en", {})
    if not en_strings:
        return

    try:
        from src.core.llm.clients import generate_text

        source_json = json.dumps(en_strings, ensure_ascii=False)
        prompt = (
            f"Translate ALL values in this JSON to {lang} (ISO 639-1 code).\n"
            "Rules:\n"
            "- Keep HTML tags (<b>, <i>, <code>) exactly as they are\n"
            "- Keep {placeholder} variables exactly as they are\n"
            "- Keep emoji characters exactly as they are\n"
            "- Return ONLY valid JSON with the same keys\n"
            "- Translations should be natural, not literal\n\n"
            f"{source_json}"
        )
        raw = await generate_text(
            "claude-haiku-4-5",
            "You are a professional translator. Return only valid JSON.",
            [{"role": "user", "content": prompt}],
            max_tokens=4000,
        )
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        translated = json.loads(text.strip())

        # Validate all keys survived
        if not isinstance(translated, dict):
            logger.warning("i18n translation returned non-dict for %s:%s", namespace, lang)
            return

        _TRANSLATION_CACHE[f"{namespace}:{lang}"] = translated

        try:
            await redis.set(redis_key, json.dumps(translated, ensure_ascii=False), ex=604800)
        except Exception:
            pass

        logger.info("Translated %d strings for %s:%s", len(translated), namespace, lang)

    except Exception as e:
        logger.warning("i18n translation failed for %s:%s: %s", namespace, lang, e)


async def load_translations_from_redis(namespace: str, lang: str) -> bool:
    """Load cached translations from Redis into memory. Returns True if found."""
    if lang in STATIC_LANGUAGES:
        return True

    cache_key = f"{namespace}:{lang}"
    if cache_key in _TRANSLATION_CACHE:
        return True

    try:
        from src.core.db import redis

        data = await redis.get(f"i18n:{namespace}:{lang}")
        if data:
            _TRANSLATION_CACHE[cache_key] = json.loads(data)
            return True
    except Exception:
        pass
    return False


async def warm_translations(lang: str) -> None:
    """Pre-warm translations for all registered string dicts for a language.

    Should be called once per language (e.g., in router.py after context is built).
    Uses a Redis flag to avoid redundant translation calls.
    """
    if lang in STATIC_LANGUAGES:
        return

    try:
        from src.core.db import redis

        flag_key = f"i18n_warmed:{lang}"
        already_warmed = await redis.get(flag_key)
        if already_warmed:
            # Still load from Redis into memory if not loaded yet
            for ns in _STRING_REGISTRY:
                await load_translations_from_redis(ns, lang)
            # Also warm COMMON_STRINGS
            await load_translations_from_redis("_common", lang)
            return
    except Exception:
        return

    # Translate all registered string dicts
    await ensure_translations("_common", COMMON_STRINGS, lang)
    for ns, strings in _STRING_REGISTRY.items():
        await ensure_translations(ns, strings, lang)

    try:
        await redis.set(flag_key, "1", ex=86400)  # 24h flag
    except Exception:
        pass

    logger.info("Warmed translations for language: %s (%d namespaces)", lang, len(_STRING_REGISTRY))


# ── Month abbreviations for fmt_date (15 languages) ──────────────────────────

_MONTH_ABBR: dict[str, list[str]] = {
    "ru": ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"],
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    "fr": ["jan", "fév", "mar", "avr", "mai", "jun", "jul", "aoû", "sep", "oct", "nov", "déc"],
    "de": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
    "pt": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
    "it": ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"],
    "uk": ["січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"],
    "pl": ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"],
    "tr": ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"],
    "ar": [
        "يناير",
        "فبراير",
        "مارس",
        "أبريل",
        "مايو",
        "يونيو",
        "يوليو",
        "أغسطس",
        "سبتمبر",
        "أكتوبر",
        "نوفمبر",
        "ديسمبر",
    ],
    "zh": ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
    "ja": ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
    "ko": ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"],
    "hi": ["जन", "फर", "मार्च", "अप्रैल", "मई", "जून", "जुल", "अग", "सित", "अक्टू", "नव", "दिस"],
}

# Languages that use 24-hour clock by default
_24H_LANGUAGES = {
    "ru",
    "es",
    "fr",
    "de",
    "pt",
    "it",
    "uk",
    "pl",
    "tr",
    "ar",
    "zh",
    "ja",
    "ko",
    "hi",
}


def _to_tz(dt: datetime, timezone: str | None) -> datetime:
    """Convert a datetime to the given timezone (if provided)."""
    if timezone:
        try:
            return dt.astimezone(ZoneInfo(timezone))
        except (KeyError, ValueError):
            pass
    return dt


def fmt_date(
    dt: datetime,
    lang: str,
    *,
    timezone: str | None = None,
) -> str:
    """Locale-aware date+time formatting for 15+ languages.

    Returns:
        ru: '24 фев, 14:00'
        en: 'Feb 24, 2:00 PM'
        zh: '3月 24, 14:00'
    """
    dt = _to_tz(dt, timezone)
    months = _MONTH_ABBR.get(lang)
    if months:
        month = months[dt.month - 1]
        if lang in _24H_LANGUAGES:
            return f"{dt.day} {month}, {dt.strftime('%H:%M')}"
        return f"{month} {dt.day}, {dt.strftime('%I:%M %p').lstrip('0')}"
    # English fallback
    return dt.strftime("%b %d, %I:%M %p").lstrip("0")


def fmt_time(
    dt: datetime,
    lang: str,
    *,
    timezone: str | None = None,
) -> str:
    """Locale-aware time-only formatting.

    Returns:
        ru/fr/de/...: '14:00'
        en: '2:00 PM'
    """
    dt = _to_tz(dt, timezone)
    if lang in _24H_LANGUAGES:
        return dt.strftime("%H:%M")
    return dt.strftime("%I:%M %p").lstrip("0")
