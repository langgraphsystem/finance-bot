"""Tests for browser_action skill."""

from unittest.mock import AsyncMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.browser_action.handler import BrowserActionSkill

# Shared mocks: no active browser subflows
_no_booking = patch(
    "src.skills.browser_action.handler.browser_booking.get_booking_state",
    new_callable=AsyncMock,
    return_value=None,
)
_no_taxi = patch(
    "src.skills.browser_action.handler.taxi_booking.get_taxi_state",
    new_callable=AsyncMock,
    return_value=None,
)
_no_login = patch(
    "src.skills.browser_action.handler.browser_login.get_login_state",
    new_callable=AsyncMock,
    return_value=None,
)


def test_browser_action_skill_attributes():
    skill = BrowserActionSkill()
    assert skill.name == "browser_action"
    assert "browser_action" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


def test_browser_action_system_prompt(sample_context):
    skill = BrowserActionSkill()
    prompt = skill.get_system_prompt(sample_context)
    assert "browser" in prompt.lower()
    assert "automation" in prompt.lower()


async def test_browser_action_empty_message(sample_context):
    skill = BrowserActionSkill()
    msg = IncomingMessage(id="1", user_id="u1", chat_id="c1", type=MessageType.text, text="")
    with _no_booking, _no_taxi, _no_login:
        result = await skill.execute(msg, sample_context, {})
    assert (
        "what" in result.response_text.lower()
        or "website" in result.response_text.lower()
    )


async def test_browser_action_vague_booking_asks_details(sample_context):
    """Vague booking request without city/dates — start_flow returns validation."""
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="забронируй отель на booking.com",
    )
    intent_data = {
        "browser_task": "забронируй отель на booking.com",
        "browser_target_site": "booking.com",
    }
    with (
        _no_booking,
        _no_taxi,
        _no_login,
        patch(
            "src.skills.browser_action.handler.browser_booking.start_flow",
            new_callable=AsyncMock,
            return_value={
                "text": (
                    "I need more details to search for hotels.\n\n"
                    "Please include: <b>city</b>, <b>dates</b>"
                ),
                "buttons": None,
            },
        ),
    ):
        result = await skill.execute(msg, sample_context, intent_data)
    assert "need" in result.response_text.lower() or "details" in result.response_text.lower()


async def test_browser_action_detailed_booking_starts_flow(sample_context):
    """Booking with city + dates on booking site should start hotel flow."""
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="забронируй отель в Барселоне на 15-18 марта на booking.com",
    )
    intent_data = {
        "browser_task": "забронируй отель в Барселоне на 15-18 марта",
        "browser_target_site": "booking.com",
    }
    with (
        _no_booking,
        _no_taxi,
        _no_login,
        patch(
            "src.skills.browser_action.handler.browser_booking.start_flow",
            new_callable=AsyncMock,
            return_value={
                "text": "<b>Hotel Search</b>\n\nBarcelona, Mar 15 — Mar 18",
                "buttons": [
                    {"text": "booking.com", "callback": "hotel_platform:abc:booking.com"},
                    {"text": "airbnb.com", "callback": "hotel_platform:abc:airbnb.com"},
                ],
            },
        ) as mock_flow,
    ):
        result = await skill.execute(msg, sample_context, intent_data)
        mock_flow.assert_called_once()
    assert "Hotel Search" in result.response_text or "Barcelona" in result.response_text
    assert result.buttons is not None


async def test_browser_action_hotel_keyword_starts_flow(sample_context):
    """Hotel keyword without booking verb should still start flow."""
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="найди отель в Париже на завтра",
    )
    intent_data = {"browser_task": "найди отель в Париже на завтра"}
    with (
        _no_booking,
        _no_taxi,
        _no_login,
        patch(
            "src.skills.browser_action.handler.browser_booking.start_flow",
            new_callable=AsyncMock,
            return_value={"text": "<b>Hotel Search</b>\n\nParis", "buttons": []},
        ) as mock_flow,
    ):
        result = await skill.execute(msg, sample_context, intent_data)
        mock_flow.assert_called_once()
    assert "Hotel Search" in result.response_text or "Paris" in result.response_text


async def test_browser_action_payment_needs_approval(sample_context):
    """Non-booking payment task with enough details should go to approval."""
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="buy Sony WH-1000XM5 headphones on amazon.com",
    )
    intent_data = {
        "browser_task": "buy Sony WH-1000XM5 headphones",
        "browser_target_site": "amazon.com",
    }
    with (
        _no_booking,
        _no_taxi,
        _no_login,
        patch("src.skills.browser_action.handler.approval_manager") as mock_approval,
    ):
        mock_approval.request_approval = AsyncMock(
            return_value=AsyncMock(response_text="Confirm?", buttons=[])
        )
        await skill.execute(msg, sample_context, intent_data)
        mock_approval.request_approval.assert_called_once()


