"""Background tasks for memory updates via Taskiq."""

import logging

from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


@broker.task
async def async_mem0_update(user_id: str, message: str, metadata: dict | None = None) -> None:
    """Background: extract and store financial facts in Mem0.

    Domain is auto-derived from metadata["category"] inside add_memory().
    After successful persistence, clears the session buffer so stale
    facts don't shadow the now-persisted Mem0 data.
    """
    from src.core.memory.mem0_client import add_memory

    try:
        await add_memory(message, user_id=user_id, metadata=metadata)
        logger.info("Mem0 updated for user %s", user_id)

        # C3: Clear session buffer after successful Mem0 persistence
        try:
            from src.core.memory.session_buffer import clear_session_buffer

            await clear_session_buffer(user_id)
        except Exception as e:
            logger.debug("Session buffer clear failed (non-critical): %s", e)
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
    from sqlalchemy import select

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

        # Create graph relationship: merchant → category (frequent_merchant)
        try:
            from src.core.memory.graph_memory import add_relationship

            await add_relationship(
                family_id,
                subject_type="merchant",
                subject_id=merchant.lower(),
                relation="frequent_merchant",
                object_type="category",
                object_id=category_id,
                metadata={"scope": scope},
            )
        except Exception as graph_err:
            logger.debug("Graph edge creation failed (non-critical): %s", graph_err)
    except Exception as e:
        logger.error("Merchant mapping update failed: %s", e)


@broker.task(schedule=[{"cron": "0 4 * * 0"}])
async def async_procedural_update() -> None:
    """Weekly (Sunday 4am): analyze corrections → generate domain procedures.

    For each user with corrections, groups by domain, extracts procedural
    rules via LLM, and saves to learned_patterns["procedures"].
    """
    from sqlalchemy import select

    from src.core.db import async_session
    from src.core.memory.procedural import (
        PROCEDURAL_DOMAINS,
        extract_procedures,
        save_procedures,
    )
    from src.core.models.user import User
    from src.core.models.user_profile import UserProfile

    try:
        async with async_session() as session:
            result = await session.execute(
                select(User.id, UserProfile.learned_patterns)
                .join(UserProfile, User.id == UserProfile.user_id)
                .where(UserProfile.learned_patterns.isnot(None))
            )
            users = result.all()

        for user_id, patterns in users:
            if not patterns or not isinstance(patterns, dict):
                continue
            corrections = patterns.get("corrections", [])
            if not corrections:
                continue

            observations = patterns.get("observations", [])
            uid = str(user_id)

            # Group corrections by domain
            by_domain: dict[str, list] = {}
            for c in corrections:
                domain = c.get("domain", "general")
                if domain not in PROCEDURAL_DOMAINS:
                    continue
                by_domain.setdefault(domain, []).append(c)

            # Extract procedures per domain
            for domain, domain_corrections in by_domain.items():
                if len(domain_corrections) < 2:
                    continue  # Need at least 2 corrections to infer a pattern
                try:
                    rules = await extract_procedures(
                        domain, domain_corrections, observations
                    )
                    if rules:
                        await save_procedures(uid, domain, rules)
                        logger.info(
                            "Generated %d procedures for user %s domain %s",
                            len(rules), uid, domain,
                        )
                except Exception as e:
                    logger.debug(
                        "Procedure extraction failed for user %s domain %s: %s",
                        uid, domain, e,
                    )
    except Exception as e:
        logger.error("Procedural update cron failed: %s", e)


@broker.task
async def async_check_budget(family_id: str, category_id: str) -> None:
    """Background: check if category spending exceeds budget."""
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from src.core.db import async_session
    from src.core.models.budget import Budget
    from src.core.models.enums import TransactionType
    from src.core.models.transaction import Transaction

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
                    family_id,
                    category_id,
                    ratio * 100,
                    spent,
                    float(budget.amount),
                )
    except Exception as e:
        logger.error("Budget check failed: %s", e)
