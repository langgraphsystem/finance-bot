"""Tests for the hotel booking flow (src/tools/browser_booking.py)."""

import json
from unittest.mock import AsyncMock, patch

from src.tools.browser_booking import (
    _build_result_buttons,
    _build_search_prompt,
    _calc_nights,
    _detect_booking_status,
    _extract_json_array,
    _extract_json_object,
    _format_confirmation_telegram,
    _format_dates,
    _format_results_telegram,
    _parse_browser_results,
    _truncate,
    _validate_results,
    cancel_flow,
    check_auth_and_search,
    execute_booking,
    execute_browser_search,
    handle_back_to_results,
    handle_hotel_selection,
    handle_login_ready,
    handle_platform_choice,
    handle_text_input,
    start_flow,
)

# ── Sample data ──────────────────────────────────────────────────────────────

SAMPLE_PARSED = {
    "city": "Barcelona",
    "check_in": "2026-03-15",
    "check_out": "2026-03-18",
    "guests": 2,
    "budget_per_night": 150,
    "currency": "USD",
    "amenities": [],
    "sort_by": "best_value",
}

SAMPLE_RESULTS = [
    {
        "name": "Hotel Arts Barcelona",
        "price_per_night": "$135",
        "total_price": "$405",
        "rating": "8.9",
        "review_count": "2341",
        "distance": "1.2 km from center",
        "amenities": ["pool", "wifi", "parking"],
        "cancellation": "Free cancellation until March 13",
        "description": "Beachfront luxury hotel",
    },
    {
        "name": "W Barcelona",
        "price_per_night": "$148",
        "total_price": "$444",
        "rating": "8.7",
        "review_count": "1892",
        "distance": "0.8 km from center",
        "amenities": ["pool", "wifi", "spa"],
        "cancellation": "Free cancellation until March 12",
        "description": "Iconic sail-shaped building",
    },
]

SAMPLE_STATE_SELECTION = {
    "flow_id": "abc12345",
    "step": "awaiting_selection",
    "site": "booking.com",
    "task": "find hotel in Barcelona March 15-18",
    "family_id": "fam-123",
    "language": "en",
    "parsed": SAMPLE_PARSED,
    "results": SAMPLE_RESULTS,
    "page": 1,
    "selected_hotel": None,
    "search_url": None,
}


# ── Utility tests ────────────────────────────────────────────────────────────


def test_extract_json_object():
    assert _extract_json_object('{"a": 1}') == {"a": 1}
    assert _extract_json_object('text {"a": 1} more') == {"a": 1}
    assert _extract_json_object("no json") is None
    assert _extract_json_object("") is None
    assert _extract_json_object(None) is None


def test_extract_json_array():
    assert _extract_json_array('[1, 2]') == [1, 2]
    assert _extract_json_array('text [{"a":1}] more') == [{"a": 1}]
    assert _extract_json_array("no json") is None
    assert _extract_json_array("") is None


def test_calc_nights():
    assert _calc_nights("2026-03-15", "2026-03-18") == 3
    assert _calc_nights("2026-03-15", "2026-03-16") == 1
    assert _calc_nights(None, "2026-03-18") == 1
    assert _calc_nights("invalid", "2026-03-18") == 1


def test_format_dates():
    assert "Mar 15" in _format_dates("2026-03-15", "2026-03-18")
    assert "Mar 18" in _format_dates("2026-03-15", "2026-03-18")
    assert _format_dates(None, None) == "dates TBD"


def test_truncate():
    assert _truncate("short", 10) == "short"
    assert _truncate("this is a longer text", 10) == "this is a ..."


def test_detect_booking_status():
    assert _detect_booking_status("SOLD_OUT room") == "SOLD_OUT"
    assert _detect_booking_status("please login") == "LOGIN_REQUIRED"
    assert _detect_booking_status("PAYMENT required") == "PAYMENT_REQUIRED"
    assert _detect_booking_status("CAPTCHA challenge") == "CAPTCHA_DETECTED"
    assert _detect_booking_status("booking confirmed") == "READY_TO_BOOK"
    assert _detect_booking_status("random text") == "UNKNOWN"


