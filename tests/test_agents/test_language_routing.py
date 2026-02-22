"""Tests for multilingual language routing in AgentRouter.

Verifies that:
1. _add_language_instruction appends correct language for any locale
2. Agent prompts contain NO hardcoded Russian language instructions
3. System prompts passed to assemble_context include language instruction
4. Guardrails allow news/search queries in non-Russian languages
"""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("APP_ENV", "testing")

from src.agents.base import AgentConfig, AgentRouter
from src.agents.config import AGENTS
from src.core.context import SessionContext
from src.core.guardrails import SAFETY_CHECK_PROMPT
from src.gateway.types import IncomingMessage, MessageType
from src.skills.base import SkillRegistry, SkillResult


# --- Fixtures ---


def _make_context(language: str) -> SessionContext:
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language=language,
        currency="USD",
        business_type="trucker",
        categories=[],
        merchant_mappings=[],
    )


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg_100",
        chat_id="chat_100",
        type=MessageType.text,
        text=text,
    )


def _make_mock_skill(name: str, intents: list[str]) -> MagicMock:
    skill = MagicMock()
    skill.name = name
    skill.intents = intents
    skill.model = "test-model"
    skill.get_system_prompt = MagicMock(return_value="test prompt")
    skill.execute = AsyncMock(return_value=SkillResult(response_text=f"Response from {name}"))
    return skill


@pytest.fixture
def mock_registry():
    registry = SkillRegistry()
    for name in ["web_search", "quick_answer", "general_chat", "add_expense", "quick_capture"]:
        registry.register(_make_mock_skill(name, [name]))
    return registry


@pytest.fixture
def agent_router(mock_registry):
    return AgentRouter(AGENTS, mock_registry)


# --- Tests: _add_language_instruction ---


class TestAddLanguageInstruction:
    """Test dynamic language instruction appended to system prompts."""

    def test_kyrgyz_language_instruction(self, agent_router):
        ctx = _make_context("ky")
        result = AgentRouter._add_language_instruction("Base prompt.", ctx)
        assert "ky" in result
        assert "Match the language" in result

    def test_russian_language_instruction(self, agent_router):
        ctx = _make_context("ru")
        result = AgentRouter._add_language_instruction("Base prompt.", ctx)
        assert "ru" in result
        assert "IMPORTANT" in result

    def test_english_language_instruction(self, agent_router):
        ctx = _make_context("en")
        result = AgentRouter._add_language_instruction("Base prompt.", ctx)
        assert "en" in result

    def test_spanish_language_instruction(self, agent_router):
        ctx = _make_context("es")
        result = AgentRouter._add_language_instruction("Base prompt.", ctx)
        assert "es" in result

    def test_default_when_language_is_empty(self, agent_router):
        ctx = _make_context("")
        result = AgentRouter._add_language_instruction("Base prompt.", ctx)
        assert "en" in result

    def test_preserves_original_prompt(self, agent_router):
        ctx = _make_context("ky")
        original = "You are a helpful assistant."
        result = AgentRouter._add_language_instruction(original, ctx)
        assert result.startswith(original)


# --- Tests: no hardcoded Russian in agent prompts ---


class TestNoHardcodedRussian:
    """Verify agent prompts don't contain hardcoded Russian language directives."""

    RUSSIAN_DIRECTIVES = [
        "Отвечай на русском",
        "на русском языке",
        "отвечай по-русски",
        "ответ на русском",
    ]

    def test_no_agent_prompt_forces_russian(self):
        for agent in AGENTS:
            prompt_lower = agent.system_prompt.lower()
            for directive in self.RUSSIAN_DIRECTIVES:
                assert directive.lower() not in prompt_lower, (
                    f"Agent '{agent.name}' contains hardcoded Russian directive: "
                    f"'{directive}'"
                )

    def test_no_literal_context_language_in_prompts(self):
        """Prompts should not contain literal 'context.language' string."""
        for agent in AGENTS:
            assert "context.language" not in agent.system_prompt, (
                f"Agent '{agent.name}' has literal 'context.language' that is never interpolated"
            )


