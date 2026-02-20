"""Tests for maps_search skill — quick (grounding) + detailed (API) modes."""

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
    ):
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
async def test_quick_mode_with_api_key_no_detail(skill, message, ctx):
    """Even with API key, no detail_mode means grounding mode."""
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="<b>Coffee Place</b>",
        ) as mock_grounding,
    ):
        mock_settings.google_maps_api_key = "fake-key"
        result = await skill.execute(message, ctx, {"maps_query": "coffee"})

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
    ):
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
async def test_detail_mode_no_api_key_falls_to_grounding(skill, message, ctx):
    """detail_mode=True without API key gracefully falls to grounding."""
    with (
        patch("src.skills.maps_search.handler.settings") as mock_settings,
        patch(
            "src.skills.maps_search.handler.search_places_grounding",
            new_callable=AsyncMock,
            return_value="<b>Coffee Shop</b>",
        ) as mock_grounding,
    ):
        mock_settings.google_maps_api_key = ""
        await skill.execute(message, ctx, {"maps_query": "coffee", "detail_mode": True})

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
    """Nearby query without user city returns a location prompt."""
    msg = IncomingMessage(
        id="msg-loc-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="coffee near me",
    )
    result = await skill.execute(msg, ctx, {"maps_query": "coffee near me"})
    assert "location" in result.response_text.lower()


@pytest.mark.asyncio
async def test_nearby_without_city_prompts_russian(skill):
    """Nearby query in Russian without city returns Russian prompt."""
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
    result = await skill.execute(msg, ctx_ru, {"maps_query": "кофе рядом"})
    assert "геолокацию" in result.response_text.lower() or "город" in result.response_text.lower()


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
    ):
        mock_settings.google_maps_api_key = ""
        await skill.execute(msg, ctx_with_city, {"maps_query": "pizza nearby"})

    args, kwargs = mock_grounding.call_args
    assert "pizza nearby, Brooklyn" == args[0]
    assert "Brooklyn" in kwargs.get("location_hint", "")


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