# ── Result parsing tests ─────────────────────────────────────────────────────


def test_validate_results_filters_invalid():
    results = [
        {"name": "Valid Hotel", "price_per_night": "$100"},
        {"price_per_night": "$50"},  # no name → invalid
        "not a dict",
        {"name": "", "price_per_night": "$50"},  # empty name → invalid
    ]
    valid = _validate_results(results)
    assert len(valid) == 1
    assert valid[0]["name"] == "Valid Hotel"


def test_parse_browser_results_json():
    json_str = json.dumps(SAMPLE_RESULTS)
    results = _parse_browser_results(json_str)
    assert len(results) == 2
    assert results[0]["name"] == "Hotel Arts Barcelona"


def test_parse_browser_results_json_in_text():
    text = f"Here are the results:\n{json.dumps(SAMPLE_RESULTS)}\nEnd."
    results = _parse_browser_results(text)
    assert len(results) == 2


def test_parse_browser_results_empty():
    assert _parse_browser_results("") == []
    assert _parse_browser_results("No hotels found.") == []


# ── Formatting tests ─────────────────────────────────────────────────────────


def test_format_results_telegram():
    text = _format_results_telegram(SAMPLE_RESULTS, "booking.com", SAMPLE_PARSED)
    assert "<b>Hotels on booking.com</b>" in text
    assert "Hotel Arts Barcelona" in text
    assert "$135" in text
    assert "8.9/10" in text
    assert "pool" in text
    assert "Free cancellation" in text
    assert "W Barcelona" in text


def test_format_results_telegram_empty():
    text = _format_results_telegram([], "booking.com", SAMPLE_PARSED)
    assert "No hotels found" in text


def test_format_confirmation_telegram():
    text = _format_confirmation_telegram(SAMPLE_RESULTS[0], SAMPLE_PARSED)
    assert "Confirm booking" in text
    assert "Hotel Arts Barcelona" in text
    assert "$135" in text
    assert "3 nights" in text
    assert "Free cancellation" in text


def test_build_result_buttons():
    buttons = _build_result_buttons(SAMPLE_RESULTS, "abc12345")
    # 2 hotel buttons + sort + more + cancel
    assert len(buttons) == 5
    assert buttons[0]["callback"] == "hotel_select:abc12345:0"
    assert buttons[1]["callback"] == "hotel_select:abc12345:1"
    assert "Sort" in buttons[2]["text"]
    assert "More" in buttons[3]["text"]
    assert "Cancel" in buttons[4]["text"]


# ── Prompt builder tests ─────────────────────────────────────────────────────


def test_build_search_prompt():
    prompt = _build_search_prompt("booking.com", SAMPLE_PARSED)
    assert "booking.com" in prompt
    assert "Barcelona" in prompt
    assert "2026-03-15" in prompt
    assert "2 adults" in prompt
    assert "$150" in prompt  # budget filter


def test_build_search_prompt_no_filters():
    parsed = {"city": "Paris", "check_in": "2026-04-01", "check_out": "2026-04-03", "guests": 1}
    prompt = _build_search_prompt("airbnb.com", parsed)
    assert "airbnb.com" in prompt
    assert "Paris" in prompt
    assert "1 adults" in prompt


# ── Flow tests (with mocked Redis) ──────────────────────────────────────────

_REDIS_PREFIX = "hotel_booking"


