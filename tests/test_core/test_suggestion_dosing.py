"""Tests for suggestion dosing via sliding window."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_count_recent_intents():
    """count_recent_intents correctly filters by intent name."""
    messages = [
        {"role": "user", "content": "hi", "intent": "general_chat"},
        {"role": "assistant", "content": "hello", "intent": None},
        {"role": "user", "content": "yo", "intent": "general_chat"},
        {"role": "user", "content": "50 gas", "intent": "add_expense"},
        {"role": "user", "content": "thanks", "intent": "general_chat"},
    ]

    with patch(
        "src.core.memory.sliding_window.get_recent_messages",
        new_callable=AsyncMock,
        return_value=messages,
    ):
        from src.core.memory.sliding_window import (
            count_recent_intents,
        )

        count = await count_recent_intents("user1", "general_chat", last_n=6)

    assert count == 3


@pytest.mark.asyncio
async def test_count_recent_intents_none():
    """Returns 0 when intent is not found."""
    messages = [
        {"role": "user", "content": "50 gas", "intent": "add_expense"},
    ]

    with patch(
        "src.core.memory.sliding_window.get_recent_messages",
        new_callable=AsyncMock,
        return_value=messages,
    ):
        from src.core.memory.sliding_window import (
            count_recent_intents,
        )

        count = await count_recent_intents("user1", "general_chat", last_n=6)

    assert count == 0


def test_dosing_suppresses_after_threshold():
    """GeneralChatSkill suppresses suggestions when suppress=True."""
    from src.skills.general_chat.handler import GeneralChatSkill

    skill = GeneralChatSkill()
    prompt_suppressed = skill._get_dosing_prompt(suppress=True)

    assert "НЕ добавляй подсказки" in prompt_suppressed


def test_dosing_allows_when_under_threshold():
    """GeneralChatSkill keeps suggestions when suppress=False."""
    from src.skills.general_chat.handler import GeneralChatSkill

    skill = GeneralChatSkill()
    prompt_normal = skill._get_dosing_prompt(suppress=False)

    assert "мягко" in prompt_normal or "подсказать" in prompt_normal
