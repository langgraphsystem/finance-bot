"""Tests for delete_data skill."""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.delete_data.handler import (
    DeleteDataSkill,
    _resolve_date_range,
)

MODULE = "src.skills.delete_data.handler"


@pytest.fixture
def skill():
    return DeleteDataSkill()


@pytest.fixture
def msg():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_user_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="удали мои расходы за январь",
    )


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="household",
        categories=[],
        merchant_mappings=[],
    )


# ---- _resolve_date_range tests ----


def test_resolve_date_range_today():
    start, end = _resolve_date_range("today", None, None)
    assert start == date.today()
    assert end == date.today()


def test_resolve_date_range_yesterday():
    start, end = _resolve_date_range("yesterday", None, None)
    assert start == date.today() - timedelta(days=1)
    assert end == start


def test_resolve_date_range_week():
    start, end = _resolve_date_range("week", None, None)
    assert start == date.today() - timedelta(days=7)
    assert end == date.today()


def test_resolve_date_range_month():
    start, end = _resolve_date_range("month", None, None)
    assert start == date.today().replace(day=1)
    assert end == date.today()


def test_resolve_date_range_year():
    start, end = _resolve_date_range("year", None, None)
    assert start == date.today().replace(month=1, day=1)
    assert end == date.today()


def test_resolve_date_range_custom():
    start, end = _resolve_date_range("custom", "2026-01-01", "2026-01-31")
    assert start == date(2026, 1, 1)
    assert end == date(2026, 1, 31)


def test_resolve_date_range_date_from_only():
    start, end = _resolve_date_range(None, "2026-01-01", None)
    assert start == date(2026, 1, 1)
    assert end == date.today()


def test_resolve_date_range_none():
    start, end = _resolve_date_range(None, None, None)
    assert start is None
    assert end is None


# ---- Skill.execute tests ----


async def test_unknown_scope_returns_help(skill, msg, ctx):
    result = await skill.execute(msg, ctx, {"delete_scope": "invalid_scope"})
    assert "Укажите" in result.response_text


async def test_empty_scope_returns_help(skill, msg, ctx):
    result = await skill.execute(msg, ctx, {})
    assert "Укажите" in result.response_text


async def test_zero_records_returns_nothing(skill, msg, ctx):
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODULE}.async_session", return_value=mock_ctx):
        result = await skill.execute(msg, ctx, {"delete_scope": "expenses", "period": "today"})

    assert "Нет записей" in result.response_text
    assert result.buttons is None


async def test_returns_confirmation_with_buttons(skill, msg, ctx):
    mock_result = MagicMock()
    mock_result.scalar.return_value = 5

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(f"{MODULE}.async_session", return_value=mock_ctx),
        patch(f"{MODULE}.store_pending_action", new_callable=AsyncMock, return_value="abc123"),
    ):
        result = await skill.execute(
            msg, ctx, {"delete_scope": "expenses", "period": "month"}
        )

    assert "5" in result.response_text
    assert "необратимо" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    assert "confirm_action:abc123" in result.buttons[0]["callback"]
    assert "cancel_action:abc123" in result.buttons[1]["callback"]


async def test_scope_alias_resolves(skill, msg, ctx):
    """Russian alias 'расходы' should resolve to 'expenses'."""
    mock_result = MagicMock()
    mock_result.scalar.return_value = 3

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(f"{MODULE}.async_session", return_value=mock_ctx),
        patch(f"{MODULE}.store_pending_action", new_callable=AsyncMock, return_value="def456"),
    ):
        result = await skill.execute(
            msg, ctx, {"delete_scope": "расходы", "period": "week"}
        )

    assert "3" in result.response_text
    assert result.buttons is not None


# ---- execute_delete tests ----


async def test_execute_delete_commits_and_logs():
    from src.skills.delete_data.handler import execute_delete

    mock_exec_result = MagicMock()
    mock_exec_result.rowcount = 7

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_exec_result
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    action_data = {
        "scope": "expenses",
        "period": "month",
        "date_from": None,
        "date_to": None,
        "count": 7,
    }

    with patch(f"{MODULE}.async_session", return_value=mock_ctx):
        result = await execute_delete(action_data, str(uuid.uuid4()), str(uuid.uuid4()))

    assert "7" in result
    assert "расходы" in result


async def test_execute_delete_all_scope():
    from src.skills.delete_data.handler import execute_delete

    mock_exec_result = MagicMock()
    mock_exec_result.rowcount = 2

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_exec_result
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    action_data = {
        "scope": "all",
        "period": None,
        "date_from": None,
        "date_to": None,
        "count": 10,
    }

    with patch(f"{MODULE}.async_session", return_value=mock_ctx):
        result = await execute_delete(action_data, str(uuid.uuid4()), str(uuid.uuid4()))

    # "all" scope deletes across 5 sub-scopes, each returning 2 = 10 total
    assert "10" in result
    assert "все данные" in result


def test_skill_attributes():
    s = DeleteDataSkill()
    assert s.name == "delete_data"
    assert s.intents == ["delete_data"]
    assert s.model == "gpt-5.2"
    assert hasattr(s, "execute")
    assert hasattr(s, "get_system_prompt")
