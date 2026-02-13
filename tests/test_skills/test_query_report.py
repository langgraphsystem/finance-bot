"""Tests for query_report skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.query_report.handler import QueryReportSkill


@pytest.fixture
def report_skill():
    return QueryReportSkill()


@pytest.fixture
def sample_message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_user_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="покажи отчёт",
    )


@pytest.fixture
def sample_ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="trucker",
        categories=[],
        merchant_mappings=[],
    )


@pytest.mark.asyncio
async def test_skill_returns_pdf_document(report_skill, sample_message, sample_ctx):
    """Skill should return a SkillResult with PDF document bytes and filename."""
    fake_pdf = b"%PDF-1.4 test report content"
    fake_filename = "report_2026_02.pdf"

    with patch(
        "src.skills.query_report.handler.generate_monthly_report",
        new_callable=AsyncMock,
        return_value=(fake_pdf, fake_filename),
    ):
        result = await report_skill.execute(sample_message, sample_ctx, {})

    assert result.document == fake_pdf
    assert result.document_name == fake_filename
    assert "отчёт" in result.response_text.lower()


@pytest.mark.asyncio
async def test_skill_handles_error_gracefully(report_skill, sample_message, sample_ctx):
    """Skill should return error message when report generation fails."""
    with patch(
        "src.skills.query_report.handler.generate_monthly_report",
        new_callable=AsyncMock,
        side_effect=RuntimeError("DB connection failed"),
    ):
        result = await report_skill.execute(sample_message, sample_ctx, {})

    assert result.document is None
    assert result.document_name is None
    assert "Ошибка" in result.response_text


@pytest.mark.asyncio
async def test_skill_passes_family_id_to_report(report_skill, sample_message, sample_ctx):
    """Skill should pass the context family_id to generate_monthly_report."""
    fake_pdf = b"%PDF"

    with patch(
        "src.skills.query_report.handler.generate_monthly_report",
        new_callable=AsyncMock,
        return_value=(fake_pdf, "report.pdf"),
    ) as mock_gen:
        await report_skill.execute(sample_message, sample_ctx, {})

    mock_gen.assert_awaited_once_with(family_id=sample_ctx.family_id)


def test_skill_attributes():
    """Skill has required attributes for registry."""
    skill = QueryReportSkill()
    assert skill.name == "query_report"
    assert "query_report" in skill.intents
    assert hasattr(skill, "model")
    assert hasattr(skill, "execute")
    assert hasattr(skill, "get_system_prompt")


def test_skill_system_prompt(report_skill, sample_ctx):
    """System prompt is a non-empty string."""
    prompt = report_skill.get_system_prompt(sample_ctx)
    assert isinstance(prompt, str)
    assert len(prompt) > 0
