"""Context assembly — builds the full LLM context from all memory layers.

Phase 2: Token budget management with overflow priority,
QUERY_CONTEXT_MAP per intent, and Lost-in-the-Middle positioning.
"""

import logging
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

# Overflow priority (lower number = NEVER drop)
# Priority 1: Current user message   — NEVER drop
# Priority 2: System prompt          — NEVER drop
# Priority 3: Mem0 memory            — trim (keep top-K relevant)
# Priority 4: SQL analytics          — trim (current month only)
# Priority 5: Sliding window         — reduce count from 10 to 5
# Priority 6: Summary                — compress/shorten
# Priority 7: Old messages           — drop FIRST

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
    "query_stats": {"mem": "budgets", "hist": 0, "sql": True, "sum": False},
    "query_report": {"mem": "profile", "hist": 0, "sql": True, "sum": False},
    "correct_category": {"mem": "mappings", "hist": 5, "sql": False, "sum": False},
    "complex_query": {"mem": "all", "hist": 5, "sql": True, "sum": True},
    "general_chat": {"mem": False, "hist": 5, "sql": False, "sum": False},
    "undo_last": {"mem": False, "hist": 5, "sql": False, "sum": False},
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
    "life_search": {"mem": "life", "hist": 0, "sql": False, "sum": False},
    "set_comm_mode": {"mem": False, "hist": 0, "sql": False, "sum": False},
    # Task intents
    "create_task": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "list_tasks": {"mem": False, "hist": 0, "sql": False, "sum": False},
    "set_reminder": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
    "complete_task": {"mem": False, "hist": 3, "sql": False, "sum": False},
    # Research intents
    "quick_answer": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "web_search": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "compare_options": {"mem": False, "hist": 3, "sql": False, "sum": False},
    # Writing intents
    "draft_message": {"mem": "profile", "hist": 5, "sql": False, "sum": False},
    "translate_text": {"mem": False, "hist": 3, "sql": False, "sum": False},
    "write_post": {"mem": "profile", "hist": 5, "sql": False, "sum": False},
    "proofread": {"mem": False, "hist": 3, "sql": False, "sum": False},
}


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
# SQL stats loader (unchanged)
# ---------------------------------------------------------------------------
async def _load_sql_stats(family_id: str) -> dict[str, Any]:
    """Layer 4: Load SQL aggregates for current month."""
    import uuid

    from sqlalchemy import func, select

    from src.core.db import async_session
    from src.core.models.category import Category
    from src.core.models.enums import TransactionType
    from src.core.models.transaction import Transaction

    today = date.today()
    month_start = today.replace(day=1)
    prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
    fid = uuid.UUID(family_id)

    stats: dict[str, Any] = {
        "period": "current_month",
        "month_start": month_start.isoformat(),
        "total_expense": 0,
        "total_income": 0,
        "by_category": [],
        "prev_month_expense": 0,
    }

    try:
        async with async_session() as session:
            # Current month expenses by category
            result = await session.execute(
                select(
                    Category.name,
                    func.sum(Transaction.amount).label("total"),
                    func.count(Transaction.id).label("cnt"),
                )
                .join(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.family_id == fid,
                    Transaction.date >= month_start,
                    Transaction.type == TransactionType.expense,
                )
                .group_by(Category.name)
                .order_by(func.sum(Transaction.amount).desc())
            )
            categories = []
            total_expense = Decimal("0")
            for name, total, cnt in result.all():
                categories.append({"name": name, "total": float(total), "count": cnt})
                total_expense += total
            stats["by_category"] = categories
            stats["total_expense"] = float(total_expense)

            # Current month income
            income_result = await session.execute(
                select(func.sum(Transaction.amount)).where(
                    Transaction.family_id == fid,
                    Transaction.date >= month_start,
                    Transaction.type == TransactionType.income,
                )
            )
            stats["total_income"] = float(income_result.scalar() or 0)

            # Previous month total expense (for comparison)
            prev_result = await session.execute(
                select(func.sum(Transaction.amount)).where(
                    Transaction.family_id == fid,
                    Transaction.date >= prev_month_start,
                    Transaction.date < month_start,
                    Transaction.type == TransactionType.expense,
                )
            )
            stats["prev_month_expense"] = float(prev_result.scalar() or 0)

    except Exception as e:
        logger.warning("Failed to load SQL stats: %s", e)

    return stats


