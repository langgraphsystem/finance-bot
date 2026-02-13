"""Tests for smart notification system (anomalies, budgets, collect, format)."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to build mock DB rows
# ---------------------------------------------------------------------------

FAMILY_ID = str(uuid.uuid4())


def _make_row(*values):
    """Create a tuple-like mock row for SQLAlchemy result.all()."""
    return tuple(values)


def _scalar_result(value):
    """Mock execute() result whose .scalar() returns *value*."""
    mock = MagicMock()
    mock.scalar.return_value = value
    return mock


def _scalars_result(items):
    """Mock execute() result whose .scalars().all() returns *items*."""
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = items
    return mock


def _rows_result(rows):
    """Mock execute() result whose .all() returns *rows*."""
    mock = MagicMock()
    mock.all.return_value = rows
    return mock


# ---------------------------------------------------------------------------
# check_anomalies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_anomalies_normal_spending():
    """No alert when today's spending is within normal range."""
    today_rows = [_make_row("Food", Decimal("20"))]
    avg_rows = [_make_row("Food", Decimal("15"))]  # ratio = 1.33, below 2.5

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(side_effect=[_rows_result(today_rows), _rows_result(avg_rows)])

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.notifications.async_session", return_value=ctx):
        from src.core.notifications import check_anomalies

        alerts = await check_anomalies(FAMILY_ID)

    assert alerts == []


@pytest.mark.asyncio
async def test_check_anomalies_high_spending():
    """Alert generated when spending > 2.5x the daily average."""
    today_rows = [_make_row("Restaurants", Decimal("340"))]
    avg_rows = [_make_row("Restaurants", Decimal("100"))]  # ratio = 3.4

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(side_effect=[_rows_result(today_rows), _rows_result(avg_rows)])

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.notifications.async_session", return_value=ctx):
        from src.core.notifications import check_anomalies

        alerts = await check_anomalies(FAMILY_ID)

    assert len(alerts) == 1
    assert "Restaurants" in alerts[0]
    assert "x3.4" in alerts[0]


@pytest.mark.asyncio
async def test_check_anomalies_no_average():
    """No alert when there is no historical average (new category)."""
    today_rows = [_make_row("NewCat", Decimal("50"))]
    avg_rows = []  # no history

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(side_effect=[_rows_result(today_rows), _rows_result(avg_rows)])

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.notifications.async_session", return_value=ctx):
        from src.core.notifications import check_anomalies

        alerts = await check_anomalies(FAMILY_ID)

    assert alerts == []


# ---------------------------------------------------------------------------
# check_budgets
# ---------------------------------------------------------------------------


def _make_budget(amount, spent, alert_at=0.8, period="monthly", category_id=None, cat_name=None):
    """Return (budget_mock, expected_execute_side_effects)."""
    budget = MagicMock()
    budget.family_id = uuid.UUID(FAMILY_ID)
    budget.category_id = category_id
    budget.amount = Decimal(str(amount))
    budget.alert_at = Decimal(str(alert_at))
    budget.is_active = True
    budget.period = MagicMock()
    budget.period.value = period

    effects = [
        _scalars_result([budget]),  # budgets query
        _scalar_result(Decimal(str(spent))),  # spending query
    ]
    if category_id:
        effects.append(_scalar_result(cat_name or "Category"))
    return budget, effects


@pytest.mark.asyncio
async def test_check_budgets_at_80_percent():
    """Alert at 80% threshold."""
    cat_id = uuid.uuid4()
    _, effects = _make_budget(500, 420, alert_at=0.8, category_id=cat_id, cat_name="Groceries")

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(side_effect=effects)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.notifications.async_session", return_value=ctx):
        from src.core.notifications import check_budgets

        alerts = await check_budgets(FAMILY_ID)

    assert len(alerts) == 1
    assert "84%" in alerts[0]
    assert "Groceries" in alerts[0]


