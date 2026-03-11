"""Locale and timezone resolution helpers for notification pipelines."""

from dataclasses import dataclass

# CIS/Central Asian languages that fall back to Russian for notifications.
# These users almost universally read Russian as a second language.
_CIS_NOTIFICATION_FALLBACK = frozenset({"ky", "kk", "uz", "tg", "mn"})


def normalize_language(lang: str | None) -> str:
    """Normalize language codes (e.g. en-US/en_US -> en)."""
    if not lang:
        return "en"
    normalized = lang.strip().lower().replace("_", "-")
    normalized = normalized.split("-", 1)[0]
    return normalized or "en"


def notification_language_fallback(lang: str | None) -> str:
    """Map language to nearest supported notification language.

    CIS languages (ky, kk, uz, tg, mn) fall back to Russian.
    Everything else passes through normalize_language.
    """
    normalized = normalize_language(lang)
    if normalized in _CIS_NOTIFICATION_FALLBACK:
        return "ru"
    return normalized


@dataclass(frozen=True)
class LocaleResolution:
    """Resolved locale and metadata for logs/telemetry."""

    language: str
    language_source: str
    timezone: str
    timezone_source: str


def resolve_notification_locale(
    *,
    user_language: str | None,
    preferred_language: str | None,
    notification_language: str | None,
    timezone: str | None,
    timezone_source: str | None,
    use_v2_read: bool,
    prefer_user_on_desync: bool = False,
) -> LocaleResolution:
    """Resolve language/timezone with source metadata.

    Behavior:
    - Legacy mode (`use_v2_read=False`): preferred_language -> user_language -> en.
    - v2 read mode (`use_v2_read=True`): notification_language -> preferred -> user -> en.
    """
    normalized_user = normalize_language(user_language) if user_language else ""
    normalized_preferred = normalize_language(preferred_language) if preferred_language else ""

    if use_v2_read and notification_language:
        language = notification_language
        language_source = "user_profile.notification_language"
    elif (
        prefer_user_on_desync
        and normalized_user
        and normalized_preferred
        and normalized_user != normalized_preferred
    ):
        # Keep async pushes aligned with current conversational language when fields diverge.
        language = user_language
        language_source = "users.language_desync_override"
    elif preferred_language:
        language = preferred_language
        language_source = "user_profile.preferred_language"
    elif user_language:
        language = user_language
        language_source = "users.language"
    else:
        language = "en"
        language_source = "default_en"

    resolved_timezone = (timezone or "").strip() or "UTC"
    resolved_timezone_source = (timezone_source or "").strip()
    if not resolved_timezone_source:
        resolved_timezone_source = "user_profile.timezone" if timezone else "default"

    return LocaleResolution(
        language=normalize_language(language),
        language_source=language_source,
        timezone=resolved_timezone,
        timezone_source=resolved_timezone_source,
    )
