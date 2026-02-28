"""Tests for analyze_document skill."""

from src.skills.analyze_document.handler import skill


async def test_analyze_no_file(sample_context, text_message):
    """No document or photo attached — asks user to upload."""
    result = await skill.execute(text_message, sample_context, {})
    assert "upload" in result.response_text.lower() or "document" in result.response_text.lower()


async def test_analyze_attributes():
    assert skill.name == "analyze_document"
    assert "analyze_document" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
