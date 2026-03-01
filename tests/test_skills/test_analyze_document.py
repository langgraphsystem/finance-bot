"""Tests for analyze_document skill."""

from unittest.mock import AsyncMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.analyze_document.handler import skill


async def test_analyze_no_file(sample_context, text_message):
    """No document or photo attached — asks user to upload."""
    result = await skill.execute(text_message, sample_context, {})
    # Response may be in Russian (sample_context.language="ru") or English
    assert "pdf" in result.response_text.lower() or "document" in result.response_text.lower()


async def test_analyze_attributes():
    assert skill.name == "analyze_document"
    assert "analyze_document" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


async def test_analyze_pdf_text_happy_path(sample_context):
    """PDF with extractable text — runs Claude analysis and returns result."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake pdf content bytes",
        document_file_name="contract.pdf",
        document_mime_type="application/pdf",
    )
    with (
        patch(
            "src.skills.analyze_document.handler.is_scanned_pdf",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "src.skills.analyze_document.handler.extract_text",
            new_callable=AsyncMock,
            return_value="This is a service agreement between Party A and Party B...",
        ),
        patch(
            "src.skills.analyze_document.handler.get_page_count",
            new_callable=AsyncMock,
            return_value=5,
        ),
        patch(
            "src.skills.analyze_document.handler.generate_text",
            new_callable=AsyncMock,
            return_value="This is a service agreement. Key terms include...",
        ),
    ):
        result = await skill.execute(msg, sample_context, {"search_query": "what are the terms?"})

    # Header contains filename; analysis body contains the mocked LLM response
    assert "contract.pdf" in result.response_text
    assert "service agreement" in result.response_text


async def test_analyze_docx_happy_path(sample_context):
    """DOCX analysis — extracts text and returns analysis."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"PK\x03\x04 fake docx",
        document_file_name="report.docx",
        document_mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    with (
        patch(
            "src.skills.analyze_document.handler.is_scanned_pdf",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "src.skills.analyze_document.handler.extract_text",
            new_callable=AsyncMock,
            return_value="Q4 Financial Report: Revenue increased 15%...",
        ),
        patch(
            "src.skills.analyze_document.handler.get_page_count",
            new_callable=AsyncMock,
            return_value=12,
        ),
        patch(
            "src.skills.analyze_document.handler.generate_text",
            new_callable=AsyncMock,
            return_value="This Q4 report shows strong revenue growth of 15%.",
        ),
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "report.docx" in result.response_text
    assert "15%" in result.response_text


async def test_analyze_empty_text_extraction(sample_context):
    """Document where text extraction returns empty — returns error."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake pdf",
        document_file_name="empty.pdf",
        document_mime_type="application/pdf",
    )
    with (
        patch(
            "src.skills.analyze_document.handler.is_scanned_pdf",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "src.skills.analyze_document.handler.extract_text",
            new_callable=AsyncMock,
            return_value="",
        ),
    ):
        result = await skill.execute(msg, sample_context, {})

    # Language-agnostic: check for Russian or English error keywords
    low = result.response_text.lower()
    assert "извлечь" in low or "extract" in low or "empty" in low or "пуст" in low


async def test_analyze_scanned_pdf_vision(sample_context):
    """Scanned PDF — uses vision analysis path."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake scanned pdf",
        document_file_name="scan.pdf",
        document_mime_type="application/pdf",
    )
    with (
        patch(
            "src.skills.analyze_document.handler.is_scanned_pdf",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "src.skills.analyze_document.handler._analyze_via_vision",
            new_callable=AsyncMock,
            return_value="The scanned document contains an invoice from ACME Corp.",
        ),
        patch(
            "src.skills.analyze_document.handler.get_page_count",
            new_callable=AsyncMock,
            return_value=2,
        ),
    ):
        result = await skill.execute(msg, sample_context, {})

    # Header present (en or ru), filename, scanned indicator, analysis body
    assert "scan.pdf" in result.response_text
    text_lower = result.response_text.lower()
    assert "scanned" in text_lower or "сканированн" in text_lower
    assert "invoice" in result.response_text.lower() or "ACME" in result.response_text


async def test_analyze_photo_input(sample_context):
    """Photo (no document) — treated as image, analyzed via vision."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.photo,
        photo_bytes=b"fake jpeg bytes",
    )
    with (
        patch(
            "src.skills.analyze_document.handler.is_scanned_pdf",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "src.skills.analyze_document.handler._analyze_via_vision",
            new_callable=AsyncMock,
            return_value="This is a store receipt for $45.99.",
        ),
    ):
        result = await skill.execute(msg, sample_context, {})

    # Header has image indicator (en or ru)
    low = result.response_text.lower()
    assert "image" in low or "изображен" in low or "vision" in low


async def test_analyze_jpg_document(sample_context):
    """JPG sent as document (not photo) — analyzed via vision, not rejected."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake jpg bytes",
        document_file_name="scan.jpg",
        document_mime_type="image/jpeg",
    )
    with (
        patch(
            "src.skills.analyze_document.handler.is_scanned_pdf",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "src.skills.analyze_document.handler._analyze_via_vision",
            new_callable=AsyncMock,
            return_value="Document contains a table with financial data.",
        ),
    ):
        result = await skill.execute(msg, sample_context, {})

    low = result.response_text.lower()
    assert "image" in low or "изображен" in low or "vision" in low
    assert "financial data" in low
