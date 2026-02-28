"""Tests for pdf_operations skill."""

from unittest.mock import MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.pdf_operations.handler import skill


async def test_pdf_ops_no_file(sample_context, text_message):
    """No document attached — asks user to upload a PDF."""
    result = await skill.execute(text_message, sample_context, {})
    assert "upload" in result.response_text.lower() or "pdf" in result.response_text.lower()


async def test_pdf_ops_no_operation(sample_context):
    """Has PDF but no operation specified — lists available operations."""
    msg = IncomingMessage(
        id="msg-pdf",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake-pdf-bytes",
        document_file_name="test.pdf",
        document_mime_type="application/pdf",
    )

    mock_reader = MagicMock()
    mock_reader.pages = [MagicMock(), MagicMock()]  # 2 pages
    mock_reader.is_encrypted = False

    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = await skill.execute(msg, sample_context, {})

    text = result.response_text.lower()
    assert "available operations" in text or "extract" in text


async def test_pdf_ops_attributes():
    assert skill.name == "pdf_operations"
    assert "pdf_operations" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
