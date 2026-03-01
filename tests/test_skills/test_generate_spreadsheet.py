"""Tests for generate_spreadsheet skill."""

from unittest.mock import AsyncMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.generate_spreadsheet.handler import skill


async def test_generate_spreadsheet_no_description(sample_context):
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


async def test_generate_spreadsheet_attributes():
    assert skill.name == "generate_spreadsheet"
    assert "generate_spreadsheet" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


async def test_generate_spreadsheet_e2b_happy_path(sample_context):
    """E2B sandbox succeeds — returns spreadsheet document."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="create expense tracker spreadsheet",
    )
    xlsx_bytes = b"PK\x03\x04fake-xlsx-output"
    with (
        patch(
            "src.skills.generate_spreadsheet.handler.generate_text",
            new_callable=AsyncMock,
            return_value=(
                "from openpyxl import Workbook\nwb=Workbook()\nwb.save('/tmp/output.xlsx')"
            ),
        ),
        patch(
            "src.tools.e2b_file_utils.execute_code_with_file",
            new_callable=AsyncMock,
            return_value=(xlsx_bytes, "Success"),
        ),
    ):
        result = await skill.execute(msg, sample_context, {"description": "expense tracker"})

    assert result.document == xlsx_bytes
    assert result.document_name.endswith(".xlsx")
    assert "ready" in result.response_text.lower()


async def test_generate_spreadsheet_e2b_fails_fallback_succeeds(sample_context):
    """E2B fails — falls back to local openpyxl JSON spec generation."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="create budget spreadsheet",
    )
    fallback_xlsx = b"PK\x03\x04local-xlsx-output"
    with (
        patch(
            "src.skills.generate_spreadsheet.handler.generate_text",
            new_callable=AsyncMock,
            side_effect=[
                # First call: E2B code generation
                "from openpyxl import Workbook\nwb=Workbook()\nwb.save('/tmp/output.xlsx')",
                # Second call: fallback JSON spec
                '{"title":"Budget","headers":["Item","Amount"],'
                '"rows":[["Rent","1500"]],"column_widths":[20,15]}',
            ],
        ),
        patch(
            "src.tools.e2b_file_utils.execute_code_with_file",
            new_callable=AsyncMock,
            side_effect=Exception("E2B unavailable"),
        ),
        patch(
            "src.skills.generate_spreadsheet.handler._build_fallback_xlsx",
            new_callable=AsyncMock,
            return_value=fallback_xlsx,
        ),
    ):
        result = await skill.execute(msg, sample_context, {"description": "budget spreadsheet"})

    assert result.document == fallback_xlsx
    assert result.document_name.endswith(".xlsx")
    assert "ready" in result.response_text.lower()


async def test_generate_spreadsheet_all_methods_fail(sample_context):
    """Both E2B and fallback fail — returns error message."""
    msg = IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="make a spreadsheet",
    )
    with (
        patch(
            "src.skills.generate_spreadsheet.handler.generate_text",
            new_callable=AsyncMock,
            return_value="code here",
        ),
        patch(
            "src.tools.e2b_file_utils.execute_code_with_file",
            new_callable=AsyncMock,
            side_effect=Exception("E2B down"),
        ),
        patch(
            "src.skills.generate_spreadsheet.handler._build_fallback_xlsx",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await skill.execute(msg, sample_context, {"description": "a spreadsheet"})

    assert "failed" in result.response_text.lower() or "simpler" in result.response_text.lower()
    assert result.document is None
