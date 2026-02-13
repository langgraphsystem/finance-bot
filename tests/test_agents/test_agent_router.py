"""Tests for AgentRouter multi-agent routing system."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set test environment before importing app modules
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("APP_ENV", "testing")

from src.agents.base import AgentConfig, AgentRouter
from src.agents.config import AGENTS
from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.base import SkillRegistry, SkillResult

# --- Fixtures ---


@pytest.fixture
def sample_context():
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


@pytest.fixture
def text_message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_100",
        chat_id="chat_100",
        type=MessageType.text,
        text="заправился на 50",
    )


def _make_mock_skill(name: str, intents: list[str]) -> MagicMock:
    """Create a mock skill with the required interface."""
    skill = MagicMock()
    skill.name = name
    skill.intents = intents
    skill.model = "test-model"
    skill.get_system_prompt = MagicMock(return_value="test prompt")
    skill.execute = AsyncMock(return_value=SkillResult(response_text=f"Response from {name}"))
    return skill


@pytest.fixture
def mock_registry():
    """A SkillRegistry populated with mock skills."""
    registry = SkillRegistry()
    skills = [
        _make_mock_skill("scan_receipt", ["scan_receipt"]),
        _make_mock_skill("query_stats", ["query_stats"]),
        _make_mock_skill("add_expense", ["add_expense"]),
        _make_mock_skill("add_income", ["add_income"]),
        _make_mock_skill("correct_category", ["correct_category"]),
        _make_mock_skill("undo_last", ["undo_last"]),
        _make_mock_skill("onboarding", ["onboarding"]),
        _make_mock_skill("general_chat", ["general_chat"]),
    ]
    for s in skills:
        registry.register(s)
    return registry


@pytest.fixture
def agent_router(mock_registry):
    return AgentRouter(AGENTS, mock_registry)


# --- Tests: intent-to-agent mapping ---


class TestIntentToAgentMapping:
    """Test that intents are correctly mapped to agents."""

    def test_scan_receipt_maps_to_receipt_agent(self, agent_router):
        agent = agent_router.get_agent("scan_receipt")
        assert agent is not None
        assert agent.name == "receipt"

    def test_query_stats_maps_to_analytics_agent(self, agent_router):
        agent = agent_router.get_agent("query_stats")
        assert agent is not None
        assert agent.name == "analytics"

    def test_add_expense_maps_to_chat_agent(self, agent_router):
        agent = agent_router.get_agent("add_expense")
        assert agent is not None
        assert agent.name == "chat"

    def test_add_income_maps_to_chat_agent(self, agent_router):
        agent = agent_router.get_agent("add_income")
        assert agent is not None
        assert agent.name == "chat"

    def test_correct_category_maps_to_chat_agent(self, agent_router):
        agent = agent_router.get_agent("correct_category")
        assert agent is not None
        assert agent.name == "chat"

    def test_undo_last_maps_to_chat_agent(self, agent_router):
        agent = agent_router.get_agent("undo_last")
        assert agent is not None
        assert agent.name == "chat"

    def test_onboarding_maps_to_onboarding_agent(self, agent_router):
        agent = agent_router.get_agent("onboarding")
        assert agent is not None
        assert agent.name == "onboarding"

    def test_general_chat_maps_to_onboarding_agent(self, agent_router):
        agent = agent_router.get_agent("general_chat")
        assert agent is not None
        assert agent.name == "onboarding"

    def test_unknown_intent_returns_none(self, agent_router):
        agent = agent_router.get_agent("totally_unknown")
        assert agent is None


# --- Tests: fallback behavior ---


class TestFallbackBehavior:
    """Test that unknown intents fall back to the onboarding agent."""

    @pytest.mark.asyncio
    async def test_unknown_intent_falls_back_to_general_chat(
        self, agent_router, text_message, sample_context, monkeypatch
    ):
        """Unknown intent should fall back to general_chat skill via onboarding agent."""
        # Patch assemble_context to avoid DB/Redis calls
        mock_assemble = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("src.agents.base.assemble_context", mock_assemble)
        result = await agent_router.route("totally_unknown", text_message, sample_context, {})
        assert result.response_text == "Response from general_chat"


# --- Tests: route() calls the correct skill ---


class TestRouteCallsCorrectSkill:
    """Test that route() dispatches to the correct skill."""

    @pytest.mark.asyncio
    async def test_route_add_expense(self, agent_router, text_message, sample_context, monkeypatch):
        mock_assemble = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("src.agents.base.assemble_context", mock_assemble)

        result = await agent_router.route("add_expense", text_message, sample_context, {})
        assert result.response_text == "Response from add_expense"

    @pytest.mark.asyncio
    async def test_route_scan_receipt(
        self, agent_router, text_message, sample_context, monkeypatch
    ):
        mock_assemble = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("src.agents.base.assemble_context", mock_assemble)

        result = await agent_router.route("scan_receipt", text_message, sample_context, {})
        assert result.response_text == "Response from scan_receipt"

    @pytest.mark.asyncio
    async def test_route_query_stats(self, agent_router, text_message, sample_context, monkeypatch):
        mock_assemble = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("src.agents.base.assemble_context", mock_assemble)

        result = await agent_router.route("query_stats", text_message, sample_context, {})
        assert result.response_text == "Response from query_stats"

    @pytest.mark.asyncio
    async def test_route_onboarding(self, agent_router, text_message, sample_context, monkeypatch):
        mock_assemble = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("src.agents.base.assemble_context", mock_assemble)

        result = await agent_router.route("onboarding", text_message, sample_context, {})
        assert result.response_text == "Response from onboarding"

    @pytest.mark.asyncio
    async def test_route_sets_agent_metadata(
        self, agent_router, text_message, sample_context, monkeypatch
    ):
        """route() should inject _agent and _model into intent_data."""
        mock_assemble = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("src.agents.base.assemble_context", mock_assemble)

        intent_data: dict = {}
        await agent_router.route("add_expense", text_message, sample_context, intent_data)
        assert intent_data.get("_agent") == "chat"
        assert intent_data.get("_model") == "claude-haiku-4-5-20251001"


# --- Tests: agent configurations completeness ---


class TestAgentConfigCompleteness:
    """Verify that all expected intents are covered by agents."""

    EXPECTED_INTENTS = [
        "scan_receipt",
        "query_stats",
        "add_expense",
        "add_income",
        "correct_category",
        "undo_last",
        "onboarding",
        "general_chat",
    ]

    def test_all_intents_have_agents(self, agent_router):
        for intent in self.EXPECTED_INTENTS:
            agent = agent_router.get_agent(intent)
            assert agent is not None, f"Intent '{intent}' has no agent"

    def test_four_agents_defined(self, agent_router):
        agents = agent_router.list_agents()
        assert len(agents) == 4

    def test_agent_names(self, agent_router):
        names = {a.name for a in agent_router.list_agents()}
        assert names == {"receipt", "analytics", "chat", "onboarding"}

    def test_each_agent_has_system_prompt(self, agent_router):
        for agent in agent_router.list_agents():
            assert agent.system_prompt, f"Agent '{agent.name}' has empty system_prompt"
            assert len(agent.system_prompt) > 50, (
                f"Agent '{agent.name}' system_prompt is suspiciously short"
            )

    def test_each_agent_has_model(self, agent_router):
        for agent in agent_router.list_agents():
            assert agent.default_model, f"Agent '{agent.name}' has no default_model"

    def test_each_agent_has_context_config(self, agent_router):
        for agent in agent_router.list_agents():
            cfg = agent.context_config
            assert "mem" in cfg, f"Agent '{agent.name}' missing 'mem' in context_config"
            assert "hist" in cfg, f"Agent '{agent.name}' missing 'hist' in context_config"
            assert "sql" in cfg, f"Agent '{agent.name}' missing 'sql' in context_config"
            assert "sum" in cfg, f"Agent '{agent.name}' missing 'sum' in context_config"


# --- Tests: context assembly error handling ---


class TestContextAssemblyErrorHandling:
    """Test graceful degradation when context assembly fails."""

    @pytest.mark.asyncio
    async def test_route_succeeds_when_context_assembly_fails(
        self, agent_router, text_message, sample_context, monkeypatch
    ):
        """If assemble_context raises, route() should still execute the skill."""
        mock_assemble = AsyncMock(side_effect=RuntimeError("DB down"))
        monkeypatch.setattr("src.agents.base.assemble_context", mock_assemble)

        result = await agent_router.route("add_expense", text_message, sample_context, {})
        # Skill should still execute (via fallback which also fails, but skill runs)
        assert result.response_text == "Response from add_expense"


# --- Tests: AgentConfig dataclass ---


class TestAgentConfigDataclass:
    def test_defaults(self):
        config = AgentConfig(
            name="test",
            system_prompt="test prompt",
            skills=["intent_a"],
            default_model="model-x",
        )
        assert config.context_config == {}

    def test_with_context_config(self):
        config = AgentConfig(
            name="test",
            system_prompt="test prompt",
            skills=["intent_a", "intent_b"],
            default_model="model-x",
            context_config={"mem": "all", "hist": 5, "sql": True, "sum": False},
        )
        assert config.context_config["hist"] == 5
        assert len(config.skills) == 2
