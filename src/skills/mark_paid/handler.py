"""Mark load as paid skill — trucking load payment tracking."""

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select

from src.core.audit import log_action
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import LoadStatus, Scope, TransactionType
from src.core.models.load import Load
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

MARK_PAID_SYSTEM_PROMPT = """Ты помогаешь отслеживать оплату грузов.
Помоги пользователю отметить груз как оплаченный."""


class MarkPaidSkill:
    name = "mark_paid"
    intents = ["mark_paid"]
    model = "claude-haiku-4-5-20251001"

    @observe(name="mark_paid")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Mark the latest unpaid/delivered load as paid."""
        async with async_session() as session:
            # Find the latest delivered but unpaid load
            result = await session.execute(
                select(Load)
                .where(
                    Load.family_id == uuid.UUID(context.family_id),
                    Load.status == LoadStatus.delivered,
                )
                .order_by(desc(Load.delivery_date))
                .limit(1)
            )
            load = result.scalar_one_or_none()

            if not load:
                # Try finding any pending load
                result2 = await session.execute(
                    select(Load)
                    .where(
                        Load.family_id == uuid.UUID(context.family_id),
                        Load.status.in_([LoadStatus.pending, LoadStatus.delivered]),
                    )
                    .order_by(desc(Load.pickup_date))
                    .limit(1)
                )
                load = result2.scalar_one_or_none()

            if not load:
                return SkillResult(response_text="Нет неоплаченных грузов для отметки.")

            # Mark as paid
            old_status = load.status.value
            load.status = LoadStatus.paid
            load.paid_date = date.today()

            # Create income transaction for the load payment
            from src.core.models.category import Category

            cat_result = await session.execute(
                select(Category)
                .where(
                    Category.family_id == uuid.UUID(context.family_id),
                    Category.scope == Scope.business,
                )
                .limit(1)
            )
            category = cat_result.scalar_one_or_none()

            if category and load.rate:
                tx = Transaction(
                    family_id=uuid.UUID(context.family_id),
                    user_id=uuid.UUID(context.user_id),
                    category_id=category.id,
                    type=TransactionType.income,
                    amount=load.rate,
                    description=(
                        f"Оплата груза: {load.broker or ''} {load.origin}\u2192{load.destination}"
                    ),
                    date=date.today(),
                    scope=Scope.business,
                    ai_confidence=Decimal("1.0"),
                    meta={"source": "mark_paid", "load_id": str(load.id)},
                )
                session.add(tx)

            # Audit log
            await log_action(
                session=session,
                user_id=context.user_id,
                family_id=context.family_id,
                action="mark_paid",
                entity_type="load",
                entity_id=str(load.id),
                old_data={"status": old_status},
                new_data={"status": "paid", "paid_date": str(date.today())},
            )

            await session.commit()

        route_info = (
            f"{load.origin} \u2192 {load.destination}" if load.origin and load.destination else ""
        )
        rate_info = f"${float(load.rate):.2f}" if load.rate else ""

        return SkillResult(
            response_text=f"\u2705 Груз отмечен как оплаченный!\n"
            f"{'Маршрут: ' + route_info if route_info else ''}\n"
            f"{'Сумма: ' + rate_info if rate_info else ''}"
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return MARK_PAID_SYSTEM_PROMPT


skill = MarkPaidSkill()
