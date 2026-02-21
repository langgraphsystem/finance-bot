"""Tests for general_chat skill."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.general_chat.handler import GeneralChatSkill


@pytest.fixture
def skill():
    return GeneralChatSkill()


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="household",
        categories=[],
        merchant_mappings=[],
    )


def _msg(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=text,
    )


def test_model_is_sonnet(skill):
    """general_chat should use Claude Sonnet 4.6."""
    assert skill.model == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_general_chat_uses_own_prompt_even_with_assembled_context(skill, ctx):
    """Assembled system prompt must not override GeneralChat rules."""
    assembled = MagicMock()
    assembled.system_prompt = "Ты агент онбординга, задавай вопросы анкеты."
    assembled.messages = [
        {"role": "system", "content": "onboarding system"},
        {"role": "user", "content": "привет"},
    ]

    mock_generate = AsyncMock(return_value="Привет! Чем могу помочь?")

    with (
        patch(
            "src.core.memory.sliding_window.count_recent_intents",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("src.skills.general_chat.handler.generate_text", mock_generate),
    ):
        result = await skill.execute(_msg("привет"), ctx, {"_assembled": assembled})

    assert result.response_text == "Привет! Чем могу помочь?"
    call_args = mock_generate.call_args.args
    sent_system_prompt = call_args[1]
    assert "персональный AI-ассистент" in sent_system_prompt
    assert "онбординга, задавай вопросы анкеты" not in sent_system_prompt


@pytest.mark.asyncio
async def test_general_chat_suppresses_suggestions_after_recent_chats(skill, ctx):
    """When recent general_chat count >= 3, suggestion dosing should be suppressed."""
    mock_generate = AsyncMock(return_value="Привет!")

    with (
        patch(
            "src.core.memory.sliding_window.count_recent_intents",
            new_callable=AsyncMock,
            return_value=3,
        ),
        patch("src.skills.general_chat.handler.generate_text", mock_generate),
    ):
        await skill.execute(_msg("привет"), ctx, {})

    sent_system_prompt = mock_generate.call_args.args[1]
    assert "НЕ добавляй подсказки" in sent_system_prompt


@pytest.mark.asyncio
async def test_general_chat_calls_sonnet_model(skill, ctx):
    """generate_text should be called with claude-sonnet-4-6."""
    mock_generate = AsyncMock(return_value="Ответ на вопрос")

    with (
        patch(
            "src.core.memory.sliding_window.count_recent_intents",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("src.skills.general_chat.handler.generate_text", mock_generate),
    ):
        result = await skill.execute(
            _msg("Как провести переговоры с трудным клиентом?"), ctx, {}
        )

    assert result.response_text == "Ответ на вопрос"
    assert mock_generate.call_args.args[0] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_general_chat_logs_original_intent(skill, ctx):
    """When redirected from low-confidence intent, original_intent is logged."""
    mock_generate = AsyncMock(return_value="Ответ")

    with (
        patch(
            "src.core.memory.sliding_window.count_recent_intents",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("src.skills.general_chat.handler.generate_text", mock_generate),
        patch("src.skills.general_chat.handler.logger") as mock_logger,
    ):
        await skill.execute(
            _msg("Что подарить жене?"),
            ctx,
            {"original_intent": "create_task", "confidence": 0.3},
        )

    mock_logger.info.assert_any_call(
        "general_chat fallback from intent=%s conf=%.2f",
        "create_task",
        0.3,
    )

