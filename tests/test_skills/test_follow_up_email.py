"""Tests for follow_up_email skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.follow_up_email.handler import FollowUpEmailSkill

MODULE = "src.skills.follow_up_email.handler"


@pytest.fixture
def skill():
    return FollowUpEmailSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="any emails I haven't replied to?",
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
async def test_follow_up_requires_google(skill, message, ctx):
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
async def test_follow_up_no_unread(skill, message, ctx):
    """Returns all-clear message when no unread emails."""
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

    assert (
        "нет" in result.response_text.lower()
        or "порядке" in result.response_text.lower()
    )


@pytest.mark.asyncio
async def test_follow_up_with_emails(skill, message, ctx):
    """Analyzes real email data for follow-ups."""
    mock_google = AsyncMock()
    mock_google.list_messages = AsyncMock(return_value=[
        {
            "id": "msg1",
            "threadId": "t1",
            "snippet": "Waiting for your reply",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Boss <boss@test.com>"},
                    {"name": "Subject", "value": "Q4 Review"},
                ]
            },
        }
    ])

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
            f"{MODULE}._analyze_follow_ups",
            new_callable=AsyncMock,
            return_value="Boss — Q4 Review (2 дня назад)\n\nОтветить?",
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert "Boss" in result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
