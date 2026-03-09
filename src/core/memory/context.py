"""Context assembly — builds the full LLM context from all memory layers.

Phase 2: Token budget management with overflow priority,
QUERY_CONTEXT_MAP per intent, and Lost-in-the-Middle positioning.

Phase 3.5: Progressive Context Disclosure — regex heuristic to skip
heavy context layers for simple queries (saves 80-96% tokens).
"""

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from src.core.memory import mem0_client, sliding_window
from src.core.memory.summarization import get_session_summary
from src.core.observability import observe

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token budget constants for 200K context window
# ---------------------------------------------------------------------------
MAX_CONTEXT_TOKENS = 200_000
BUDGET_RATIO = 0.75  # S + M + A + H + U <= W * 0.75

# Per-layer budget caps (share of max_tokens)
BUDGET_SYSTEM_PROMPT = 0.10  # 5-10% -> cap at 10%
BUDGET_MEM0 = 0.15  # 10-15%
BUDGET_SQL = 0.15  # 10-15%
BUDGET_SUMMARY = 0.10  # 10%
BUDGET_HISTORY = 0.20  # 15-20%
BUDGET_USER_MSG = 0.05  # 5%

# Overflow priority — revised (lower number = drop FIRST)
# Drop 1: Mem0 non-core namespaces     — life, tasks, research, etc.
# Drop 2: Session summary              — compress/shorten
# Drop 3: SQL analytics                — compress before drop (~2K summary)
# Drop 4: Old history messages          — keep MIN_SLIDING_WINDOW
# Drop 5: Mem0 core + finance          — last among Mem0 to drop
# Drop 6: Remaining history            — absolute last resort
# NEVER:  System prompt + core_identity + user_rules + session buffer + user message

# Minimum sliding window messages to keep during trimming
MIN_SLIDING_WINDOW = 5
MAX_SLIDING_WINDOW = 10

# ---------------------------------------------------------------------------
# QUERY_CONTEXT_MAP — what to load per intent
# ---------------------------------------------------------------------------
QUERY_CONTEXT_MAP: dict[str, dict[str, Any]] = {
    "add_expense": {"mem": "mappings", "hist": 3, "sql": False, "sum": False},
    "add_income": {"mem": "mappings", "hist": 3, "sql": False, "sum": False},
    "scan_receipt": {"mem": "mappings", "hist": 1, "sql": False, "sum": False},
    "scan_document": {"mem": "mappings", "hist": 1, "sql": False, "sum": False},
    "query_stats": {"mem": "budgets", "hist": 3, "sql": True, "sum": False},
    "query_report": {"mem": "profile", "hist": 3, "sql": True, "sum": False},
    "export_excel": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "correct_category": {"mem": "mappings", "hist": 5, "sql": False, "sum": False},
    "complex_query": {"mem": "all", "hist": 5, "sql": True, "sum": True},
    "general_chat": {"mem": "profile", "hist": 0, "sql": False, "sum": False},
    "undo_last": {"mem": False, "hist": 5, "sql": False, "sum": False},
    "delete_data": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "set_budget": {"mem": "budgets", "hist": 3, "sql": True, "sum": False},
    "mark_paid": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "add_recurring": {"mem": "mappings", "hist": 3, "sql": False, "sum": False},
    "onboarding": {"mem": "profile", "hist": 10, "sql": False, "sum": False},
    "quick_capture": {"mem": "life", "hist": 3, "sql": False, "sum": False},
    "track_food": {"mem": "life", "hist": 2, "sql": False, "sum": False},
    "track_drink": {"mem": "life", "hist": 2, "sql": False, "sum": False},
    "mood_checkin": {"mem": "life", "hist": 2, "sql": False, "sum": False},
    "day_plan": {"mem": "life", "hist": 3, "sql": False, "sum": False},
    "day_reflection": {"mem": "life", "hist": 3, "sql": False, "sum": False},
    "life_search": {"mem": "life", "hist": 3, "sql": False, "sum": False},
    "set_comm_mode": {"mem": False, "hist": 2, "sql": False, "sum": False},
    # Memory Vault
    "memory_show": {"mem": "life", "hist": 3, "sql": False, "sum": False},
    "memory_forget": {"mem": "life", "hist": 3, "sql": False, "sum": False},
    "memory_save": {"mem": "life", "hist": 3, "sql": False, "sum": False},
    "set_user_rule": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "dialog_history": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "memory_update": {"mem": "life", "hist": 3, "sql": False, "sum": False},
    # Project intents (Phase 12)
    "set_project": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "create_project": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "list_projects": {"mem": False, "hist": 2, "sql": False, "sum": False},
    # Task intents
    "create_task": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "list_tasks": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "set_reminder": {"mem": "profile", "hist": 5, "sql": False, "sum": False},
    "schedule_action": {"mem": "profile", "hist": 5, "sql": False, "sum": False},
    "list_scheduled_actions": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "manage_scheduled_action": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "complete_task": {"mem": False, "hist": 3, "sql": False, "sum": False},
    # Team management intents
    "invite_member": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "list_members": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "manage_member": {"mem": False, "hist": 3, "sql": False, "sum": False},
    # Research intents
    "quick_answer": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "web_search": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "compare_options": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "maps_search": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "youtube_search": {"mem": False, "hist": 2, "sql": False, "sum": False},
    # Writing intents
    "draft_message": {"mem": "profile", "hist": 5, "sql": False, "sum": False},
    "translate_text": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "write_post": {"mem": "profile", "hist": 5, "sql": False, "sum": False},
    "proofread": {"mem": False, "hist": 3, "sql": False, "sum": False},
    # Email intents
    "read_inbox": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "send_email": {"mem": "profile", "hist": 5, "sql": False, "sum": False},
    "draft_reply": {"mem": "profile", "hist": 5, "sql": False, "sum": False},
    "follow_up_email": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "summarize_thread": {"mem": False, "hist": 3, "sql": False, "sum": False},
    # Calendar intents
    "list_events": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "create_event": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "find_free_slots": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "reschedule_event": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "morning_brief": {"mem": "life", "hist": 3, "sql": False, "sum": False},
    "evening_recap": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    # Shopping list intents
    "shopping_list_add": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "shopping_list_view": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "shopping_list_remove": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "shopping_list_clear": {"mem": False, "hist": 2, "sql": False, "sum": False},
    # Browser + monitor intents (Phase 5)
    "browser_action": {"mem": False, "hist": 5, "sql": False, "sum": False},
    "web_action": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "price_check": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "price_alert": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "news_monitor": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    # Booking + CRM intents (Phase 6)
    "create_booking": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "list_bookings": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "cancel_booking": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "reschedule_booking": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "add_contact": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "list_contacts": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "find_contact": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "send_to_client": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "receptionist": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    # Visual card / image generation
    "generate_image": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "generate_card": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "generate_program": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "modify_program": {"mem": "profile", "hist": 5, "sql": False, "sum": False},
    "convert_document": {"mem": False, "hist": 2, "sql": False, "sum": False},
    # Document agent
    "list_documents": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "search_documents": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "extract_table": {"mem": False, "hist": 1, "sql": False, "sum": False},
    "fill_template": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "fill_pdf_form": {"mem": "profile", "hist": 2, "sql": False, "sum": False},
    "analyze_document": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "merge_documents": {"mem": False, "hist": 1, "sql": False, "sum": False},
    "pdf_operations": {"mem": False, "hist": 1, "sql": False, "sum": False},
    "generate_spreadsheet": {"mem": "profile", "hist": 2, "sql": False, "sum": False},
    "compare_documents": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "summarize_document": {"mem": False, "hist": 1, "sql": False, "sum": False},
    "generate_document": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "generate_presentation": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    # Google Sheets
    "read_sheets": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "write_sheets": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "append_sheets": {"mem": False, "hist": 2, "sql": False, "sum": False},
    "create_sheets": {"mem": "profile", "hist": 1, "sql": False, "sum": False},
    # Wave 1 Financial Specialists
    "financial_summary": {"mem": "budgets", "hist": 3, "sql": True, "sum": True},
    "generate_invoice": {"mem": "profile", "hist": 3, "sql": True, "sum": False},
    "tax_estimate": {"mem": "budgets", "hist": 3, "sql": True, "sum": False},
    "cash_flow_forecast": {"mem": "budgets", "hist": 3, "sql": True, "sum": True},
}


