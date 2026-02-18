"""Tests for summarize_thread skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.summarize_thread.handler import SummarizeThreadSkill

MODULE = "src.skills.summarize_thread.handler"


@pytest.fixture
def skill():
    return SummarizeThreadSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="summarize the thread with Sarah about the budget",
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
async def test_summarize_thread_requires_google(skill, message, ctx):
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
async def test_summarize_thread_no_emails(skill, message, ctx):
    """Returns empty message when no emails found."""
    mock_google = AsyncMock()
    mock_google.list_messages = AsyncMock(return_value=[])

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
    ):
        result = await skill.execute(message, ctx, {})

    assert "нет" in result.response_text.lower() or "суммаризац" in result.response_text.lower()


@pytest.mark.asyncio
async def test_summarize_thread_with_thread(skill, message, ctx):
    """Summarizes real thread data."""
    email_msg = {
        "id": "msg1",
        "threadId": "t1",
        "snippet": "Budget Q1",
        "payload": {
            "headers": [
                {"name": "From", "value": "Sarah <sarah@test.com>"},
                {"name": "Subject", "value": "Budget discussion"},
            ]
        },
    }
    mock_google = AsyncMock()
    mock_google.list_messages = AsyncMock(return_value=[email_msg])
    mock_google.get_thread = AsyncMock(return_value=[email_msg])

    summary = "<b>Budget Q1</b>\nSarah proposed 15% increase."
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
            f"{MODULE}._summarize",
            new_callable=AsyncMock,
            return_value=summary,
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert "Sarah" in result.response_text or "Budget" in result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
