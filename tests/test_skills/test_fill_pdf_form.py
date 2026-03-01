"""Tests for fill_pdf_form skill."""

from unittest.mock import patch

from src.gateway.types import IncomingMessage, MessageType
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


async def test_fill_pdf_form_non_pdf_rejected(sample_context):
    """Non-PDF file — rejects with error."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake docx",
        document_file_name="form.docx",
        document_mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    result = await skill.execute(msg, sample_context, {})
    assert "pdf" in result.response_text.lower()


async def test_fill_pdf_form_list_fields(sample_context):
    """PDF with form fields, no values provided — lists fields."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake pdf form",
        document_file_name="w9.pdf",
        document_mime_type="application/pdf",
    )
    with patch(
        "src.skills.fill_pdf_form.handler._read_form_fields",
        return_value={"name": None, "ssn": None, "address": "123 Main St"},
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "PDF Form Fields" in result.response_text
    assert "name" in result.response_text
    assert "ssn" in result.response_text
    assert "123 Main St" in result.response_text
    assert result.document is None


async def test_fill_pdf_form_no_form_fields(sample_context):
    """PDF without fillable fields — informs user."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"regular pdf",
        document_file_name="plain.pdf",
        document_mime_type="application/pdf",
    )
    with patch(
        "src.skills.fill_pdf_form.handler._read_form_fields",
        return_value={},
    ):
        result = await skill.execute(msg, sample_context, {})

    assert (
        "fillable" in result.response_text.lower() or "form fields" in result.response_text.lower()
    )
    assert result.document is None


async def test_fill_pdf_form_with_values(sample_context):
    """PDF with form fields + values provided — fills and returns document."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake pdf form",
        document_file_name="w9.pdf",
        document_mime_type="application/pdf",
    )
    filled_bytes = b"filled pdf output bytes"
    with (
        patch(
            "src.skills.fill_pdf_form.handler._read_form_fields",
            return_value={"name": None, "ssn": None, "address": None},
        ),
        patch(
            "src.skills.fill_pdf_form.handler._fill_form",
            return_value=filled_bytes,
        ),
    ):
        result = await skill.execute(
            msg, sample_context, {"form_values": {"name": "John Smith", "address": "456 Oak Ave"}}
        )

    assert "PDF form filled" in result.response_text
    assert "2 field" in result.response_text
    assert "John Smith" in result.response_text
    assert result.document == filled_bytes
    assert result.document_name == "w9_filled.pdf"


async def test_fill_pdf_form_with_skipped_fields(sample_context):
    """Some values don't match form fields — fills valid ones, reports skipped."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake pdf form",
        document_file_name="tax_form.pdf",
        document_mime_type="application/pdf",
    )
    with (
        patch(
            "src.skills.fill_pdf_form.handler._read_form_fields",
            return_value={"name": None, "date": None},
        ),
        patch(
            "src.skills.fill_pdf_form.handler._fill_form",
            return_value=b"filled output",
        ),
    ):
        result = await skill.execute(
            msg,
            sample_context,
            {"form_values": {"name": "Jane Doe", "nonexistent_field": "value"}},
        )

    assert "PDF form filled" in result.response_text
    assert "Skipped" in result.response_text
    assert "nonexistent_field" in result.response_text
    assert result.document == b"filled output"


async def test_fill_pdf_form_no_matching_fields(sample_context):
    """All provided values have no matching form fields — error."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake pdf form",
        document_file_name="form.pdf",
        document_mime_type="application/pdf",
    )
    with patch(
        "src.skills.fill_pdf_form.handler._read_form_fields",
        return_value={"name": None, "date": None},
    ):
        result = await skill.execute(
            msg,
            sample_context,
            {"form_values": {"wrong_field": "value", "also_wrong": "data"}},
        )

    assert "none" in result.response_text.lower() or "match" in result.response_text.lower()
    assert result.document is None


async def test_fill_pdf_form_read_error(sample_context):
    """PDF reading fails — returns error."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"corrupt pdf",
        document_file_name="bad.pdf",
        document_mime_type="application/pdf",
    )
    with patch(
        "src.skills.fill_pdf_form.handler._read_form_fields",
        side_effect=Exception("Invalid PDF"),
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "failed" in result.response_text.lower() or "valid" in result.response_text.lower()
    assert result.document is None
