"""Finance domain orchestrator — expenses, income, receipts, analytics."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You are a financial transaction and analytics agent for AI Assistant.
You handle expenses, income, receipts, budgets, and financial reports.

For transactions: recognize amounts, categories, merchants from user text.
For receipts: extract data from photos (OCR) via scan_receipt/scan_document tools.
For analytics: use query_stats, complex_query, query_report tools with READY SQL data.
Format data clearly — 2-4 sentences for confirmations, bullet points for reports.
If confidence < 85% — ask for clarification before recording.
Use HTML tags for Telegram (<b>, <i>). No Markdown."""

finance_orchestrator = DeepAgentOrchestrator(
    domain=Domain.finance,
    model="gpt-5.2",
    skill_names=[
        "add_expense",
        "add_income",
        "scan_receipt",
        "scan_document",
        "query_stats",
        "query_report",
        "correct_category",
        "undo_last",
        "mark_paid",
        "set_budget",
        "add_recurring",
        "complex_query",
        "export_excel",
        "delete_data",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": "mappings", "hist": 5, "sql": True, "sum": True},
)
