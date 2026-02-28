"""Tests for smart suggestions — contextual next-action buttons."""

from unittest.mock import AsyncMock, patch

from src.core.suggestions import (
    SUGGESTION_COOLDOWN,
    SUGGESTION_MAP,
    get_suggestions,
)


def test_suggestion_map_has_common_intents():
    assert "add_expense" in SUGGESTION_MAP
    assert "add_income" in SUGGESTION_MAP
    assert "create_task" in SUGGESTION_MAP
    assert "track_food" in SUGGESTION_MAP


def test_suggestion_map_values_have_text_and_callback():
    for intent, suggestions in SUGGESTION_MAP.items():
        for s in suggestions:
            assert "text" in s, f"Missing 'text' in {intent} suggestion"
            assert "callback" in s, f"Missing 'callback' in {intent} suggestion"
            assert s["callback"].startswith("suggest:"), "Callback must start with suggest:"


def test_cooldown_value():
    assert SUGGESTION_COOLDOWN == 300


@patch("src.core.suggestions.redis")
async def test_get_suggestions_returns_suggestions(mock_redis):
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()
    result = await get_suggestions("add_expense", "user1")
    assert result is not None
    assert len(result) >= 1
    mock_redis.set.assert_called_once()


@patch("src.core.suggestions.redis")
async def test_get_suggestions_cooldown_active(mock_redis):
    mock_redis.get = AsyncMock(return_value="1")
    result = await get_suggestions("add_expense", "user1")
    assert result is None


@patch("src.core.suggestions.redis")
async def test_get_suggestions_unknown_intent(mock_redis):
    mock_redis.get = AsyncMock(return_value=None)
    result = await get_suggestions("unknown_intent_xyz", "user1")
    assert result is None


@patch("src.core.suggestions.redis")
async def test_get_suggestions_no_override_existing(mock_redis):
    """No suggestions for intents not in the map."""
    mock_redis.get = AsyncMock(return_value=None)
    result = await get_suggestions("general_chat", "user1")
    assert result is None
