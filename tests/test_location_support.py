"""Tests for location support: reverse-geocode, save city, city-from-text, location pin flow."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.router import _reverse_geocode_city, _save_user_city, _try_set_city_from_text
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
    """Logs warning when no profile exists for the user."""
    user_id = str(uuid.uuid4())

    mock_result = MagicMock()
    mock_result.rowcount = 0

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)
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
# _try_set_city_from_text
# ---------------------------------------------------------------------------


@pytest.fixture
def base_msg():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="Brooklyn",
    )


@pytest.fixture
def base_ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


async def test_city_from_text_after_location_prompt(base_msg, base_ctx):
    """Sets city when bot previously asked for location."""
    recent = [
        {"role": "user", "content": "coffee near me"},
        {
            "role": "assistant",
            "content": "To find nearby places, I need to know your location.",
        },
    ]
    with patch("src.core.router._save_user_city", new_callable=AsyncMock) as mock_save:
        result = await _try_set_city_from_text(base_msg, base_ctx, recent)

    assert result is not None
    assert "Brooklyn" in result.text
    mock_save.assert_awaited_once_with(base_ctx.user_id, "Brooklyn")


async def test_city_from_text_strips_prefix(base_ctx):
    """Strips 'I'm in' prefix before saving city."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="I'm in Queens",
    )
    recent = [
        {
            "role": "assistant",
            "content": "Share your location pin or tell me your city.",
        },
    ]
    with patch("src.core.router._save_user_city", new_callable=AsyncMock) as mock_save:
        result = await _try_set_city_from_text(msg, base_ctx, recent)

    assert result is not None
    assert "Queens" in result.text
    mock_save.assert_awaited_once_with(base_ctx.user_id, "Queens")


async def test_city_from_text_russian_prefix(base_ctx):
    """Strips Russian prefix 'я в'."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="я в Бруклине",
    )
    recent = [
        {
            "role": "assistant",
            "content": "Чтобы найти места рядом, мне нужно знать ваш город. "
            "Отправьте геолокацию или напишите город.",
        },
    ]
    with patch("src.core.router._save_user_city", new_callable=AsyncMock) as mock_save:
        result = await _try_set_city_from_text(msg, base_ctx, recent)

    assert result is not None
    assert "Бруклине" in result.text
    mock_save.assert_awaited_once()


async def test_city_from_text_no_location_prompt(base_msg, base_ctx):
    """Returns None when bot didn't ask for location."""
    recent = [
        {"role": "assistant", "content": "Here are your expenses for today."},
    ]
    with patch("src.core.router._save_user_city", new_callable=AsyncMock) as mock_save:
        result = await _try_set_city_from_text(base_msg, base_ctx, recent)

    assert result is None
    mock_save.assert_not_awaited()


async def test_city_from_text_empty_recent(base_msg, base_ctx):
    """Returns None when no recent messages."""
    result = await _try_set_city_from_text(base_msg, base_ctx, [])
    assert result is None


async def test_city_from_text_rejects_digits(base_ctx):
    """Rejects text with digits (not a city name)."""
    msg = IncomingMessage(
        id="msg-4",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="10001",
    )
    recent = [
        {
            "role": "assistant",
            "content": "I need to know your location. Share your location pin.",
        },
    ]
    result = await _try_set_city_from_text(msg, base_ctx, recent)
    assert result is None


async def test_city_from_text_rejects_long_text(base_ctx):
    """Rejects text that's too long to be a city name."""
    msg = IncomingMessage(
        id="msg-5",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="I want to find the best coffee shop in my neighborhood please",
    )
    recent = [
        {
            "role": "assistant",
            "content": "To find nearby places, I need to know your location.",
        },
    ]
    result = await _try_set_city_from_text(msg, base_ctx, recent)
    assert result is None


async def test_city_from_text_rejects_commas(base_ctx):
    """Rejects text with commas (likely a full sentence, not a city)."""
    msg = IncomingMessage(
        id="msg-6",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="Brooklyn, New York",
    )
    recent = [
        {
            "role": "assistant",
            "content": "Share your location pin or tell me your city.",
        },
    ]
    result = await _try_set_city_from_text(msg, base_ctx, recent)
    assert result is None


async def test_city_from_text_multi_word_city(base_ctx):
    """Accepts multi-word city names like 'Salt Lake City'."""
    msg = IncomingMessage(
        id="msg-7",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="Salt Lake City",
    )
    recent = [
        {
            "role": "assistant",
            "content": "I need to know your location.",
        },
    ]
    with patch("src.core.router._save_user_city", new_callable=AsyncMock) as mock_save:
        result = await _try_set_city_from_text(msg, base_ctx, recent)

    assert result is not None
    assert "Salt Lake City" in result.text
    mock_save.assert_awaited_once()


async def test_city_from_text_no_text_message(base_ctx):
    """Returns None for messages with no text."""
    msg = IncomingMessage(
        id="msg-8",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=None,
    )
    recent = [
        {
            "role": "assistant",
            "content": "Share your location.",
        },
    ]
    result = await _try_set_city_from_text(msg, base_ctx, recent)
    assert result is None


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
