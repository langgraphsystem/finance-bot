"""Tests for the deepagents brief orchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrators.deep.domains.brief import BriefOrchestrator, brief_orchestrator
from src.skills.base import SkillResult


async def test_brief_morning_uses_subagents(sample_context, text_message):
    """Morning brief uses collector subagents."""
    text_message.text = "Morning brief"

    mock_agent = AsyncMock()
    mock_agent.ainvoke.return_value = {
        "messages": [MagicMock(content="<b>Good morning!</b>\nHere's your brief...")]
    }

    mock_plugin = MagicMock()
    mock_plugin.morning_brief_sections = ["schedule", "tasks", "money_summary"]

    with (
        patch(
            "src.orchestrators.deep.domains.brief.create_deep_agent",
            return_value=mock_agent,
        ) as mock_create,
        patch("src.orchestrators.deep.domains.brief.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.domains.brief.build_skill_tools", return_value=[]),
        patch("src.orchestrators.deep.domains.brief.plugin_loader") as mock_pl,
    ):
        mock_get_reg.return_value = MagicMock()
        mock_pl.load.return_value = mock_plugin

        result = await brief_orchestrator.invoke("morning_brief", text_message, sample_context, {})

    assert isinstance(result, SkillResult)
    assert "morning" in result.response_text.lower() or "Good" in result.response_text

    # Verify subagents were included
    call_kwargs = mock_create.call_args.kwargs
    assert "subagents" in call_kwargs
    subagent_names = [s["name"] for s in call_kwargs["subagents"]]
    assert "calendar_collector" in subagent_names
    assert "tasks_collector" in subagent_names


async def test_brief_evening_uses_recap_sections(sample_context, text_message):
    """Evening recap uses evening_recap_sections from plugin."""
    text_message.text = "Evening recap"

    mock_agent = AsyncMock()
    mock_agent.ainvoke.return_value = {
        "messages": [MagicMock(content="Great day! Here's your recap.")]
    }

    mock_plugin = MagicMock()
    mock_plugin.evening_recap_sections = ["completed_tasks", "spending_total"]

    with (
        patch(
            "src.orchestrators.deep.domains.brief.create_deep_agent",
            return_value=mock_agent,
        ),
        patch("src.orchestrators.deep.domains.brief.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.domains.brief.build_skill_tools", return_value=[]),
        patch("src.orchestrators.deep.domains.brief.plugin_loader") as mock_pl,
    ):
        mock_get_reg.return_value = MagicMock()
        mock_pl.load.return_value = mock_plugin

        result = await brief_orchestrator.invoke("evening_recap", text_message, sample_context, {})

    assert isinstance(result, SkillResult)
    assert "recap" in result.response_text.lower() or "day" in result.response_text.lower()


async def test_brief_handles_failure(sample_context, text_message):
    """Brief orchestrator handles exceptions gracefully."""
    text_message.text = "Morning brief"

    mock_agent = AsyncMock()
    mock_agent.ainvoke.side_effect = RuntimeError("DB unavailable")

    mock_plugin = MagicMock()
    mock_plugin.morning_brief_sections = ["schedule"]

    with (
        patch(
            "src.orchestrators.deep.domains.brief.create_deep_agent",
            return_value=mock_agent,
        ),
        patch("src.orchestrators.deep.domains.brief.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.domains.brief.build_skill_tools", return_value=[]),
        patch("src.orchestrators.deep.domains.brief.plugin_loader") as mock_pl,
    ):
        mock_get_reg.return_value = MagicMock()
        mock_pl.load.return_value = mock_plugin

        result = await brief_orchestrator.invoke("morning_brief", text_message, sample_context, {})

    assert isinstance(result, SkillResult)
    assert "couldn't" in result.response_text.lower()


async def test_brief_evening_failure_message(sample_context, text_message):
    """Evening recap failure returns appropriate error message."""
    text_message.text = "Evening recap"

    mock_agent = AsyncMock()
    mock_agent.ainvoke.side_effect = RuntimeError("Timeout")

    mock_plugin = MagicMock()
    mock_plugin.evening_recap_sections = ["completed_tasks"]

    with (
        patch(
            "src.orchestrators.deep.domains.brief.create_deep_agent",
            return_value=mock_agent,
        ),
        patch("src.orchestrators.deep.domains.brief.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.domains.brief.build_skill_tools", return_value=[]),
        patch("src.orchestrators.deep.domains.brief.plugin_loader") as mock_pl,
    ):
        mock_get_reg.return_value = MagicMock()
        mock_pl.load.return_value = mock_plugin

        result = await brief_orchestrator.invoke("evening_recap", text_message, sample_context, {})

    assert "evening recap" in result.response_text.lower()


def test_brief_orchestrator_config():
    """Brief orchestrator has correct configuration."""
    assert brief_orchestrator.model == "claude-sonnet-4-6"
    assert "morning_brief" in brief_orchestrator.skill_names
    assert "evening_recap" in brief_orchestrator.skill_names
    assert isinstance(brief_orchestrator, BriefOrchestrator)
