"""Tests for browser booking flow."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.browser_booking import (
    _format_confirmation,
    _format_for_telegram,
    _parse_results,
    cancel_booking,
    execute_booking,
    handle_selection,
    handle_text_selection,
    start_search,
)

_SAMPLE_RAW = """\
[1] Hotel Arts Barcelona | $135/night | 8.9 | Beachfront, Olympic Port
[2] W Barcelona | $180/night | 8.7 | Iconic sail-shaped building
[3] Mandarin Oriental | $220/night | 9.1 | Passeig de Gracia"""

_TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
_TEST_FAMILY_ID = "00000000-0000-0000-0000-000000000002"


def test_parse_results_standard_format():
    results = _parse_results(_SAMPLE_RAW)
    assert len(results) == 3
    assert results[0]["name"] == "Hotel Arts Barcelona"
    assert results[0]["price"] == "$135/night"
    assert results[0]["rating"] == "8.9"
    assert results[0]["description"] == "Beachfront, Olympic Port"
    assert results[2]["name"] == "Mandarin Oriental"


def test_parse_results_malformed():
    results = _parse_results("Some random text without proper format\nAnother line")
    assert results == []


def test_parse_results_mixed():
    text = "Here are results:\n[1] Hotel X | $100/night | 7.5 | Nice place\nSome filler text"
    results = _parse_results(text)
    assert len(results) == 1
    assert results[0]["name"] == "Hotel X"


def test_format_for_telegram_with_results():
    results = _parse_results(_SAMPLE_RAW)
    text = _format_for_telegram(results, "booking.com", _SAMPLE_RAW)
    assert "booking.com" in text
    assert "Hotel Arts Barcelona" in text
    assert "$135/night" in text
    assert "Select" in text


def test_format_for_telegram_no_results():
    text = _format_for_telegram([], "booking.com", "Raw text from search")
    assert "booking.com" in text
    assert "Raw text from search" in text
    assert "number or name" in text.lower()


def test_format_confirmation():
    selected = {
        "name": "Hotel Arts", "price": "$135/night",
        "rating": "8.9", "description": "Beach",
    }
    text = _format_confirmation(selected, "book hotel in Barcelona", "booking.com")
    assert "Hotel Arts" in text
    assert "$135/night" in text
    assert "booking.com" in text


async def test_start_search_returns_results():
    mock_response = MagicMock()
    mock_response.text = _SAMPLE_RAW
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with (
        patch("src.tools.browser_booking.redis") as mock_redis,
        patch("src.core.llm.clients.google_client", return_value=mock_client),
    ):
        mock_redis.set = AsyncMock()
        result = await start_search(
            _TEST_USER_ID, _TEST_FAMILY_ID, "booking.com",
            "book hotel in Barcelona March 15-18", "en",
        )

    assert "Hotel Arts Barcelona" in result["text"]
    assert result["buttons"] is not None
    assert len(result["buttons"]) == 3
    assert result["buttons"][0]["callback"].startswith("booking_select:")
    mock_redis.set.assert_called_once()


async def test_start_search_grounding_fails():
    with (
        patch("src.tools.browser_booking.redis") as mock_redis,
        patch(
            "src.core.llm.clients.google_client",
            side_effect=Exception("API error"),
        ),
    ):
        mock_redis.set = AsyncMock()
        result = await start_search(
            _TEST_USER_ID, _TEST_FAMILY_ID, "booking.com",
            "book hotel in Barcelona", "en",
        )

    # Should still return text (fallback) but no buttons
    assert result["buttons"] is None
    assert "booking.com" in result["text"]


async def test_handle_selection_valid():
    state = {
        "flow_id": "abc123",
        "step": "awaiting_selection",
        "site": "booking.com",
        "task": "book hotel in Barcelona March 15-18",
        "family_id": _TEST_FAMILY_ID,
        "results": [
            {"name": "Hotel Arts", "price": "$135/night", "rating": "8.9", "description": "Beach"},
            {"name": "W Barcelona", "price": "$180/night", "rating": "8.7", "description": "Sail"},
        ],
        "raw_text": "...",
    }

    with patch("src.tools.browser_booking.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_redis.set = AsyncMock()
        result = await handle_selection(_TEST_USER_ID, 0)

    assert result["action"] == "confirm"
    assert "Hotel Arts" in result["text"]
    assert len(result["buttons"]) == 2
    assert "booking_confirm" in result["buttons"][0]["callback"]
    assert "booking_cancel" in result["buttons"][1]["callback"]


async def test_handle_selection_no_flow():
    with patch("src.tools.browser_booking.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        result = await handle_selection(_TEST_USER_ID, 0)

    assert result["action"] == "no_flow"


async def test_handle_selection_out_of_range():
    state = {
        "flow_id": "abc123",
        "step": "awaiting_selection",
        "site": "booking.com",
        "task": "book hotel",
        "family_id": _TEST_FAMILY_ID,
        "results": [
            {"name": "Hotel A", "price": "$100/night", "rating": "8.0", "description": "Nice"},
        ],
        "raw_text": "...",
    }

    with patch("src.tools.browser_booking.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        result = await handle_selection(_TEST_USER_ID, 5)

    assert result["action"] == "error"
    assert "1" in result["text"]


async def test_handle_text_selection_by_number():
    state = {
        "flow_id": "abc123",
        "step": "awaiting_selection",
        "site": "booking.com",
        "task": "book hotel",
        "family_id": _TEST_FAMILY_ID,
        "results": [
            {"name": "Hotel A", "price": "$100/night", "rating": "8.0", "description": "Nice"},
            {"name": "Hotel B", "price": "$120/night", "rating": "8.5", "description": "Great"},
        ],
        "raw_text": "...",
    }

    with patch("src.tools.browser_booking.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_redis.set = AsyncMock()
        result = await handle_text_selection(_TEST_USER_ID, "2")

    assert result is not None
    assert result["action"] == "confirm"
    assert "Hotel B" in result["text"]


async def test_handle_text_selection_by_name():
    state = {
        "flow_id": "abc123",
        "step": "awaiting_selection",
        "site": "booking.com",
        "task": "book hotel",
        "family_id": _TEST_FAMILY_ID,
        "results": [
            {"name": "Hotel Arts", "price": "$135/night", "rating": "8.9", "description": "Beach"},
        ],
        "raw_text": "...",
    }

    with patch("src.tools.browser_booking.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_redis.set = AsyncMock()
        result = await handle_text_selection(_TEST_USER_ID, "hotel arts")

    assert result is not None
    assert result["action"] == "confirm"


async def test_handle_text_selection_no_match():
    state = {
        "flow_id": "abc123",
        "step": "awaiting_selection",
        "site": "booking.com",
        "task": "book hotel",
        "family_id": _TEST_FAMILY_ID,
        "results": [
            {"name": "Hotel A", "price": "$100/night", "rating": "8.0", "description": "Nice"},
        ],
        "raw_text": "...",
    }

    with patch("src.tools.browser_booking.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        result = await handle_text_selection(_TEST_USER_ID, "something unrelated")

    assert result is None


async def test_execute_booking_with_session():
    state = {
        "flow_id": "abc123",
        "step": "confirming",
        "site": "booking.com",
        "task": "book hotel in Barcelona March 15-18",
        "family_id": _TEST_FAMILY_ID,
        "selected_idx": 0,
        "results": [
            {"name": "Hotel Arts", "price": "$135/night", "rating": "8.9", "description": "Beach"},
        ],
        "raw_text": "...",
    }

    with (
        patch("src.tools.browser_booking.redis") as mock_redis,
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value={"cookies": [{"name": "s", "value": "v"}]},
        ),
        patch(
            "src.tools.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={"success": True, "result": "Booking confirmed!"},
        ),
    ):
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_redis.delete = AsyncMock()
        result = await execute_booking(_TEST_USER_ID)

    assert result["action"] == "success"
    assert "Hotel Arts" in result["text"]


async def test_execute_booking_no_session():
    state = {
        "flow_id": "abc123",
        "step": "confirming",
        "site": "booking.com",
        "task": "book hotel in Barcelona",
        "family_id": _TEST_FAMILY_ID,
        "selected_idx": 0,
        "results": [
            {"name": "Hotel Arts", "price": "$135/night", "rating": "8.9", "description": "Beach"},
        ],
        "raw_text": "...",
    }

    with (
        patch("src.tools.browser_booking.redis") as mock_redis,
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_redis.set = AsyncMock()
        result = await execute_booking(_TEST_USER_ID)

    assert result["action"] == "need_login"
    assert result["site"] == "booking.com"


async def test_cancel_booking():
    with patch("src.tools.browser_booking.redis") as mock_redis:
        mock_redis.delete = AsyncMock()
        await cancel_booking(_TEST_USER_ID)
        mock_redis.delete.assert_called_once()