async def test_start_flow_missing_city():
    """Start flow without city should return validation error."""
    with patch(
        "src.tools.browser_booking.parse_booking_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await start_flow("u1", "f1", "book a hotel", "en")
    assert "need more details" in result["text"].lower()
    assert result["buttons"] is None


async def test_start_flow_missing_dates():
    """Start flow without dates should ask for dates."""
    with patch(
        "src.tools.browser_booking.parse_booking_request",
        new_callable=AsyncMock,
        return_value={"city": "Barcelona", "guests": 2},
    ):
        result = await start_flow("u1", "f1", "hotel in Barcelona", "en")
    assert "dates" in result["text"].lower()
    assert result["buttons"] is None


async def test_start_flow_success():
    """Full request should return Gemini preview + platform buttons."""
    with (
        patch(
            "src.tools.browser_booking.parse_booking_request",
            new_callable=AsyncMock,
            return_value=SAMPLE_PARSED,
        ),
        patch(
            "src.tools.browser_booking._get_price_preview",
            new_callable=AsyncMock,
            return_value="Prices range from $78 to $250/night",
        ),
        patch(
            "src.tools.browser_booking._set_state",
            new_callable=AsyncMock,
        ) as mock_set,
    ):
        result = await start_flow("u1", "f1", "hotel in Barcelona March 15-18", "en")
    assert "Barcelona" in result["text"]
    assert "$78" in result["text"] or "platform" in result["text"].lower()
    assert result["buttons"] is not None
    assert any("booking.com" in b["text"] for b in result["buttons"])
    mock_set.assert_called_once()


async def test_handle_platform_choice_valid():
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value={
                "flow_id": "abc",
                "step": "platform_selection",
                "family_id": "f1",
                "parsed": SAMPLE_PARSED,
                "language": "en",
            },
        ),
        patch(
            "src.tools.browser_booking.check_auth_and_search",
            new_callable=AsyncMock,
            return_value={"action": "need_login", "text": "Login needed", "buttons": []},
        ) as mock_auth,
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
    ):
        result = await handle_platform_choice("u1", "booking.com")
    mock_auth.assert_called_once()
    assert result["text"] == "Login needed"


async def test_handle_platform_choice_invalid():
    with patch(
        "src.tools.browser_booking.get_booking_state",
        new_callable=AsyncMock,
        return_value={"flow_id": "abc", "step": "platform_selection"},
    ):
        result = await handle_platform_choice("u1", "unknown.com")
    assert result["action"] == "error"


async def test_handle_platform_choice_no_flow():
    with patch(
        "src.tools.browser_booking.get_booking_state",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await handle_platform_choice("u1", "booking.com")
    assert result["action"] == "no_flow"


async def test_check_auth_with_session_starts_search():
    """When cookies exist, should start browser search."""
    state = {**SAMPLE_STATE_SELECTION, "step": "platform_selection", "site": "booking.com"}
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value={"cookies": [{"name": "sid", "value": "x"}]},
        ),
        patch(
            "src.tools.browser_booking.execute_browser_search",
            new_callable=AsyncMock,
            return_value={"action": "results", "text": "Found 5 hotels", "buttons": []},
        ) as mock_search,
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
    ):
        result = await check_auth_and_search("u1")
    mock_search.assert_called_once()
    assert result["action"] == "results"


async def test_check_auth_no_session_prompts_login():
    """When no cookies, should return login prompt."""
    state = {**SAMPLE_STATE_SELECTION, "step": "platform_selection", "site": "booking.com"}
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.tools.browser_service.get_login_url",
            return_value="https://www.booking.com/sign-in.html",
        ),
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
    ):
        result = await check_auth_and_search("u1")
    assert result["action"] == "need_login"
    assert "Log in" in result["text"] or "log in" in result["text"]


async def test_handle_login_ready_no_session():
    """When user clicks Ready but no session, show retry message."""
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value={"flow_id": "abc", "step": "awaiting_login", "site": "booking.com"},
        ),
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.tools.browser_service.get_login_url",
            return_value="https://www.booking.com/sign-in.html",
        ),
    ):
        result = await handle_login_ready("u1")
    assert result["action"] == "need_login"
    assert "still" in result["text"].lower() or "don't see" in result["text"].lower()