@pytest.mark.asyncio
async def test_check_budgets_exceeded():
    """Alert when budget is exceeded (>= 100%)."""
    cat_id = uuid.uuid4()
    _, effects = _make_budget(500, 520, alert_at=0.8, category_id=cat_id, cat_name="Groceries")

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(side_effect=effects)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.notifications.async_session", return_value=ctx):
        from src.core.notifications import check_budgets

        alerts = await check_budgets(FAMILY_ID)

    assert len(alerts) == 1
    assert "\u043f\u0440\u0435\u0432\u044b\u0448\u0435\u043d" in alerts[0]
    assert "$520.00" in alerts[0]
    assert "$500.00" in alerts[0]


@pytest.mark.asyncio
async def test_check_budgets_under_threshold():
    """No alert when spending is below alert_at threshold."""
    cat_id = uuid.uuid4()
    _, effects = _make_budget(500, 200, alert_at=0.8, category_id=cat_id, cat_name="Food")

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(side_effect=effects)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.notifications.async_session", return_value=ctx):
        from src.core.notifications import check_budgets

        alerts = await check_budgets(FAMILY_ID)

    assert alerts == []


@pytest.mark.asyncio
async def test_check_budgets_no_category():
    """Budget without category_id uses general label."""
    _, effects = _make_budget(1000, 1050, alert_at=0.8, category_id=None)

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(side_effect=effects)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.notifications.async_session", return_value=ctx):
        from src.core.notifications import check_budgets

        alerts = await check_budgets(FAMILY_ID)

    assert len(alerts) == 1
    assert "\u041e\u0431\u0449\u0438\u0439" in alerts[0]


# ---------------------------------------------------------------------------
# collect_alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_alerts_combines():
    """collect_alerts combines anomaly and budget alerts."""
    with (
        patch(
            "src.core.notifications.check_anomalies",
            new_callable=AsyncMock,
            return_value=["anomaly1"],
        ),
        patch(
            "src.core.notifications.check_budgets",
            new_callable=AsyncMock,
            return_value=["budget1", "budget2"],
        ),
    ):
        from src.core.notifications import collect_alerts

        alerts = await collect_alerts(FAMILY_ID)

    assert alerts == ["anomaly1", "budget1", "budget2"]


@pytest.mark.asyncio
async def test_collect_alerts_anomaly_failure():
    """If anomaly check fails, budget alerts are still collected."""
    with (
        patch(
            "src.core.notifications.check_anomalies",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db error"),
        ),
        patch(
            "src.core.notifications.check_budgets",
            new_callable=AsyncMock,
            return_value=["budget1"],
        ),
    ):
        from src.core.notifications import collect_alerts

        alerts = await collect_alerts(FAMILY_ID)

    assert alerts == ["budget1"]


@pytest.mark.asyncio
async def test_collect_alerts_budget_failure():
    """If budget check fails, anomaly alerts are still collected."""
    with (
        patch(
            "src.core.notifications.check_anomalies",
            new_callable=AsyncMock,
            return_value=["anomaly1"],
        ),
        patch(
            "src.core.notifications.check_budgets",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db error"),
        ),
    ):
        from src.core.notifications import collect_alerts

        alerts = await collect_alerts(FAMILY_ID)

    assert alerts == ["anomaly1"]


# ---------------------------------------------------------------------------
# format_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_format_notification_empty():
    """Empty alerts list produces empty string."""
    from src.core.notifications import format_notification

    result = await format_notification([])
    assert result == ""


@pytest.mark.asyncio
async def test_format_notification_with_alerts():
    """Non-empty alerts are formatted with header."""
    from src.core.notifications import format_notification

    result = await format_notification(["alert1", "alert2"])
    assert "Финансовые уведомления" in result
    assert "alert1" in result
    assert "alert2" in result


@pytest.mark.asyncio
async def test_format_notification_single_alert():
    """Single alert is formatted correctly without extra newlines."""
    from src.core.notifications import format_notification

    result = await format_notification(["one alert"])
    lines = result.strip().split("\n")
    # header line + empty line + alert line
    assert len(lines) == 3
    assert lines[2] == "one alert"
