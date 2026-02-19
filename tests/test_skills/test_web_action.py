"""Tests for web_action skill."""

from unittest.mock import AsyncMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.web_action.handler import WebActionSkill


def test_web_action_skill_attributes():
    skill = WebActionSkill()
    assert skill.name == "web_action"
    assert "web_action" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


def test_web_action_system_prompt(sample_context):
    skill = WebActionSkill()
    prompt = skill.get_system_prompt(sample_context)
    assert "browser automation" in prompt.lower() or "web" in prompt.lower()


async def test_web_action_empty_message(sample_context):
    skill = WebActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=""
    )
    result = await skill.execute(msg, sample_context, {})
    assert "what" in result.response_text.lower()


async def test_web_action_write_needs_approval(sample_context):
    skill = WebActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1",
        type=MessageType.text, text="submit order on Amazon",
    )
    with patch(
        "src.skills.web_action.handler.approval_manager"
    ) as mock_approval:
        mock_approval.request_approval = AsyncMock(return_value=AsyncMock(
            response_text="Confirm?", buttons=[]
        ))
        await skill.execute(msg, sample_context, {})
        mock_approval.request_approval.assert_called_once()


async def test_web_action_read_executes_directly(sample_context):
    skill = WebActionSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1",
        type=MessageType.text, text="check what time Costco closes",
    )
    with patch(
        "src.skills.web_action.handler.browser_tool"
    ) as mock_browser:
        mock_browser.execute_task = AsyncMock(
            return_value={"success": True, "result": "Costco closes at 8pm", "steps": 3}
        )
        result = await skill.execute(msg, sample_context, {})
    assert "8pm" in result.response_text
