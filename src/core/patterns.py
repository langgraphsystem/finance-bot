"""Financial pattern detection -- weekly LLM analysis of spending."""

import json
import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from src.core.db import async_session
from src.core.llm.clients import google_client
from src.core.models.category import Category
from src.core.models.enums import TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe

logger = logging.getLogger(__name__)

PATTERN_EXTRACTION_PROMPT = """
Проанализируй транзакции пользователя и историю диалогов.
Извлеки финансовые паттерны.

ТРАНЗАКЦИИ:
{transactions}

СУЩЕСТВУЮЩИЕ ПАТТЕРНЫ:
{existing_patterns}

ИЗВЛЕКИ:
1. ТРЕНДЫ РАСХОДОВ: рост/снижение в категориях?
2. РЕГУЛЯРНЫЕ ПЛАТЕЖИ: новые подписки, повторяющиеся суммы?
3. АНОМАЛИИ: нетипичные траты по сравнению с историей?
4. ВРЕМЕННЫЕ ПАТТЕРНЫ: когда обычно тратит (день недели, время)?
5. СМЕНА КАТЕГОРИЙ: меняются ли приоритеты расходов?

Верни JSON:
{{
  "patterns": ["pattern1", ...],
  "anomalies": ["anomaly1", ...],
  "recommendations": ["recommendation1", ...]
}}
"""

MIN_TRANSACTIONS_FOR_ANALYSIS = 5


@observe(name="detect_patterns")
async def detect_patterns(family_id: str) -> dict | None:
    """Analyze last 30 days of transactions for a family and extract patterns.

    Returns a dict with keys ``patterns``, ``anomalies``, ``recommendations``
    or *None* when there is not enough data or the LLM call fails.
    """
    today = date.today()
    start = today - timedelta(days=30)

    async with async_session() as session:
        result = await session.execute(
            select(
                Transaction.description,
                Transaction.amount,
                Transaction.date,
                Transaction.merchant,
                Category.name.label("category"),
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= start,
                Transaction.type == TransactionType.expense,
            )
            .order_by(Transaction.date.desc())
            .limit(100)
        )
        transactions = result.all()

    if len(transactions) < MIN_TRANSACTIONS_FOR_ANALYSIS:
        logger.debug(
            "Skipping pattern detection for family %s: only %d transactions",
            family_id,
            len(transactions),
        )
        return None

    # Format transactions for the prompt
    tx_text = "\n".join(
        f"- {t.date}: {t.category} | {t.merchant or t.description} | ${float(t.amount):.2f}"
        for t in transactions
    )

    prompt = PATTERN_EXTRACTION_PROMPT.format(
        transactions=tx_text,
        existing_patterns="Нет предыдущих паттернов.",
    )

    try:
        client = google_client()
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text

        # Extract JSON from LLM response (may contain markdown fences etc.)
        start_idx = text.find("{")
        end_idx = text.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            parsed: dict = json.loads(text[start_idx:end_idx])
            logger.info(
                "Pattern detection for family %s: %d patterns, %d anomalies, %d recs",
                family_id,
                len(parsed.get("patterns", [])),
                len(parsed.get("anomalies", [])),
                len(parsed.get("recommendations", [])),
            )
            return parsed

        logger.warning("No JSON found in LLM response for family %s", family_id)
    except Exception as e:
        logger.error("Pattern detection failed for family %s: %s", family_id, e)

    return None


async def store_patterns(family_id: str, patterns: dict) -> None:
    """Store detected patterns in Mem0 for future reference."""
    from src.core.memory.mem0_client import add_memory

    summary_parts: list[str] = []
    for p in patterns.get("patterns", []):
        summary_parts.append(f"Паттерн: {p}")
    for a in patterns.get("anomalies", []):
        summary_parts.append(f"Аномалия: {a}")
    for r in patterns.get("recommendations", []):
        summary_parts.append(f"Рекомендация: {r}")

    if summary_parts:
        content = "\n".join(summary_parts)
        await add_memory(
            content=content,
            user_id=f"family:{family_id}",
            metadata={"type": "spending_pattern", "source": "weekly_analysis"},
        )
        logger.info("Stored %d pattern items for family %s", len(summary_parts), family_id)
