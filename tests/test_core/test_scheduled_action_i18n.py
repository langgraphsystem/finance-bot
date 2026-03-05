"""Tests for SIA i18n string completeness across all supported languages."""

from src.core.scheduled_actions.i18n import (
    _STRINGS,
    DATE_FORMATS,
    SCHEDULE_LABELS,
    SOURCE_LABELS,
    SUPPORTED_LANGS,
    WEEKDAY_NAMES,
)


def test_all_string_keys_present_in_all_languages():
    """Every key in the English string table must exist in RU and ES."""
    en_keys = set(_STRINGS["en"].keys())
    for lang in SUPPORTED_LANGS - {"en"}:
        lang_keys = set(_STRINGS[lang].keys())
        missing = en_keys - lang_keys
        assert not missing, f"Language '{lang}' is missing i18n keys: {missing}"


def test_no_extra_keys_in_non_english_languages():
    """Non-English languages should not have keys absent from English."""
    en_keys = set(_STRINGS["en"].keys())
    for lang in SUPPORTED_LANGS - {"en"}:
        lang_keys = set(_STRINGS[lang].keys())
        extra = lang_keys - en_keys
        assert not extra, f"Language '{lang}' has extra i18n keys not in EN: {extra}"


def test_weekday_names_all_languages_have_7_entries():
    for lang in SUPPORTED_LANGS:
        assert lang in WEEKDAY_NAMES, f"WEEKDAY_NAMES missing language '{lang}'"
        assert len(WEEKDAY_NAMES[lang]) == 7, (
            f"WEEKDAY_NAMES['{lang}'] has {len(WEEKDAY_NAMES[lang])} entries, expected 7"
        )


def test_schedule_labels_all_languages_same_keys():
    en_keys = set(SCHEDULE_LABELS["en"].keys())
    for lang in SUPPORTED_LANGS:
        assert lang in SCHEDULE_LABELS, f"SCHEDULE_LABELS missing language '{lang}'"
        lang_keys = set(SCHEDULE_LABELS[lang].keys())
        assert lang_keys == en_keys, (
            f"SCHEDULE_LABELS['{lang}'] keys mismatch: "
            f"missing={en_keys - lang_keys}, extra={lang_keys - en_keys}"
        )


def test_source_labels_all_languages_same_keys():
    en_keys = set(SOURCE_LABELS["en"].keys())
    for lang in SUPPORTED_LANGS:
        assert lang in SOURCE_LABELS, f"SOURCE_LABELS missing language '{lang}'"
        lang_keys = set(SOURCE_LABELS[lang].keys())
        assert lang_keys == en_keys, (
            f"SOURCE_LABELS['{lang}'] keys mismatch: "
            f"missing={en_keys - lang_keys}, extra={lang_keys - en_keys}"
        )


def test_date_formats_all_languages_same_keys():
    en_keys = set(DATE_FORMATS["en"].keys())
    for lang in SUPPORTED_LANGS:
        assert lang in DATE_FORMATS, f"DATE_FORMATS missing language '{lang}'"
        lang_keys = set(DATE_FORMATS[lang].keys())
        assert lang_keys == en_keys, (
            f"DATE_FORMATS['{lang}'] keys mismatch: "
            f"missing={en_keys - lang_keys}, extra={lang_keys - en_keys}"
        )
