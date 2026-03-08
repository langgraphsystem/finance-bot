"""Tests for taxi booking flow."""

from unittest.mock import AsyncMock, patch

from src.tools import taxi_booking

_TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
_TEST_FAMILY_ID = "00000000-0000-0000-0000-000000000002"


def test_parse_taxi_request_russian_uber_destination():
    parsed = taxi_booking.parse_taxi_request("закажи такси в uber до аэропорта")
    assert parsed["provider"] == "uber.com"
    assert parsed["destination"] == "аэропорта"


def test_parse_taxi_request_english_pickup_and_destination():
    parsed = taxi_booking.parse_taxi_request(
        "book a Lyft from Union Station to O'Hare Airport"
    )
    assert parsed["provider"] == "lyft.com"
    assert parsed["pickup"] == "Union Station"
    assert parsed["destination"] == "O'Hare Airport"


async def test_start_flow_requires_destination():
    with patch("src.tools.taxi_booking._set_state", new_callable=AsyncMock) as mock_set:
        result = await taxi_booking.start_flow(
            user_id=_TEST_USER_ID,
            family_id=_TEST_FAMILY_ID,
            task="закажи такси в uber",
            language="ru",
        )
    mock_set.assert_awaited_once()
    assert result["action"] == "need_destination"
    assert "Uber" in result["text"]


async def test_check_auth_and_fetch_options_prompts_login_when_session_missing():
    state = {
        "flow_id": "flow-1",
        "family_id": _TEST_FAMILY_ID,
        "provider": "uber.com",
        "destination": "Airport",
        "step": "checking_auth",
    }
    with (
        patch("src.tools.taxi_booking.get_taxi_state", new_callable=AsyncMock, return_value=state),
        patch("src.tools.taxi_booking._set_state", new_callable=AsyncMock) as mock_set,
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await taxi_booking.check_auth_and_fetch_options(_TEST_USER_ID)
    mock_set.assert_awaited_once()
    assert result["action"] == "need_login"
    assert result["buttons"][0]["url"].startswith("https://")


async def test_handle_option_selection_prepares_confirmation():
    state = {
        "flow_id": "flow-1",
        "family_id": _TEST_FAMILY_ID,
        "provider": "uber.com",
        "destination": "Airport",
        "pickup": "Home",
        "step": "awaiting_selection",
        "options": [{"label": "UberX", "price": "$18", "eta": "4 min"}],
    }
    with (
        patch("src.tools.taxi_booking.get_taxi_state", new_callable=AsyncMock, return_value=state),
        patch("src.tools.taxi_booking._set_state", new_callable=AsyncMock) as mock_set,
        patch(
            "src.tools.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "result": (
                    '{"status":"READY_TO_CONFIRM","label":"UberX","pickup":"Home",'
                    '"destination":"Airport","price":"$18","eta":"4 min"}'
                ),
            },
        ),
    ):
        result = await taxi_booking.handle_option_selection(_TEST_USER_ID, 0)
    mock_set.assert_awaited_once()
    assert result["action"] == "confirming"
    assert "Confirm this ride" in result["text"]


async def test_confirm_booking_returns_success_and_clears_flow():
    state = {
        "flow_id": "flow-1",
        "family_id": _TEST_FAMILY_ID,
        "provider": "uber.com",
        "destination": "Airport",
        "pickup": "Home",
        "step": "confirming",
        "selected_option": {"label": "UberX", "price": "$18"},
        "review": {
            "label": "UberX",
            "pickup": "Home",
            "destination": "Airport",
            "price": "$18",
        },
    }
    with (
        patch("src.tools.taxi_booking.get_taxi_state", new_callable=AsyncMock, return_value=state),
        patch("src.tools.taxi_booking._clear_state", new_callable=AsyncMock) as mock_clear,
        patch(
            "src.tools.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "result": (
                    '{"status":"BOOKED","label":"UberX","price":"$18",'
                    '"eta":"3 min","driver_name":"John"}'
                ),
            },
        ),
    ):
        result = await taxi_booking.confirm_booking(_TEST_USER_ID)
    mock_clear.assert_awaited_once()
    assert result["action"] == "booked"
    assert "Ride requested" in result["text"]
