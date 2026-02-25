"""Tests for the skill-to-tool adapter."""

import json
from unittest.mock import AsyncMock, MagicMock

from src.orchestrators.deep.skill_tools import (
    SkillTool,
    build_skill_tools,
    extract_last_skill_result,
)
from src.skills.base import SkillResult


async def test_skill_tool_arun_calls_execute(sample_context, text_message):
    """SkillTool._arun calls skill.execute and returns response_text."""
    mock_skill = MagicMock()
    mock_skill.name = "add_expense"
    mock_skill.intents = ["add_expense"]
    mock_skill.execute = AsyncMock(
        return_value=SkillResult(response_text="Recorded $50 for diesel.")
    )

    tool = SkillTool(
        name="add_expense",
        description="Add an expense",
        skill=mock_skill,
        context=sample_context,
        message=text_message,
    )

    intent_data = {"amount": 50, "category": "diesel"}
    result = await tool._arun(json.dumps(intent_data))

    assert result == "Recorded $50 for diesel."
    mock_skill.execute.assert_awaited_once_with(text_message, sample_context, intent_data)


async def test_skill_tool_captures_full_result(sample_context, text_message):
    """SkillTool captures the full SkillResult in last_result."""
    buttons = [{"text": "Undo", "callback": "undo:123"}]
    expected = SkillResult(response_text="Done", buttons=buttons)

    mock_skill = MagicMock()
    mock_skill.name = "test_skill"
    mock_skill.intents = ["test"]
    mock_skill.execute = AsyncMock(return_value=expected)

    tool = SkillTool(
        name="test_skill",
        description="Test",
        skill=mock_skill,
        context=sample_context,
        message=text_message,
    )

    await tool._arun("{}")
    assert tool.last_result is expected
    assert tool.last_result.buttons == buttons


async def test_skill_tool_handles_invalid_json(sample_context, text_message):
    """SkillTool handles invalid JSON gracefully."""
    mock_skill = MagicMock()
    mock_skill.name = "test_skill"
    mock_skill.intents = ["test"]
    mock_skill.execute = AsyncMock(return_value=SkillResult(response_text="OK"))

    tool = SkillTool(
        name="test_skill",
        description="Test",
        skill=mock_skill,
        context=sample_context,
        message=text_message,
    )

    result = await tool._arun("not valid json")
    assert result == "OK"
    # Should have been called with empty dict
    mock_skill.execute.assert_awaited_once_with(text_message, sample_context, {})


def test_build_skill_tools_creates_tools(sample_context, text_message):
    """build_skill_tools creates SkillTool instances for registered skills."""
    mock_registry = MagicMock()
    mock_skill = MagicMock()
    mock_skill.name = "add_expense"
    mock_skill.intents = ["add_expense"]
    mock_registry.get.return_value = mock_skill

    tools = build_skill_tools(["add_expense"], mock_registry, sample_context, text_message)

    assert len(tools) == 1
    assert tools[0].name == "add_expense"
    assert tools[0].skill is mock_skill


def test_build_skill_tools_deduplicates(sample_context, text_message):
    """build_skill_tools deduplicates skills that handle multiple intents."""
    mock_registry = MagicMock()
    mock_skill = MagicMock()
    mock_skill.name = "track_food"
    mock_skill.intents = ["track_food"]
    mock_registry.get.return_value = mock_skill

    tools = build_skill_tools(
        ["track_food", "track_food"], mock_registry, sample_context, text_message
    )

    assert len(tools) == 1


def test_build_skill_tools_skips_missing(sample_context, text_message):
    """build_skill_tools skips intents not found in registry."""
    mock_registry = MagicMock()
    mock_registry.get.return_value = None

    tools = build_skill_tools(["nonexistent_intent"], mock_registry, sample_context, text_message)

    assert len(tools) == 0


def test_extract_last_skill_result_returns_last():
    """extract_last_skill_result returns the most recent SkillResult."""
    tool1 = MagicMock()
    tool1.last_result = SkillResult(response_text="First")
    tool2 = MagicMock()
    tool2.last_result = SkillResult(response_text="Second")

    result = extract_last_skill_result([tool1, tool2])
    assert result.response_text == "Second"


def test_extract_last_skill_result_returns_none_when_empty():
    """extract_last_skill_result returns None when no tools were invoked."""
    tool1 = MagicMock()
    tool1.last_result = None

    result = extract_last_skill_result([tool1])
    assert result is None
