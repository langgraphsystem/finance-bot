"""Tests for compare_documents skill."""

from src.skills.compare_documents.handler import skill


async def test_compare_no_file(sample_context, text_message):
    """No document attached — asks user to upload."""
    result = await skill.execute(text_message, sample_context, {})
    assert "upload" in result.response_text.lower() or "document" in result.response_text.lower()


async def test_compare_attributes():
    assert skill.name == "compare_documents"
    assert "compare_documents" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
