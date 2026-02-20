"""Add recurring payment skill — manages subscriptions, rent, and other recurring expenses."""

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from src.core.audit import log_action
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import PaymentFrequency
from src.core.models.recurring_payment import RecurringPayment
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

RECURRING_SYSTEM_PROMPT = """\
Ты записываешь регулярный платёж пользователя \
(подписки, аренда и т.д.).
Извлеки: название, сумму, периодичность \
(weekly/monthly/quarterly/yearly), категорию.

Категории пользователя:
{categories}

Триггеры: "подписка", "recurring", "каждый месяц плачу", "аренда 50000"

Периодичность по умолчанию — monthly, если не указана явно."""

FREQUENCY_ALIASES = {
    "еженедельно": PaymentFrequency.weekly,
    "weekly": PaymentFrequency.weekly,
    "каждую неделю": PaymentFrequency.weekly,
    "ежемесячно": PaymentFrequency.monthly,
    "monthly": PaymentFrequency.monthly,
    "каждый месяц": PaymentFrequency.monthly,
    "ежеквартально": PaymentFrequency.quarterly,
    "quarterly": PaymentFrequency.quarterly,
    "каждый квартал": PaymentFrequency.quarterly,
    "ежегодно": PaymentFrequency.yearly,
    "yearly": PaymentFrequency.yearly,
    "каждый год": PaymentFrequency.yearly,
}

FREQUENCY_LABELS = {
    PaymentFrequency.weekly: "еженедельно",
    PaymentFrequency.monthly: "ежемесячно",
    PaymentFrequency.quarterly: "ежеквартально",
    PaymentFrequency.yearly: "ежегодно",
}


def _resolve_frequency(raw: str | None) -> PaymentFrequency:
    """Resolve frequency string to PaymentFrequency enum."""
    if not raw:
        return PaymentFrequency.monthly
    raw_lower = raw.lower().strip()
    # Direct enum value match
    try:
        return PaymentFrequency(raw_lower)
    except ValueError:
        pass
    # Exact alias match (full string)
    if raw_lower in FREQUENCY_ALIASES:
        return FREQUENCY_ALIASES[raw_lower]
    # Phrase alias match — only multi-word aliases to avoid false positives
    for alias, freq in sorted(FREQUENCY_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if " " in alias and alias in raw_lower:
            return freq
    return PaymentFrequency.monthly


def _compute_next_date(from_date: date, frequency: PaymentFrequency) -> date:
    """Compute next payment date from a given date and frequency."""
    if frequency == PaymentFrequency.weekly:
        return from_date + timedelta(weeks=1)
    elif frequency == PaymentFrequency.monthly:
        month = from_date.month + 1
        year = from_date.year
        if month > 12:
            month = 1
            year += 1
        day = min(from_date.day, 28)
        return date(year, month, day)
    elif frequency == PaymentFrequency.quarterly:
        month = from_date.month + 3
        year = from_date.year
        while month > 12:
            month -= 12
            year += 1
        return date(year, month, min(from_date.day, 28))
    elif frequency == PaymentFrequency.yearly:
        return date(from_date.year + 1, from_date.month, from_date.day)
    return from_date + timedelta(days=30)


class AddRecurringSkill:
    name = "add_recurring"
    intents = ["add_recurring"]
    model = "gpt-5.2"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        amount = intent_data.get("amount")
        name = intent_data.get("description") or intent_data.get("merchant") or ""
        category_name = intent_data.get("category")
        frequency_raw = intent_data.get("frequency")

        if not amount:
            return SkillResult(
                response_text="Не удалось определить сумму. Укажите сумму регулярного платежа."
            )

        if not name:
            return SkillResult(
                response_text=(
                    "Укажите название регулярного платежа (например: аренда, Netflix, спортзал)."
                )
            )

        # Resolve category
        category_id = self._resolve_category(category_name, context)
        if not category_id:
            return SkillResult(
                response_text=f"Не нашёл категорию \u00ab{category_name}\u00bb. Выберите:",
                buttons=[
                    {"text": c["name"], "callback": f"recurring_cat:{c['id']}:{amount}:{name}"}
                    for c in context.categories[:6]
                ],
            )

        frequency = _resolve_frequency(frequency_raw)
        today = date.today()
        next_date = _compute_next_date(today, frequency)

        async with async_session() as session:
            payment = RecurringPayment(
                family_id=uuid.UUID(context.family_id),
                user_id=uuid.UUID(context.user_id),
                category_id=uuid.UUID(category_id),
                name=name,
                amount=Decimal(str(amount)),
                frequency=frequency,
                next_date=next_date,
                auto_record=True,
                is_active=True,
            )
            session.add(payment)
            await session.flush()

            await log_action(
                session=session,
                family_id=context.family_id,
                user_id=context.user_id,
                action="create",
                entity_type="recurring_payment",
                entity_id=str(payment.id),
                new_data={
                    "name": name,
                    "amount": float(payment.amount),
                    "frequency": frequency.value,
                    "category": category_name,
                },
            )

            await session.commit()

        freq_label = FREQUENCY_LABELS.get(frequency, frequency.value)
        response = (
            f"Регулярный платёж создан:\n"
            f"  {name} — ${amount} ({freq_label})\n"
            f"  Следующая дата: {next_date.isoformat()}"
        )

        return SkillResult(response_text=response)

    def _resolve_category(self, category_name: str | None, context: SessionContext) -> str | None:
        if not category_name:
            return None
        for cat in context.categories:
            if cat.get("name", "").lower() == category_name.lower():
                return cat.get("id")
        return None

    def get_system_prompt(self, context: SessionContext) -> str:
        categories = "\n".join(f"- {c['name']} ({c.get('scope', '')})" for c in context.categories)
        return RECURRING_SYSTEM_PROMPT.format(categories=categories)


skill = AddRecurringSkill()
