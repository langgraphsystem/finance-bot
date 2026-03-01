"""Tests for summarize_document skill."""

from unittest.mock import AsyncMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.summarize_document.handler import skill


async def test_summarize_no_file(sample_context, text_message):
    """No document attached — asks user to upload."""
    result = await skill.execute(text_message, sample_context, {})
    # Response may be in Russian (sample_context.language="ru") or English
    assert result.response_text  # Non-empty response asking to upload


async def test_summarize_attributes():
    assert skill.name == "summarize_document"
    assert "summarize_document" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


async def test_summarize_pdf_happy_path(sample_context):
    """PDF with extractable text — generates and returns summary."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake pdf bytes for financial report",
        document_file_name="report_q4.pdf",
        document_mime_type="application/pdf",
    )
    with (
        patch(
            "src.tools.document_reader.extract_text",
            new_callable=AsyncMock,
            return_value=(
                "Q4 2025 Financial Report. Revenue: $1.2M, up 15% YoY. "
                "Net profit margin: 22%. Key risk: supply chain delays."
            ),
        ),
        patch(
            "src.tools.document_reader.get_page_count",
            new_callable=AsyncMock,
            return_value=10,
        ),
        patch(
            "src.skills.summarize_document.handler.generate_text",
            new_callable=AsyncMock,
            return_value=(
                "<b>Executive Summary</b>\n"
                "Q4 report shows 15% revenue growth to $1.2M with 22% margins.\n\n"
                "<b>Key Points</b>\n"
                "- Revenue: $1.2M (up 15% YoY)\n"
                "- Net profit margin: 22%\n"
                "- Supply chain delays flagged as risk"
            ),
        ),
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "Summary" in result.response_text
    assert "report_q4.pdf" in result.response_text
    assert "10 page" in result.response_text
    assert "Executive Summary" in result.response_text


async def test_summarize_with_focus_hint(sample_context):
    """Summary with user-specified focus — passes description to LLM."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake docx content",
        document_file_name="contract.docx",
        document_mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    with (
        patch(
            "src.tools.document_reader.extract_text",
            new_callable=AsyncMock,
            return_value="Service Agreement between Party A and Party B. Term: 12 months.",
        ),
        patch(
            "src.tools.document_reader.get_page_count",
            new_callable=AsyncMock,
            return_value=3,
        ),
        patch(
            "src.skills.summarize_document.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Executive Summary</b>\n12-month service agreement.",
        ) as mock_gen,
    ):
        result = await skill.execute(msg, sample_context, {"description": "focus on payment terms"})

    assert "Summary" in result.response_text
    # Verify the focus hint was included in the prompt
    call_kwargs = mock_gen.call_args
    assert "payment terms" in call_kwargs.kwargs.get("prompt", "") or "payment terms" in str(
        call_kwargs
    )


async def test_summarize_empty_text(sample_context):
    """Empty text extraction — returns error."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"blank doc bytes",
        document_file_name="empty.pdf",
        document_mime_type="application/pdf",
    )
    with patch(
        "src.tools.document_reader.extract_text",
        new_callable=AsyncMock,
        return_value="",
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "extract" in result.response_text.lower() or "text" in result.response_text.lower()


async def test_summarize_extraction_fails(sample_context):
    """Text extraction throws — returns error."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"corrupt bytes",
        document_file_name="corrupt.pdf",
        document_mime_type="application/pdf",
    )
    with patch(
        "src.tools.document_reader.extract_text",
        new_callable=AsyncMock,
        side_effect=Exception("PDF corrupted"),
    ):
        result = await skill.execute(msg, sample_context, {})

    assert (
        "could not" in result.response_text.lower() or "supported" in result.response_text.lower()
    )


async def test_summarize_photo_input(sample_context):
    """Photo input — summarizes the image-based document."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.photo,
        photo_bytes=b"fake receipt jpeg",
    )
    with (
        patch(
            "src.tools.document_reader.extract_text",
            new_callable=AsyncMock,
            return_value="Receipt: Coffee $4.50, Tax $0.38, Total $4.88",
        ),
        patch(
            "src.tools.document_reader.get_page_count",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "src.skills.summarize_document.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Executive Summary</b>\nCoffee receipt for $4.88.",
        ),
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "Summary" in result.response_text


async def test_summarize_truncates_long_document(sample_context):
    """Very long document — truncated before sending to LLM."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"x" * 100,
        document_file_name="huge.pdf",
        document_mime_type="application/pdf",
    )
    long_text = "A" * 80_000  # > 60K char limit
    with (
        patch(
            "src.tools.document_reader.extract_text",
            new_callable=AsyncMock,
            return_value=long_text,
        ),
        patch(
            "src.tools.document_reader.get_page_count",
            new_callable=AsyncMock,
            return_value=50,
        ),
        patch(
            "src.skills.summarize_document.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Executive Summary</b>\nVery long document summarized.",
        ),
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "Summary" in result.response_text
    assert "truncated" in result.response_text.lower()
