"""Tests for general_chat skill."""

import importlib
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType


class _DummyConnectionPool:
    pass


def _load_general_chat_handler():
    if "psycopg_pool" not in sys.modules:
        psycopg_pool = types.ModuleType("psycopg_pool")
        psycopg_pool.ConnectionPool = _DummyConnectionPool
        sys.modules["psycopg_pool"] = psycopg_pool

    if "mem0" not in sys.modules:
        mem0 = types.ModuleType("mem0")

        class _DummyMemory:
            @classmethod
            def from_config(cls, config):
                return cls()

        mem0.Memory = _DummyMemory
        sys.modules["mem0"] = mem0
        sys.modules["mem0.vector_stores"] = types.ModuleType("mem0.vector_stores")
        pgvector = types.ModuleType("mem0.vector_stores.pgvector")
        pgvector.ConnectionPool = _DummyConnectionPool
        sys.modules["mem0.vector_stores.pgvector"] = pgvector

    return importlib.import_module("src.skills.general_chat.handler")


_HANDLER = _load_general_chat_handler()
GeneralChatSkill = _HANDLER.GeneralChatSkill
_affirmation_reply = _HANDLER._affirmation_reply
_detect_greeting_lang = _HANDLER._detect_greeting_lang
_is_affirmation = _HANDLER._is_affirmation
_is_greeting = _HANDLER._is_greeting
_time_greeting = _HANDLER._time_greeting


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


# --- Greeting fast-path tests ---


@pytest.mark.parametrize(
    "text",
    ["привет", "Привет!", "hi", "Hello", "здравствуйте", "хай", "прив", "ку", "Yo!"],
)
def test_is_greeting_positive(text):
    """Various greetings should be recognized."""
    assert _is_greeting(text)


@pytest.mark.parametrize(
    "text",
    ["привет как дела", "покажи расходы", "hello world", "кофе 150", ""],
)
def test_is_greeting_negative(text):
    """Non-greetings and multi-word messages should not be matched."""
    assert not _is_greeting(text)


def test_time_greeting_returns_string():
    """_time_greeting should return a non-empty string."""
    result = _time_greeting("America/New_York")
    assert isinstance(result, str)
    assert len(result) > 0


def test_time_greeting_invalid_tz_fallback():
    """Invalid timezone falls back to EST without error."""
    result = _time_greeting("Invalid/Timezone")
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_greeting_fast_path_no_llm(skill, ctx):
    """Simple greeting returns immediate response without calling LLM."""
    result = await skill.execute(_msg("привет"), ctx, {})

    # Should contain a greeting phrase
    assert any(
        word in result.response_text.lower()
        for word in ["привет", "утро", "день", "вечер", "спишь", "слушаю"]
    )


@pytest.mark.asyncio
async def test_greeting_fast_path_with_exclamation(skill, ctx):
    """Greeting with punctuation still hits fast-path."""
    result = await skill.execute(_msg("Привет!"), ctx, {})
    assert any(
        word in result.response_text.lower()
        for word in ["привет", "утро", "день", "вечер", "спишь", "слушаю"]
    )


# --- LLM path tests (non-greeting messages) ---


@pytest.mark.asyncio
async def test_general_chat_uses_own_prompt_even_with_assembled_context(skill, ctx):
    """Assembled system prompt must not override GeneralChat rules."""
    assembled = MagicMock()
    assembled.system_prompt = "Ты агент онбординга, задавай вопросы анкеты."
    assembled.messages = [
        {"role": "system", "content": "onboarding system"},
        {"role": "user", "content": "расскажи анекдот"},
    ]

    mock_generate = AsyncMock(return_value="Вот анекдот...")

    with (
        patch(
            "src.core.memory.sliding_window.count_recent_intents",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("src.skills.general_chat.handler.generate_text", mock_generate),
    ):
        result = await skill.execute(
            _msg("расскажи анекдот"), ctx, {"_assembled": assembled}
        )

    assert result.response_text == "Вот анекдот..."
    call_args = mock_generate.call_args.args
    sent_system_prompt = call_args[1]
    assert "personal AI assistant" in sent_system_prompt
    assert "онбординга, задавай вопросы анкеты" not in sent_system_prompt


@pytest.mark.asyncio
async def test_general_chat_suppresses_suggestions_after_recent_chats(skill, ctx):
    """When recent general_chat count >= 3, suggestion dosing should be suppressed."""
    mock_generate = AsyncMock(return_value="Вот совет...")

    with (
        patch(
            "src.core.memory.sliding_window.count_recent_intents",
            new_callable=AsyncMock,
            return_value=3,
        ),
        patch("src.skills.general_chat.handler.generate_text", mock_generate),
    ):
        await skill.execute(_msg("как провести переговоры?"), ctx, {})

    sent_system_prompt = mock_generate.call_args.args[1]
    assert "do NOT suggest features" in sent_system_prompt


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


# --- Language-aware greeting tests ---


def test_detect_greeting_lang_russian():
    """Russian greeting words should detect 'ru'."""
    assert _detect_greeting_lang("привет", "en") == "ru"
    assert _detect_greeting_lang("Здравствуйте!", "en") == "ru"


def test_detect_greeting_lang_spanish():
    """Spanish greeting words should detect 'es'."""
    assert _detect_greeting_lang("hola", "en") == "es"
    assert _detect_greeting_lang("ола", "ru") == "es"


def test_detect_greeting_lang_english():
    """English greetings with English context should detect 'en'."""
    assert _detect_greeting_lang("hi", "en") == "en"
    assert _detect_greeting_lang("hello", None) == "en"


def test_detect_greeting_lang_english_word_russian_context():
    """English greeting word but Russian context → 'ru'."""
    assert _detect_greeting_lang("hi", "ru") == "ru"
    assert _detect_greeting_lang("hey", "ru-RU") == "ru"


def test_time_greeting_english():
    """English greeting should return English text."""
    result = _time_greeting("America/New_York", "en")
    assert any(w in result.lower() for w in ["morning", "hi", "hey", "evening", "sleep"])


def test_time_greeting_russian():
    """Russian greeting should return Russian text."""
    result = _time_greeting("Europe/Moscow", "ru")
    assert any(
        w in result.lower()
        for w in ["привет", "утро", "день", "вечер", "спишь", "слушаю", "помочь"]
    )


@pytest.mark.asyncio
async def test_english_greeting_returns_english(skill):
    """'hi' from English user returns English greeting."""
    ctx_en = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type="household",
        categories=[],
        merchant_mappings=[],
    )
    result = await skill.execute(_msg("hi"), ctx_en, {})
    # Should NOT contain Russian
    assert not any(
        word in result.response_text
        for word in ["Привет", "Добрый", "Слушаю", "Утро"]
    )
    # Should contain English
    assert any(
        word in result.response_text
        for word in ["Hi", "Hey", "Good", "Morning", "help", "need", "sleep"]
    )


