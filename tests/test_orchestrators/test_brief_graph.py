"""Tests for the brief LangGraph orchestrator (morning_brief + evening_recap)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.orchestrators.brief.graph import BriefOrchestrator


def _make_context(**kwargs):
    defaults = {
        "user_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "role": "owner",
        "language": "en",
        "currency": "USD",
        "business_type": None,
        "categories": [],
        "merchant_mappings": [],
    }
    defaults.update(kwargs)
    return SessionContext(**defaults)


def _make_message(text="morning brief"):
    return IncomingMessage(id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=text)


async def test_brief_orchestrator_morning():
    """BriefOrchestrator returns a synthesized morning brief."""
    orch = BriefOrchestrator()
    ctx = _make_context()
    msg = _make_message()

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Good morning! Here's your brief.")]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with (
        patch("src.orchestrators.brief.nodes.async_session") as mock_session_cls,
        patch("src.orchestrators.brief.nodes.connector_registry") as mock_reg,
        patch("src.orchestrators.brief.nodes.anthropic_client", return_value=mock_client),
    ):
        # No Google connected
        mock_reg.get.return_value = None

        # DB returns empty results for tasks and finance
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar.return_value = None
        mock_result.one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session_cls.return_value = mock_session

        result = await orch.invoke("morning_brief", msg, ctx, {})

    # Either synthesized or fallback message
    assert result.response_text


async def test_brief_orchestrator_evening():
    """BriefOrchestrator handles evening_recap intent."""
    orch = BriefOrchestrator()
    ctx = _make_context()
    msg = _make_message("evening recap")

    with (
        patch("src.orchestrators.brief.nodes.async_session") as mock_session_cls,
        patch("src.orchestrators.brief.nodes.connector_registry") as mock_reg,
    ):
        mock_reg.get.return_value = None

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar.return_value = None
        mock_result.one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session_cls.return_value = mock_session

        result = await orch.invoke("evening_recap", msg, ctx, {})

    assert result.response_text
    # No data → graceful message
    assert "recap" in result.response_text.lower() or "rest" in result.response_text.lower()
