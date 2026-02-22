"""Tests for browser_action skill."""

from unittest.mock import AsyncMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.browser_action.handler import BrowserActionSkill


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
    with patch(
        "src.skills.browser_action.handler.browser_login.get_login_state",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await skill.execute(msg, sample_context, {})
    assert "what" in result.response_text.lower() or "website" in result.response_text.lower()


async def test_browser_action_vague_booking_asks_details(sample_context):
    """Vague booking request without city/dates should ask for details."""
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
        patch(
            "src.skills.browser_action.handler.browser_login.get_login_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await skill.execute(msg, sample_context, intent_data)
    # Should ask for missing details, not start login
    assert "missing" in result.response_text.lower() or "need" in result.response_text.lower()
    assert "booking.com" in result.response_text


async def test_browser_action_detailed_booking_proceeds(sample_context):
    """Booking with city + dates should proceed to approval."""
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
        patch(
            "src.skills.browser_action.handler.browser_login.get_login_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("src.skills.browser_action.handler.approval_manager") as mock_approval,
    ):
        mock_approval.request_approval = AsyncMock(
            return_value=AsyncMock(response_text="Confirm?", buttons=[])
        )
        await skill.execute(msg, sample_context, intent_data)
        mock_approval.request_approval.assert_called_once()


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
        patch(
            "src.skills.browser_action.handler.browser_login.get_login_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
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
        patch(
            "src.skills.browser_action.handler.browser_login.get_login_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
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


async def test_browser_action_no_session_starts_login(sample_context):
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
        patch(
            "src.skills.browser_action.handler.browser_login.get_login_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.skills.browser_action.handler.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.skills.browser_action.handler.browser_login.start_login",
            new_callable=AsyncMock,
            return_value={
                "action": "ask_email",
                "text": "Please enter your email:",
                "screenshot_bytes": b"fake_screenshot",
            },
        ),
    ):
        result = await skill.execute(msg, sample_context, intent_data)
    assert "email" in result.response_text.lower()
    assert result.photo_bytes == b"fake_screenshot"


async def test_browser_action_expired_session_relogins(sample_context):
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
        patch(
            "src.skills.browser_action.handler.browser_login.get_login_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
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
        patch(
            "src.skills.browser_action.handler.browser_login.start_login",
            new_callable=AsyncMock,
            return_value={
                "action": "ask_email",
                "text": "Please enter your email:",
                "screenshot_bytes": b"login_screenshot",
            },
        ),
    ):
        result = await skill.execute(msg, sample_context, intent_data)
    mock_delete.assert_called_once()
    assert "email" in result.response_text.lower()


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
    with patch(
        "src.skills.browser_action.handler.browser_login.get_login_state",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await skill.execute(msg, sample_context, intent_data)
    assert "amazon.com" in result.response_text
    assert "what" in result.response_text.lower() or "find" in result.response_text.lower()
