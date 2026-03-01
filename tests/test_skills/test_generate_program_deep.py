"""Tests for generate_program deep agent path (complexity gate)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.base import SkillResult
from src.skills.generate_program.handler import GenerateProgramSkill


@pytest.fixture
def skill():
    return GenerateProgramSkill()


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type="household",
        categories=[],
        merchant_mappings=[],
    )


def _msg(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=text,
    )


def _patch_redis():
    return patch(
        "src.skills.generate_program.handler.redis",
        setex=AsyncMock(),
    )


def _patch_e2b_off():
    return patch(
        "src.skills.generate_program.handler.e2b_runner.is_configured",
        return_value=False,
    )


# --- Tests: feature flag OFF → simple path always ---


async def test_flag_off_simple_request(skill, ctx):
    """With ff_deep_agents=False, simple requests use the normal path."""
    code = 'print("hello")'
    with (
        patch("src.core.config.settings.ff_deep_agents", False),
        patch(
            "src.skills.generate_program.handler.generate_text",
            new_callable=AsyncMock,
            return_value=code,
        ),
        _patch_e2b_off(),
        _patch_redis(),
    ):
        result = await skill.execute(
            _msg("hello world"),
            ctx,
            {"program_description": "hello world"},
        )

    assert result.document is not None


async def test_flag_off_complex_request_still_simple(skill, ctx):
    """With ff_deep_agents=False, even complex requests use normal path."""
    code = "from flask import Flask\napp = Flask(__name__)"
    with (
        patch("src.core.config.settings.ff_deep_agents", False),
        patch(
            "src.skills.generate_program.handler.generate_text",
            new_callable=AsyncMock,
            return_value=code,
        ),
        _patch_e2b_off(),
        _patch_redis(),
    ):
        result = await skill.execute(
            _msg("build CRM with auth and database"),
            ctx,
            {"program_description": "CRM with auth and database dashboard"},
        )

    # Should still use normal path (document returned, not deep agent)
    assert result.document is not None


# --- Tests: feature flag ON ---


async def test_flag_on_simple_request_uses_normal_path(skill, ctx):
    """With ff_deep_agents=True, simple requests still use normal path."""
    code = 'print("hello")'
    with (
        patch("src.core.config.settings.ff_deep_agents", True),
        patch(
            "src.skills.generate_program.handler.generate_text",
            new_callable=AsyncMock,
            return_value=code,
        ),
        _patch_e2b_off(),
        _patch_redis(),
    ):
        result = await skill.execute(
            _msg("hello world script"),
            ctx,
            {"program_description": "hello world script"},
        )

    # Simple → normal path → document
    assert result.document is not None


async def test_flag_on_complex_request_uses_deep_agent(skill, ctx):
    """With ff_deep_agents=True, complex requests route to deep agent."""
    deep_result = SkillResult(
        response_text="<b>app.py</b>\nPlan: 3/3 steps completed",
    )

    with (
        patch("src.core.config.settings.ff_deep_agents", True),
        patch(
            "src.orchestrators.deep_agent.graph.DeepAgentOrchestrator.run",
            new_callable=AsyncMock,
            return_value=deep_result,
        ) as mock_run,
    ):
        result = await skill.execute(
            _msg("build CRM with auth and database"),
            ctx,
            {"program_description": "CRM with auth and database dashboard"},
        )

    mock_run.assert_called_once()
    assert "Plan:" in result.response_text

    # Verify orchestrator was called with correct params
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["skill_type"] == "generate_program"
    assert call_kwargs["user_id"] == ctx.user_id


async def test_deep_agent_adds_mem0_task(skill, ctx):
    """Deep agent path adds a Mem0 background task."""
    deep_result = SkillResult(response_text="Done")

    with (
        patch("src.core.config.settings.ff_deep_agents", True),
        patch(
            "src.orchestrators.deep_agent.graph.DeepAgentOrchestrator.run",
            new_callable=AsyncMock,
            return_value=deep_result,
        ),
    ):
        result = await skill.execute(
            _msg("build e-commerce with auth"),
            ctx,
            {"program_description": "e-commerce marketplace with authentication"},
        )

    assert len(result.background_tasks) == 1
    assert callable(result.background_tasks[0])


async def test_deep_agent_passes_language(skill, ctx):
    """Deep agent path passes the program language."""
    deep_result = SkillResult(response_text="Done")

    with (
        patch("src.core.config.settings.ff_deep_agents", True),
        patch(
            "src.orchestrators.deep_agent.graph.DeepAgentOrchestrator.run",
            new_callable=AsyncMock,
            return_value=deep_result,
        ) as mock_run,
    ):
        await skill.execute(
            _msg("build CRM with auth"),
            ctx,
            {
                "program_description": "CRM with authentication and database",
                "program_language": "python",
            },
        )

    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["program_language"] == "python"
    assert call_kwargs["model"] == "claude-sonnet-4-6"  # Python routes to Sonnet
