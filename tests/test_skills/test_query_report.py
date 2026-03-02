"""Tests for query_report skill."""

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.query_report.handler import (
    QueryReportSkill,
    _parse_report_period,
    _prev_month,
    _user_explicitly_chose_period,
)

_HAS_TXN = "src.skills.query_report.handler.has_transactions_for_period"
_GEN_REPORT = "src.skills.query_report.handler.generate_monthly_report"
_CLARIFY = "src.skills._clarification.maybe_ask_period"


def _ctx(**overrides):
    defaults = dict(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="trucker",
        categories=[],
        merchant_mappings=[],
    )
    defaults.update(overrides)
    return SessionContext(**defaults)


def _msg(text="покажи отчёт"):
    return IncomingMessage(
        id="msg-1", user_id="tg_user_1", chat_id="chat_1",
        type=MessageType.text, text=text,
    )


def _skill():
    return QueryReportSkill()


# --- basic tests ---


def test_skill_attributes():
    skill = _skill()
    assert skill.name == "query_report"
    assert "query_report" in skill.intents
    assert hasattr(skill, "model")
    assert hasattr(skill, "execute")
    assert hasattr(skill, "get_system_prompt")


def test_skill_system_prompt():
    prompt = _skill().get_system_prompt(_ctx())
    assert isinstance(prompt, str) and len(prompt) > 0


# --- _parse_report_period ---


def test_parse_report_period_default():
    today = date.today()
    year, month = _parse_report_period({})
    assert (year, month) == (today.year, today.month)


def test_parse_report_period_prev_month():
    today = date.today()
    year, month = _parse_report_period({"period": "prev_month"})
    assert (year, month) == _prev_month(today.year, today.month)


def test_parse_report_period_explicit_date():
    assert _parse_report_period({"date": "2025-06-15"}) == (2025, 6)


def test_parse_report_period_date_from():
    assert _parse_report_period({"date_from": "2026-01-01"}) == (2026, 1)


# --- _user_explicitly_chose_period ---


def test_explicit_period_true():
    assert _user_explicitly_chose_period({"period": "prev_month"}) is True
    assert _user_explicitly_chose_period({"date": "2026-01-01"}) is True


def test_explicit_period_false():
    assert _user_explicitly_chose_period({}) is False


# --- execute: happy path (data exists) ---


async def test_returns_pdf_when_data_exists():
    pdf = b"%PDF-1.4 test"
    with (
        patch(_CLARIFY, new_callable=AsyncMock, return_value=None),
        patch(_HAS_TXN, new_callable=AsyncMock, return_value=True),
        patch(_GEN_REPORT, new_callable=AsyncMock, return_value=(pdf, "r.pdf")),
    ):
        result = await _skill().execute(_msg(), _ctx(), {})
    assert result.document == pdf
    assert result.document_name == "r.pdf"
    assert "отчёт" in result.response_text.lower()


async def test_passes_family_and_period():
    today = date.today()
    ctx = _ctx()
    with (
        patch(_CLARIFY, new_callable=AsyncMock, return_value=None),
        patch(_HAS_TXN, new_callable=AsyncMock, return_value=True),
        patch(
            _GEN_REPORT, new_callable=AsyncMock, return_value=(b"p", "r.pdf"),
        ) as mock_gen,
    ):
        await _skill().execute(_msg(), ctx, {})
    mock_gen.assert_awaited_once_with(
        family_id=ctx.family_id,
        year=today.year,
        month=today.month,
        language="ru",
    )


async def test_passes_prev_month_period():
    today = date.today()
    ey, em = _prev_month(today.year, today.month)
    ctx = _ctx()
    with (
        patch(_CLARIFY, new_callable=AsyncMock, return_value=None),
        patch(_HAS_TXN, new_callable=AsyncMock, return_value=True),
        patch(
            _GEN_REPORT, new_callable=AsyncMock, return_value=(b"p", "r.pdf"),
        ) as mock_gen,
    ):
        await _skill().execute(_msg(), ctx, {"period": "prev_month"})
    mock_gen.assert_awaited_once_with(
        family_id=ctx.family_id, year=ey, month=em, language="ru",
    )


# --- execute: no data — fallback to previous month ---


async def test_no_data_current_month_falls_back_to_prev():
    """If current month is empty, auto-generates previous month report."""
    pdf = b"%PDF-fallback"
    today = date.today()
    py, pm = _prev_month(today.year, today.month)

    async def _has_txn(fid, y, m):
        return (y, m) == (py, pm)

    with (
        patch(_CLARIFY, new_callable=AsyncMock, return_value=None),
        patch(_HAS_TXN, side_effect=_has_txn),
        patch(
            _GEN_REPORT, new_callable=AsyncMock, return_value=(pdf, "r.pdf"),
        ) as mock_gen,
    ):
        result = await _skill().execute(_msg(), _ctx(), {})

    assert result.document == pdf
    assert "не найдено" in result.response_text.lower()
    mock_gen.assert_awaited_once()
    call_kwargs = mock_gen.call_args.kwargs
    assert call_kwargs["year"] == py
    assert call_kwargs["month"] == pm


async def test_no_data_anywhere_returns_text_only():
    """Neither current nor previous month has data — text message only."""
    with (
        patch(_CLARIFY, new_callable=AsyncMock, return_value=None),
        patch(_HAS_TXN, new_callable=AsyncMock, return_value=False),
    ):
        result = await _skill().execute(_msg(), _ctx(), {})
    assert result.document is None
    assert "не найдено" in result.response_text.lower()


# --- execute: explicit period with no data ---


async def test_explicit_period_no_data_returns_text():
    """User chose a specific period with no data — don't auto-fallback."""
    with (
        patch(_CLARIFY, new_callable=AsyncMock, return_value=None),
        patch(_HAS_TXN, new_callable=AsyncMock, return_value=False),
    ):
        result = await _skill().execute(
            _msg(), _ctx(), {"date": "2025-08-01"},
        )
    assert result.document is None
    assert "не найдено" in result.response_text.lower()


# --- execute: error handling ---


async def test_error_returns_error_message():
    with (
        patch(_CLARIFY, new_callable=AsyncMock, return_value=None),
        patch(
            _HAS_TXN, new_callable=AsyncMock,
            side_effect=RuntimeError("DB down"),
        ),
    ):
        result = await _skill().execute(_msg(), _ctx(), {})
    assert result.document is None
    assert "Ошибка" in result.response_text


# --- i18n ---


async def test_english_no_data_message():
    ctx = _ctx(language="en")
    with (
        patch(_CLARIFY, new_callable=AsyncMock, return_value=None),
        patch(_HAS_TXN, new_callable=AsyncMock, return_value=False),
    ):
        result = await _skill().execute(_msg(), ctx, {"date": "2025-08-01"})
    assert "no transactions" in result.response_text.lower()


async def test_spanish_report_ready():
    ctx = _ctx(language="es")
    pdf = b"%PDF"
    with (
        patch(_CLARIFY, new_callable=AsyncMock, return_value=None),
        patch(_HAS_TXN, new_callable=AsyncMock, return_value=True),
        patch(_GEN_REPORT, new_callable=AsyncMock, return_value=(pdf, "r.pdf")),
    ):
        result = await _skill().execute(_msg(), ctx, {})
    assert "informe" in result.response_text.lower()
