"""Tests for generate_spreadsheet skill."""

from src.skills.generate_spreadsheet.handler import skill


async def test_generate_spreadsheet_no_description(sample_context):
    """No description provided — asks user what to create."""
    from src.gateway.types import IncomingMessage, MessageType

    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, sample_context, {})
    assert "what" in result.response_text.lower() or "describe" in result.response_text.lower()
    assert result.document is None


async def test_generate_spreadsheet_attributes():
    assert skill.name == "generate_spreadsheet"
    assert "generate_spreadsheet" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
