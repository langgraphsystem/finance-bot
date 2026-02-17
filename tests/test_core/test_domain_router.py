"""Tests for DomainRouter."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.context import SessionContext
from src.core.domain_router import DomainRouter
from src.core.domains import Domain
from src.gateway.types import IncomingMessage, MessageType
from src.skills.base import SkillResult


@pytest.fixture
def mock_agent_router():
    router = MagicMock()
    router.route = AsyncMock(return_value=SkillResult(response_text="agent response"))
    return router


@pytest.fixture
def domain_router(mock_agent_router):
    return DomainRouter(mock_agent_router)


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


@pytest.fixture
def msg():
    return IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text, text="test"
    )


def test_get_domain_finance(domain_router):
    assert domain_router.get_domain("add_expense") == Domain.finance


def test_get_domain_general_fallback(domain_router):
    assert domain_router.get_domain("unknown_intent") == Domain.general


def test_get_domain_life_tracking(domain_router):
    assert domain_router.get_domain("track_food") == Domain.general
    assert domain_router.get_domain("day_plan") == Domain.tasks


async def test_route_delegates_to_agent_router(domain_router, mock_agent_router, msg, ctx):
    """Without orchestrators, DomainRouter delegates to AgentRouter."""
    result = await domain_router.route("add_expense", msg, ctx, {})
    assert result.response_text == "agent response"
    mock_agent_router.route.assert_called_once_with("add_expense", msg, ctx, {"_domain": "finance"})


async def test_route_uses_orchestrator_when_registered(domain_router, msg, ctx):
    """When an orchestrator is registered for a domain, it should be used."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.invoke = AsyncMock(
        return_value=SkillResult(response_text="orchestrator response")
    )
    # Register orchestrator for finance domain (which has known intents)
    domain_router.register_orchestrator(Domain.finance, mock_orchestrator)

    result = await domain_router.route("add_expense", msg, ctx, {})
    assert result.response_text == "orchestrator response"
    mock_orchestrator.invoke.assert_called_once()


async def test_route_adds_domain_to_intent_data(domain_router, mock_agent_router, msg, ctx):
    """DomainRouter should add _domain key to intent_data."""
    intent_data = {"confidence": 0.95}
    await domain_router.route("track_food", msg, ctx, intent_data)
    assert intent_data["_domain"] == "general"


def test_agent_router_property(domain_router, mock_agent_router):
    assert domain_router.agent_router is mock_agent_router
