"""Tests for location support: reverse-geocode, save city, city-from-text, location pin flow."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.router import _reverse_geocode_city, _save_user_city
from src.gateway.types import IncomingMessage, MessageType

# ---------------------------------------------------------------------------
# _reverse_geocode_city
# ---------------------------------------------------------------------------


@pytest.fixture
def google_geocode_response():
    return {
        "results": [
            {
                "address_components": [
                    {"long_name": "Brooklyn", "types": ["locality", "political"]},
                    {"long_name": "Kings County", "types": ["administrative_area_level_2"]},
                    {"long_name": "New York", "types": ["administrative_area_level_1"]},
                ],
                "formatted_address": "Brooklyn, NY, USA",
            }
        ],
        "status": "OK",
    }


@pytest.fixture
def nominatim_response():
    return {
        "address": {
            "city": "Brooklyn",
            "county": "Kings County",
            "state": "New York",
            "country": "United States",
        }
    }


async def test_reverse_geocode_google_maps(google_geocode_response):
    """Uses Google Maps Geocoding API when key is available."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = google_geocode_response
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with (
        patch("src.core.config.settings.google_maps_api_key", "fake-key"),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await _reverse_geocode_city("40.6782,-73.9442")

    assert result == "Brooklyn"


async def test_reverse_geocode_nominatim_fallback(nominatim_response):
    """Falls back to Nominatim when no Google Maps API key."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = nominatim_response
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with (
        patch("src.core.config.settings.google_maps_api_key", ""),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await _reverse_geocode_city("40.6782,-73.9442")

    assert result == "Brooklyn"


async def test_reverse_geocode_invalid_coords():
    """Invalid coordinates (no comma) return None."""
    result = await _reverse_geocode_city("not-coords")
    assert result is None


async def test_reverse_geocode_both_fail():
    """When both APIs fail, returns None."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("network error"))

    with (
        patch("src.core.config.settings.google_maps_api_key", ""),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await _reverse_geocode_city("40.6782,-73.9442")

    assert result is None


async def test_reverse_geocode_google_no_locality():
    """Falls back to formatted_address when no locality component."""
    data = {
        "results": [
            {
                "address_components": [
                    {"long_name": "Queens", "types": ["administrative_area_level_2"]},
                ],
                "formatted_address": "Astoria, Queens, NY, USA",
            }
        ],
        "status": "OK",
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with (
        patch("src.core.config.settings.google_maps_api_key", "fake-key"),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await _reverse_geocode_city("40.7720,-73.9300")

    assert result == "Astoria"


# ---------------------------------------------------------------------------
# _save_user_city
# ---------------------------------------------------------------------------


async def test_save_user_city_updates_profile():
    """Saves city to user_profiles via UPDATE."""
    user_id = str(uuid.uuid4())

    mock_result = MagicMock()
    mock_result.rowcount = 1

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    with patch("src.core.router.async_session", return_value=mock_session):
        await _save_user_city(user_id, "Brooklyn")

    mock_session.execute.assert_awaited_once()
    mock_session.commit.assert_awaited_once()


async def test_save_user_city_no_profile_logs_warning():
    """Logs warning when no user exists for the user_id."""
    user_id = str(uuid.uuid4())

    mock_result = MagicMock()
    mock_result.rowcount = 0

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.scalar = AsyncMock(return_value=None)  # No User found
    mock_session.commit = AsyncMock()

    with (
        patch("src.core.router.async_session", return_value=mock_session),
        patch("src.core.router.logger") as mock_logger,
    ):
        await _save_user_city(user_id, "Brooklyn")

    mock_logger.warning.assert_called_once()


async def test_save_user_city_handles_db_error():
    """Gracefully handles database errors."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(side_effect=Exception("db error"))
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.router.async_session", return_value=mock_session),
        patch("src.core.router.logger") as mock_logger,
    ):
        await _save_user_city(str(uuid.uuid4()), "Brooklyn")

    mock_logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# Location pin flow (integration-style with _dispatch_message mocks)
# ---------------------------------------------------------------------------


async def test_location_pin_saves_city_and_responds():
    """Location message triggers reverse-geocode → save → confirmation."""
    from src.core.router import _dispatch_message

    msg = IncomingMessage(
        id="msg-loc-1",
        user_id="tg_loc_user",
        chat_id="chat_loc_1",
        type=MessageType.location,
        text="40.6782,-73.9442",
    )
    ctx = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )
    registry = MagicMock()

    with (
        patch(
            "src.core.router._reverse_geocode_city",
            new_callable=AsyncMock,
            return_value="Brooklyn",
        ) as mock_geo,
        patch(
            "src.core.router._save_user_city",
            new_callable=AsyncMock,
        ) as mock_save,
        patch(
            "src.core.router._execute_pending_maps_search",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await _dispatch_message(msg, ctx, registry)

    mock_geo.assert_awaited_once_with("40.6782,-73.9442")
    mock_save.assert_awaited_once_with(ctx.user_id, "Brooklyn")
    assert "Brooklyn" in result.text


async def test_location_pin_geocode_failure():
    """When reverse-geocode fails, asks user to type city."""
    from src.core.router import _dispatch_message

    msg = IncomingMessage(
        id="msg-loc-2",
        user_id="tg_loc_user2",
        chat_id="chat_loc_2",
        type=MessageType.location,
        text="0.0,0.0",
    )
    ctx = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )
    registry = MagicMock()

    with patch(
        "src.core.router._reverse_geocode_city",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _dispatch_message(msg, ctx, registry)

    assert "type your city" in result.text.lower() or "city name" in result.text.lower()
