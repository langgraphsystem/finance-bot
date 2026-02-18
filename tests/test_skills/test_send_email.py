"""Tests for send_email skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.send_email.handler import SendEmailSkill

MODULE = "src.skills.send_email.handler"


@pytest.fixture
def skill():
    return SendEmailSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="send an email to sarah@example.com about the project update",
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


@pytest.mark.asyncio
async def test_send_email_requires_google(skill, message, ctx):
    """Returns connect button when Google not connected."""
    from src.skills.base import SkillResult

    prompt = SkillResult(
        response_text="Подключите Google",
        buttons=[{"text": "🔗 Подключить Google", "url": "https://example.com"}],
    )
    with patch(
        f"{MODULE}.require_google_or_prompt",
        new_callable=AsyncMock,
        return_value=prompt,
    ):
        result = await skill.execute(message, ctx, {})

    assert result.buttons


@pytest.mark.asyncio
async def test_send_email_missing_recipient(skill, ctx):
    """Returns error when no email_to."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="send email",
    )
    with patch(
        f"{MODULE}.require_google_or_prompt",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await skill.execute(msg, ctx, {})

    assert "получателя" in result.response_text.lower()


@pytest.mark.asyncio
async def test_send_email_returns_preview_with_buttons(skill, message, ctx):
    """Returns preview + confirm/cancel buttons instead of sending."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()

    intent_data = {
        "email_to": "sarah@example.com",
        "email_subject": "Project Update",
        "email_body_hint": "share project update",
    }

    with (
        patch(
            f"{MODULE}.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            f"{MODULE}._draft_body",
            new_callable=AsyncMock,
            return_value="Here's the project update.",
        ),
        patch("src.core.pending_actions.redis", mock_redis),
    ):
        result = await skill.execute(message, ctx, intent_data)

    assert "Черновик" in result.response_text
    assert "sarah@example.com" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    assert "confirm_action" in result.buttons[0]["callback"]
    assert "cancel_action" in result.buttons[1]["callback"]


@pytest.mark.asyncio
async def test_execute_send_success():
    """execute_send sends email via Gmail API."""
    from src.skills.send_email.handler import execute_send

    mock_google = AsyncMock()
    mock_google.send_message = AsyncMock(return_value={"id": "ok"})

    action_data = {
        "email_to": "sarah@example.com",
        "email_subject": "Test",
        "email_body": "Hello!",
    }

    with patch(
        f"{MODULE}.get_google_client",
        new_callable=AsyncMock,
        return_value=mock_google,
    ):
        result = await execute_send(action_data, "user-1")

    assert "отправлен" in result.lower()
    mock_google.send_message.assert_awaited_once()


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
