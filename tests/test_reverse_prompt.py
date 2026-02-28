"""Tests for reverse prompting — plan proposal before complex execution."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.core.reverse_prompt import (
    SKIP_REVERSE_INTENTS,
    delete_pending_plan,
    get_pending_plan,
    should_reverse_prompt,
    store_pending_plan,
)

# --- should_reverse_prompt tests ---


def test_short_message_no_trigger():
    assert should_reverse_prompt("100 кофе", "add_expense", 0.95) is False


def test_skip_intent():
    long_text = "a " * 60  # >50 words
    assert should_reverse_prompt(long_text, "add_expense", 0.95) is False
    assert should_reverse_prompt(long_text, "track_food", 0.95) is False
    assert should_reverse_prompt(long_text, "general_chat", 0.95) is False


def test_long_message_triggers():
    words = " ".join(f"word{i}" for i in range(55))  # 55 words
    assert should_reverse_prompt(words, "write_post", 0.95) is True


def test_multi_step_keyword_triggers():
    assert should_reverse_prompt(
        "Send email to John and then create a calendar event", "send_email", 0.9
    ) is True


def test_multi_step_russian():
    assert should_reverse_prompt(
        "Отправь письмо а потом создай задачу", "send_email", 0.9
    ) is True


def test_medium_confidence_with_length():
    text = " ".join(f"word{i}" for i in range(20))  # 20 words, conf 0.7
    assert should_reverse_prompt(text, "write_post", 0.7) is True


def test_medium_confidence_short_no_trigger():
    assert should_reverse_prompt("write a post", "write_post", 0.7) is False


def test_high_confidence_short_no_trigger():
    assert should_reverse_prompt("draft an email", "draft_message", 0.95) is False


def test_bypass_keyword():
    text = "Просто сделай email to John and then create event"
    assert should_reverse_prompt(text, "send_email", 0.9) is False


def test_bypass_just_do_it():
    text = "just do it — send email and create event"
    assert should_reverse_prompt(text, "send_email", 0.9) is False


def test_empty_text():
    assert should_reverse_prompt("", "write_post", 0.9) is False


def test_all_skip_intents_are_strings():
    for intent in SKIP_REVERSE_INTENTS:
        assert isinstance(intent, str)


# --- Redis store/get/delete tests ---


@pytest.fixture
def mock_redis():
    with patch("src.core.reverse_prompt.redis") as mock:
        mock.set = AsyncMock()
        mock.get = AsyncMock(return_value=None)
        mock.delete = AsyncMock()
        yield mock


async def test_store_and_get_plan(mock_redis):
    payload = {
        "intent": "write_post",
        "original_text": "write a blog post about AI",
        "intent_data": {"topic": "AI"},
        "plan_text": "1. Research\n2. Draft\n3. Review",
    }
    mock_redis.get = AsyncMock(return_value=json.dumps(payload))

    await store_pending_plan(
        "user1", "write_post", "write a blog post about AI", {"topic": "AI"}, "1. Research"
    )
    mock_redis.set.assert_called_once()

    result = await get_pending_plan("user1")
    assert result["intent"] == "write_post"


async def test_get_pending_plan_empty(mock_redis):
    result = await get_pending_plan("user1")
    assert result is None


async def test_delete_pending_plan(mock_redis):
    await delete_pending_plan("user1")
    mock_redis.delete.assert_called_once_with("plan_pending:user1")


# --- generate_plan_proposal test ---


async def test_generate_plan_proposal():
    from dataclasses import dataclass

    @dataclass
    class _Ctx:
        language: str = "en"
        user_id: str = "u1"
        family_id: str = "f1"
        user_profile: dict = None

    with patch("src.core.llm.clients.generate_text", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "1. Step one\n2. Step two"
        from src.core.reverse_prompt import generate_plan_proposal

        result = await generate_plan_proposal("write post about AI", "write_post", _Ctx())
        assert "Step one" in result
        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args
        assert "planning" in call_kwargs.kwargs["system"].lower()
