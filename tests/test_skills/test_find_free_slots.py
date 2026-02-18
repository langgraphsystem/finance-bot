"""Tests for find_free_slots skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.find_free_slots.handler import FindFreeSlotsSkill

MODULE = "src.skills.find_free_slots.handler"


@pytest.fixture
def skill():
    return FindFreeSlotsSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="when am I free tomorrow?",
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
async def test_find_free_slots_requires_google(skill, message, ctx):
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
async def test_find_free_slots_all_free(skill, message, ctx):
    """Returns all-day-free when no busy periods."""
    mock_google = AsyncMock()
    mock_google.get_free_busy = AsyncMock(return_value=[])

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

    assert "свободен" in result.response_text.lower()


@pytest.mark.asyncio
async def test_find_free_slots_with_busy(skill, message, ctx):
    """Computes free gaps between busy periods."""
    mock_google = AsyncMock()
    mock_google.get_free_busy = AsyncMock(return_value=[
        {
            "start": "2026-02-18T10:00:00+00:00",
            "end": "2026-02-18T11:00:00+00:00",
        },
        {
            "start": "2026-02-18T14:00:00+00:00",
            "end": "2026-02-18T15:00:00+00:00",
        },
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
    ):
        result = await skill.execute(message, ctx, {})

    assert (
        "Свободное время" in result.response_text
        or "свободен" in result.response_text.lower()
    )


def test_system_prompt_static(skill, ctx):
    """System prompt is a static string."""
    prompt = skill.get_system_prompt(ctx)
    assert "free" in prompt.lower() or "Calendar" in prompt
