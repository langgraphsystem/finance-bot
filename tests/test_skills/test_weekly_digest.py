"""Tests for weekly digest skill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.skills.weekly_digest.handler import WeeklyDigestSkill


def test_skill_attributes():
    skill = WeeklyDigestSkill()
    assert skill.name == "weekly_digest"
    assert skill.intents == ["weekly_digest"]
    assert skill.model == "claude-sonnet-4-6"


def test_get_system_prompt(sample_context):
    skill = WeeklyDigestSkill()
    prompt = skill.get_system_prompt(sample_context)
    lower = prompt.lower()
    assert "weekly" in lower or "week" in lower
    assert "digest" in lower or "summary" in lower or "review" in lower


@patch("src.skills.weekly_digest.handler.async_session")
@patch("src.skills.weekly_digest.handler.generate_text", new_callable=AsyncMock)
async def test_execute_no_data(mock_gen, mock_session, sample_context, text_message):
    """When no data is collected, return a friendly onboarding message."""
    mock_sess = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.one_or_none.return_value = None
    mock_result.scalar.return_value = 0
    mock_result.all.return_value = []
    mock_sess.execute = AsyncMock(return_value=mock_result)
    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

    skill = WeeklyDigestSkill()
    # Patch internal collectors that use external modules
    skill._collect_life_events = AsyncMock(return_value="")
    skill._collect_upcoming_events = AsyncMock(return_value="")
    result = await skill.execute(text_message, sample_context, {})
    assert result.response_text
    text = result.response_text.lower()
    assert "not much" in text or "next sunday" in text


@patch("src.skills.weekly_digest.handler.async_session")
@patch("src.skills.weekly_digest.handler.generate_text", new_callable=AsyncMock)
async def test_execute_with_spending(mock_gen, mock_session, sample_context, text_message):
    """When spending data exists, synthesize via LLM."""
    mock_gen.return_value = "<b>Your week in review</b>\nSpent $500 on groceries."

    mock_sess = AsyncMock()

    # First call: spending total, second call: previous week, third+: other collectors
    call_count = 0

    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # Current week spending
            result.one_or_none.return_value = (500.00, 12)
        elif call_count == 2:
            # Previous week spending
            result.one_or_none.return_value = (450.00,)
        elif call_count == 3:
            # Spending by category
            result.all.return_value = [("Groceries", 300.0), ("Transport", 200.0)]
        else:
            # Other collectors return empty
            result.scalars.return_value.all.return_value = []
            result.scalar.return_value = 0
            result.one_or_none.return_value = None
            result.all.return_value = []
        return result

    mock_sess.execute = mock_execute
    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

    skill = WeeklyDigestSkill()
    result = await skill.execute(text_message, sample_context, {})
    assert result.response_text
    assert mock_gen.called


@patch("src.skills.weekly_digest.handler.async_session")
async def test_collect_spending_empty(mock_session, sample_context):
    """_collect_spending returns empty string when no transactions."""
    from datetime import date, timedelta

    mock_sess = AsyncMock()
    mock_result = MagicMock()
    mock_result.one_or_none.return_value = None
    mock_sess.execute = AsyncMock(return_value=mock_result)
    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

    skill = WeeklyDigestSkill()
    today = date.today()
    result = await skill._collect_spending(sample_context, today - timedelta(days=7), today)
    assert result == ""


@patch("src.skills.weekly_digest.handler.async_session")
async def test_collect_completed_tasks(mock_session, sample_context):
    """_collect_completed_tasks returns count string."""
    from datetime import date, timedelta

    mock_sess = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 5
    mock_sess.execute = AsyncMock(return_value=mock_result)
    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

    skill = WeeklyDigestSkill()
    today = date.today()
    result = await skill._collect_completed_tasks(
        sample_context, today - timedelta(days=7), today
    )
    assert "5" in result
    assert "completed" in result.lower()
