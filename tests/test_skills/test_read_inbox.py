"""Tests for read_inbox skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.read_inbox.handler import ReadInboxSkill

MODULE = "src.skills.read_inbox.handler"


@pytest.fixture
def skill():
    return ReadInboxSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="check my email",
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
async def test_read_inbox_requires_google(skill, message, ctx):
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

    assert "Подключить Google" in result.buttons[0]["text"]


@pytest.mark.asyncio
async def test_read_inbox_no_emails(skill, message, ctx):
    """Returns empty inbox message when no unread emails."""
    mock_google = AsyncMock()
    mock_google.list_messages = AsyncMock(return_value=[])

    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
    ):
        result = await skill.execute(message, ctx, {})

    assert "Новых писем нет" in result.response_text


@pytest.mark.asyncio
async def test_read_inbox_with_emails(skill, message, ctx):
    """Summarizes real email data."""
    mock_google = AsyncMock()
    mock_google.list_messages = AsyncMock(return_value=[
        {
            "id": "msg1",
            "threadId": "t1",
            "snippet": "Deadline moved",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Sarah <sarah@test.com>"},
                    {"name": "Subject", "value": "Project deadline"},
                ]
            },
        }
    ])

    summary = "1. Sarah — Project deadline\n\nNeed me to reply?"
    with (
        patch(
            f"{MODULE}.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            f"{MODULE}.get_google_client",
            new_callable=AsyncMock,
            return_value=mock_google,
        ),
        patch(
            f"{MODULE}._summarize_with_llm",
            new_callable=AsyncMock,
            return_value=summary,
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert "Sarah" in result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
