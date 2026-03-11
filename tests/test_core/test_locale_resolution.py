"""Tests for locale resolution helpers used by notification tasks."""

from src.core.locale_resolution import (
    normalize_language,
    notification_language_fallback,
    resolve_notification_locale,
)


def test_normalize_language_region_code():
    assert normalize_language("en-US") == "en"
    assert normalize_language("es_MX") == "es"


def test_resolve_locale_legacy_mode():
    resolved = resolve_notification_locale(
        user_language="ru",
        preferred_language="en",
        notification_language="es",
        timezone="America/New_York",
        timezone_source=None,
        use_v2_read=False,
    )
    assert resolved.language == "en"
    assert resolved.language_source == "user_profile.preferred_language"
    assert resolved.timezone == "America/New_York"
    assert resolved.timezone_source == "user_profile.timezone"


def test_resolve_locale_v2_mode_prefers_notification_language():
    resolved = resolve_notification_locale(
        user_language="ru",
        preferred_language="en",
        notification_language="es",
        timezone=None,
        timezone_source=None,
        use_v2_read=True,
    )
    assert resolved.language == "es"
    assert resolved.language_source == "user_profile.notification_language"
    assert resolved.timezone == "UTC"
    assert resolved.timezone_source == "default"


def test_resolve_locale_prefers_user_when_desynced():
    resolved = resolve_notification_locale(
        user_language="en",
        preferred_language="ru",
        notification_language=None,
        timezone="America/New_York",
        timezone_source="user_profile.timezone",
        use_v2_read=False,
        prefer_user_on_desync=True,
    )
    assert resolved.language == "en"
    assert resolved.language_source == "users.language_desync_override"


# ---------------------------------------------------------------------------
# CIS language notification fallback
# ---------------------------------------------------------------------------

def test_notification_fallback_kyrgyz_to_russian():
    assert notification_language_fallback("ky") == "ru"


def test_notification_fallback_kazakh_to_russian():
    assert notification_language_fallback("kk") == "ru"


def test_notification_fallback_uzbek_to_russian():
    assert notification_language_fallback("uz") == "ru"


def test_notification_fallback_tajik_to_russian():
    assert notification_language_fallback("tg") == "ru"


def test_notification_fallback_mongolian_to_russian():
    assert notification_language_fallback("mn") == "ru"


def test_notification_fallback_english_stays():
    assert notification_language_fallback("en") == "en"


def test_notification_fallback_russian_stays():
    assert notification_language_fallback("ru") == "ru"


def test_notification_fallback_spanish_stays():
    assert notification_language_fallback("es") == "es"


def test_notification_fallback_none():
    assert notification_language_fallback(None) == "en"