# --- Affirmation fast-path tests ---


@pytest.mark.parametrize(
    "text",
    ["да", "ок", "ok", "yes", "готов", "спасибо", "thanks", "👍", "👌", "🙌", "круто", "норм"],
)
def test_is_affirmation_positive(text):
    """Various affirmations should be recognized."""
    assert _is_affirmation(text)


@pytest.mark.parametrize(
    "text",
    ["да, конечно, но мне нужна помощь", "расскажи подробнее", "кофе 150", ""],
)
def test_is_affirmation_negative(text):
    """Multi-word messages and non-affirmations should not match."""
    assert not _is_affirmation(text)


def test_affirmation_reply_russian():
    reply = _affirmation_reply("да", "ru")
    assert isinstance(reply, str)
    assert len(reply) > 0


def test_affirmation_reply_thanks():
    reply = _affirmation_reply("спасибо", "ru")
    assert any(w in reply for w in ["Пожалуйста", "Рад помочь", "Обращайся"])


def test_affirmation_reply_english_thanks():
    reply = _affirmation_reply("thanks", "en")
    assert any(w in reply for w in ["welcome", "Happy", "Anytime"])


@pytest.mark.asyncio
async def test_affirmation_fast_path_no_llm(skill, ctx):
    """Simple affirmation returns immediate response without calling LLM."""
    result = await skill.execute(_msg("👍"), ctx, {})
    assert len(result.response_text) < 50


@pytest.mark.asyncio
async def test_emoji_fast_path(skill, ctx):
    """Pure emoji message returns short acknowledgment."""
    result = await skill.execute(_msg("🙌"), ctx, {})
    assert result.response_text
    assert len(result.response_text) < 50


@pytest.mark.asyncio
async def test_short_input_uses_lower_max_tokens(skill, ctx):
    """Short non-greeting/non-affirmation input uses max_tokens=256."""
    mock_generate = AsyncMock(return_value="Short reply")

    with (
        patch(
            "src.core.memory.sliding_window.count_recent_intents",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("src.skills.general_chat.handler.generate_text", mock_generate),
    ):
        await skill.execute(_msg("что это?"), ctx, {})

    call_kwargs = mock_generate.call_args.kwargs
    assert call_kwargs.get("max_tokens", 1024) == 256


@pytest.mark.asyncio
async def test_bot_name_question_uses_identity_fast_path(skill, ctx):
    """Assistant name questions should return deterministic identity-backed answer."""
    with patch(
        "src.core.identity.get_core_identity",
        new_callable=AsyncMock,
        return_value={"bot_name": "Хюррем"},
    ):
        result = await skill.execute(_msg("как тебя зовут?"), ctx, {})

    assert "Хюррем" in result.response_text


@pytest.mark.asyncio
async def test_user_name_question_uses_identity_fast_path(skill, ctx):
    """User name questions should use saved core identity, not LLM guesswork."""
    with patch(
        "src.core.identity.get_core_identity",
        new_callable=AsyncMock,
        return_value={"name": "Манас"},
    ):
        result = await skill.execute(_msg("как меня зовут?"), ctx, {})

    assert "Манас" in result.response_text


@pytest.mark.asyncio
async def test_user_name_question_without_saved_name(skill, ctx):
    """When no name is stored, the bot should ask for a direct identity statement."""
    with patch(
        "src.core.identity.get_core_identity",
        new_callable=AsyncMock,
        return_value={},
    ):
        result = await skill.execute(_msg("как меня зовут?"), ctx, {})

    assert "Меня зовут" in result.response_text