# ---------------------------------------------------------------------------
# Progressive Context Disclosure (Phase 3.5)
# ---------------------------------------------------------------------------
# Simple patterns that NEVER need heavy context (Mem0, SQL, summary).
SIMPLE_PATTERNS: list[str] = [
    r"^\d+[.,]?\d*\s+\w{1,20}$",  # "100 кофе", "50.5 uber"
    r"^(да|нет|ок|ok|спасибо|thanks|thx)\b",  # confirmations
    r"^(привет|hello|hi|hey)\b",  # greetings
    r"^(готово|done|сделано)\b",  # completions
    r"^\+?\d[\d\s\-()]{5,15}$",  # phone numbers
]

# Signals that message needs full context loading.
COMPLEX_SIGNALS: list[str] = [
    "сравни",
    "compare",
    "тренд",
    "trend",
    "обычно",
    "usually",
    "прошлый",
    "last",
    "бюджет",
    "budget",
    "итого",
    "total",
    "за месяц",
    "за неделю",
    "this month",
    "this week",
    "как обычно",
    "as usual",
    "всего",
    "average",
    "средн",
]

# Intents that always load full context regardless of message simplicity.
ALWAYS_HEAVY_INTENTS: set[str] = {
    "query_stats",
    "complex_query",
    "query_report",
    "deep_research",
    "onboarding",
    "morning_brief",
    "evening_recap",
    "financial_summary",
    "tax_estimate",
    "cash_flow_forecast",
}


def needs_heavy_context(message: str, intent: str) -> bool:
    """Decide whether *message* + *intent* need heavy context layers.

    Returns ``True`` (load everything) or ``False`` (skip Mem0/SQL/summary).
    Conservative default: when unsure, load everything.
    """
    if intent in ALWAYS_HEAVY_INTENTS:
        return True

    text = message.strip().lower()
    if not text:
        return False

    # Simple patterns → skip heavy context
    for pattern in SIMPLE_PATTERNS:
        if re.match(pattern, text, re.IGNORECASE):
            return False

    # Complex signals → definitely load everything
    if any(signal in text for signal in COMPLEX_SIGNALS):
        return True

    # Conservative default: follow QUERY_CONTEXT_MAP as-is
    return True


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------
def count_tokens(text: str) -> int:
    """Rough token count estimate (1 token ~ 4 chars for Russian/English mix)."""
    return len(text) // 4 + 1


