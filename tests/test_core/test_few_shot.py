"""Tests for dynamic few-shot retrieval module."""

import uuid
from unittest.mock import AsyncMock, patch

from src.core.few_shot import (
    format_few_shot_block,
    retrieve_few_shot_examples,
    save_few_shot_example,
)

# --- format_few_shot_block tests ---


def test_format_empty_examples():
    """Empty examples return empty string (zero-shot preserved)."""
    assert format_few_shot_block([]) == ""


def test_format_single_example():
    """Single example formatted as XML block."""
    examples = [
        {
            "user_message": "100 кофе",
            "intent": "add_expense",
            "intent_data": {"amount": 100, "category": "Продукты"},
            "score": 0.92,
        }
    ]
    result = format_few_shot_block(examples)
    assert "<few_shot_examples>" in result
    assert "</few_shot_examples>" in result
    assert "<example_1>" in result
    assert "User: 100 кофе" in result
    assert "Intent: add_expense" in result
    assert "'amount': 100" in result


def test_format_multiple_examples():
    """Multiple examples are numbered correctly."""
    examples = [
        {"user_message": "100 кофе", "intent": "add_expense", "intent_data": None, "score": 0.9},
        {"user_message": "мой бюджет", "intent": "query_stats", "intent_data": None, "score": 0.8},
    ]
    result = format_few_shot_block(examples)
    assert "<example_1>" in result
    assert "<example_2>" in result


def test_format_skips_null_intent_data():
    """Null intent_data doesn't produce Data line."""
    examples = [
        {"user_message": "привет", "intent": "general_chat", "intent_data": None, "score": 0.7},
    ]
    result = format_few_shot_block(examples)
    assert "Data:" not in result


def test_format_skips_empty_intent_data():
    """Intent data with all nulls doesn't produce Data line."""
    examples = [
        {
            "user_message": "привет",
            "intent": "general_chat",
            "intent_data": {"amount": None, "category": None},
            "score": 0.7,
        },
    ]
    result = format_few_shot_block(examples)
    assert "Data:" not in result


# --- retrieve_few_shot_examples tests ---


async def test_retrieve_empty_query():
    """Empty query returns empty list without calling embedding API."""
    result = await retrieve_few_shot_examples("", str(uuid.uuid4()))
    assert result == []


async def test_retrieve_embedding_failure():
    """Embedding failure returns empty list gracefully."""
    with patch(
        "src.core.few_shot.get_embedding",
        new_callable=AsyncMock,
        side_effect=RuntimeError("OpenAI down"),
    ):
        result = await retrieve_few_shot_examples("кофе", str(uuid.uuid4()))
    assert result == []


async def test_retrieve_db_failure():
    """Database failure returns empty list gracefully."""
    with (
        patch(
            "src.core.few_shot.get_embedding",
            new_callable=AsyncMock,
            return_value=[0.1] * 1536,
        ),
        patch(
            "src.core.few_shot._search_by_embedding",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB down"),
        ),
    ):
        result = await retrieve_few_shot_examples("кофе", str(uuid.uuid4()))
    assert result == []


async def test_retrieve_success():
    """Successful retrieval returns formatted examples."""
    mock_results = [
        {
            "user_message": "100 бензин",
            "intent": "add_expense",
            "intent_data": {"amount": 100},
            "score": 0.88,
        },
    ]

    with (
        patch(
            "src.core.few_shot.get_embedding",
            new_callable=AsyncMock,
            return_value=[0.1] * 1536,
        ),
        patch(
            "src.core.few_shot._search_by_embedding",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
    ):
        result = await retrieve_few_shot_examples("150 дизель", str(uuid.uuid4()))

    assert len(result) == 1
    assert result[0]["intent"] == "add_expense"
    assert result[0]["score"] == 0.88


# --- save_few_shot_example tests ---


async def test_save_embedding_failure():
    """Save with embedding failure returns None."""
    with patch(
        "src.core.few_shot.get_embedding",
        new_callable=AsyncMock,
        side_effect=RuntimeError("OpenAI down"),
    ):
        result = await save_few_shot_example(
            family_id=str(uuid.uuid4()),
            user_message="test",
            detected_intent="add_expense",
        )
    assert result is None


async def test_save_db_failure():
    """Save with DB failure returns None."""
    with (
        patch(
            "src.core.few_shot.get_embedding",
            new_callable=AsyncMock,
            return_value=[0.1] * 1536,
        ),
        patch("src.core.few_shot.async_session") as mock_session_maker,
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
        mock_session.__aexit__ = AsyncMock()
        mock_session_maker.return_value = mock_session

        result = await save_few_shot_example(
            family_id=str(uuid.uuid4()),
            user_message="test",
            detected_intent="add_expense",
        )
    assert result is None


# --- Integration with detect_intent ---


async def test_detect_intent_with_few_shot():
    """detect_intent injects few-shot examples when family_id provided."""
    from src.core.schemas.intent import IntentDetectionResult

    mock_examples = [
        {
            "user_message": "100 бензин",
            "intent": "add_expense",
            "intent_data": {"amount": 100},
            "score": 0.9,
        },
    ]

    mock_result = IntentDetectionResult(
        intent="add_expense",
        confidence=0.95,
    )

    with (
        patch(
            "src.core.intent.retrieve_few_shot_examples",
            new_callable=AsyncMock,
            return_value=mock_examples,
        ) as mock_retrieve,
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_gemini,
    ):
        from src.core.intent import detect_intent

        result = await detect_intent(
            text="150 дизель",
            family_id=str(uuid.uuid4()),
        )

    mock_retrieve.assert_called_once()
    system_prompt_arg = mock_gemini.call_args[0][0]
    assert "<few_shot_examples>" in system_prompt_arg
    assert "100 бензин" in system_prompt_arg
    assert result.intent == "add_expense"


async def test_detect_intent_without_family_id():
    """detect_intent skips few-shot when no family_id provided."""
    from src.core.schemas.intent import IntentDetectionResult

    mock_result = IntentDetectionResult(
        intent="general_chat",
        confidence=0.8,
    )

    with (
        patch(
            "src.core.intent.retrieve_few_shot_examples",
            new_callable=AsyncMock,
        ) as mock_retrieve,
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
    ):
        from src.core.intent import detect_intent

        await detect_intent(text="привет")

    mock_retrieve.assert_not_called()


async def test_detect_intent_few_shot_failure_graceful():
    """detect_intent continues normally if few-shot retrieval fails."""
    from src.core.schemas.intent import IntentDetectionResult

    mock_result = IntentDetectionResult(
        intent="add_expense",
        confidence=0.9,
    )

    with (
        patch(
            "src.core.intent.retrieve_few_shot_examples",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB down"),
        ),
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
    ):
        from src.core.intent import detect_intent

        result = await detect_intent(
            text="100 кофе",
            family_id=str(uuid.uuid4()),
        )

    assert result.intent == "add_expense"


async def test_detect_intent_no_examples_found():
    """detect_intent with empty few-shot results doesn't modify prompt."""
    from src.core.schemas.intent import IntentDetectionResult

    mock_result = IntentDetectionResult(intent="general_chat", confidence=0.8)

    with (
        patch(
            "src.core.intent.retrieve_few_shot_examples",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_gemini,
    ):
        from src.core.intent import detect_intent

        await detect_intent(text="привет", family_id=str(uuid.uuid4()))

    system_prompt_arg = mock_gemini.call_args[0][0]
    assert "<few_shot_examples>" not in system_prompt_arg