async def test_browser_action_with_session_executes(sample_context):
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="check my booking status on booking.com",
    )
    intent_data = {
        "browser_task": "check my booking status",
        "browser_target_site": "booking.com",
    }
    with (
        _no_booking,
        _no_taxi,
        _no_login,
        patch(
            "src.skills.browser_action.handler.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value={"cookies": [{"name": "session", "value": "abc"}]},
        ),
        patch(
            "src.skills.browser_action.handler.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={"success": True, "result": "Booking confirmed for March 15"},
        ),
        patch(
            "src.skills.browser_action.handler.generate_text",
            new_callable=AsyncMock,
            return_value="Your booking is confirmed for March 15.",
        ),
    ):
        result = await skill.execute(msg, sample_context, intent_data)
    assert "march 15" in result.response_text.lower()


async def test_browser_action_no_session_suggests_extension(sample_context):
    """No saved session should suggest browser extension."""
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="check booking on booking.com",
    )
    intent_data = {
        "browser_task": "check booking",
        "browser_target_site": "booking.com",
    }
    with (
        _no_booking,
        _no_taxi,
        _no_login,
        patch(
            "src.skills.browser_action.handler.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await skill.execute(msg, sample_context, intent_data)
    assert "extension" in result.response_text.lower()
    assert "/extension" in result.response_text


async def test_browser_action_expired_session_suggests_extension(sample_context):
    """Expired session should clear cookies and suggest extension."""
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="check reservation on booking.com",
    )
    intent_data = {
        "browser_task": "check reservation",
        "browser_target_site": "booking.com",
    }
    with (
        _no_booking,
        _no_taxi,
        _no_login,
        patch(
            "src.skills.browser_action.handler.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value={"cookies": [{"name": "old", "value": "expired"}]},
        ),
        patch(
            "src.skills.browser_action.handler.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={"success": False, "result": "Please sign in to continue"},
        ),
        patch(
            "src.skills.browser_action.handler.browser_service.delete_session",
            new_callable=AsyncMock,
        ) as mock_delete,
    ):
        result = await skill.execute(msg, sample_context, intent_data)
    mock_delete.assert_called_once()
    assert "expired" in result.response_text.lower()
    assert "/extension" in result.response_text


async def test_browser_action_vague_shopping_asks_product(sample_context):
    """Vague shopping request without product should ask what to buy."""
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="купи на amazon.com",
    )
    intent_data = {
        "browser_task": "купи",
        "browser_target_site": "amazon.com",
    }
    with _no_booking, _no_taxi, _no_login:
        result = await skill.execute(msg, sample_context, intent_data)
    assert "amazon.com" in result.response_text
    assert "find" in result.response_text.lower()


async def test_browser_action_read_only_on_booking_site_skips_search(sample_context):
    """Read-only task on booking site should NOT start search flow."""
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="check my booking status on booking.com",
    )
    intent_data = {
        "browser_task": "check my booking status",
        "browser_target_site": "booking.com",
    }
    with (
        _no_booking,
        _no_taxi,
        _no_login,
        patch(
            "src.skills.browser_action.handler.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value={"cookies": [{"name": "session", "value": "abc"}]},
        ),
        patch(
            "src.skills.browser_action.handler.browser_service.execute_with_session",
            new_callable=AsyncMock,
            return_value={"success": True, "result": "Your booking is confirmed."},
        ),
        patch(
            "src.skills.browser_action.handler.generate_text",
            new_callable=AsyncMock,
            return_value="Your booking is confirmed.",
        ),
    ):
        result = await skill.execute(msg, sample_context, intent_data)
    assert "confirmed" in result.response_text.lower()


async def test_browser_action_taxi_request_starts_flow(sample_context):
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        type=MessageType.text,
        text="закажи такси в uber до аэропорта",
    )
    intent_data = {
        "browser_task": "закажи такси в uber до аэропорта",
    }
    with (
        _no_booking,
        _no_taxi,
        _no_login,
        patch(
            "src.skills.browser_action.handler.taxi_booking.start_flow",
            new_callable=AsyncMock,
            return_value={
                "text": "<b>Uber ride options</b>",
                "buttons": [{"text": "1. UberX", "callback": "taxi_select:abc:0"}],
            },
        ) as mock_flow,
    ):
        result = await skill.execute(msg, sample_context, intent_data)
    mock_flow.assert_awaited_once()
    assert "Uber" in result.response_text
    assert result.buttons is not None


async def test_browser_action_extracts_uber_alias(sample_context):
    skill = BrowserActionSkill()
    msg = IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        type=MessageType.text,
        text="order an uber to downtown",
    )
    with (
        _no_booking,
        _no_taxi,
        _no_login,
        patch(
            "src.skills.browser_action.handler.taxi_booking.start_flow",
            new_callable=AsyncMock,
            return_value={"text": "OK", "buttons": None},
        ) as mock_flow,
    ):
        await skill.execute(msg, sample_context, {"browser_task": msg.text})
    assert mock_flow.await_args.kwargs["site_hint"] == "uber.com"



