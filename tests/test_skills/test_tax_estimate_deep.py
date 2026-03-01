"""Tests for tax_estimate deep agent path (complexity gate)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.base import SkillResult
from src.skills.tax_estimate.handler import TaxEstimateSkill


@pytest.fixture
def skill():
    return TaxEstimateSkill()


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type="plumber",
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


def _patch_db_totals(income: float = 5000, expenses: float = 2000):
    """Patch DB query methods on TaxEstimateSkill."""
    return (
        patch.object(
            TaxEstimateSkill,
            "_get_total",
            new_callable=AsyncMock,
            side_effect=lambda fid, s, e, t: income if t == "income" else expenses,
        ),
        patch.object(
            TaxEstimateSkill,
            "_get_expense_categories",
            new_callable=AsyncMock,
            return_value=[
                {"category": "Office", "amount": 1000},
                {"category": "Travel", "amount": 500},
                {"category": "Supplies", "amount": 500},
            ],
        ),
    )


# --- Tests: feature flag OFF ---


async def test_flag_off_simple_uses_normal_path(skill, ctx):
    """With ff_deep_agents=False, simple tax requests use normal path."""
    p_total, p_cats = _patch_db_totals()
    with (
        patch("src.core.config.settings.ff_deep_agents", False),
        p_total,
        p_cats,
        patch(
            "src.skills.tax_estimate.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Q1 Tax Estimate</b>\nEstimated: $900",
        ),
    ):
        result = await skill.execute(
            _msg("tax estimate"),
            ctx,
            {},
        )

    assert "Tax" in result.response_text or "tax" in result.response_text


async def test_flag_off_complex_still_normal(skill, ctx):
    """With ff_deep_agents=False, even complex requests use normal path."""
    p_total, p_cats = _patch_db_totals()
    with (
        patch("src.core.config.settings.ff_deep_agents", False),
        p_total,
        p_cats,
        patch(
            "src.skills.tax_estimate.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Tax Report</b>",
        ),
    ):
        result = await skill.execute(
            _msg("annual tax report with deduction analysis"),
            ctx,
            {},
        )

    # Normal path produces a response (not deep agent)
    assert result.response_text


# --- Tests: feature flag ON ---


async def test_flag_on_simple_uses_normal_path(skill, ctx):
    """With ff_deep_agents=True, simple tax requests still use normal path."""
    p_total, p_cats = _patch_db_totals()
    with (
        patch("src.core.config.settings.ff_deep_agents", True),
        p_total,
        p_cats,
        patch(
            "src.skills.tax_estimate.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Q1 Estimate</b>\n$900",
        ),
    ):
        result = await skill.execute(
            _msg("tax estimate this quarter"),
            ctx,
            {},
        )

    assert result.response_text


async def test_flag_on_complex_routes_to_deep_agent(skill, ctx):
    """With ff_deep_agents=True, complex tax requests route to deep agent."""
    deep_result = SkillResult(
        response_text="<b>Annual Tax Report</b>\nDetailed analysis...",
    )

    p_total, p_cats = _patch_db_totals()
    with (
        patch("src.core.config.settings.ff_deep_agents", True),
        p_total,
        p_cats,
        patch(
            "src.orchestrators.deep_agent.graph.DeepAgentOrchestrator.run",
            new_callable=AsyncMock,
            return_value=deep_result,
        ) as mock_run,
    ):
        result = await skill.execute(
            _msg("annual tax report with deduction analysis"),
            ctx,
            {},
        )

    mock_run.assert_called_once()
    assert "Annual Tax Report" in result.response_text

    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["skill_type"] == "tax_report"
    assert call_kwargs["user_id"] == ctx.user_id
    assert "quarters" in call_kwargs["financial_data"]


async def test_deep_agent_collects_all_quarters(skill, ctx):
    """Deep agent path collects financial data for all 4 quarters."""
    deep_result = SkillResult(response_text="Report")

    p_total, p_cats = _patch_db_totals(income=10000, expenses=3000)
    with (
        patch("src.core.config.settings.ff_deep_agents", True),
        p_total,
        p_cats,
        patch(
            "src.orchestrators.deep_agent.graph.DeepAgentOrchestrator.run",
            new_callable=AsyncMock,
            return_value=deep_result,
        ) as mock_run,
    ):
        await skill.execute(
            _msg("detailed annual tax report with all quarters comparison"),
            ctx,
            {},
        )

    data = mock_run.call_args.kwargs["financial_data"]
    assert "Q1" in data["quarters"]
    assert "Q2" in data["quarters"]
    assert "Q3" in data["quarters"]
    assert "Q4" in data["quarters"]
    assert data["annual"]["gross_income"] == 40000  # 10000 * 4
    assert data["annual"]["total_expenses"] == 12000  # 3000 * 4


async def test_deep_agent_includes_se_tax_for_business(skill, ctx):
    """Deep agent includes self-employment tax for business users."""
    deep_result = SkillResult(response_text="Report")

    p_total, p_cats = _patch_db_totals(income=10000, expenses=3000)
    with (
        patch("src.core.config.settings.ff_deep_agents", True),
        p_total,
        p_cats,
        patch(
            "src.orchestrators.deep_agent.graph.DeepAgentOrchestrator.run",
            new_callable=AsyncMock,
            return_value=deep_result,
        ) as mock_run,
    ):
        await skill.execute(
            _msg("annual tax report with self-employment tax planning"),
            ctx,  # business_type="plumber"
            {},
        )

    data = mock_run.call_args.kwargs["financial_data"]
    assert "self_employment_tax" in data["annual"]
    assert data["annual"]["self_employment_tax"] > 0


async def test_no_family_id_returns_early(skill):
    """No family_id returns setup prompt even with deep agents enabled."""
    ctx = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id="",
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )

    with patch("src.core.config.settings.ff_deep_agents", True):
        result = await skill.execute(
            _msg("annual tax report"),
            ctx,
            {},
        )

    assert "Set up" in result.response_text
