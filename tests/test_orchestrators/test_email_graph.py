"""Tests for the email LangGraph orchestrator."""

import uuid
from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.orchestrators.email.graph import EmailOrchestrator


def _make_context():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


def _make_message(text="read my inbox"):
    return IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=text
    )


async def test_email_orchestrator_simple_intent_uses_agent_router():
    """Simple intents like read_inbox should go through AgentRouter."""
    mock_agent_router = AsyncMock()
    mock_agent_router.route = AsyncMock(
        return_value=AsyncMock(response_text="You have 3 unread emails.")
    )

    orch = EmailOrchestrator(agent_router=mock_agent_router)
    ctx = _make_context()
    msg = _make_message("read my inbox")

    result = await orch.invoke("read_inbox", msg, ctx, {})
    mock_agent_router.route.assert_called_once()
    assert "3 unread" in result.response_text


async def test_email_orchestrator_compose_intent_uses_graph():
    """Compose intents like send_email should attempt LangGraph first."""
    orch = EmailOrchestrator(agent_router=AsyncMock())

    with patch(
        "src.orchestrators.email.graph._email_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(
            return_value={"response_text": "Draft ready for review."}
        )
        ctx = _make_context()
        msg = _make_message("send email to john")

        result = await orch.invoke("send_email", msg, ctx, {})

    assert result.response_text == "Draft ready for review."


async def test_email_orchestrator_graph_fallback_on_error():
    """If graph fails for compose intent, fall back to AgentRouter."""
    mock_agent_router = AsyncMock()
    mock_agent_router.route = AsyncMock(
        return_value=AsyncMock(response_text="Email sent via fallback.")
    )

    orch = EmailOrchestrator(agent_router=mock_agent_router)

    with patch(
        "src.orchestrators.email.graph._email_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("graph broke"))
        ctx = _make_context()
        msg = _make_message("send email to john")

        result = await orch.invoke("send_email", msg, ctx, {})

    # Falls back to agent router
    mock_agent_router.route.assert_called_once()
    assert "fallback" in result.response_text.lower()


async def test_email_orchestrator_graph_intents():
    """Verify which intents are routed through the graph."""
    assert "send_email" in EmailOrchestrator._GRAPH_INTENTS
    assert "draft_reply" in EmailOrchestrator._GRAPH_INTENTS
    assert "read_inbox" not in EmailOrchestrator._GRAPH_INTENTS
    assert "summarize_thread" not in EmailOrchestrator._GRAPH_INTENTS
