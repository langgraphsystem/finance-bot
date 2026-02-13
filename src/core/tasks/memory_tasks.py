"""Background tasks for memory updates via Taskiq."""

import logging

from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


@broker.task
async def async_mem0_update(user_id: str, message: str, metadata: dict | None = None) -> None:
    """Background: extract and store financial facts in Mem0."""
    from src.core.memory.mem0_client import add_memory

    try:
        await add_memory(message, user_id=user_id, metadata=metadata)
        logger.info("Mem0 updated for user %s", user_id)
    except Exception as e:
        logger.error("Mem0 update failed for user %s: %s", user_id, e)


@broker.task
async def async_update_merchant_mapping(
    family_id: str,
    merchant: str,
    category_id: str,
    scope: str,
) -> None:
    """Background: update merchant → category mapping."""
    from sqlalchemy import select, update as sa_update
    from src.core.db import async_session
    from src.core.models.merchant_mapping import MerchantMapping

    try:
        async with async_session() as session:
            result = await session.execute(
                select(MerchantMapping).where(
                    MerchantMapping.family_id == family_id,
                    MerchantMapping.merchant_pattern == merchant,
                )
            )
            mapping = result.scalar_one_or_none()
            if mapping:
                mapping.usage_count += 1
                mapping.confidence = min(1.0, mapping.confidence + 0.05)
            else:
                import uuid
                new_mapping = MerchantMapping(
                    family_id=uuid.UUID(family_id),
                    merchant_pattern=merchant,
                    category_id=uuid.UUID(category_id),
                    scope=scope,
                    usage_count=1,
                    confidence=0.6,
                )
                session.add(new_mapping)
            await session.commit()
            logger.info("Merchant mapping updated: %s → %s", merchant, category_id)
    except Exception as e:
        logger.error("Merchant mapping update failed: %s", e)


@broker.task
async def async_check_budget(family_id: str, category_id: str) -> None:
    """Background: check if category spending exceeds budget."""
    from sqlalchemy import select, func
    from src.core.db import async_session
    from src.core.models.budget import Budget
    from src.core.models.transaction import Transaction
    from src.core.models.enums import TransactionType
    from datetime import date, timedelta

    try:
        async with async_session() as session:
            result = await session.execute(
                select(Budget).where(
                    Budget.family_id == family_id,
                    Budget.category_id == category_id,
                    Budget.is_active.is_(True),
                )
            )
            budget = result.scalar_one_or_none()
            if not budget:
                return

            # Calculate current spending
            today = date.today()
            if budget.period.value == "monthly":
                start = today.replace(day=1)
            else:
                start = today - timedelta(days=today.weekday())

            spent_result = await session.execute(
                select(func.sum(Transaction.amount)).where(
                    Transaction.family_id == family_id,
                    Transaction.category_id == category_id,
                    Transaction.date >= start,
                    Transaction.type == TransactionType.expense,
                )
            )
            spent = spent_result.scalar() or 0

            ratio = float(spent) / float(budget.amount) if budget.amount else 0
            if ratio >= float(budget.alert_at):
                logger.warning(
                    "Budget alert: family %s, category %s at %.0f%% (%.2f/%.2f)",
                    family_id, category_id, ratio * 100, spent, float(budget.amount),
                )
    except Exception as e:
        logger.error("Budget check failed: %s", e)
