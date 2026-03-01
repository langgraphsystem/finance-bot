"""Tests for compare_documents skill."""

from unittest.mock import AsyncMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.compare_documents.handler import skill


async def test_compare_no_file(sample_context, text_message):
    """No document attached — asks user to upload."""
    result = await skill.execute(text_message, sample_context, {})
    # Response may be in Russian (sample_context.language="ru") or English
    assert result.response_text  # Non-empty response asking to upload


async def test_compare_attributes():
    assert skill.name == "compare_documents"
    assert "compare_documents" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


async def test_compare_single_document_happy_path(sample_context):
    """Single document with a question — analyzes and returns comparison."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake pdf content for contract v2",
        document_file_name="contract_v2.pdf",
        document_mime_type="application/pdf",
    )
    with (
        patch(
            "src.tools.document_reader.extract_text",
            new_callable=AsyncMock,
            return_value="Contract v2: Added force majeure clause. NET 30.",
        ),
        patch(
            "src.skills.compare_documents.handler.generate_text",
            new_callable=AsyncMock,
            return_value=(
                "<b>Overview</b>\nContract v2 adds new clauses.\n"
                "<b>Key Differences</b>\n- Force majeure clause added\n"
                "- Payment terms changed to NET 30"
            ),
        ),
    ):
        result = await skill.execute(
            msg, sample_context, {"description": "compare with previous version"}
        )

    assert "Document Analysis" in result.response_text
    assert "contract_v2.pdf" in result.response_text
    assert (
        "force majeure" in result.response_text.lower()
        or "differences" in result.response_text.lower()
    )


async def test_compare_two_documents_via_intent(sample_context):
    """Document with second_document_text in intent_data — compares two docs."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake contract v2 bytes",
        document_file_name="contract_v2.pdf",
        document_mime_type="application/pdf",
    )
    with (
        patch(
            "src.tools.document_reader.extract_text",
            new_callable=AsyncMock,
            return_value="Contract v2: Price is $5000. Delivery by Q2.",
        ),
        patch(
            "src.skills.compare_documents.handler.generate_text",
            new_callable=AsyncMock,
            return_value=(
                "<b>Key Differences</b>\n"
                "- Price increased from $3000 to $5000\n"
                "- Delivery deadline moved from Q1 to Q2"
            ),
        ),
    ):
        result = await skill.execute(
            msg,
            sample_context,
            {
                "description": "compare contracts",
                "second_document_text": "Contract v1: Price is $3000. Delivery by Q1.",
            },
        )

    assert "Document Analysis" in result.response_text
    assert "contract_v2.pdf" in result.response_text


async def test_compare_empty_text_extraction(sample_context):
    """Text extraction returns empty — returns error."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"corrupt file bytes",
        document_file_name="blank.pdf",
        document_mime_type="application/pdf",
    )
    with patch(
        "src.tools.document_reader.extract_text",
        new_callable=AsyncMock,
        return_value="",
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "extract" in result.response_text.lower() or "text" in result.response_text.lower()
    assert result.document is None


async def test_compare_extraction_fails(sample_context):
    """Text extraction throws exception — returns error."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"broken file",
        document_file_name="broken.xlsx",
        document_mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    with patch(
        "src.tools.document_reader.extract_text",
        new_callable=AsyncMock,
        side_effect=Exception("Unsupported format"),
    ):
        result = await skill.execute(msg, sample_context, {})

    assert (
        "could not" in result.response_text.lower() or "supported" in result.response_text.lower()
    )


async def test_compare_photo_input(sample_context):
    """Photo input — treated as image document for comparison."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.photo,
        photo_bytes=b"fake jpeg bytes",
    )
    with (
        patch(
            "src.tools.document_reader.extract_text",
            new_callable=AsyncMock,
            return_value="Invoice #123: Total $500",
        ),
        patch(
            "src.skills.compare_documents.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Overview</b>\nInvoice for $500 from vendor.",
        ),
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "Document Analysis" in result.response_text
