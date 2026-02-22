"""Tests for maps_search skill — quick (grounding) + detailed (API) modes."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.maps_search.handler import MapsSearchSkill, _format_places_raw, _is_nearby_query


@pytest.fixture
def skill():
    return MapsSearchSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="coffee near me",
    )


@pytest.fixture
def ctx():
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


@pytest.fixture
def ctx_with_city():
    """Context with user city set for nearby queries."""
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
        user_profile={"city": "Brooklyn"},
    )


# ---------------------------------------------------------------------------
# Quick mode (Gemini Google Search Grounding)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quick_mode_default(skill, message, ctx_with_city):
    """Default (no detail_mode, no API key) uses Gemini grounding."""
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="<b>Starbucks</b> — 4.2/5 | Open now",
        ) as mock_grounding,
        patch("src.skills.maps_search.handler.redis") as mock_redis,
    ):
        mock_redis.set = AsyncMock()
        mock_settings.google_maps_api_key = ""
        result = await skill.execute(
            message, ctx_with_city, {"maps_query": "coffee near me"}
        )

    mock_grounding.assert_awaited_once()
    args, kwargs = mock_grounding.call_args
    assert "coffee near me" in args[0]
    assert "Brooklyn" in args[0]  # city appended to nearby query
    assert "Brooklyn" in kwargs.get("location_hint", "")
    assert "Starbucks" in result.response_text


@pytest.mark.asyncio
async def test_quick_mode_with_api_key_no_detail(skill, ctx):
    """Even with API key, no detail_mode means grounding mode."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="coffee in Manhattan",
    )
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="<b>Coffee Place</b>",
        ) as mock_grounding,
    ):
        mock_settings.google_maps_api_key = "fake-key"
        result = await skill.execute(msg, ctx, {"maps_query": "coffee in Manhattan"})

    mock_grounding.assert_awaited_once()
    assert "Coffee" in result.response_text


@pytest.mark.asyncio
async def test_grounding_calls_gemini_with_google_search_tool(skill, ctx):
    """search_places_grounding calls Gemini with GoogleSearch tool."""
    mock_response = MagicMock()
    mock_response.text = "<b>Pizza Hut</b> — 3.8/5"

    mock_generate = AsyncMock(return_value=mock_response)

    with patch("src.skills.maps_search.handler.google_client") as mock_gc:
        mock_gc.return_value.aio.models.generate_content = mock_generate
        from src.skills.maps_search.handler import search_places_grounding

        result = await search_places_grounding("pizza near me", "en")

    assert "Pizza Hut" in result
    # Verify google_search tool was passed
    call_kwargs = mock_generate.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
    assert config is not None
    assert len(config.tools) == 1


# ---------------------------------------------------------------------------
# Detailed mode (Google Maps REST API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_mode_uses_api(skill, ctx_with_city):
    """detail_mode=True + API key → uses search_places (REST API)."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="coffee near me",
    )
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places",
            new_callable=AsyncMock,
            return_value="<b>Starbucks</b> — 4.2/5 | Open now | 123 Main St",
        ) as mock_api,
        patch("src.skills.maps_search.handler.redis") as mock_redis,
    ):
        mock_redis.set = AsyncMock()
        mock_settings.google_maps_api_key = "fake-key"
        result = await skill.execute(
            msg, ctx_with_city, {"maps_query": "coffee near me", "detail_mode": True}
        )

    mock_api.assert_awaited_once()
    assert "Starbucks" in result.response_text


@pytest.mark.asyncio
async def test_directions_default_uses_grounding(skill, ctx):
    """Directions without detail_mode uses Gemini grounding."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="directions to Walmart",
    )
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="Head south on I-95, take exit 12...",
        ) as mock_grounding,
    ):
        mock_settings.google_maps_api_key = "fake-key"
        await skill.execute(
            msg,
            ctx,
            {"maps_mode": "directions", "maps_query": "Home", "destination": "Walmart"},
        )

    mock_grounding.assert_awaited_once()
    args = mock_grounding.call_args[0]
    assert args[0] == "directions from Home to Walmart"
    assert args[1] == "en"