def _truncate_to_budget(text: str, max_tokens: int) -> str:
    """Truncate text to fit within max_tokens budget.

    Cuts at the character level (max_tokens * 4) and appends an ellipsis
    marker so the model knows content was truncated.
    """
    max_chars = max(0, (max_tokens - 1) * 4)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[обрезано]"


# ---------------------------------------------------------------------------
# AssembledContext dataclass (unchanged interface)
# ---------------------------------------------------------------------------
@dataclass
class AssembledContext:
    """Result of context assembly from all memory layers."""

    system_prompt: str
    messages: list[dict[str, str]]
    memories: list[dict] = field(default_factory=list)
    sql_stats: dict[str, Any] | None = None
    token_usage: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SQL stats loader
# ---------------------------------------------------------------------------
def _parse_sql_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD strings used by analytics intent data."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _resolve_sql_period(
    intent: str,
    intent_data: dict[str, Any] | None,
) -> tuple[date, date, str]:
    """Resolve the analytics period from query_stats/query_report intent data."""
    today = date.today()
    data = intent_data or {}

    if intent == "query_report":
        period = data.get("period")
        month_date = _parse_sql_date(data.get("date") or data.get("date_from"))

        if period == "prev_month":
            first_this_month = today.replace(day=1)
            last_day_prev = first_this_month - timedelta(days=1)
            start = last_day_prev.replace(day=1)
            return start, first_this_month, start.strftime("%Y-%m")

        if month_date:
            start = month_date.replace(day=1)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
            return start, end, start.strftime("%Y-%m")

        start = today.replace(day=1)
        return start, today + timedelta(days=1), "этот месяц"

    period = (data.get("period") or "month").lower()

    if period == "today":
        return today, today + timedelta(days=1), "сегодня"

    if period == "day":
        day = _parse_sql_date(data.get("date")) or today
        return day, day + timedelta(days=1), day.strftime("%d.%m.%Y")

    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, today + timedelta(days=1), "эту неделю"

    if period == "prev_week":
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
        return start, end, "прошлую неделю"

    if period == "prev_month":
        first_this_month = today.replace(day=1)
        last_day_prev = first_this_month - timedelta(days=1)
        start = last_day_prev.replace(day=1)
        return start, first_this_month, "прошлый месяц"

    if period == "year":
        start = today.replace(month=1, day=1)
        return start, today + timedelta(days=1), "этот год"

    if period == "custom":
        date_from = _parse_sql_date(data.get("date_from"))
        date_to = _parse_sql_date(data.get("date_to"))
        if date_from and date_to:
            label = f"{date_from.strftime('%d.%m')} – {date_to.strftime('%d.%m.%Y')}"
            return date_from, date_to + timedelta(days=1), label
        if date_from:
            return date_from, today + timedelta(days=1), f"с {date_from.strftime('%d.%m.%Y')}"

    start = today.replace(day=1)
    return start, today + timedelta(days=1), "этот месяц"


def _previous_sql_period(
    start: date,
    end: date,
    intent: str,
    intent_data: dict[str, Any] | None,
) -> tuple[date, date, str]:
    """Build a comparison period aligned to the current analytics window."""
    data = intent_data or {}
    period = (data.get("period") or "month").lower()

    if intent == "query_report":
        if start.day == 1 and end.day == 1:
            last_day_prev = start - timedelta(days=1)
            prev_start = last_day_prev.replace(day=1)
            return prev_start, start, prev_start.strftime("%Y-%m")
        delta = end - start
        prev_start = start - delta
        return prev_start, start, prev_start.strftime("%Y-%m")

    if period in {"today", "day"}:
        return start - timedelta(days=1), start, "предыдущий день"
    if period in {"week", "prev_week"}:
        return start - timedelta(days=7), start, "предыдущую неделю"
    if period == "year":
        return start.replace(year=start.year - 1), end.replace(year=end.year - 1), "предыдущий год"
    if period == "custom":
        delta = end - start
        prev_start = start - delta
        return prev_start, start, "предыдущий период"

    last_day_prev = start - timedelta(days=1)
    prev_start = last_day_prev.replace(day=1)
    return prev_start, start, "предыдущий месяц"


