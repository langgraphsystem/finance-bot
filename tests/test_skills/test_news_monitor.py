"""Tests for news_monitor skill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.news_monitor.handler import NewsMonitorSkill


def test_news_monitor_skill_attributes():
    skill = NewsMonitorSkill()
    assert skill.name == "news_monitor"
    assert "news_monitor" in skill.intents
    assert skill.model == "claude-haiku-4-5"


def test_news_monitor_system_prompt(sample_context):
    skill = NewsMonitorSkill()
    prompt = skill.get_system_prompt(sample_context)
    assert "news" in prompt.lower() or "monitor" in prompt.lower()


async def test_news_monitor_empty_message(sample_context):
    skill = NewsMonitorSkill()
    msg = IncomingMessage(id="1", user_id="u1", chat_id="c1", type=MessageType.text, text="")
    result = await skill.execute(msg, sample_context, {})
    assert "topic" in result.response_text.lower()


async def test_news_monitor_creates_monitor(sample_context):
    skill = NewsMonitorSkill()
    msg = IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        type=MessageType.text,
        text="plumbing industry news",
    )

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    with patch("src.skills.news_monitor.handler.async_session", return_value=mock_session):
        result = await skill.execute(msg, sample_context, {})

    assert "plumbing industry news" in result.response_text
    mock_session.add.assert_called_once()

    # Verify the monitor was created with correct config
    added_monitor = mock_session.add.call_args[0][0]
    assert added_monitor.config["topic"] == "plumbing industry news"
    assert added_monitor.check_interval_minutes == 720
    assert added_monitor.is_active is True