async def test_handle_login_ready_with_session():
    """When user has saved session, proceed to search."""
    state = {**SAMPLE_STATE_SELECTION, "step": "awaiting_login", "site": "booking.com"}
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value={"cookies": [{"name": "s", "value": "v"}]},
        ),
        patch(
            "src.tools.browser_booking.execute_browser_search",
            new_callable=AsyncMock,
            return_value={"action": "results", "text": "Hotels found", "buttons": []},
        ) as mock_search,
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
    ):
        result = await handle_login_ready("u1")
    mock_search.assert_called_once()
    assert result["action"] == "results"


async def test_execute_browser_search_success():
    """Browser-Use returns JSON results — parsed and formatted."""
    state = {**SAMPLE_STATE_SELECTION, "step": "browser_searching"}
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch(
            "src.tools.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "result": json.dumps(SAMPLE_RESULTS),
            },
        ),
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
    ):
        result = await execute_browser_search("u1")
    assert result["action"] == "results"
    assert "Hotel Arts" in result["text"]
    assert result["buttons"] is not None


async def test_execute_browser_search_captcha():
    """Browser-Use hits CAPTCHA — user gets manual search link."""
    state = {**SAMPLE_STATE_SELECTION, "step": "browser_searching"}
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch(
            "src.tools.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={"success": False, "result": "CAPTCHA_DETECTED"},
        ),
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
    ):
        result = await execute_browser_search("u1")
    assert result["action"] == "captcha"
    assert "CAPTCHA" in result["text"]


async def test_execute_browser_search_login_required():
    """Browser-Use detects session expired."""
    state = {**SAMPLE_STATE_SELECTION, "step": "browser_searching"}
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch(
            "src.tools.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={"success": False, "result": "LOGIN_REQUIRED"},
        ),
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
        patch(
            "src.tools.browser_booking.check_auth_and_search",
            new_callable=AsyncMock,
            return_value={"action": "need_login", "text": "Login", "buttons": []},
        ),
    ):
        result = await execute_browser_search("u1")
    assert result["action"] == "need_login"


async def test_handle_hotel_selection_valid():
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value={**SAMPLE_STATE_SELECTION},
        ),
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
    ):
        result = await handle_hotel_selection("u1", 0)
    assert result["action"] == "confirm"
    assert "Hotel Arts" in result["text"]
    assert "Confirm" in str(result["buttons"])


async def test_handle_hotel_selection_invalid_index():
    with patch(
        "src.tools.browser_booking.get_booking_state",
        new_callable=AsyncMock,
        return_value={**SAMPLE_STATE_SELECTION},
    ):
        result = await handle_hotel_selection("u1", 99)
    assert result["action"] == "error"


async def test_handle_text_input_number():
    """Typing '1' selects first hotel."""
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value={**SAMPLE_STATE_SELECTION},
        ),
        patch(
            "src.tools.browser_booking.handle_hotel_selection",
            new_callable=AsyncMock,
            return_value={"action": "confirm", "text": "Confirm?"},
        ) as mock_select,
    ):
        result = await handle_text_input("u1", "1")
    mock_select.assert_called_once_with("u1", 0)
    assert result is not None


async def test_handle_text_input_name():
    """Typing hotel name substring selects it."""
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value={**SAMPLE_STATE_SELECTION},
        ),
        patch(
            "src.tools.browser_booking.handle_hotel_selection",
            new_callable=AsyncMock,
            return_value={"action": "confirm", "text": "Confirm?"},
        ) as mock_select,
    ):
        result = await handle_text_input("u1", "arts")
    mock_select.assert_called_once_with("u1", 0)
    assert result is not None


