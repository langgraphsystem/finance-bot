"""Tests for fill_pdf_form skill."""

from src.skills.fill_pdf_form.handler import skill


async def test_fill_pdf_form_no_file(sample_context, text_message):
    """No document attached — asks user to upload a PDF form."""
    result = await skill.execute(text_message, sample_context, {})
    assert "upload" in result.response_text.lower() or "pdf" in result.response_text.lower()
    assert result.document is None


async def test_fill_pdf_form_attributes():
    assert skill.name == "fill_pdf_form"
    assert "fill_pdf_form" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
