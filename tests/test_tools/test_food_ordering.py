"""Tests for food delivery ordering flow."""

from unittest.mock import AsyncMock, patch

from src.tools import food_ordering

_TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
_TEST_FAMILY_ID = "00000000-0000-0000-0000-000000000002"


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------


def test_parse_food_request_english_uber_eats():
    parsed = food_ordering.parse_food_request("order pizza from Uber Eats")
    assert parsed["platform"] == "ubereats.com"
    assert parsed["query"] is not None
    assert "pizza" in parsed["query"].lower()


def test_parse_food_request_russian():
    parsed = food_ordering.parse_food_request("закажи суши через ubereats")
    assert parsed["platform"] == "ubereats.com"
    assert parsed["query"] is not None
    assert "суши" in parsed["query"].lower()


def test_parse_food_request_no_platform():
    parsed = food_ordering.parse_food_request("order food nearby")
    assert parsed["platform"] is None


def test_parse_food_request_doordash():
    parsed = food_ordering.parse_food_request("get burgers on DoorDash")
    assert parsed["platform"] == "doordash.com"


def test_parse_food_request_with_address():
    parsed = food_ordering.parse_food_request("order pizza from Uber Eats deliver to 123 Main St")
    assert parsed["platform"] == "ubereats.com"
    assert parsed["address"] is not None
    assert "123 Main St" in parsed["address"]


# ---------------------------------------------------------------------------
# start_flow
# ---------------------------------------------------------------------------


async def test_start_flow_no_platform_shows_selection():
    with patch("src.tools.food_ordering._set_state", new_callable=AsyncMock):
        result = await food_ordering.start_flow(
            user_id=_TEST_USER_ID,
            family_id=_TEST_FAMILY_ID,
            task="order food",
            language="en",
        )
    assert result["action"] == "need_platform"
    assert result.get("buttons")
    # Should have platform buttons + cancel
    assert any("Uber Eats" in b["text"] for b in result["buttons"])


async def test_start_flow_with_platform_checks_auth():
    with (
        patch("src.tools.food_ordering._set_state", new_callable=AsyncMock),
        patch("src.tools.food_ordering.get_food_state", new_callable=AsyncMock) as mock_get,
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.tools.food_ordering._get_connect_url",
            new_callable=AsyncMock,
            return_value="https://example.com",
        ),
    ):
        mock_get.return_value = {
            "flow_id": "abc12345",
            "user_id": _TEST_USER_ID,
            "family_id": _TEST_FAMILY_ID,
            "language": "en",
            "platform": "ubereats.com",
            "platform_label": "Uber Eats",
            "query": "pizza",
            "address": None,
            "task": "order pizza from Uber Eats",
            "cart": [],
            "step": "checking_auth",
        }
        result = await food_ordering.start_flow(
            user_id=_TEST_USER_ID,
            family_id=_TEST_FAMILY_ID,
            task="order pizza from Uber Eats",
            language="en",
        )
    assert result["action"] == "need_login"
    assert "Uber Eats" in result["text"]


async def test_start_flow_russian_locale():
    with patch("src.tools.food_ordering._set_state", new_callable=AsyncMock):
        result = await food_ordering.start_flow(
            user_id=_TEST_USER_ID,
            family_id=_TEST_FAMILY_ID,
            task="закажи еду",
            language="ru",
        )
    assert result["action"] == "need_platform"
    assert "сервис" in result["text"].lower()


# ---------------------------------------------------------------------------
# handle_platform_selection
# ---------------------------------------------------------------------------


async def test_handle_platform_selection_valid():
    state = {
        "flow_id": "abc12345",
        "user_id": _TEST_USER_ID,
        "family_id": _TEST_FAMILY_ID,
        "language": "en",
        "platform": None,
        "query": "pizza",
        "address": None,
        "task": "order pizza",
        "cart": [],
        "step": "selecting_platform",
    }
    with (
        patch(
            "src.tools.food_ordering.get_food_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch("src.tools.food_ordering._set_state", new_callable=AsyncMock),
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.tools.food_ordering._get_connect_url",
            new_callable=AsyncMock,
            return_value="https://example.com",
        ),
    ):
        result = await food_ordering.handle_platform_selection(_TEST_USER_ID, "ubereats.com")
    assert result["action"] == "need_login"