@pytest.mark.asyncio
async def test_directions_detail_mode_uses_api(skill, ctx):
    """Directions with detail_mode=True + API key uses REST API."""
    msg = IncomingMessage(
        id="msg-5",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="подробный маршрут до Walmart",
    )
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.get_directions",
            new_callable=AsyncMock,
            return_value="<b>Home</b> → <b>Walmart</b>\nDistance: 5 mi · Time: 12 min",
        ) as mock_dirs,
    ):
        mock_settings.google_maps_api_key = "fake-key"
        result = await skill.execute(
            msg,
            ctx,
            {
                "maps_mode": "directions",
                "maps_query": "Home",
                "destination": "Walmart",
                "detail_mode": True,
            },
        )

    mock_dirs.assert_awaited_once()
    assert "Walmart" in result.response_text
    assert "Distance" in result.response_text


@pytest.mark.asyncio
async def test_detail_mode_no_api_key_falls_to_grounding(skill, ctx):
    """detail_mode=True without API key gracefully falls to grounding."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="coffee shops in Manhattan",
    )
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="<b>Coffee Shop</b>",
        ) as mock_grounding,
    ):
        mock_settings.google_maps_api_key = ""
        await skill.execute(msg, ctx, {"maps_query": "coffee in Manhattan", "detail_mode": True})

    mock_grounding.assert_awaited_once()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_query(skill, ctx):
    """Empty query returns prompt."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "looking for" in result.response_text.lower()


@pytest.mark.asyncio
async def test_uses_message_text_as_fallback(skill, ctx):
    """Falls back to message.text when no maps_query in intent_data."""
    msg = IncomingMessage(
        id="msg-4",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="best pizza in Brooklyn",
    )
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="<b>Di Fara Pizza</b>",
        ) as mock_grounding,
    ):
        mock_settings.google_maps_api_key = ""
        result = await skill.execute(msg, ctx, {})

    mock_grounding.assert_awaited_once()
    assert mock_grounding.call_args[0][0] == "best pizza in Brooklyn"
    assert "Di Fara" in result.response_text


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def test_format_places_raw_includes_rating():
    """_format_places_raw includes name and rating."""
    places = [
        {
            "name": "Blue Bottle Coffee",
            "formatted_address": "123 Main St",
            "rating": 4.7,
            "price_level": 2,
            "opening_hours": {"open_now": True},
        }
    ]
    result = _format_places_raw(places)
    assert "Blue Bottle Coffee" in result
    assert "4.7" in result
    assert "$$" in result
    assert "Open now" in result


def test_format_places_raw_closed():
    """_format_places_raw shows Closed when place is closed."""
    places = [
        {
            "name": "Closed Cafe",
            "formatted_address": "456 Oak Ave",
            "opening_hours": {"open_now": False},
        }
    ]
    result = _format_places_raw(places)
    assert "Closed" in result


def test_system_prompt_includes_language(skill, ctx):
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt


# ---------------------------------------------------------------------------
# Location-awareness
# ---------------------------------------------------------------------------


def test_is_nearby_query_english():
    assert _is_nearby_query("coffee near me") is True
    assert _is_nearby_query("restaurants nearby") is True
    assert _is_nearby_query("best pizza in Brooklyn") is False


def test_is_nearby_query_russian():
    assert _is_nearby_query("кофе рядом") is True
    assert _is_nearby_query("ближайшая аптека") is True
    assert _is_nearby_query("пиццерия в Бруклине") is False


@pytest.mark.asyncio
async def test_nearby_without_city_prompts_for_location(skill, ctx):
    """Nearby query without user city returns a location prompt + reply_keyboard."""
    msg = IncomingMessage(
        id="msg-loc-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="coffee near me",
    )
    with patch("src.skills.maps_search.handler.redis") as mock_redis:
        mock_redis.set = AsyncMock()
        result = await skill.execute(msg, ctx, {"maps_query": "coffee near me"})

    assert "location" in result.response_text.lower()
    # Must include location button
    assert result.reply_keyboard is not None
    assert result.reply_keyboard[0]["request_location"] is True
    # Must store pending query in Redis
    mock_redis.set.assert_awaited_once()
    call_args = mock_redis.set.call_args
    assert call_args[0][0] == f"maps_pending:{ctx.user_id}"