async def _load_sql_stats(
    family_id: str,
    *,
    role: str = "owner",
    user_id: str = "",
    intent: str = "",
    intent_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Layer 4: Load visibility-aware SQL aggregates for the relevant period."""
    from sqlalchemy import func, select

    from src.core.access import apply_visibility_filter
    from src.core.db import async_session
    from src.core.models.category import Category
    from src.core.models.enums import TransactionType
    from src.core.models.transaction import Transaction

    start_date, end_date, period_label = _resolve_sql_period(intent, intent_data)
    prev_start, prev_end, previous_label = _previous_sql_period(
        start_date, end_date, intent, intent_data
    )
    fid = uuid.UUID(family_id)

    period_name = (intent_data or {}).get("period") or (
        "month" if intent != "query_report" else "report"
    )
    stats: dict[str, Any] = {
        "period": period_name,
        "period_label": period_label,
        "period_start": start_date.isoformat(),
        "period_end": (end_date - timedelta(days=1)).isoformat(),
        "total_expense": 0.0,
        "total_income": 0.0,
        "by_category": [],
        "previous_expense": 0.0,
        "previous_label": previous_label,
        "month_start": start_date.isoformat(),
        "prev_month_expense": 0.0,
    }

    try:
        async with async_session() as session:
            expense_stmt = (
                select(
                    Category.name,
                    func.sum(Transaction.amount).label("total"),
                    func.count(Transaction.id).label("cnt"),
                )
                .outerjoin(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.family_id == fid,
                    Transaction.date >= start_date,
                    Transaction.date < end_date,
                    Transaction.type == TransactionType.expense,
                )
                .group_by(Category.name)
                .order_by(func.sum(Transaction.amount).desc())
            )
            result = await session.execute(
                apply_visibility_filter(expense_stmt, Transaction, role, user_id)
            )

            categories = []
            total_expense = Decimal("0")
            for name, total, cnt in result.all():
                amount = total or Decimal("0")
                categories.append(
                    {
                        "name": name or "Без категории",
                        "total": float(amount),
                        "count": cnt,
                    }
                )
                total_expense += amount
            stats["by_category"] = categories
            stats["total_expense"] = float(total_expense)

            income_stmt = select(func.sum(Transaction.amount)).where(
                Transaction.family_id == fid,
                Transaction.date >= start_date,
                Transaction.date < end_date,
                Transaction.type == TransactionType.income,
            )
            income_result = await session.execute(
                apply_visibility_filter(income_stmt, Transaction, role, user_id)
            )
            stats["total_income"] = float(income_result.scalar() or 0)

            prev_stmt = select(func.sum(Transaction.amount)).where(
                Transaction.family_id == fid,
                Transaction.date >= prev_start,
                Transaction.date < prev_end,
                Transaction.type == TransactionType.expense,
            )
            prev_result = await session.execute(
                apply_visibility_filter(prev_stmt, Transaction, role, user_id)
            )
            previous_expense = float(prev_result.scalar() or 0)
            stats["previous_expense"] = previous_expense
            stats["prev_month_expense"] = previous_expense

    except Exception as e:
        logger.warning("Failed to load SQL stats: %s", e)

    return stats


def _format_sql_block(stats: dict[str, Any]) -> str:
    """Format SQL stats as a text block for system prompt injection."""
    period_label = stats.get("period_label") or "текущий месяц"
    lines = [f"{period_label.capitalize()}:"]
    lines.append(f"- Расходы: ${stats['total_expense']:.2f}")
    lines.append(f"- Доходы: ${stats['total_income']:.2f}")
    net = stats["total_income"] - stats["total_expense"]
    lines.append(f"- Баланс: ${net:.2f}")

    prev = stats.get("previous_expense", stats.get("prev_month_expense", 0))
    if prev:
        diff_pct = ((stats["total_expense"] - prev) / prev * 100) if prev else 0
        prev_label = stats.get("previous_label") or "предыдущий период"
        lines.append(f"- {prev_label.capitalize()} расходы: ${prev:.2f} ({diff_pct:+.0f}%)")

    if stats["by_category"]:
        lines.append("\nТоп категории:")
        for cat in stats["by_category"][:5]:
            lines.append(f"  - {cat['name']}: ${cat['total']:.2f} ({cat['count']} раз)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Memory loading helper
# ---------------------------------------------------------------------------
async def _load_memories(
    mem_type: str | bool,
    current_message: str,
    user_id: str,
    intent: str = "",
) -> list[dict]:
    """Load Mem0 memories based on the mem_type configuration.

    Uses domain segmentation when possible: searches only relevant
    domains for the intent, falling back to unscoped search.
    For temporal-history intents, also loads archived ``fact_history`` entries.
    """
    if not mem_type:
        return []

    try:
        from src.core.memory.mem0_domains import (
            TEMPORAL_HISTORY_INTENTS,
            MemoryDomain,
            get_domains_for_intent,
        )

        domains = get_domains_for_intent(intent, mem_type)

        if domains:
            # Domain-scoped search — parallel across relevant domains
            memories = await mem0_client.search_memories_multi_domain(
                current_message,
                user_id,
                domains=domains,
                limit_per_domain=5,
            )
            # Fallback for pre-migration users: if scoped namespaces are empty,
            # search the legacy unscoped user_id so old memories aren't lost
            # until a data-migration task copies them into domain namespaces.
            if not memories:
                memories = await mem0_client.search_memories(
                    current_message, user_id, limit=20
                )
        # Fallback: unscoped search for unmapped intents
        elif mem_type == "all":
            memories = await mem0_client.search_memories(
                current_message, user_id, limit=20
            )
        elif mem_type == "mappings":
            memories = await mem0_client.search_memories(
                current_message,
                user_id,
                limit=10,
                domain=MemoryDomain.finance,
            )
        elif mem_type == "profile":
            memories = await mem0_client.get_all_memories(
                user_id, domain=MemoryDomain.core
            )
        elif mem_type == "budgets":
            memories = await mem0_client.search_memories(
                "budget limits goals",
                user_id,
                limit=10,
                domain=MemoryDomain.finance,
            )
        elif mem_type == "life":
            memories = await mem0_client.search_memories(
                current_message,
                user_id,
                limit=10,
                domain=MemoryDomain.life,
            )
        else:
            memories = []

        # Temporal fact history: for analytical intents, also load archived facts
        if intent in TEMPORAL_HISTORY_INTENTS and memories:
            try:
                history = await mem0_client.search_memories(
                    current_message,
                    user_id,
                    limit=5,
                    filters={"category": "fact_history"},
                    domain=MemoryDomain.finance,
                )
                if history:
                    memories.extend(history)
            except Exception as e:
                logger.debug("Temporal history load failed: %s", e)

        return memories
    except Exception as e:
        logger.warning("Mem0 search failed: %s", e)
        return []


def _format_memories_block(memories: list[dict]) -> str:
    """Format a list of Mem0 memories as a text block."""
    if not memories:
        return ""
    lines = [f"- {m.get('memory', m.get('text', ''))}" for m in memories]
    return "\n\n## Что я знаю о вас:\n" + "\n".join(lines)


def _trim_memories(memories: list[dict], max_tokens: int) -> list[dict]:
    """Trim memories list to fit within token budget (keep top-K relevant)."""
    if not memories:
        return []

    result: list[dict] = []
    used = count_tokens("\n\n## Что я знаю о вас:\n")
    for m in memories:
        line = f"- {m.get('memory', m.get('text', ''))}"
        line_tokens = count_tokens(line + "\n")
        if used + line_tokens > max_tokens:
            break
        result.append(m)
        used += line_tokens
    return result


# ---------------------------------------------------------------------------
# Overflow trimming — respects priority order
# ---------------------------------------------------------------------------
def _split_memories_by_priority(
    memories: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split memories into core (high priority) and non-core (low priority).

    Core domains (finance, core, contacts) are kept longest during overflow.
    Non-core (life, tasks, research, etc.) are dropped first.
    """
    from src.core.memory.mem0_domains import MemoryDomain

    core_domains = {
        MemoryDomain.core.value,
        MemoryDomain.finance.value,
        MemoryDomain.contacts.value,
    }
    core_mems: list[dict] = []
    noncore_mems: list[dict] = []
    for m in memories:
        # Domain is embedded in scoped user_id metadata or category
        domain = m.get("metadata", {}).get("domain", "")
        category = m.get("metadata", {}).get("category", "")
        from src.core.memory.mem0_domains import CATEGORY_DOMAIN_MAP

        resolved_domain = CATEGORY_DOMAIN_MAP.get(category, MemoryDomain.core).value
        if domain:
            resolved_domain = domain
        if resolved_domain in core_domains:
            core_mems.append(m)
        else:
            noncore_mems.append(m)
    return core_mems, noncore_mems


def _apply_overflow_trimming(
    *,
    system_prompt_tokens: int,
    user_msg_tokens: int,
    session_buffer_tokens: int = 0,
    observations_tokens: int = 0,
    mem_block: str,
    sql_block: str,
    summary_block: str,
    history_messages: list[dict[str, str]],
    memories: list[dict],
    total_budget: int,
) -> tuple[str, str, str, list[dict[str, str]], list[dict]]:
    """Trim layers following revised overflow priority until within budget.

    Returns (mem_block, sql_block, summary_block, history_messages, memories).

    Drop order (first to drop → last to drop):
      1. Mem0 non-core namespaces (life, tasks, research, etc.)
      2. Session summary (compress/shorten)
      3. SQL analytics (compress before full drop)
      4. Old history messages (keep MIN_SLIDING_WINDOW)
      5. Mem0 core + finance + contacts (last Mem0 to drop)
      6. Remaining history (absolute last resort)
      NEVER: System prompt + core_identity + session buffer + user message
    """
    # Tokens from layers that are never trimmed — must be counted in every check.
    _fixed_tokens = (
        system_prompt_tokens + user_msg_tokens + session_buffer_tokens + observations_tokens
    )

    def _current_total() -> int:
        total = _fixed_tokens
        if mem_block:
            total += count_tokens(mem_block)
        if sql_block:
            total += count_tokens(sql_block)
        if summary_block:
            total += count_tokens(summary_block)
        total += sum(count_tokens(m["content"]) for m in history_messages)
        return total

    # Overflow priority — conversation history is the most important short-term
    # context. Drop background data first, then history as last resort.

    # Step 1: Drop non-core Mem0 memories (life, tasks, research, etc.)
    if _current_total() > total_budget and mem_block and memories:
        core_mems, noncore_mems = _split_memories_by_priority(memories)
        if noncore_mems:
            memories = core_mems
            mem_block = _format_memories_block(memories)

    # Step 2: Compress/drop summary
    if _current_total() > total_budget and summary_block:
        over = _current_total() - total_budget
        allowed = max(0, count_tokens(summary_block) - over)
        if allowed <= 0:
            summary_block = ""
        else:
            summary_block = _truncate_to_budget(summary_block, allowed)

    # Step 3: Compress SQL before dropping entirely
    if _current_total() > total_budget and sql_block:
        sql_tokens = count_tokens(sql_block)
        if sql_tokens > 2000:
            sql_block = _truncate_to_budget(sql_block, 2000)
        if _current_total() > total_budget:
            sql_block = ""

    # Step 4: Trim oldest history messages (keep MIN_SLIDING_WINDOW)
    while _current_total() > total_budget and len(history_messages) > MIN_SLIDING_WINDOW:
        history_messages = history_messages[1:]

    # Step 5: Trim core Mem0 memories (last resort)
    if _current_total() > total_budget and mem_block:
        over = _current_total() - total_budget
        allowed = max(0, count_tokens(mem_block) - over)
        if allowed <= 0:
            mem_block = ""
            memories = []
        else:
            mem_block = _truncate_to_budget(mem_block, allowed)
            kept = 0
            block_so_far = count_tokens("\n\n## Что я знаю о вас:\n")
            for m in memories:
                line = f"- {m.get('memory', m.get('text', ''))}"
                block_so_far += count_tokens(line + "\n")
                if block_so_far > allowed:
                    break
                kept += 1
            memories = memories[:kept]

    # Step 6: Drop remaining history below MIN_SLIDING_WINDOW (absolute last resort)
    while _current_total() > total_budget and len(history_messages) > 0:
        history_messages = history_messages[1:]

    return mem_block, sql_block, summary_block, history_messages, memories


# ---------------------------------------------------------------------------
# Main assembly function
# ---------------------------------------------------------------------------
@observe(name="assemble_context")
async def assemble_context(
    user_id: str,
    family_id: str,
    current_message: str,
    intent: str,
    system_prompt: str,
    max_tokens: int = MAX_CONTEXT_TOKENS,
    role: str = "owner",
    intent_data: dict[str, Any] | None = None,
) -> AssembledContext:
    """Assemble full context for LLM call from all memory layers.

    Respects token budget: S + M + A + H + U <= max_tokens * 0.75.
    Applies overflow priority trimming and Lost-in-the-Middle positioning.
    """
    ctx_config = QUERY_CONTEXT_MAP.get(intent, QUERY_CONTEXT_MAP["general_chat"])

    # Phase 3.5 — Progressive Context Disclosure
    # Only skip heavy layers (Mem0/SQL/summary). NEVER reduce history —
    # even simple messages like "100 кофе" or "да" need conversation context
    # for merchant mappings, category corrections, and confirmation flow.
    if not needs_heavy_context(current_message, intent):
        ctx_config = {
            **ctx_config,
            "mem": False,
            "sql": False,
            "sum": False,
        }

    # 1. Calculate available budget
    total_budget = int(max_tokens * BUDGET_RATIO)

    # Per-layer budgets (caps, not guaranteed allocations)
    budget_system = int(max_tokens * BUDGET_SYSTEM_PROMPT)
    budget_mem = int(max_tokens * BUDGET_MEM0)
    budget_sql = int(max_tokens * BUDGET_SQL)
    budget_summary = int(max_tokens * BUDGET_SUMMARY)
    budget_history = int(max_tokens * BUDGET_HISTORY)
    # user message budget is implicit (always included, priority 1)

    token_usage: dict[str, int] = {}

    # ------------------------------------------------------------------
    # 2. Core Identity (Priority 0 — NEVER drop, loaded before system prompt)
    # ------------------------------------------------------------------
    identity_block = ""
    try:
        from src.core.identity import format_identity_block, get_core_identity

        identity = await get_core_identity(user_id)
        identity_block = format_identity_block(identity)
    except Exception as e:
        logger.debug("Core identity load failed: %s", e)
    if identity_block:
        # Prepend identity to system prompt (inside cache prefix)
        system_prompt = identity_block + "\n" + system_prompt
    token_usage["identity"] = count_tokens(identity_block) if identity_block else 0

    # ------------------------------------------------------------------
    # 2a. User Rules (Priority 0.5 — NEVER drop, loaded after identity)
    # ------------------------------------------------------------------
    rules_block = ""
    try:
        from src.core.identity import format_rules_block, get_user_rules

        user_rules = await get_user_rules(user_id)
        rules_block = format_rules_block(user_rules)
    except Exception as e:
        logger.debug("User rules load failed: %s", e)
    if rules_block:
        # Append rules right after identity block (inside cache prefix)
        system_prompt = system_prompt + "\n" + rules_block
    token_usage["user_rules"] = count_tokens(rules_block) if rules_block else 0

    # ------------------------------------------------------------------
    # 2a½. Active Project Context (Priority 0.75 — loaded after rules)
    # ------------------------------------------------------------------
    project_block = ""
    try:
        from src.core.memory.project_context import get_active_project_block

        project_block = await get_active_project_block(user_id)
    except Exception as e:
        logger.debug("Project context load failed: %s", e)
    if project_block:
        system_prompt = system_prompt + "\n" + project_block
    token_usage["project_context"] = count_tokens(project_block) if project_block else 0

    # ------------------------------------------------------------------
    # 2b. System prompt (Priority 2 — NEVER drop, but cap)
    # ------------------------------------------------------------------
    system_tokens = count_tokens(system_prompt)
    if system_tokens > budget_system:
        system_prompt = _truncate_to_budget(system_prompt, budget_system)
        system_tokens = count_tokens(system_prompt)
    token_usage["system_prompt"] = system_tokens

    # ------------------------------------------------------------------
    # 3. Current user message (Priority 1 — NEVER drop)
    # ------------------------------------------------------------------
    user_msg_tokens = count_tokens(current_message)
    token_usage["user_message"] = user_msg_tokens

    # ------------------------------------------------------------------
    # 3b. Session buffer (Priority 2.5 — fresh facts from current session)
    # ------------------------------------------------------------------
    buffer_block = ""
    try:
        from src.core.memory.session_buffer import format_buffer_block, get_session_buffer

        buffer_facts = await get_session_buffer(user_id)
        buffer_block = format_buffer_block(buffer_facts)
    except Exception as e:
        logger.debug("Session buffer load failed: %s", e)
    token_usage["session_buffer"] = count_tokens(buffer_block) if buffer_block else 0

    # ------------------------------------------------------------------
    # 3c. Behavioral observations (for analytics/forecast intents)
    # ------------------------------------------------------------------
    observations_block = ""
    try:
        from src.core.memory.observational import (
            OBSERVATION_INTENTS,
            format_observations_block,
            load_user_observations,
        )

        if intent in OBSERVATION_INTENTS:
            observations = await load_user_observations(user_id)
            observations_block = format_observations_block(observations)
    except Exception as e:
        logger.debug("Observations load failed: %s", e)
    token_usage["observations"] = (
        count_tokens(observations_block) if observations_block else 0
    )

    # ------------------------------------------------------------------
    # 3d. Procedural memory (learned rules from corrections)
    # ------------------------------------------------------------------
    procedures_block = ""
    try:
        from src.core.memory.procedural import (
            PROCEDURAL_INTENTS,
            format_procedures_block,
            get_domain_for_intent,
            get_procedures,
            get_realtime_procedures,
        )

        if intent in PROCEDURAL_INTENTS:
            proc_domain = get_domain_for_intent(intent)
            procedures = await get_procedures(user_id, domain=proc_domain)
            # Merge realtime corrections (applied immediately, not waiting weekly cron)
            rt_procedures = await get_realtime_procedures(user_id, domain=proc_domain)
            procedures = rt_procedures + procedures
            procedures_block = format_procedures_block(procedures)
    except Exception as e:
        logger.debug("Procedures load failed: %s", e)
    token_usage["procedures"] = (
        count_tokens(procedures_block) if procedures_block else 0
    )

    # ------------------------------------------------------------------
    # 3e. Episodic memory (past episodes as few-shot for generative intents)
    # ------------------------------------------------------------------
    episodes_block = ""
    try:
        from src.core.memory.episodic import (
            EPISODIC_INTENTS,
            format_episodes_block,
            search_episodes,
        )

        if intent in EPISODIC_INTENTS:
            episodes = await search_episodes(user_id, topic=intent, limit=3)
            episodes_block = format_episodes_block(episodes)
    except Exception as e:
        logger.debug("Episodes load failed: %s", e)
    token_usage["episodes"] = count_tokens(episodes_block) if episodes_block else 0

    # ------------------------------------------------------------------
    # 3f. Graph memory (entity relationships for CRM/booking/email intents)
    # ------------------------------------------------------------------
    graph_block = ""
    try:
        from src.core.memory.graph_memory import GRAPH_INTENTS, format_graph_block

        if intent in GRAPH_INTENTS:
            from src.core.memory.graph_memory import get_relationships

            edges = await get_relationships(family_id, "person", user_id, limit=10)
            graph_block = format_graph_block(edges)
    except Exception as e:
        logger.debug("Graph memory load failed: %s", e)
    token_usage["graph"] = count_tokens(graph_block) if graph_block else 0

    # ------------------------------------------------------------------
    # 4. Mem0 memories (Priority 3)
    # ------------------------------------------------------------------
    memories: list[dict] = []
    mem_block = ""
    if ctx_config["mem"]:
        try:
            memories = await asyncio.wait_for(
                _load_memories(ctx_config["mem"], current_message, user_id, intent=intent),
                timeout=5.0,
            )
        except TimeoutError:
            logger.warning("Mem0 load timed out after 5s for user %s", user_id)
            memories = []
        if memories:
            # Pre-trim to per-layer budget
            memories = _trim_memories(memories, budget_mem)
            mem_block = _format_memories_block(memories)
    token_usage["mem0"] = count_tokens(mem_block) if mem_block else 0

    # ------------------------------------------------------------------
    # 5. SQL analytics (Priority 4)
    # ------------------------------------------------------------------
    sql_stats: dict[str, Any] | None = None
    sql_block = ""
    if ctx_config["sql"]:
        try:
            sql_stats = await _load_sql_stats(
                family_id,
                role=role,
                user_id=user_id,
                intent=intent,
                intent_data=intent_data,
            )
            sql_block = "\n\n## Финансовая сводка:\n" + _format_sql_block(sql_stats)
            if count_tokens(sql_block) > budget_sql:
                sql_block = _truncate_to_budget(sql_block, budget_sql)
        except Exception as e:
            logger.warning("SQL stats load failed: %s", e)
    token_usage["sql"] = count_tokens(sql_block) if sql_block else 0

    # ------------------------------------------------------------------
    # 6. Dialog summary (Priority 6)
    # ------------------------------------------------------------------
    summary_block = ""
    if ctx_config["sum"]:
        try:
            summary = await get_session_summary(user_id)
            if summary:
                summary_block = f"\n\n## Ранее в диалоге:\n{summary.summary}"
                if count_tokens(summary_block) > budget_summary:
                    summary_block = _truncate_to_budget(summary_block, budget_summary)
        except Exception as e:
            logger.warning("Session summary load failed: %s", e)
    token_usage["summary"] = count_tokens(summary_block) if summary_block else 0

    # ------------------------------------------------------------------
    # 7. Sliding window history (Priority 5/7)
    # ------------------------------------------------------------------
    history_messages: list[dict[str, str]] = []
    hist_limit = ctx_config["hist"]
    if hist_limit > 0:
        try:
            recent = await sliding_window.get_recent_messages(user_id, limit=hist_limit)
            for msg in recent:
                content = msg.get("content", "")
                if not content:
                    continue
                msg_entry = {"role": msg["role"], "content": content}
                history_messages.append(msg_entry)

            # Pre-trim history to per-layer budget
            hist_tokens = sum(count_tokens(m["content"]) for m in history_messages)
            while hist_tokens > budget_history and len(history_messages) > MIN_SLIDING_WINDOW:
                removed = history_messages.pop(0)
                hist_tokens -= count_tokens(removed["content"])
        except Exception as e:
            logger.warning("Sliding window fetch failed: %s", e)

    token_usage["history"] = sum(count_tokens(m["content"]) for m in history_messages)

    # ------------------------------------------------------------------
    # 8. Overflow trimming — global budget enforcement
    # ------------------------------------------------------------------
    total_used = (
        system_tokens
        + user_msg_tokens
        + token_usage.get("session_buffer", 0)
        + token_usage.get("observations", 0)
        + token_usage.get("procedures", 0)
        + token_usage.get("episodes", 0)
        + token_usage.get("graph", 0)
        + token_usage.get("mem0", 0)
        + token_usage.get("sql", 0)
        + token_usage.get("summary", 0)
        + token_usage.get("history", 0)
    )

    if total_used > total_budget:
        mem_block, sql_block, summary_block, history_messages, memories = _apply_overflow_trimming(
            system_prompt_tokens=system_tokens,
            user_msg_tokens=user_msg_tokens,
            session_buffer_tokens=token_usage.get("session_buffer", 0),
            observations_tokens=token_usage.get("observations", 0)
            + token_usage.get("procedures", 0)
            + token_usage.get("episodes", 0)
            + token_usage.get("graph", 0),
            mem_block=mem_block,
            sql_block=sql_block,
            summary_block=summary_block,
            history_messages=history_messages,
            memories=memories,
            total_budget=total_budget,
        )
        # Recalculate usage after trimming
        token_usage["mem0"] = count_tokens(mem_block) if mem_block else 0
        token_usage["sql"] = count_tokens(sql_block) if sql_block else 0
        token_usage["summary"] = count_tokens(summary_block) if summary_block else 0
        token_usage["history"] = sum(count_tokens(m["content"]) for m in history_messages)

    token_usage["total"] = (
        token_usage["system_prompt"]
        + token_usage["user_message"]
        + token_usage.get("session_buffer", 0)
        + token_usage.get("observations", 0)
        + token_usage.get("procedures", 0)
        + token_usage.get("episodes", 0)
        + token_usage.get("graph", 0)
        + token_usage.get("mem0", 0)
        + token_usage.get("sql", 0)
        + token_usage.get("summary", 0)
        + token_usage.get("history", 0)
    )
    token_usage["budget"] = total_budget

    # ------------------------------------------------------------------
    # 9. Lost-in-the-Middle positioning
    #
    # BEGINNING (high priority): System prompt, critical rules, categories
    # MIDDLE   (low priority):   Analytics, summary, old messages
    # END      (high priority):  Mem0 memory, last 2-3 messages, current msg
    # ------------------------------------------------------------------

    # Build the enriched system prompt with cache-friendly ordering:
    #   STATIC PREFIX (cacheable — identical across requests for the same agent):
    #     base system prompt (role, rules, categories)
    #   CACHE BREAKPOINT
    #   DYNAMIC SUFFIX (changes per request):
    #     SQL block (MIDDLE — lower priority)
    #     summary block (MIDDLE)
    #     mem block (END of system prompt — high priority, close to recent msgs)
    from src.core.llm.prompts import CACHE_BREAKPOINT

    has_dynamic = bool(
        sql_block or summary_block or mem_block or buffer_block
        or observations_block or procedures_block or episodes_block or graph_block
    )
    enriched_prompt_parts = [system_prompt]
    if has_dynamic:
        enriched_prompt_parts.append(CACHE_BREAKPOINT)
        if sql_block:
            enriched_prompt_parts.append(sql_block)
        if summary_block:
            enriched_prompt_parts.append(summary_block)
        if observations_block:
            enriched_prompt_parts.append(observations_block)
        if procedures_block:
            enriched_prompt_parts.append(procedures_block)
        if episodes_block:
            enriched_prompt_parts.append(episodes_block)
        if graph_block:
            enriched_prompt_parts.append(graph_block)
        if mem_block:
            enriched_prompt_parts.append(mem_block)
        if buffer_block:
            enriched_prompt_parts.append(buffer_block)
    enriched_prompt = "".join(enriched_prompt_parts)

    # Build messages list with Lost-in-the-Middle positioning:
    #   [system] (BEGINNING)
    #   [old history messages] (MIDDLE — low priority)
    #   [last 2-3 history messages] (END — high priority)
    #   [current user message] (END — highest priority)
    messages: list[dict[str, str]] = []

    # System prompt is always first
    messages.append({"role": "system", "content": enriched_prompt})

    # History messages: already in chronological order (old -> recent)
    # The last 2-3 are "high priority" (near end), older ones are "middle"
    for msg in history_messages:
        messages.append(msg)

    # Current user message is always last
    messages.append({"role": "user", "content": current_message})

    logger.debug(
        "Assembled context for intent=%s: %d messages, %d memories, sql=%s, tokens=%d/%d",
        intent,
        len(messages),
        len(memories),
        sql_stats is not None,
        token_usage["total"],
        total_budget,
    )

    return AssembledContext(
        system_prompt=enriched_prompt,
        messages=messages,
        memories=memories,
        sql_stats=sql_stats,
        token_usage=token_usage,
    )
