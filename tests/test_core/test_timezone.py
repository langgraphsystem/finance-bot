"""Tests for centralized timezone detection helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.timezone import (
    TIMEZONE_CONFIDENCE,
    maybe_update_timezone,
    timezone_from_phone,
    validate_timezone,
)


class TestValidateTimezone:
    def test_valid_iana(self):
        assert validate_timezone("America/New_York") is True
        assert validate_timezone("Europe/Moscow") is True
        assert validate_timezone("Asia/Bishkek") is True
        assert validate_timezone("UTC") is True

    def test_invalid(self):
        assert validate_timezone("Not/A/Zone") is False
        assert validate_timezone("") is False
        assert validate_timezone("INVALID") is False

    def test_rejects_non_string(self):
        assert validate_timezone(123) is False
        assert validate_timezone(["UTC"]) is False


class TestTimezoneFromPhone:
    def test_kyrgyzstan_single_zone(self):
        tz, conf = timezone_from_phone("+996555123456")
        assert tz == "Asia/Bishkek"
        assert conf == 80

    def test_uk_multi_zone(self):
        # UK mobile returns 4 zones (Guernsey, Isle of Man, Jersey, London)
        tz, conf = timezone_from_phone("+447911123456")
        assert tz is not None
        assert conf == 40  # Multiple zones

    def test_russia_multi_zone(self):
        tz, conf = timezone_from_phone("+79161234567")
        assert tz == "Europe/Moscow"
        assert conf == 40

    def test_us_single_area_code(self):
        # 212 is NYC area code → single zone
        tz, conf = timezone_from_phone("+12125551234")
        assert tz == "America/New_York"
        assert conf == 80

    def test_without_plus(self):
        tz, conf = timezone_from_phone("996555123456")
        assert tz == "Asia/Bishkek"
        assert conf == 80

    def test_invalid_number(self):
        tz, conf = timezone_from_phone("invalid")
        assert tz is None
        assert conf == 0

    def test_empty_string(self):
        tz, conf = timezone_from_phone("")
        assert tz is None
        assert conf == 0


class TestMaybeUpdateTimezone:
    async def test_updates_when_higher_confidence(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch("src.core.timezone.async_session", return_value=mock_session):
            result = await maybe_update_timezone(
                "d2910149-303d-45f5-9eef-0c9788638221",
                "Europe/Moscow",
                "mini_app_js",
            )
        assert result is True
        mock_session.commit.assert_called_once()

    async def test_skips_when_lower_confidence(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.rollback = AsyncMock()

        with patch("src.core.timezone.async_session", return_value=mock_session):
            result = await maybe_update_timezone(
                "d2910149-303d-45f5-9eef-0c9788638221",
                "Europe/Moscow",
                "channel_hint",
                30,
            )
        assert result is False

    async def test_skips_when_equal_confidence(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.scalar = AsyncMock(side_effect=[object()])
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.rollback = AsyncMock()

        with patch("src.core.timezone.async_session", return_value=mock_session):
            result = await maybe_update_timezone(
                "d2910149-303d-45f5-9eef-0c9788638221",
                "Europe/Moscow",
                "phone_number_single",
                80,
            )

        assert result is False
        mock_session.rollback.assert_called_once()

    async def test_creates_missing_profile(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.scalar = AsyncMock(
            side_effect=[
                None,
                SimpleNamespace(
                    id="d2910149-303d-45f5-9eef-0c9788638221",
                    family_id="family-id",
                    name="Test User",
                    language="ru",
                ),
            ]
        )
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        with patch("src.core.timezone.async_session", return_value=mock_session):
            result = await maybe_update_timezone(
                "d2910149-303d-45f5-9eef-0c9788638221",
                "Europe/Moscow",
                "mini_app_js",
            )

        assert result is True
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    async def test_rejects_invalid_timezone(self):
        result = await maybe_update_timezone(
            "d2910149-303d-45f5-9eef-0c9788638221",
            "Invalid/Zone",
            "mini_app_js",
        )
        assert result is False

    async def test_default_confidence_from_map(self):
        assert TIMEZONE_CONFIDENCE["mini_app_js"] == 90
        assert TIMEZONE_CONFIDENCE["slack_api"] == 85
        assert TIMEZONE_CONFIDENCE["channel_hint"] == 30
        assert TIMEZONE_CONFIDENCE["default"] == 0
