"""Tests for generate_presentation skill."""

from src.skills.generate_presentation.handler import skill


async def test_generate_presentation_no_topic(sample_context):
    """No topic provided — asks user what to create."""
    from src.gateway.types import IncomingMessage, MessageType

    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, sample_context, {})
    assert "what" in result.response_text.lower() or "about" in result.response_text.lower()
    assert result.document is None


async def test_generate_presentation_attributes():
    assert skill.name == "generate_presentation"
    assert "generate_presentation" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
