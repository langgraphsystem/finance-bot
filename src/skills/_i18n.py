"""Shared i18n helpers for skill response localization."""

from datetime import datetime
from zoneinfo import ZoneInfo

# Russian month abbreviations (nominative short form)
_RU_MONTHS = [
    "янв", "фев", "мар", "апр", "мая", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


def t(strings: dict[str, dict[str, str]], key: str, lang: str, **kw: str) -> str:
    """Get a translated string with English fallback.

    Usage:
        _STRINGS = {"en": {"empty": "No items"}, "ru": {"empty": "Нет элементов"}}
        t(_STRINGS, "empty", context.language or "en")
    """
    bucket = strings.get(lang, strings.get("en", {}))
    template = bucket.get(key) or strings.get("en", {}).get(key, key)
    return template.format(**kw) if kw else template


def _to_tz(dt: datetime, timezone: str | None) -> datetime:
    """Convert a datetime to the given timezone (if provided)."""
    if timezone:
        try:
            return dt.astimezone(ZoneInfo(timezone))
        except (KeyError, ValueError):
            pass
    return dt


def fmt_date(
    dt: datetime, lang: str, *, timezone: str | None = None,
) -> str:
    """Locale-aware date+time formatting.

    Returns:
        ru: '24 фев, 14:00'
        en: 'Feb 24, 2:00 PM'
    """
    dt = _to_tz(dt, timezone)
    if lang == "ru":
        month = _RU_MONTHS[dt.month - 1]
        return f"{dt.day} {month}, {dt.strftime('%H:%M')}"
    return dt.strftime("%b %d, %I:%M %p").lstrip("0")


def fmt_time(
    dt: datetime, lang: str, *, timezone: str | None = None,
) -> str:
    """Locale-aware time-only formatting.

    Returns:
        ru: '14:00'
        en: '2:00 PM'
    """
    dt = _to_tz(dt, timezone)
    if lang == "ru":
        return dt.strftime("%H:%M")
    return dt.strftime("%I:%M %p").lstrip("0")