@pytest.mark.asyncio
async def test_nearby_without_city_prompts_russian(skill):
    """Nearby query in Russian without city returns Russian prompt + button."""
    ctx_ru = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )
    msg = IncomingMessage(
        id="msg-loc-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="кофе рядом",
    )
    with patch("src.skills.maps_search.handler.redis") as mock_redis:
        mock_redis.set = AsyncMock()
        result = await skill.execute(msg, ctx_ru, {"maps_query": "кофе рядом"})

    assert "город" in result.response_text.lower()
    assert result.reply_keyboard is not None
    assert result.reply_keyboard[0]["request_location"] is True


@pytest.mark.asyncio
async def test_nearby_with_city_appends_city(skill, ctx_with_city):
    """Nearby query with city set appends city to query."""
    msg = IncomingMessage(
        id="msg-loc-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="pizza nearby",
    )
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="<b>Joe's Pizza</b>",
        ) as mock_grounding,
        patch("src.skills.maps_search.handler.redis") as mock_redis,
    ):
        mock_redis.set = AsyncMock()
        mock_settings.google_maps_api_key = ""
        result = await skill.execute(msg, ctx_with_city, {"maps_query": "pizza nearby"})

    args, kwargs = mock_grounding.call_args
    assert "pizza nearby, Brooklyn" == args[0]
    assert "Brooklyn" in kwargs.get("location_hint", "")
    # Nearby with city should offer location update button
    assert result.reply_keyboard is not None
    assert result.reply_keyboard[0]["request_location"] is True


@pytest.mark.asyncio
async def test_nearby_in_message_but_not_in_query_prompts(skill, ctx):
    """When message.text has 'рядом' but maps_query doesn't, still detect as nearby."""
    msg = IncomingMessage(
        id="msg-loc-5",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="Найди гостиницу рядом где я сейчас",
    )
    with patch("src.skills.maps_search.handler.redis") as mock_redis:
        mock_redis.set = AsyncMock()
        # LLM extracted just "гостиница" without "рядом"
        result = await skill.execute(msg, ctx, {"maps_query": "гостиница"})
    # Should ask for location, NOT hallucinate a city
    assert "город" in result.response_text.lower() or "location" in result.response_text.lower()
    assert result.reply_keyboard is not None


@pytest.mark.asyncio
async def test_nearby_in_message_but_not_in_query_prompts_en(skill, ctx):
    """English: message has 'near me' but maps_query is stripped."""
    msg = IncomingMessage(
        id="msg-loc-6",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="find a hotel near me",
    )
    with patch("src.skills.maps_search.handler.redis") as mock_redis:
        mock_redis.set = AsyncMock()
        result = await skill.execute(msg, ctx, {"maps_query": "hotel"})
    assert "location" in result.response_text.lower()
    assert result.reply_keyboard is not None


@pytest.mark.asyncio
async def test_nearby_in_message_with_city_works(skill, ctx_with_city):
    """Nearby detected from message.text + city set → search proceeds."""
    msg = IncomingMessage(
        id="msg-loc-7",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="Найди гостиницу рядом где я сейчас",
    )
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="<b>Hilton Brooklyn</b>",
        ) as mock_grounding,
        patch("src.skills.maps_search.handler.redis") as mock_redis,
    ):
        mock_redis.set = AsyncMock()
        mock_settings.google_maps_api_key = ""
        result = await skill.execute(msg, ctx_with_city, {"maps_query": "гостиница"})

    mock_grounding.assert_awaited_once()
    args = mock_grounding.call_args[0]
    assert "Brooklyn" in args[0]
    assert "Hilton" in result.response_text


@pytest.mark.asyncio
async def test_non_nearby_query_no_city_works(skill, ctx):
    """Non-nearby queries work even without a city."""
    msg = IncomingMessage(
        id="msg-loc-4",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="Statue of Liberty",
    )
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="<b>Statue of Liberty</b>",
        ) as mock_grounding,
    ):
        mock_settings.google_maps_api_key = ""
        result = await skill.execute(msg, ctx, {"maps_query": "Statue of Liberty"})

    mock_grounding.assert_awaited_once()
    assert "Statue of Liberty" in result.response_text