def _format_sql_block(stats: dict[str, Any]) -> str:
    """Format SQL stats as a text block for system prompt injection."""
    lines = [f"Текущий месяц (с {stats['month_start']}):"]
    lines.append(f"- Расходы: ${stats['total_expense']:.2f}")
    lines.append(f"- Доходы: ${stats['total_income']:.2f}")
    net = stats["total_income"] - stats["total_expense"]
    lines.append(f"- Баланс: ${net:.2f}")

    if stats["prev_month_expense"]:
        prev = stats["prev_month_expense"]
        diff_pct = ((stats["total_expense"] - prev) / prev * 100) if prev else 0
        lines.append(f"- Прошлый месяц расходы: ${prev:.2f} ({diff_pct:+.0f}%)")

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
) -> list[dict]:
    """Load Mem0 memories based on the mem_type configuration."""
    if not mem_type:
        return []

    try:
        if mem_type == "all":
            return await mem0_client.search_memories(current_message, user_id, limit=20)
        elif mem_type == "mappings":
            return await mem0_client.search_memories(
                current_message,
                user_id,
                limit=10,
                filters={"category": "merchant_mapping"},
            )
        elif mem_type == "profile":
            return await mem0_client.get_all_memories(user_id)
        elif mem_type == "budgets":
            return await mem0_client.search_memories(
                "budget limits goals",
                user_id,
                limit=10,
            )
        elif mem_type == "life":
            memories = await mem0_client.search_memories(
                current_message,
                user_id,
                limit=10,
            )
            # Filter to life-related memories
            return [
                m for m in memories if m.get("metadata", {}).get("category", "").startswith("life_")
            ]
        else:
            return []
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
def _apply_overflow_trimming(
    *,
    system_prompt_tokens: int,
    user_msg_tokens: int,
    mem_block: str,
    sql_block: str,
    summary_block: str,
    history_messages: list[dict[str, str]],
    memories: list[dict],
    total_budget: int,
) -> tuple[str, str, str, list[dict[str, str]], list[dict]]:
    """Trim layers following overflow priority until within budget.

    Returns (mem_block, sql_block, summary_block, history_messages, memories)
    after trimming.

    Priority (what to drop first -> last):
      7. Old messages from sliding window (drop FIRST)
      6. Summary (shorten)
      5. Sliding window (reduce count from 10->5)
      4. SQL analytics (trim to current month only)
      3. Mem0 memory (trim top-K)
      1-2. User message + System prompt (NEVER drop)
    """

    def _current_total() -> int:
        total = system_prompt_tokens + user_msg_tokens
        if mem_block:
            total += count_tokens(mem_block)
        if sql_block:
            total += count_tokens(sql_block)
        if summary_block:
            total += count_tokens(summary_block)
        total += sum(count_tokens(m["content"]) for m in history_messages)
        return total

    # Priority 7: Drop oldest messages from sliding window first
    while _current_total() > total_budget and len(history_messages) > MIN_SLIDING_WINDOW:
        history_messages = history_messages[1:]  # drop oldest

    # Priority 6: Compress summary
    if _current_total() > total_budget and summary_block:
        over = _current_total() - total_budget
        allowed = max(0, count_tokens(summary_block) - over)
        if allowed <= 0:
            summary_block = ""
        else:
            summary_block = _truncate_to_budget(summary_block, allowed)

    # Priority 5: Reduce sliding window further (below MIN if needed)
    while _current_total() > total_budget and len(history_messages) > 0:
        history_messages = history_messages[1:]

    # Priority 4: Trim SQL analytics
    if _current_total() > total_budget and sql_block:
        over = _current_total() - total_budget
        allowed = max(0, count_tokens(sql_block) - over)
        if allowed <= 0:
            sql_block = ""
        else:
            sql_block = _truncate_to_budget(sql_block, allowed)

    # Priority 3: Trim Mem0 memories (keep fewer)
    if _current_total() > total_budget and mem_block:
        over = _current_total() - total_budget
        allowed = max(0, count_tokens(mem_block) - over)
        if allowed <= 0:
            mem_block = ""
            memories = []
        else:
            mem_block = _truncate_to_budget(mem_block, allowed)
            # Re-derive memories list to match trimmed block
            kept = 0
            block_so_far = count_tokens("\n\n## Что я знаю о вас:\n")
            for m in memories:
                line = f"- {m.get('memory', m.get('text', ''))}"
                block_so_far += count_tokens(line + "\n")
                if block_so_far > allowed:
                    break
                kept += 1
            memories = memories[:kept]

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
) -> AssembledContext:
    """Assemble full context for LLM call from all memory layers.

    Respects token budget: S + M + A + H + U <= max_tokens * 0.75.
    Applies overflow priority trimming and Lost-in-the-Middle positioning.
    """
    ctx_config = QUERY_CONTEXT_MAP.get(intent, QUERY_CONTEXT_MAP["general_chat"])

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
    # 2. System prompt (Priority 2 — NEVER drop, but cap)
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
    # 4. Mem0 memories (Priority 3)
    # ------------------------------------------------------------------
    memories: list[dict] = []
    mem_block = ""
    if ctx_config["mem"]:
        memories = await _load_memories(ctx_config["mem"], current_message, user_id)
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
            sql_stats = await _load_sql_stats(family_id)
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
        + token_usage.get("mem0", 0)
        + token_usage.get("sql", 0)
        + token_usage.get("summary", 0)
        + token_usage.get("history", 0)
    )

    if total_used > total_budget:
        mem_block, sql_block, summary_block, history_messages, memories = _apply_overflow_trimming(
            system_prompt_tokens=system_tokens,
            user_msg_tokens=user_msg_tokens,
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

    # Build the enriched system prompt with Lost-in-the-Middle ordering:
    #   base system prompt (BEGINNING)
    #   + SQL block (MIDDLE — lower priority content)
    #   + summary block (MIDDLE)
    #   + mem block (END of system prompt — high priority, close to recent msgs)
    enriched_prompt_parts = [system_prompt]
    if sql_block:
        enriched_prompt_parts.append(sql_block)
    if summary_block:
        enriched_prompt_parts.append(summary_block)
    if mem_block:
        enriched_prompt_parts.append(mem_block)
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