# --- Tests: route() passes language-enhanced prompt to assemble_context ---


class TestRouteLanguageInjection:
    """Verify route() injects language instruction into system prompt."""

    @pytest.mark.asyncio
    async def test_route_passes_language_to_assemble_context(
        self, agent_router, monkeypatch
    ):
        mock_assemble = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("src.agents.base.assemble_context", mock_assemble)

        ctx = _make_context("ky")
        msg = _make_message("Саламатсызбы")
        await agent_router.route("web_search", msg, ctx, {})

        mock_assemble.assert_called_once()
        call_kwargs = mock_assemble.call_args
        system_prompt = call_kwargs.kwargs.get("system_prompt") or call_kwargs[1].get(
            "system_prompt"
        )
        if system_prompt is None:
            system_prompt = call_kwargs[0][4] if len(call_kwargs[0]) > 4 else ""
        assert "ky" in system_prompt
        assert "Match the language" in system_prompt

    @pytest.mark.asyncio
    async def test_route_with_russian_context(self, agent_router, monkeypatch):
        mock_assemble = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("src.agents.base.assemble_context", mock_assemble)

        ctx = _make_context("ru")
        msg = _make_message("Привет")
        await agent_router.route("add_expense", msg, ctx, {})

        mock_assemble.assert_called_once()
        call_kwargs = mock_assemble.call_args
        system_prompt = call_kwargs.kwargs.get("system_prompt") or call_kwargs[1].get(
            "system_prompt"
        )
        if system_prompt is None:
            system_prompt = call_kwargs[0][4] if len(call_kwargs[0]) > 4 else ""
        assert "ru" in system_prompt

    @pytest.mark.asyncio
    async def test_fallback_also_injects_language(self, agent_router, monkeypatch):
        """When main context assembly fails, fallback should also add language."""
        call_count = 0

        async def fail_then_succeed(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("DB down")
            return MagicMock()

        mock_assemble = AsyncMock(side_effect=fail_then_succeed)
        monkeypatch.setattr("src.agents.base.assemble_context", mock_assemble)

        ctx = _make_context("ky")
        msg = _make_message("Жардам бер")
        await agent_router.route("quick_capture", msg, ctx, {})

        assert mock_assemble.call_count == 2
        # Second call (fallback) should also have language instruction
        fallback_call = mock_assemble.call_args_list[1]
        system_prompt = fallback_call.kwargs.get("system_prompt") or fallback_call[1].get(
            "system_prompt"
        )
        if system_prompt is None:
            system_prompt = fallback_call[0][4] if len(fallback_call[0]) > 4 else ""
        assert "ky" in system_prompt
        assert "Match the language" in system_prompt


# --- Tests: guardrails allow news/search in non-Russian ---


class TestGuardrailsAllowMultilingualQueries:
    """Verify guardrails prompt includes news, web search, etc. as allowed."""

    def test_guardrails_allows_news(self):
        assert "news" in SAFETY_CHECK_PROMPT.lower()

    def test_guardrails_allows_web_search(self):
        assert "web search" in SAFETY_CHECK_PROMPT.lower()

    def test_guardrails_allows_shopping(self):
        assert "shopping" in SAFETY_CHECK_PROMPT.lower()

    def test_guardrails_allows_bookings(self):
        assert "bookings" in SAFETY_CHECK_PROMPT.lower()

    def test_guardrails_allows_contacts(self):
        assert "contacts" in SAFETY_CHECK_PROMPT.lower()

    def test_guardrails_allows_weather(self):
        assert "weather" in SAFETY_CHECK_PROMPT.lower()

    def test_guardrails_not_finance_only(self):
        """Should say 'multi-purpose', not 'finance AND life-tracking'."""
        assert "multi-purpose" in SAFETY_CHECK_PROMPT.lower()
