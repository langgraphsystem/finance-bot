"""Tests for send_email skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.send_email.handler import SendEmailSkill


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
async def test_send_email_basic(skill, message, ctx):
    """Returns email draft with confirmation prompt."""
    draft = (
        "<b>To:</b> sarah@example.com\n"
        "<b>Subject:</b> Project Update\n\n"
        "Hi Sarah,\n\n"
        "Just wanted to share a quick update on the project.\n\n"
        "Best,\nUser\n\nSend this?"
    )
    with patch(
        "src.skills.send_email.handler.compose_email",
        new_callable=AsyncMock,
        return_value=draft,
    ):
        result = await skill.execute(
            message,
            ctx,
            {
                "email_to": "sarah@example.com",
                "email_subject": "Project Update",
                "email_body_hint": "share project update",
            },
        )

    assert "sarah@example.com" in result.response_text
    assert "Send this?" in result.response_text


@pytest.mark.asyncio
async def test_send_email_with_intent_data(skill, ctx):
    """Uses email_to, email_subject, email_body_hint from intent_data."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="email Mike about lunch tomorrow",
    )
    with patch(
        "src.skills.send_email.handler.compose_email",
        new_callable=AsyncMock,
        return_value="<b>To:</b> Mike\n<b>Subject:</b> Lunch Tomorrow\n\nSend this?",
    ) as mock_compose:
        result = await skill.execute(
            msg,
            ctx,
            {"email_to": "Mike", "email_subject": "Lunch Tomorrow", "email_body_hint": "lunch"},
        )

    call_args = mock_compose.call_args[0][0]
    assert "Mike" in call_args
    assert "Lunch Tomorrow" in call_args
    assert "Mike" in result.response_text


@pytest.mark.asyncio
async def test_send_email_empty_text(skill, ctx):
    """Empty text still builds prompt from intent_data."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    with patch(
        "src.skills.send_email.handler.compose_email",
        new_callable=AsyncMock,
        return_value="Who would you like to email?",
    ) as mock_compose:
        result = await skill.execute(msg, ctx, {})

    mock_compose.assert_awaited_once()
    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
