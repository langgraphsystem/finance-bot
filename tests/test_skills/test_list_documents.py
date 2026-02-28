"""Tests for list_documents skill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.skills.list_documents.handler import skill


async def test_list_documents_empty(sample_context, text_message):
    """Returns message when no documents found."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    with patch("src.skills.list_documents.handler.async_session") as mock_session:
        session = AsyncMock()
        session.execute.return_value = mock_result
        mock_session.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await skill.execute(text_message, sample_context, {})
        assert "No documents" in result.response_text


async def test_list_documents_with_results(sample_context, text_message):
    """Returns formatted list when documents exist."""
    doc = MagicMock()
    doc.type = "invoice"
    doc.title = "Test Invoice"
    doc.file_name = "invoice.pdf"
    doc.file_size_bytes = 1024
    doc.created_at = MagicMock()
    doc.created_at.strftime.return_value = "28.02.2026"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [doc]

    with patch("src.skills.list_documents.handler.async_session") as mock_session:
        session = AsyncMock()
        session.execute.return_value = mock_result
        mock_session.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await skill.execute(text_message, sample_context, {})
        assert "Documents" in result.response_text
        assert "Test Invoice" in result.response_text


async def test_skill_attributes():
    assert skill.name == "list_documents"
    assert "list_documents" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
