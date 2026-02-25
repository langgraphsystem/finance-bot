"""Tests for locale resolution helpers used by notification tasks."""

from src.core.locale_resolution import normalize_language, resolve_notification_locale


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

