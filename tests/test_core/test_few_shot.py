"""Tests for dynamic few-shot examples."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.core.few_shot import (
    format_few_shot_block,
    retrieve_few_shot_examples,
    save_few_shot_example,
)


def test_format_empty():
    assert format_few_shot_block([]) == ""


def test_format_single_example():
    examples = [
        {
            "user_message": "100 кофе",
            "detected_intent": "add_expense",
            "corrected_intent": None,
            "intent_data": {"amount": 100, "category": "Coffee"},
        }
    ]
    result = format_few_shot_block(examples)
    assert "<few_shot_examples>" in result
    assert "100 кофе" in result
    assert "add_expense" in result
    assert "<amount>100</amount>" in result


def test_format_multiple_examples():
    examples = [
        {
            "user_message": "напомни завтра",
            "detected_intent": "create_task",
            "corrected_intent": "set_reminder",
            "intent_data": None,
        },
        {
            "user_message": "что я ел?",
            "detected_intent": "life_search",
            "corrected_intent": None,
            "intent_data": {"life_event_type": "food"},
        },
    ]
    result = format_few_shot_block(examples)
    assert result.count("<example>") == 2
    assert "set_reminder" in result  # corrected intent used
    assert "life_search" in result


def test_format_null_intent_data():
    examples = [
        {
            "user_message": "test",
            "detected_intent": "general_chat",
            "corrected_intent": None,
            "intent_data": None,
        }
    ]
    result = format_few_shot_block(examples)
    assert "general_chat" in result


async def test_retrieve_empty_query():
    result = await retrieve_few_shot_examples("", "family-1")
    assert result == []


async def test_retrieve_embedding_failure():
    with patch(
        "src.core.few_shot.get_embedding",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await retrieve_few_shot_examples("test query", "family-1")
    assert result == []


async def test_retrieve_db_failure():
    with (
        patch(
            "src.core.few_shot.get_embedding",
            new_callable=AsyncMock,
            return_value=[0.1] * 1536,
        ),
        patch("src.core.db.async_session", side_effect=RuntimeError("DB down")),
    ):
        result = await retrieve_few_shot_examples("test query", "family-1")
    assert result == []


async def test_save_embedding_failure():
    with patch(
        "src.core.few_shot.get_embedding",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await save_few_shot_example("fam-1", "msg", "intent")
    assert result is None


async def test_retrieve_success():
    mock_row = MagicMock()
    mock_row.id = "ex-1"
    mock_row.user_message = "100 кофе"
    mock_row.detected_intent = "add_expense"
    mock_row.corrected_intent = None
    mock_row.intent_data = {"amount": 100}
    mock_row.similarity = 0.85

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with (
        patch(
            "src.core.few_shot.get_embedding",
            new_callable=AsyncMock,
            return_value=[0.1] * 1536,
        ),
        patch("src.core.db.async_session") as mock_ctx,
    ):
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await retrieve_few_shot_examples("100 чай", "fam-1")

    assert len(result) == 1
    assert result[0]["user_message"] == "100 кофе"
    assert result[0]["similarity"] == 0.85