async def test_handle_platform_selection_no_flow():
    with patch(
        "src.tools.food_ordering.get_food_state",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await food_ordering.handle_platform_selection(_TEST_USER_ID, "ubereats.com")
    assert result["action"] == "no_flow"


# ---------------------------------------------------------------------------
# handle_text_input
# ---------------------------------------------------------------------------


async def test_handle_text_input_awaiting_restaurant_by_number():
    state = {
        "flow_id": "abc12345",
        "user_id": _TEST_USER_ID,
        "family_id": _TEST_FAMILY_ID,
        "language": "en",
        "platform": "ubereats.com",
        "step": "awaiting_restaurant",
        "restaurants": [
            {"name": "Pizza Palace", "rating": "4.7"},
            {"name": "Sushi Bar", "rating": "4.5"},
        ],
        "cart": [],
    }
    with (
        patch(
            "src.tools.food_ordering.get_food_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch(
            "src.tools.food_ordering.handle_restaurant_selection",
            new_callable=AsyncMock,
            return_value={"action": "menu", "text": "Menu loaded"},
        ) as mock_select,
    ):
        result = await food_ordering.handle_text_input(_TEST_USER_ID, "1")
    mock_select.assert_awaited_once_with(_TEST_USER_ID, 0)
    assert result is not None


async def test_handle_text_input_viewing_menu_done():
    state = {
        "flow_id": "abc12345",
        "user_id": _TEST_USER_ID,
        "family_id": _TEST_FAMILY_ID,
        "language": "ru",
        "platform": "ubereats.com",
        "step": "viewing_menu",
        "menu_items": [{"name": "Pizza", "price": "$12"}],
        "cart": [{"name": "Pizza", "price": "$12", "index": 0}],
    }
    with (
        patch(
            "src.tools.food_ordering.get_food_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch(
            "src.tools.food_ordering.handle_done_selecting",
            new_callable=AsyncMock,
            return_value={"action": "confirming", "text": "Review order"},
        ) as mock_done,
    ):
        result = await food_ordering.handle_text_input(_TEST_USER_ID, "готово")
    mock_done.assert_awaited_once()
    assert result is not None


async def test_handle_text_input_no_flow_returns_none():
    with patch(
        "src.tools.food_ordering.get_food_state",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await food_ordering.handle_text_input(_TEST_USER_ID, "hello")
    assert result is None


# ---------------------------------------------------------------------------
# handle_menu_item_toggle
# ---------------------------------------------------------------------------


async def test_menu_item_toggle_adds_item():
    state = {
        "flow_id": "abc12345",
        "user_id": _TEST_USER_ID,
        "family_id": _TEST_FAMILY_ID,
        "language": "en",
        "platform": "ubereats.com",
        "step": "viewing_menu",
        "selected_restaurant": {"name": "Pizza Palace"},
        "menu_items": [
            {"name": "Margherita", "price": "$12.99", "description": "Classic"},
            {"name": "Pepperoni", "price": "$14.99", "description": "Spicy"},
        ],
        "cart": [],
    }
    with (
        patch(
            "src.tools.food_ordering.get_food_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch("src.tools.food_ordering._set_state", new_callable=AsyncMock),
    ):
        result = await food_ordering.handle_menu_item_toggle(_TEST_USER_ID, 0)
    assert result["action"] == "item_added"
    assert "Margherita" in result["text"]


async def test_menu_item_toggle_removes_item():
    state = {
        "flow_id": "abc12345",
        "user_id": _TEST_USER_ID,
        "family_id": _TEST_FAMILY_ID,
        "language": "en",
        "platform": "ubereats.com",
        "step": "viewing_menu",
        "selected_restaurant": {"name": "Pizza Palace"},
        "menu_items": [
            {"name": "Margherita", "price": "$12.99", "description": "Classic"},
        ],
        "cart": [{"name": "Margherita", "price": "$12.99", "index": 0}],
    }
    with (
        patch(
            "src.tools.food_ordering.get_food_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch("src.tools.food_ordering._set_state", new_callable=AsyncMock),
    ):
        result = await food_ordering.handle_menu_item_toggle(_TEST_USER_ID, 0)
    assert result["action"] == "item_removed"
    assert "Margherita" in result["text"]


# ---------------------------------------------------------------------------
# handle_done_selecting — cart empty
# ---------------------------------------------------------------------------


async def test_done_selecting_empty_cart():
    state = {
        "flow_id": "abc12345",
        "user_id": _TEST_USER_ID,
        "family_id": _TEST_FAMILY_ID,
        "language": "en",
        "platform": "ubereats.com",
        "step": "viewing_menu",
        "selected_restaurant": {"name": "Pizza Palace"},
        "menu_items": [{"name": "Pizza", "price": "$12"}],
        "cart": [],
    }
    with patch(
        "src.tools.food_ordering.get_food_state",
        new_callable=AsyncMock,
        return_value=state,
    ):
        result = await food_ordering.handle_done_selecting(_TEST_USER_ID)
    assert result["action"] == "cart_empty"


# ---------------------------------------------------------------------------
# cancel_flow
# ---------------------------------------------------------------------------


async def test_cancel_flow_clears_state():
    with patch("src.tools.food_ordering._clear_state", new_callable=AsyncMock) as mock:
        await food_ordering.cancel_flow(_TEST_USER_ID)
    mock.assert_awaited_once_with(_TEST_USER_ID)


# ---------------------------------------------------------------------------
# confirm_order — login required sentinel
# ---------------------------------------------------------------------------


async def test_confirm_order_login_required():
    state = {
        "flow_id": "abc12345",
        "user_id": _TEST_USER_ID,
        "family_id": _TEST_FAMILY_ID,
        "language": "en",
        "platform": "ubereats.com",
        "step": "confirming",
        "selected_restaurant": {"name": "Pizza Palace"},
        "cart": [{"name": "Pizza", "price": "$12", "index": 0}],
        "review": {"total": "$15.00"},
    }
    with (
        patch(
            "src.tools.food_ordering.get_food_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch("src.tools.food_ordering._set_state", new_callable=AsyncMock),
        patch(
            "src.tools.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={"success": False, "result": "LOGIN_REQUIRED"},
        ),
        patch(
            "src.tools.food_ordering._get_connect_url",
            new_callable=AsyncMock,
            return_value="https://example.com",
        ),
    ):
        result = await food_ordering.confirm_order(_TEST_USER_ID)
    assert result["action"] == "need_login"


# ---------------------------------------------------------------------------
# handle_back_to_restaurants
# ---------------------------------------------------------------------------


async def test_back_to_restaurants():
    state = {
        "flow_id": "abc12345",
        "user_id": _TEST_USER_ID,
        "family_id": _TEST_FAMILY_ID,
        "language": "en",
        "platform": "ubereats.com",
        "platform_label": "Uber Eats",
        "query": "pizza",
        "step": "viewing_menu",
        "restaurants": [
            {"name": "Pizza Palace", "rating": "4.7"},
        ],
        "selected_restaurant": {"name": "Pizza Palace"},
        "menu_items": [{"name": "Pizza", "price": "$12"}],
        "cart": [{"name": "Pizza"}],
    }
    with (
        patch(
            "src.tools.food_ordering.get_food_state",
            new_callable=AsyncMock,
            return_value=state,
        ),
        patch("src.tools.food_ordering._set_state", new_callable=AsyncMock),
    ):
        result = await food_ordering.handle_back_to_restaurants(_TEST_USER_ID)
    assert result["action"] == "results"
    assert "Pizza Palace" in result["text"]
