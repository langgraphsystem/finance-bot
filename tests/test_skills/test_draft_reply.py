"""Tests for draft_reply skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.draft_reply.handler import DraftReplySkill

MODULE = "src.skills.draft_reply.handler"


@pytest.fixture
def skill():
    return DraftReplySkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="reply to Sarah's email saying I'll be there at 3pm",
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
async def test_draft_reply_requires_google(skill, message, ctx):
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
async def test_draft_reply_no_unread(skill, message, ctx):
    """Returns message when no unread emails."""
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
        or "непрочитанных" in result.response_text.lower()
    )


@pytest.mark.asyncio
async def test_draft_reply_with_thread(skill, message, ctx):
    """Drafts reply from real thread data."""
    email_msg = {
        "id": "msg1",
        "threadId": "t1",
        "snippet": "See you at 3pm",
        "payload": {
            "headers": [
                {"name": "From", "value": "Sarah <sarah@test.com>"},
                {"name": "Subject", "value": "Meeting"},
            ]
        },
    }
    mock_google = AsyncMock()
    mock_google.list_messages = AsyncMock(return_value=[email_msg])
    mock_google.get_thread = AsyncMock(return_value=[email_msg])

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
            f"{MODULE}._draft_reply",
            new_callable=AsyncMock,
            return_value="Sure, 3pm works!",
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert "Meeting" in result.response_text
    assert "Sarah" in result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
