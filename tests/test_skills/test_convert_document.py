"""Tests for convert_document skill."""

from unittest.mock import AsyncMock, patch

import pytest

from src.gateway.types import IncomingMessage, MessageType
from src.skills.convert_document.handler import ConvertDocumentSkill, _extract_target_from_text


@pytest.fixture
def skill():
    return ConvertDocumentSkill()


@pytest.fixture
def ctx(sample_context):
    return sample_context


def _make_doc_message(
    text="convert to pdf",
    doc_bytes=b"fake-docx-content",
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    filename="report.docx",
):
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.document,
        text=text,
        document_bytes=doc_bytes,
        document_mime_type=mime,
        document_file_name=filename,
    )


async def test_convert_basic(skill, ctx):
    """Successful conversion returns document bytes and filename."""
    msg = _make_doc_message()
    with patch(
        "src.skills.convert_document.handler.convert_document",
        new_callable=AsyncMock,
        return_value=(b"pdf-content", "report.pdf"),
    ):
        result = await skill.execute(msg, ctx, {"target_format": "pdf"})

    assert result.document == b"pdf-content"
    assert result.document_name == "report.pdf"
    assert "DOCX" in result.response_text
    assert "PDF" in result.response_text


async def test_convert_no_file(skill, ctx):
    """No file attached → prompt user."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="convert to pdf",
    )
    result = await skill.execute(msg, ctx, {"target_format": "pdf"})
    assert "send a file" in result.response_text.lower()
    assert result.document is None


async def test_convert_no_target_format(skill, ctx):
    """No target format specified → ask user."""
    msg = _make_doc_message(text="convert this")
    result = await skill.execute(msg, ctx, {})
    assert "what format" in result.response_text.lower()


async def test_convert_same_format(skill, ctx):
    """Source == target → inform user."""
    msg = _make_doc_message(text="convert to docx")
    result = await skill.execute(msg, ctx, {"target_format": "docx"})
    assert "already in" in result.response_text.lower()


async def test_convert_unsupported_pair(skill, ctx):
    """Unsupported conversion pair → show supported targets."""
    msg = _make_doc_message(
        text="convert to mobi",
        mime="image/jpeg",
        filename="photo.jpg",
        doc_bytes=b"fake-jpg",
    )
    result = await skill.execute(msg, ctx, {"target_format": "mobi"})
    assert "can't convert" in result.response_text.lower()
    assert "PDF" in result.response_text  # PDF is a supported target for jpg


async def test_convert_unknown_source(skill, ctx):
    """Unknown source format → error message."""
    msg = _make_doc_message(
        filename="data.xyz",
        mime="application/octet-stream",
    )
    result = await skill.execute(msg, ctx, {"target_format": "pdf"})
    assert "couldn't determine" in result.response_text.lower()


async def test_convert_file_too_large(skill, ctx):
    """File > 20MB → size error."""
    big_bytes = b"x" * (21 * 1024 * 1024)
    msg = _make_doc_message(doc_bytes=big_bytes)
    result = await skill.execute(msg, ctx, {"target_format": "pdf"})
    assert "too large" in result.response_text.lower()


async def test_convert_failure(skill, ctx):
    """ConversionError → friendly error message."""
    from src.tools.conversion_service import ConversionError

    msg = _make_doc_message()
    with patch(
        "src.skills.convert_document.handler.convert_document",
        new_callable=AsyncMock,
        side_effect=ConversionError("LibreOffice crashed"),
    ):
        result = await skill.execute(msg, ctx, {"target_format": "pdf"})

    assert "conversion failed" in result.response_text.lower()
    assert result.document is None


async def test_convert_photo_input(skill, ctx):
    """Photo bytes (no document_bytes) should work for image conversion."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.photo,
        text="convert to png",
        photo_bytes=b"fake-jpg-photo",
    )
    with patch(
        "src.skills.convert_document.handler.convert_document",
        new_callable=AsyncMock,
        return_value=(b"png-content", "photo.png"),
    ):
        result = await skill.execute(msg, ctx, {"target_format": "png"})

    assert result.document == b"png-content"
    assert result.document_name == "photo.png"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("convert to pdf", "pdf"),
        ("конвертируй в docx", "docx"),
        ("в PDF", "pdf"),
        ("save as xlsx", "xlsx"),
        ("to .html", "html"),
        ("в формат epub", "epub"),
        ("hello world", ""),
    ],
)
def test_extract_target_from_text(text, expected):
    assert _extract_target_from_text(text) == expected


def test_skill_attributes(skill):
    assert skill.name == "convert_document"
    assert skill.intents == ["convert_document"]
    assert skill.model == "claude-haiku-4-5"
    assert hasattr(skill, "execute")
    assert hasattr(skill, "get_system_prompt")