async def test_handle_text_input_sort_command():
    """Typing 'по цене' triggers sort by price."""
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value={**SAMPLE_STATE_SELECTION},
        ),
        patch(
            "src.tools.browser_booking.handle_sort_change",
            new_callable=AsyncMock,
            return_value={"action": "results", "text": "Sorted", "buttons": []},
        ) as mock_sort,
    ):
        result = await handle_text_input("u1", "по цене")
    mock_sort.assert_called_once_with("u1", "price")
    assert result is not None


async def test_handle_text_input_confirm_text():
    """Typing 'да' during confirming triggers booking."""
    confirming_state = {**SAMPLE_STATE_SELECTION, "step": "confirming"}
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=confirming_state,
        ),
        patch(
            "src.tools.browser_booking.execute_booking",
            new_callable=AsyncMock,
            return_value={"action": "ready", "text": "Booked"},
        ) as mock_book,
    ):
        result = await handle_text_input("u1", "да")
    mock_book.assert_called_once()
    assert result is not None


async def test_handle_text_input_ready_during_login():
    """Typing 'готово' during awaiting_login checks session."""
    login_state = {**SAMPLE_STATE_SELECTION, "step": "awaiting_login"}
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=login_state,
        ),
        patch(
            "src.tools.browser_booking.handle_login_ready",
            new_callable=AsyncMock,
            return_value={"action": "need_login", "text": "Still no session"},
        ) as mock_ready,
    ):
        result = await handle_text_input("u1", "готово")
    mock_ready.assert_called_once()
    assert result is not None


async def test_handle_text_input_no_match():
    """Unrecognized text during selection returns None."""
    with patch(
        "src.tools.browser_booking.get_booking_state",
        new_callable=AsyncMock,
        return_value={**SAMPLE_STATE_SELECTION},
    ):
        result = await handle_text_input("u1", "random gibberish 42xyz")
    assert result is None


async def test_handle_back_to_results():
    confirming_state = {
        **SAMPLE_STATE_SELECTION,
        "step": "confirming",
        "selected_hotel": SAMPLE_RESULTS[0],
    }
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=confirming_state,
        ),
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
    ):
        result = await handle_back_to_results("u1")
    assert result["action"] == "results"
    assert "Hotel Arts" in result["text"]


async def test_cancel_flow():
    with patch(
        "src.tools.browser_booking._clear_state",
        new_callable=AsyncMock,
    ) as mock_clear:
        await cancel_flow("u1")
    mock_clear.assert_called_once_with("u1")


async def test_execute_booking_no_state():
    with patch(
        "src.tools.browser_booking.get_booking_state",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await execute_booking("u1")
    assert result["action"] == "error"


async def test_execute_booking_sold_out():
    """Browser-Use detects hotel sold out."""
    state = {
        **SAMPLE_STATE_SELECTION,
        "step": "confirming",
        "selected_hotel": SAMPLE_RESULTS[0],
    }
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value={"cookies": [{"name": "s", "value": "v"}]},
        ),
        patch(
            "src.tools.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "result": json.dumps({"status": "SOLD_OUT"}),
            },
        ),
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
    ):
        result = await execute_booking("u1")
    assert result["action"] == "sold_out"
    assert "no longer available" in result["text"].lower()


async def test_execute_booking_payment_required():
    """Browser-Use detects payment is needed."""
    state = {
        **SAMPLE_STATE_SELECTION,
        "step": "confirming",
        "selected_hotel": SAMPLE_RESULTS[0],
    }
    with (
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value={"cookies": [{"name": "s", "value": "v"}]},
        ),
        patch(
            "src.tools.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "result": json.dumps({
                    "status": "PAYMENT_REQUIRED",
                    "final_price": "$405",
                    "booking_url": "https://booking.com/checkout",
                }),
            },
        ),
        patch("src.tools.browser_booking._set_state", new_callable=AsyncMock),
    ):
        result = await execute_booking("u1")
    assert result["action"] == "payment_required"
    assert "$405" in result["text"]
    # Should have a URL button for manual payment
    assert any("url" in str(b) for b in result.get("buttons", []))
