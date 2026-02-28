"""Tests for fill_template skill."""

from src.skills.fill_template.handler import skill


async def test_fill_template_no_file(sample_context, text_message):
    """No document attached — asks user to upload a template."""
    result = await skill.execute(text_message, sample_context, {})
    assert "upload" in result.response_text.lower() or "docx" in result.response_text.upper()
    assert result.document is None


async def test_fill_template_attributes():
    assert skill.name == "fill_template"
    assert "fill_template" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
