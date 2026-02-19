"""Tests for evening recap skill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.skills.evening_recap.handler import EveningRecapSkill


def test_skill_attributes():
    skill = EveningRecapSkill()
    assert skill.name == "evening_recap"
    assert skill.intents == ["evening_recap"]
    assert skill.model == "claude-sonnet-4-6"


def test_get_system_prompt(sample_context):
    skill = EveningRecapSkill()
    prompt = skill.get_system_prompt(sample_context)
    lower = prompt.lower()
    assert "evening recap" in lower or "wrap-up" in lower or "recap" in lower


@patch("src.skills.evening_recap.handler.async_session")
@patch("src.skills.evening_recap.handler.anthropic_client")
async def test_execute_no_data(mock_client, mock_session, sample_context, text_message):
    """When no data is collected, return a friendly fallback."""
    # Mock DB returning empty results
    mock_sess = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.one_or_none.return_value = None
    mock_sess.execute = AsyncMock(return_value=mock_result)
    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

    skill = EveningRecapSkill()
    result = await skill.execute(text_message, sample_context, {})
    assert result.response_text  # should have some response
