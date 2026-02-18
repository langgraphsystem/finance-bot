"""Tests for read_inbox skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.read_inbox.handler import (
    ReadInboxSkill,
    _build_gmail_query,
    _detect_detail_request,
)

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
    """Summarizes real email data and caches results."""
    mock_google = AsyncMock()
    mock_google.list_messages = AsyncMock(
        return_value=[
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
        ]
    )

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()

    summary = "1. Sarah — Project deadline"
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
        patch(f"{MODULE}._summarize_with_llm", new_callable=AsyncMock, return_value=summary),
        patch(f"{MODULE}.redis", mock_redis),
    ):
        result = await skill.execute(message, ctx, {})

    assert "Sarah" in result.response_text
    # Verify inbox was cached
    mock_redis.set.assert_called_once()


def test_build_gmail_query_unread():
    """Default query for generic inbox check is unread."""
    assert _build_gmail_query("check my email") == "is:unread"


def test_build_gmail_query_sent():
    """Detects sent mail requests."""
    assert "in:sent" in _build_gmail_query("кому я сегодня отправил письмо?")
    assert "in:sent" in _build_gmail_query("my sent emails today")


def test_build_gmail_query_today():
    """Adds date filter for today."""
    q = _build_gmail_query("какие письма были сегодня?")
    assert "newer_than:1d" in q


def test_build_gmail_query_sent_today():
    """Sent + today combo."""
    q = _build_gmail_query("что я отправил сегодня")
    assert "in:sent" in q
    assert "newer_than:1d" in q


def test_detect_detail_request():
    """Detects numbered email references."""
    assert _detect_detail_request("о чем 1 письмо") == 1
    assert _detect_detail_request("подробнее о 3") == 3
    assert _detect_detail_request("расскажи о 2 письме") == 2
    assert _detect_detail_request("#2") == 2
    assert _detect_detail_request("check my email") is None
    assert _detect_detail_request("") is None


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
