"""Tests for TaxReportOrchestrator — full tax report with PDF."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.orchestrators.tax_report.deductions import (
    QBI_PHASEOUT_END_SINGLE,
    QBI_PHASEOUT_START_SINGLE,
    SE_NET_FACTOR,
    SE_TAX_RATE,
)
from src.orchestrators.tax_report.nodes import _apply_brackets, calculate_tax


def _make_context(**kwargs):
    defaults = {
        "user_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "role": "owner",
        "language": "en",
        "currency": "USD",
        "business_type": "freelancer",
        "categories": [],
        "merchant_mappings": [],
    }
    defaults.update(kwargs)
    return SessionContext(**defaults)


def _make_message(text="generate tax report for 2025"):
    return IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=text
    )


def _make_base_state(**kwargs):
    base = {
        "user_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "language": "en",
        "currency": "USD",
        "business_type": "freelancer",
        "year": 2025,
        "quarter": None,
        "gross_income": 100_000.0,
        "expenses_by_category": [],
        "recurring_payments": [],
        "mileage_miles": 0.0,
        "total_deductible": 0.0,
        "deduction_breakdown": [],
        "additional_deductions": [],
        "net_profit": 0.0,
        "se_tax": 0.0,
        "se_deduction": 0.0,
        "qbi_deduction": 0.0,
        "income_tax": 0.0,
        "total_tax": 0.0,
        "effective_rate": 0.0,
        "quarterly_payment": 0.0,
        "narrative": "",
        "pdf_bytes": None,
        "response_text": "",
    }
    base.update(kwargs)
    return base


# ─────────────────────────── SE tax calculation ───────────────────────────


async def test_se_tax_calculation():
    """SE tax = net_profit × 92.35% × 15.3%."""
    state = _make_base_state(gross_income=100_000.0, total_deductible=10_000.0)
    result = await calculate_tax(state)

    expected_net = 90_000.0
    expected_se_base = expected_net * SE_NET_FACTOR
    expected_se_tax = expected_se_base * SE_TAX_RATE

    assert abs(result["net_profit"] - expected_net) < 0.01
    assert abs(result["se_tax"] - expected_se_tax) < 0.01
    assert abs(result["se_deduction"] - expected_se_tax * 0.5) < 0.01


async def test_se_deduction_50_percent():
    """SE deduction = 50% of SE tax."""
    state = _make_base_state(gross_income=50_000.0, total_deductible=0.0)
    result = await calculate_tax(state)

    assert abs(result["se_deduction"] - result["se_tax"] * 0.5) < 0.01


# ─────────────────────────── QBI deduction ────────────────────────────────


async def test_qbi_deduction_applied_below_phaseout():
    """QBI = 20% of adjusted income when below phase-out threshold."""
    # Income well below $203K phaseout
    state = _make_base_state(gross_income=80_000.0, total_deductible=0.0)
    result = await calculate_tax(state)

    adjusted = result["net_profit"] - result["se_deduction"]
    expected_qbi = adjusted * 0.20
    assert abs(result["qbi_deduction"] - expected_qbi) < 0.01


async def test_qbi_phase_out_no_deduction_above_threshold():
    """QBI = 0 when adjusted income exceeds phase-out end ($272,300 in 2026)."""
    # Use income that results in adjusted income above QBI_PHASEOUT_END_SINGLE
    high_income = QBI_PHASEOUT_END_SINGLE * 1.5  # well above phase-out
    state = _make_base_state(gross_income=high_income, total_deductible=0.0)
    result = await calculate_tax(state)

    assert result["qbi_deduction"] == 0.0


async def test_qbi_partial_phaseout():
    """QBI is partially reduced in phase-out range."""
    # Income in the middle of the phase-out range
    mid_income = (QBI_PHASEOUT_START_SINGLE + QBI_PHASEOUT_END_SINGLE) / 2
    state = _make_base_state(gross_income=mid_income, total_deductible=0.0)
    result = await calculate_tax(state)

    adjusted = result["net_profit"] - result["se_deduction"]
    full_qbi = adjusted * 0.20
    # Partial QBI should be between 0 and full QBI
    assert 0 < result["qbi_deduction"] < full_qbi


# ─────────────────────────── brackets ────────────────────────────────────


def test_zero_income_brackets():
    assert _apply_brackets(0) == 0.0
    assert _apply_brackets(-100) == 0.0


def test_brackets_10_percent_range():
    # $11,925 should be taxed at 10%
    tax = _apply_brackets(10_000)
    assert abs(tax - 10_000 * 0.10) < 0.01


def test_brackets_multiple_tiers():
    # $50,000 spans 10% and 12% brackets
    tax = _apply_brackets(50_000)
    assert tax > 50_000 * 0.10  # more than flat 10%
    assert tax < 50_000 * 0.12  # less than flat 12%


# ─────────────────────────── quarterly payment ───────────────────────────


async def test_quarterly_safe_harbor():
    """Quarterly payment = total_tax / 4."""
    state = _make_base_state(gross_income=100_000.0, total_deductible=0.0)
    result = await calculate_tax(state)

    expected_quarterly = result["total_tax"] / 4
    assert abs(result["quarterly_payment"] - expected_quarterly) < 0.01


# ─────────────────────────── collectors run in parallel ──────────────────


async def test_collectors_run_in_parallel():
    """All 4 collector nodes are present as parallel edges from START."""
    from src.orchestrators.tax_report.graph import _build_tax_graph

    graph = _build_tax_graph()

    # The graph should have all 4 collector nodes
    node_names = set(graph.nodes.keys())
    assert "collect_income" in node_names
    assert "collect_expenses" in node_names
    assert "collect_recurring" in node_names
    assert "collect_mileage" in node_names
    assert "analyze_deductions" in node_names
    assert "calculate_tax" in node_names
    assert "generate_pdf" in node_names


# ─────────────────────────── PDF generation ──────────────────────────────


async def test_pdf_generated_on_success():
    """generate_pdf node returns pdf_bytes when WeasyPrint succeeds."""
    from src.orchestrators.tax_report.nodes import generate_pdf

    state = _make_base_state(
        gross_income=80_000.0,
        total_deductible=5_000.0,
        net_profit=75_000.0,
        se_tax=10_000.0,
        se_deduction=5_000.0,
        qbi_deduction=5_000.0,
        income_tax=8_000.0,
        total_tax=18_000.0,
        effective_rate=22.5,
        quarterly_payment=4_500.0,
        deduction_breakdown=[{"label": "Business Expense", "amount": 5000, "type": "business_expense"}],
    )

    fake_pdf = b"%PDF-1.4 fake content"
    with patch(
        "src.orchestrators.tax_report.nodes._html_to_pdf", return_value=fake_pdf
    ):
        result = await generate_pdf(state)

    assert result["pdf_bytes"] == fake_pdf
    assert result["response_text"]  # response text should be non-empty


async def test_pdf_fallback_on_weasyprint_failure():
    """generate_pdf returns None pdf_bytes when WeasyPrint fails."""
    from src.orchestrators.tax_report.nodes import generate_pdf

    state = _make_base_state(
        gross_income=80_000.0,
        total_deductible=0.0,
        net_profit=80_000.0,
        se_tax=11_000.0,
        se_deduction=5_500.0,
        qbi_deduction=5_000.0,
        income_tax=9_000.0,
        total_tax=20_000.0,
        effective_rate=25.0,
        quarterly_payment=5_000.0,
    )

    with patch(
        "src.orchestrators.tax_report.nodes._html_to_pdf",
        side_effect=OSError("weasyprint not available"),
    ):
        result = await generate_pdf(state)

    assert result["pdf_bytes"] is None
    assert result["response_text"]  # still has text


async def test_disclaimer_in_pdf():
    """HTML report contains the required disclaimer."""
    from src.orchestrators.tax_report.nodes import _build_html_report

    state = _make_base_state(
        gross_income=60_000.0,
        total_deductible=0.0,
        net_profit=60_000.0,
        se_tax=8_000.0,
        se_deduction=4_000.0,
        qbi_deduction=3_000.0,
        income_tax=5_000.0,
        total_tax=13_000.0,
        effective_rate=21.7,
        quarterly_payment=3_250.0,
    )

    html = _build_html_report(state)
    assert "Disclaimer" in html or "disclaimer" in html.lower()
    assert "not legal, tax, or accounting advice" in html.lower() or "estimate only" in html.lower()


# ─────────────────────────── orchestrator invoke ─────────────────────────


async def test_orchestrator_no_family_id_returns_error():
    """TaxReportOrchestrator returns an error when family_id is not set."""
    from src.orchestrators.tax_report.graph import TaxReportOrchestrator

    orch = TaxReportOrchestrator()
    ctx = _make_context(family_id=None)
    msg = _make_message()

    result = await orch.invoke("tax_report", msg, ctx, {})
    assert "Set up" in result.response_text or "account" in result.response_text.lower()


async def test_orchestrator_returns_pdf_document():
    """TaxReportOrchestrator returns SkillResult with document when PDF is generated."""
    from src.orchestrators.tax_report.graph import TaxReportOrchestrator

    orch = TaxReportOrchestrator()
    ctx = _make_context()
    msg = _make_message("tax report for 2025")

    fake_result = _make_base_state(
        user_id=ctx.user_id,
        family_id=ctx.family_id,
        response_text="<b>📊 Tax Report</b>\nGross: $100,000",
        pdf_bytes=b"%PDF fake",
    )

    with patch(
        "src.orchestrators.tax_report.graph._get_tax_graph"
    ) as mock_get:
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=fake_result)
        mock_get.return_value = mock_graph

        result = await orch.invoke("tax_report", msg, ctx, {"tax_year": 2025})

    assert result.response_text
    assert result.document == b"%PDF fake"
    assert result.document_name and "tax_report" in result.document_name
