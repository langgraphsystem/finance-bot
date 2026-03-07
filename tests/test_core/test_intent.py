"""Tests for intent detection with Instructor structured output."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.core.schemas.intent import IntentData, IntentDetectionResult

_TEST_SYSTEM_PROMPT = "test system prompt"

# ---------------------------------------------------------------------------
# Schema-level tests
# ---------------------------------------------------------------------------


def test_intent_detection_result_full():
    """IntentDetectionResult with all fields populated."""
    result = IntentDetectionResult(
        intent="add_expense",
        confidence=0.95,
        data=IntentData(
            amount=Decimal("50"),
            merchant="Shell",
            category="Дизель",
            scope="business",
        ),
        response="Записал расход 50 на дизель",
    )
    assert result.intent == "add_expense"
    assert result.confidence == 0.95
    assert result.data.amount == Decimal("50")
    assert result.data.merchant == "Shell"


def test_intent_detection_result_minimal():
    """IntentDetectionResult with only required fields."""
    result = IntentDetectionResult(intent="general_chat", confidence=0.8)
    assert result.intent == "general_chat"
    assert result.data is None
    assert result.response is None


def test_intent_detection_result_rejects_bad_confidence():
    """Confidence must be a valid float; random strings should fail."""
    with pytest.raises(ValidationError):
        IntentDetectionResult(intent="add_expense", confidence="not_a_number")


# ---------------------------------------------------------------------------
# _detect_with_claude – Instructor integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_with_claude_returns_validated_model():
    """Instructor returns a validated IntentDetectionResult directly."""
    expected = IntentDetectionResult(
        intent="add_expense",
        confidence=0.92,
        data=IntentData(amount=Decimal("50"), category="Дизель"),
        response="Записал расход",
    )

    mock_messages = MagicMock()
    mock_messages.create = AsyncMock(return_value=expected)
    mock_client = MagicMock()
    mock_client.messages = mock_messages

    with patch("src.core.intent.get_instructor_anthropic", return_value=mock_client):
        from src.core.intent import _detect_with_claude

        result = await _detect_with_claude(_TEST_SYSTEM_PROMPT, "Сообщение: заправился на 50", "ru")

    assert isinstance(result, IntentDetectionResult)
    assert result.intent == "add_expense"
    assert result.confidence == 0.92
    assert result.data.amount == Decimal("50")

    # Verify Instructor-specific kwargs were passed
    call_kwargs = mock_messages.create.call_args.kwargs
    assert call_kwargs["response_model"] is IntentDetectionResult
    assert call_kwargs["max_retries"] == 2


@pytest.mark.asyncio
async def test_detect_with_claude_instructor_retry_on_validation_error():
    """Simulate Instructor retry: first call raises ValidationError, second succeeds.

    In real Instructor flow, retry is handled internally. Here we verify that if
    the first attempt raises and Instructor retries, the second valid response
    is returned.
    """
    valid_result = IntentDetectionResult(
        intent="add_income",
        confidence=0.88,
        response="Записал доход",
    )

    mock_messages = MagicMock()
    # First call raises, second call succeeds (simulates Instructor internal retry)
    mock_messages.create = AsyncMock(
        side_effect=[ValidationError.from_exception_data("test", []), valid_result],
    )
    mock_client = MagicMock()
    mock_client.messages = mock_messages

    with patch("src.core.intent.get_instructor_anthropic", return_value=mock_client):
        from src.core.intent import _detect_with_claude

        # First call raises — the caller (detect_intent) would catch this
        with pytest.raises(ValidationError):
            await _detect_with_claude(_TEST_SYSTEM_PROMPT, "Сообщение: получил зарплату", "ru")

        # Second call succeeds (simulates retry succeeding)
        result = await _detect_with_claude(_TEST_SYSTEM_PROMPT, "Сообщение: получил зарплату", "ru")
        assert result.intent == "add_income"


# ---------------------------------------------------------------------------
# detect_intent – fallback chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_intent_gemini_success():
    """When Gemini succeeds, Claude is not called."""
    expected = IntentDetectionResult(intent="add_expense", confidence=0.95, response="OK")

    with (
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_gemini,
        patch(
            "src.core.intent._detect_with_claude",
            new_callable=AsyncMock,
        ) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("заправился на 50")

    assert result.intent == "add_expense"
    mock_gemini.assert_awaited_once()
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_intent_falls_back_to_claude():
    """When Gemini fails, Claude is called as fallback."""
    expected = IntentDetectionResult(intent="add_expense", confidence=0.90, response="OK")

    with (
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Gemini down"),
        ),
        patch(
            "src.core.intent._detect_with_claude",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("заправился на 50")

    assert result.intent == "add_expense"
    mock_claude.assert_awaited_once()


@pytest.mark.asyncio
async def test_detect_intent_both_fail_returns_default():
    """When both Gemini and Claude fail, a safe default is returned."""
    with (
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ),
        patch(
            "src.core.intent._detect_with_claude",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ),
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("что-то непонятное")

    assert result.intent == "general_chat"
    assert result.confidence == 0.5


@pytest.mark.asyncio
async def test_detect_intent_fast_path_delete_drink_specific_entry():
    """Delete drink-like commands should route to delete_data before LLM call."""
    with (
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
        ) as mock_gemini,
        patch(
            "src.core.intent._detect_with_claude",
            new_callable=AsyncMock,
        ) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("удалить Напиток вода (250ml)")

    assert result.intent == "delete_data"
    assert result.data is not None
    assert result.data.delete_scope == "drinks"
    assert result.data.period == "today"
    mock_gemini.assert_not_awaited()
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_intent_fast_path_set_user_rule_for_explicit_name():
    """'Запомни: меня зовут ...' should bypass LLM and route to set_user_rule."""
    with (
        patch("src.core.intent._detect_with_gemini", new_callable=AsyncMock) as mock_gemini,
        patch("src.core.intent._detect_with_claude", new_callable=AsyncMock) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("Запомни: меня зовут Манас")

    assert result.intent == "set_user_rule"
    assert result.data is not None
    assert result.data.rule_text == "меня зовут Манас"
    mock_gemini.assert_not_awaited()
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_intent_fast_path_name_reply_from_recent_context():
    """A bare name after the bot asks for it should be normalized into set_user_rule."""
    with (
        patch("src.core.intent._detect_with_gemini", new_callable=AsyncMock) as mock_gemini,
        patch("src.core.intent._detect_with_claude", new_callable=AsyncMock) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent(
            "Манас",
            recent_context="Bot: Скажи, пожалуйста: как тебя зовут?",
        )

    assert result.intent == "set_user_rule"
    assert result.data is not None
    assert result.data.rule_text == "меня зовут Манас"
    mock_gemini.assert_not_awaited()
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_intent_fast_path_forget_rule_routes_to_memory_forget():
    with (
        patch("src.core.intent._detect_with_gemini", new_callable=AsyncMock) as mock_gemini,
        patch("src.core.intent._detect_with_claude", new_callable=AsyncMock) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("забудь Мындан кийин сенин атын Хюррем болот")

    assert result.intent == "memory_forget"
    assert result.data is not None
    assert result.data.memory_query == "забудь Мындан кийин сенин атын Хюррем болот"
    mock_gemini.assert_not_awaited()
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_intent_fast_path_forget_name_does_not_route_to_set_user_rule():
    with (
        patch("src.core.intent._detect_with_gemini", new_callable=AsyncMock) as mock_gemini,
        patch("src.core.intent._detect_with_claude", new_callable=AsyncMock) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("забудь как тебя зовут")

    assert result.intent == "memory_forget"
    assert result.data is not None
    assert result.data.memory_query == "забудь как тебя зовут"
    mock_gemini.assert_not_awaited()
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_intent_question_with_marker_not_set_user_rule():
    """Questions containing name markers must NOT route to set_user_rule."""
    questions = [
        "как тебя зовут?",
        "как твое имя?",
        "а как твое имя?",
        "ты знаешь мое имя?",
        "какое у тебя имя?",
        "меня зовут как?",
        "как меня зовут?",
        "what is your name?",
        "what's my name?",
        "who are you?",
    ]
    with (
        patch("src.core.intent._detect_with_gemini", new_callable=AsyncMock) as mock_gemini,
        patch("src.core.intent._detect_with_claude", new_callable=AsyncMock),
    ):
        mock_gemini.return_value = IntentDetectionResult(
            intent="general_chat", confidence=0.9, intent_type="chat",
        )
        from src.core.intent import detect_intent

        for q in questions:
            result = await detect_intent(q)
            assert result.intent != "set_user_rule", f"'{q}' wrongly routed to set_user_rule"


@pytest.mark.asyncio
async def test_detect_intent_fast_path_relative_reminder_uses_tz_aware_deadline():
    """Relative reminder should bypass LLM and return timezone-aware ISO deadline."""
    with (
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
        ) as mock_gemini,
        patch(
            "src.core.intent._detect_with_claude",
            new_callable=AsyncMock,
        ) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("Remind me in 2 minutes that I need to turn on the oven.")

    assert result.intent == "set_reminder"
    assert result.data is not None
    assert result.data.task_title == "that I need to turn on the oven."
    assert result.data.task_deadline is not None
    deadline = datetime.fromisoformat(result.data.task_deadline)
    assert deadline.tzinfo is not None
    assert 60 <= (deadline - datetime.now(UTC)).total_seconds() <= 180
    mock_gemini.assert_not_awaited()
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_intent_fast_path_delete_with_period():
    """Explicit period in delete command should be propagated."""
    with (
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
        ) as mock_gemini,
        patch(
            "src.core.intent._detect_with_claude",
            new_callable=AsyncMock,
        ) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("удали напитки за неделю")

    assert result.intent == "delete_data"
    assert result.data is not None
    assert result.data.delete_scope == "drinks"
    assert result.data.period == "week"
    mock_gemini.assert_not_awaited()
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_intent_undo_last_phrase_not_overridden_by_fast_path():
    """Legacy 'delete last transaction' must stay on normal LLM routing."""
    expected = IntentDetectionResult(intent="undo_last", confidence=0.93, response="OK")

    with (
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_gemini,
        patch(
            "src.core.intent._detect_with_claude",
            new_callable=AsyncMock,
        ) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("удали последнюю транзакцию")

    assert result.intent == "undo_last"
    mock_gemini.assert_awaited_once()
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_intent_fast_path_explicit_memory_save_without_rules():
    with (
        patch("src.core.intent._detect_with_gemini", new_callable=AsyncMock) as mock_gemini,
        patch("src.core.intent._detect_with_claude", new_callable=AsyncMock) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("Запомни: я люблю зелёный чай")

    assert result.intent == "memory_save"
    assert result.data is not None
    assert result.data.memory_query == "я люблю зелёный чай"
    mock_gemini.assert_not_awaited()
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_intent_fast_path_name_question_routes_to_general_chat_without_llm():
    with (
        patch("src.core.intent._detect_with_gemini", new_callable=AsyncMock) as mock_gemini,
        patch("src.core.intent._detect_with_claude", new_callable=AsyncMock) as mock_claude,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent("как тебя зовут?")

    assert result.intent == "general_chat"
    mock_gemini.assert_not_awaited()
    mock_claude.assert_not_awaited()
