"""Tests for the approval (pending action) LangGraph orchestrator."""

from unittest.mock import AsyncMock, patch

import pytest

from src.orchestrators.approval.state import ApprovalState


@pytest.mark.asyncio
async def test_start_approval_returns_buttons():
    """start_approval should return a SkillResult with confirmation buttons."""
    with patch(
        "src.orchestrators.approval.graph._approval_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value={
            "__interrupt__": [{"type": "pending_action_approval"}],
        })

        from src.orchestrators.approval.graph import start_approval

        result = await start_approval(
            intent="send_email",
            user_id="user-1",
            family_id="fam-1",
            action_data={"email_to": "test@example.com"},
            preview_text="Send email to test@example.com?",
        )

    assert result.response_text == "Send email to test@example.com?"
    assert len(result.buttons) == 2
    assert result.buttons[0]["text"] == "✅ Confirm"
    assert "graph_resume:" in result.buttons[0]["callback"]
    assert ":yes" in result.buttons[0]["callback"]
    assert result.buttons[1]["text"] == "❌ Cancel"
    assert ":no" in result.buttons[1]["callback"]


@pytest.mark.asyncio
async def test_resume_approval_yes():
    """Resuming with 'yes' should execute the action."""
    with patch(
        "src.orchestrators.approval.graph._approval_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value={
            "result_text": "Email sent!",
        })

        from src.orchestrators.approval.graph import resume_approval

        result = await resume_approval("approval-abc123", "yes")

    assert result == "Email sent!"


@pytest.mark.asyncio
async def test_resume_approval_no():
    """Resuming with 'no' should cancel."""
    with patch(
        "src.orchestrators.approval.graph._approval_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value={
            "result_text": "Cancelled.",
        })

        from src.orchestrators.approval.graph import resume_approval

        result = await resume_approval("approval-abc123", "no")

    assert result == "Cancelled."


@pytest.mark.asyncio
async def test_resume_approval_error_handling():
    """Resuming should handle errors gracefully."""
    with patch(
        "src.orchestrators.approval.graph._approval_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("db down"))

        from src.orchestrators.approval.graph import resume_approval

        result = await resume_approval("approval-abc123", "yes")

    assert "Error" in result


@pytest.mark.asyncio
async def test_approval_node_interrupt():
    """The ask_approval node should call interrupt()."""
    with patch(
        "src.orchestrators.approval.nodes.interrupt",
        return_value="yes",
    ) as mock_interrupt:
        from src.orchestrators.approval.nodes import ask_approval

        state: ApprovalState = {
            "intent": "delete_data",
            "user_id": "u1",
            "family_id": "f1",
            "action_data": {"table": "transactions"},
            "approved": False,
            "result_text": "",
        }
        result = await ask_approval(state)

    mock_interrupt.assert_called_once()
    assert result["approved"] is True


@pytest.mark.asyncio
async def test_execute_action_cancelled():
    """Execute node should return cancellation when not approved."""
    from src.orchestrators.approval.nodes import execute_action

    state: ApprovalState = {
        "intent": "send_email",
        "user_id": "u1",
        "family_id": "f1",
        "action_data": {},
        "approved": False,
        "result_text": "",
    }
    result = await execute_action(state)
    assert result["result_text"] == "Cancelled."


@pytest.mark.asyncio
async def test_execute_action_unknown_intent():
    """Unknown intent returns a message, not an error."""
    from src.orchestrators.approval.nodes import execute_action

    state: ApprovalState = {
        "intent": "unknown_intent",
        "user_id": "u1",
        "family_id": "f1",
        "action_data": {},
        "approved": True,
        "result_text": "",
    }
    result = await execute_action(state)
    assert result["result_text"] == "Unknown action."
