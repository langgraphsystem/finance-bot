"""Tests for merge_documents skill."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.merge_documents.handler import skill


async def test_merge_no_file_no_context(sample_context, text_message):
    """No document and no pending merge — shows instruction message."""
    with patch("src.skills.merge_documents.handler.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        result = await skill.execute(text_message, sample_context, {})
    assert "pdf" in result.response_text.lower()
    # Response may be in Russian or English
    assert "done" in result.response_text.lower() or "merge" in result.response_text.lower()


async def test_merge_attributes():
    assert skill.name == "merge_documents"
    assert "merge_documents" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


async def test_merge_add_first_file(sample_context):
    """First PDF file added to the merge queue — stored in Redis."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake pdf bytes",
        document_file_name="doc1.pdf",
        document_mime_type="application/pdf",
    )
    with patch("src.skills.merge_documents.handler.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        result = await skill.execute(msg, sample_context, {})

    assert "doc1.pdf" in result.response_text
    assert "1 file" in result.response_text or "1 файл" in result.response_text
    assert "done" in result.response_text.lower()
    mock_redis.set.assert_called_once()


async def test_merge_add_second_file(sample_context):
    """Second PDF file added — shows updated count."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"second pdf bytes",
        document_file_name="doc2.pdf",
        document_mime_type="application/pdf",
    )
    existing_meta = json.dumps(
        {
            "count": 1,
            "names": ["doc1.pdf"],
            "files": [base64.b64encode(b"first pdf").decode()],
        }
    )
    with patch("src.skills.merge_documents.handler.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=existing_meta)
        mock_redis.set = AsyncMock()
        result = await skill.execute(msg, sample_context, {})

    assert "doc2.pdf" in result.response_text
    assert "2 files" in result.response_text or "2 файлов" in result.response_text


async def test_merge_reject_non_pdf(sample_context):
    """Non-PDF file sent — rejects with error message."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake docx bytes",
        document_file_name="letter.docx",
        document_mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    result = await skill.execute(msg, sample_context, {})
    assert "only" in result.response_text.lower() or "pdf" in result.response_text.lower()


async def test_merge_finish_happy_path(sample_context):
    """User says 'done' with 2+ PDFs queued — merges and returns document."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="done",
    )
    queued_meta = json.dumps(
        {
            "count": 2,
            "names": ["doc1.pdf", "doc2.pdf"],
            "files": [
                base64.b64encode(b"pdf-bytes-1").decode(),
                base64.b64encode(b"pdf-bytes-2").decode(),
            ],
        }
    )
    merged_output = b"merged-pdf-output"
    with patch("src.skills.merge_documents.handler.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=queued_meta)
        mock_redis.delete = AsyncMock()
        with patch(
            "src.skills.merge_documents.handler._merge_pdfs",
            return_value=merged_output,
        ):
            # Also mock PdfReader for page count
            with patch("src.skills.merge_documents.handler.PdfReader", create=True) as mock_cls:
                mock_reader = MagicMock()
                mock_reader.pages = [MagicMock(), MagicMock(), MagicMock()]
                mock_cls.return_value = mock_reader
                # The PdfReader import is inside the method, so we mock pypdf.PdfReader
                with patch("pypdf.PdfReader", return_value=mock_reader):
                    result = await skill.execute(msg, sample_context, {})

    assert "Merged 2 PDFs" in result.response_text or "Объединено 2 PDF" in result.response_text
    assert result.document == merged_output
    assert result.document_name == "merged.pdf"
    mock_redis.delete.assert_called_once()


async def test_merge_finish_only_one_file(sample_context):
    """User says 'merge' but only 1 file queued — asks for more."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="merge",
    )
    queued_meta = json.dumps(
        {
            "count": 1,
            "names": ["single.pdf"],
            "files": [base64.b64encode(b"pdf-bytes").decode()],
        }
    )
    with patch("src.skills.merge_documents.handler.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=queued_meta)
        result = await skill.execute(msg, sample_context, {})

    assert "2" in result.response_text.lower() or "another" in result.response_text.lower()


async def test_merge_status_check(sample_context, text_message):
    """No file, not finishing, but pending merge exists — shows status."""
    queued_meta = json.dumps(
        {
            "count": 3,
            "names": ["a.pdf", "b.pdf", "c.pdf"],
            "files": [],
        }
    )
    with patch("src.skills.merge_documents.handler.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=queued_meta)
        result = await skill.execute(text_message, sample_context, {})

    assert "3 file" in result.response_text or "3 файл" in result.response_text
    assert "a.pdf" in result.response_text
