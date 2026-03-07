"""Regression tests for intents that must bypass tool-augmented routing."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("APP_ENV", "testing")

from src.agents.base import AgentRouter
from src.agents.config import AGENTS
from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.base import SkillRegistry, SkillResult


def _make_mock_skill(name: str, intents: list[str]) -> MagicMock:
    skill = MagicMock()
    skill.name = name
    skill.intents = intents
    skill.model = "test-model"
    skill.get_system_prompt = MagicMock(return_value="test prompt")
    skill.execute = AsyncMock(return_value=SkillResult(response_text=f"Response from {name}"))
    return skill


@pytest.fixture
def sample_context():
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


@pytest.fixture
def text_message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_100",
        chat_id="chat_100",
        type=MessageType.text,
        text="test",
    )


@pytest.fixture
def agent_router():
    registry = SkillRegistry()
    for skill in (
        _make_mock_skill("track_drink", ["track_drink"]),
        _make_mock_skill("list_bookings", ["list_bookings"]),
        _make_mock_skill("shopping_list_add", ["shopping_list_add"]),
        _make_mock_skill("general_chat", ["general_chat"]),
    ):
        registry.register(skill)
    return AgentRouter(AGENTS, registry)


@pytest.mark.asyncio
async def test_track_drink_bypasses_tool_routing(
    agent_router, sample_context, text_message, monkeypatch
):
    monkeypatch.setattr("src.agents.base.assemble_context", AsyncMock(return_value=MagicMock()))
    route_with_tools = AsyncMock(return_value=SkillResult(response_text="tool response"))
    monkeypatch.setattr(agent_router, "route_with_tools", route_with_tools)

    result = await agent_router.route("track_drink", text_message, sample_context, {})

    assert result.response_text == "Response from track_drink"
    route_with_tools.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_bookings_bypasses_tool_routing(
    agent_router, sample_context, text_message, monkeypatch
):
    monkeypatch.setattr("src.agents.base.assemble_context", AsyncMock(return_value=MagicMock()))
    route_with_tools = AsyncMock(return_value=SkillResult(response_text="tool response"))
    monkeypatch.setattr(agent_router, "route_with_tools", route_with_tools)

    result = await agent_router.route("list_bookings", text_message, sample_context, {})

    assert result.response_text == "Response from list_bookings"
    route_with_tools.assert_not_awaited()


@pytest.mark.asyncio
async def test_shopping_list_add_bypasses_tool_routing(
    agent_router, sample_context, text_message, monkeypatch
):
    monkeypatch.setattr("src.agents.base.assemble_context", AsyncMock(return_value=MagicMock()))
    route_with_tools = AsyncMock(return_value=SkillResult(response_text="tool response"))
    monkeypatch.setattr(agent_router, "route_with_tools", route_with_tools)

    result = await agent_router.route("shopping_list_add", text_message, sample_context, {})

    assert result.response_text == "Response from shopping_list_add"
    route_with_tools.assert_not_awaited()