# ---------------------------------------------------------------------------
# Router: auto-execute pending maps search after location
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_maps_auto_executes_after_location():
    """Router auto-executes pending maps search after receiving location."""
    from src.core.router import _execute_pending_maps_search

    user_id = str(uuid.uuid4())
    pending_data = json.dumps({
        "query": "гостиница",
        "maps_mode": "search",
        "destination": "",
        "detail_mode": False,
        "language": "ru",
    })

    msg = IncomingMessage(
        id="loc-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.location,
        text="40.7128,-74.0060",
    )

    with (
        patch("src.core.db.redis") as mock_redis,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="<b>Hilton Brooklyn</b> — 4.5/5",
        ) as mock_grounding,
        patch("src.core.config.settings") as mock_settings,
    ):
        mock_redis.get = AsyncMock(return_value=pending_data)
        mock_redis.delete = AsyncMock()
        mock_settings.google_maps_api_key = ""

        result = await _execute_pending_maps_search(user_id, "Brooklyn", msg)

    assert result is not None
    assert "Hilton" in result.text
    assert result.remove_reply_keyboard is True
    # Verify query was enriched with city
    args = mock_grounding.call_args[0]
    assert "Brooklyn" in args[0]
    assert "гостиница" in args[0]
    # Verify pending key was deleted
    mock_redis.delete.assert_awaited_once_with(f"maps_pending:{user_id}")


@pytest.mark.asyncio
async def test_pending_maps_returns_none_when_no_pending():
    """No pending search → returns None (router falls back to default message)."""
    from src.core.router import _execute_pending_maps_search

    msg = IncomingMessage(
        id="loc-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.location,
        text="40.7128,-74.0060",
    )

    with patch("src.core.db.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        result = await _execute_pending_maps_search("user-123", "Brooklyn", msg)

    assert result is None


# ---------------------------------------------------------------------------
# Reverse geocoding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reverse_geocode_finds_locality_in_second_result():
    """Reverse geocode searches all results for locality, not just the first."""
    from src.core.router import _reverse_geocode_city

    # First result has no locality, second result does
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "address_components": [
                    {"long_name": "Kings County", "types": ["administrative_area_level_2"]},
                ],
                "formatted_address": "Kings County, NY, USA",
            },
            {
                "address_components": [
                    {"long_name": "Brooklyn", "types": ["locality", "political"]},
                ],
                "formatted_address": "Brooklyn, NY 11201, USA",
            },
        ],
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.config.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.google_maps_api_key = "test-key"
        city = await _reverse_geocode_city("40.6892,-73.9857")

    assert city == "Brooklyn"


@pytest.mark.asyncio
async def test_reverse_geocode_fallback_to_formatted_address():
    """When no locality found, fall back to first part of formatted_address."""
    from src.core.router import _reverse_geocode_city

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "address_components": [
                    {"long_name": "Some County", "types": ["administrative_area_level_2"]},
                ],
                "formatted_address": "Schaumburg, IL 60173, USA",
            },
        ],
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.config.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.google_maps_api_key = "test-key"
        city = await _reverse_geocode_city("41.9742,-88.0844")

    assert city == "Schaumburg"


@pytest.mark.asyncio
async def test_reverse_geocode_nominatim_fallback():
    """When Google API has no key, falls back to Nominatim."""
    from src.core.router import _reverse_geocode_city

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "address": {"city": "New York", "state": "New York", "country": "USA"},
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.config.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.google_maps_api_key = ""  # No Google key
        city = await _reverse_geocode_city("40.7128,-74.0060")

    assert city == "New York"


@pytest.mark.asyncio
async def test_reverse_geocode_invalid_coords():
    """Invalid coordinates return None."""
    from src.core.router import _reverse_geocode_city

    result = await _reverse_geocode_city("not-coordinates")
    assert result is None
