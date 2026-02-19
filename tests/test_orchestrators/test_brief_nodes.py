"""Tests for brief orchestrator individual nodes."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrators.brief.nodes import (
    collect_calendar,
    collect_email,
    collect_finance,
    collect_outstanding,
    collect_tasks,
    synthesize,
)


async def test_collect_calendar_no_google():
    with patch("src.orchestrators.brief.nodes.connector_registry") as mock_reg:
        mock_reg.get.return_value = None
        result = await collect_calendar({"user_id": "u1"})
    assert result["calendar_data"] == ""


async def test_collect_tasks_morning_no_tasks():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.orchestrators.brief.nodes.async_session",
        return_value=mock_session,
    ):
        result = await collect_tasks(
            {"intent": "morning_brief", "user_id": "u1", "family_id": "f1"}
        )
    assert result["tasks_data"] == ""


async def test_collect_tasks_evening_no_tasks():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.orchestrators.brief.nodes.async_session",
        return_value=mock_session,
    ):
        result = await collect_tasks(
            {"intent": "evening_recap", "user_id": "u1", "family_id": "f1"}
        )
    assert result["tasks_data"] == ""


async def test_collect_finance_no_data():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.orchestrators.brief.nodes.async_session",
        return_value=mock_session,
    ):
        result = await collect_finance({"intent": "morning_brief", "family_id": "f1"})
    assert result["finance_data"] == ""


async def test_collect_email_no_google():
    with patch("src.orchestrators.brief.nodes.connector_registry") as mock_reg:
        mock_reg.get.return_value = None
        result = await collect_email({"user_id": "u1"})
    assert result["email_data"] == ""


async def test_collect_outstanding_no_overdue():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.orchestrators.brief.nodes.async_session",
        return_value=mock_session,
    ):
        result = await collect_outstanding({"family_id": "f1"})
    assert result["outstanding_data"] == ""


async def test_synthesize_no_data_morning():
    result = await synthesize(
        {
            "intent": "morning_brief",
            "language": "en",
            "active_sections": ["schedule", "tasks"],
            "calendar_data": "",
            "tasks_data": "",
            "finance_data": "",
            "email_data": "",
            "outstanding_data": "",
        }
    )
    assert "brief" in result["response_text"].lower() or "load" in result["response_text"].lower()


async def test_synthesize_no_data_evening():
    result = await synthesize(
        {
            "intent": "evening_recap",
            "language": "en",
            "active_sections": ["completed_tasks", "spending_total"],
            "calendar_data": "",
            "tasks_data": "",
            "finance_data": "",
            "email_data": "",
            "outstanding_data": "",
        }
    )
    assert "recap" in result["response_text"].lower() or "rest" in result["response_text"].lower()


async def test_synthesize_with_data():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Here's your morning summary.")]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch(
        "src.orchestrators.brief.nodes.anthropic_client",
        return_value=mock_client,
    ):
        result = await synthesize(
            {
                "intent": "morning_brief",
                "language": "en",
                "active_sections": ["tasks", "money_summary"],
                "calendar_data": "",
                "tasks_data": "Open tasks (2):\n- Buy milk\n- Fix faucet",
                "finance_data": "Money:\n- Yesterday: $50.00 spent",
                "email_data": "",
                "outstanding_data": "",
            }
        )
    assert result["response_text"] == "Here's your morning summary."
    mock_client.messages.create.assert_called_once()
