"""Locale and timezone resolution helpers for notification pipelines."""

from dataclasses import dataclass


def normalize_language(lang: str | None) -> str:
    """Normalize language codes (e.g. en-US/en_US -> en)."""
    if not lang:
        return "en"
    normalized = lang.strip().lower().replace("_", "-")
    normalized = normalized.split("-", 1)[0]
    return normalized or "en"


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
) -> LocaleResolution:
    """Resolve language/timezone with source metadata.

    Behavior:
    - Legacy mode (`use_v2_read=False`): preferred_language -> user_language -> en.
    - v2 read mode (`use_v2_read=True`): notification_language -> preferred -> user -> en.
    """
    if use_v2_read and notification_language:
        language = notification_language
        language_source = "user_profile.notification_language"
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

