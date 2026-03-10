"""Tax report orchestrator state definition."""

from typing import TypedDict


class TaxReportState(TypedDict, total=False):
    """State for the TaxReportOrchestrator LangGraph."""

    # Input
    user_id: str
    family_id: str
    language: str
    currency: str
    business_type: str | None
    year: int
    quarter: int | None   # None = full year

    # Collected from DB (parallel phase)
    gross_income: float
    expenses_by_category: list[dict]    # [{category, amount, is_deductible, deductible_amount, deduction_type}]
    recurring_payments: list[dict]      # [{name, amount, frequency}]
    mileage_miles: float                # transport/taxi total converted to miles

    # Deductions analysis
    total_deductible: float
    deduction_breakdown: list[dict]     # [{label, amount, type}]
    additional_deductions: list[str]    # AI-identified missed deductions

    # Tax calculations
    net_profit: float
    se_tax: float
    se_deduction: float
    qbi_deduction: float
    income_tax: float
    total_tax: float
    effective_rate: float
    quarterly_payment: float

    # Narrative and output
    narrative: str
    pdf_bytes: bytes | None
    response_text: str
