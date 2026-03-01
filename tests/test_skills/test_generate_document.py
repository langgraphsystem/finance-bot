"""Tests for generate_document skill."""

from unittest.mock import AsyncMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.generate_document.handler import skill


async def test_generate_document_no_description(sample_context):
    """No description provided — asks user what to create."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, sample_context, {})
    # Response may be in Russian (sample_context.language="ru") or English
    assert result.response_text  # Non-empty prompt asking what to create
    assert result.document is None


async def test_generate_document_attributes():
    assert skill.name == "generate_document"
    assert "generate_document" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


async def test_generate_document_pdf_happy_path(sample_context):
    """Generates an NDA as PDF — returns document bytes."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="create an NDA for my business",
    )
    pdf_bytes = b"%PDF-1.4 fake pdf output"
    with (
        patch(
            "src.skills.generate_document.handler.generate_text",
            new_callable=AsyncMock,
            return_value=("<html><body><h1>NDA</h1><p>This NDA...</p></body></html>"),
        ),
        patch(
            "src.skills.generate_document.handler._html_to_pdf",
            return_value=pdf_bytes,
        ),
    ):
        result = await skill.execute(
            msg, sample_context, {"description": "NDA for my plumbing business"}
        )

    assert result.document == pdf_bytes
    assert result.document_name.endswith(".pdf")
    assert "ready" in result.response_text.lower()


async def test_generate_document_html_format(sample_context):
    """Generates document as HTML when target_format=html."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="create a price list",
    )
    html_content = (
        "<html><body><h1>Price List</h1>"
        "<table><tr><td>Service</td><td>$100</td></tr></table>"
        "</body></html>"
    )
    with patch(
        "src.skills.generate_document.handler.generate_text",
        new_callable=AsyncMock,
        return_value=html_content,
    ):
        result = await skill.execute(
            msg,
            sample_context,
            {"description": "price list for services", "target_format": "html"},
        )

    assert result.document is not None
    assert result.document_name.endswith(".html")
    assert result.document == html_content.encode("utf-8")
    assert "ready" in result.response_text.lower()


async def test_generate_document_pdf_fails_returns_html(sample_context):
    """PDF generation fails — falls back to HTML."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="create a service agreement",
    )
    with (
        patch(
            "src.skills.generate_document.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<html><body><h1>Service Agreement</h1></body></html>",
        ),
        patch(
            "src.skills.generate_document.handler._html_to_pdf",
            side_effect=Exception("WeasyPrint unavailable"),
        ),
    ):
        result = await skill.execute(msg, sample_context, {"description": "service agreement"})

    assert result.document is not None
    assert result.document_name.endswith(".html")
    assert "html" in result.response_text.lower() or "unavailable" in result.response_text.lower()


async def test_generate_document_llm_fails(sample_context):
    """LLM generation fails — returns error message."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="create a contract",
    )
    with patch(
        "src.skills.generate_document.handler.generate_text",
        new_callable=AsyncMock,
        side_effect=Exception("LLM API error"),
    ):
        result = await skill.execute(msg, sample_context, {"description": "contract"})

    assert "failed" in result.response_text.lower() or "try again" in result.response_text.lower()
    assert result.document is None


async def test_generate_document_strips_markdown_fences(sample_context):
    """LLM wraps HTML in markdown fences — stripped before processing."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="create an invoice template",
    )
    fenced_html = "```html\n<html><body><h1>Invoice</h1></body></html>\n```"
    pdf_bytes = b"%PDF-fake"
    with (
        patch(
            "src.skills.generate_document.handler.generate_text",
            new_callable=AsyncMock,
            return_value=fenced_html,
        ),
        patch(
            "src.skills.generate_document.handler._html_to_pdf",
            return_value=pdf_bytes,
        ),
    ):
        result = await skill.execute(msg, sample_context, {"description": "invoice template"})

    assert result.document == pdf_bytes
    assert result.document_name.endswith(".pdf")
