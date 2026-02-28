"""Tests for summarize_document skill."""

from src.skills.summarize_document.handler import skill


async def test_summarize_no_file(sample_context, text_message):
    """No document attached — asks user to upload."""
    result = await skill.execute(text_message, sample_context, {})
    assert "upload" in result.response_text.lower() or "document" in result.response_text.lower()


async def test_summarize_attributes():
    assert skill.name == "summarize_document"
    assert "summarize_document" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
