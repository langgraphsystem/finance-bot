"""Tests for search_documents skill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.skills.search_documents.handler import skill


async def test_search_documents_no_query(sample_context, text_message):
    """Asks for query when none provided."""
    text_message.text = ""
    result = await skill.execute(text_message, sample_context, {})
    assert "искать" in result.response_text.lower() or "search for" in result.response_text.lower()


async def test_search_documents_no_results(sample_context, text_message):
    """Returns not found message."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    with patch("src.skills.search_documents.handler.async_session") as mock_session:
        session = AsyncMock()
        session.execute.return_value = mock_result
        mock_session.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await skill.execute(text_message, sample_context, {"search_query": "contract"})
        assert "не найдены" in result.response_text or "No documents" in result.response_text


async def test_search_documents_with_results(sample_context, text_message):
    """Returns matching documents."""
    doc = MagicMock()
    doc.title = "Employment Contract"
    doc.file_name = "contract.pdf"
    doc.type = "contract"
    doc.extracted_text = "This is an employment contract for testing purposes"
    doc.created_at = MagicMock()
    doc.created_at.strftime.return_value = "28.02.2026"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [doc]

    with patch("src.skills.search_documents.handler.async_session") as mock_session:
        session = AsyncMock()
        session.execute.return_value = mock_result
        mock_session.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await skill.execute(text_message, sample_context, {"search_query": "contract"})
        assert "Найдено" in result.response_text or "Found" in result.response_text
        assert "Employment Contract" in result.response_text


async def test_skill_attributes():
    assert skill.name == "search_documents"
    assert "search_documents" in skill.intents
