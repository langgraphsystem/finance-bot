"""Tests for extract_table skill."""

from unittest.mock import AsyncMock, patch

from src.skills.extract_table.handler import skill
from src.tools.document_reader import Table


async def test_extract_table_no_file(sample_context, text_message):
    """Asks user to send a file."""
    result = await skill.execute(text_message, sample_context, {})
    assert "Отправьте" in result.response_text or "Send a document" in result.response_text


async def test_extract_table_from_pdf(sample_context, text_message):
    """Extracts tables from PDF using document_reader."""
    text_message.document_bytes = b"fake-pdf-bytes"
    text_message.document_file_name = "data.pdf"
    text_message.document_mime_type = "application/pdf"

    test_table = Table(
        headers=["Name", "Amount"],
        rows=[["Item 1", "100"], ["Item 2", "200"]],
        page=1,
    )

    with patch(
        "src.skills.extract_table.handler.extract_tables",
        new_callable=AsyncMock,
        return_value=[test_table],
    ):
        result = await skill.execute(text_message, sample_context, {})
        assert "Found 1 table" in result.response_text
        assert result.document is not None
        assert result.document_name == "table.csv"


async def test_extract_table_no_tables(sample_context, text_message):
    """Reports when no tables found."""
    text_message.document_bytes = b"fake-pdf-bytes"
    text_message.document_file_name = "empty.pdf"
    text_message.document_mime_type = "application/pdf"

    with patch(
        "src.skills.extract_table.handler.extract_tables",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await skill.execute(text_message, sample_context, {})
        assert "таблицы не найдены" in result.response_text or "No tables" in result.response_text


async def test_skill_attributes():
    assert skill.name == "extract_table"
    assert "extract_table" in skill.intents
