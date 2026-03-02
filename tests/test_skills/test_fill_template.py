"""Tests for fill_template skill."""

from unittest.mock import patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.fill_template.handler import skill


async def test_fill_template_no_file(sample_context, text_message):
    """No document attached — asks user to upload a template."""
    result = await skill.execute(text_message, sample_context, {})
    # Response may be in Russian (sample_context.language="ru") or English
    assert "docx" in result.response_text.lower() or "DOCX" in result.response_text
    assert result.document is None


async def test_fill_template_attributes():
    assert skill.name == "fill_template"
    assert "fill_template" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


async def test_fill_template_unsupported_format(sample_context):
    """Non-DOCX/XLSX file — returns unsupported format message."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"fake txt content",
        document_file_name="readme.txt",
        document_mime_type="text/plain",
    )
    result = await skill.execute(msg, sample_context, {})
    # EN: "Unsupported format" / RU: "Формат не поддерживается"
    assert "unsupported" in result.response_text.lower() or "формат" in result.response_text.lower()
    assert result.document is None


async def test_fill_template_docx_happy_path(sample_context):
    """DOCX template with placeholders — fills and returns document."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"PK\x03\x04fake-docx-bytes",
        document_file_name="invoice_template.docx",
        document_mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    filled_bytes = b"PK\x03\x04filled-output"
    with patch(
        "src.skills.fill_template.handler._fill_docx",
        return_value=(filled_bytes, ["name", "currency"], ["date"]),
    ):
        result = await skill.execute(msg, sample_context, {"template_values": {"name": "John"}})

    # EN: "Template filled" / RU: "Шаблон заполнен"
    assert "Template filled" in result.response_text or "Шаблон заполнен" in result.response_text
    assert "name" in result.response_text
    assert "date" in result.response_text
    assert result.document == filled_bytes
    assert result.document_name == "invoice_template_filled.docx"


async def test_fill_template_xlsx_happy_path(sample_context):
    """XLSX template with placeholders — fills and returns document."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"PK\x03\x04fake-xlsx-bytes",
        document_file_name="budget.xlsx",
        document_mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filled_bytes = b"PK\x03\x04filled-xlsx"
    with patch(
        "src.skills.fill_template.handler._fill_xlsx",
        return_value=(filled_bytes, ["amount"], []),
    ):
        result = await skill.execute(msg, sample_context, {})

    # EN: "Template filled" / RU: "Шаблон заполнен"
    assert "Template filled" in result.response_text or "Шаблон заполнен" in result.response_text
    assert "XLSX" in result.response_text
    assert result.document == filled_bytes
    assert result.document_name == "budget_filled.xlsx"


async def test_fill_template_no_placeholders(sample_context):
    """Template with no placeholders found — informs user."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"PK\x03\x04fake-docx",
        document_file_name="plain.docx",
        document_mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    with patch(
        "src.skills.fill_template.handler._fill_docx",
        return_value=(b"output", [], []),
    ):
        result = await skill.execute(msg, sample_context, {})

    # EN: "No placeholders" / RU: "не найдено заполнителей"
    assert (
        "No placeholders" in result.response_text
        or "не найдено заполнителей" in result.response_text
    )
    assert result.document == b"output"


async def test_fill_template_processing_error(sample_context):
    """Template processing fails — returns error message."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        document_bytes=b"PK\x03\x04corrupt",
        document_file_name="broken.docx",
        document_mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    with patch(
        "src.skills.fill_template.handler._fill_docx",
        side_effect=Exception("Template corrupt"),
    ):
        result = await skill.execute(msg, sample_context, {})

    # EN: "Failed" / RU: "Не удалось"
    assert (
        "failed" in result.response_text.lower()
        or "не удалось" in result.response_text.lower()
    )
    assert result.document is None
