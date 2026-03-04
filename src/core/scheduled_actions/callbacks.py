"""Callback handlers for scheduled action inline buttons."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import ActionStatus
from src.core.models.scheduled_action import ScheduledAction
from src.core.scheduled_actions.engine import compute_next_run, now_utc
from src.core.scheduled_actions.i18n import t

logger = logging.getLogger(__name__)


def _extract_snooze_minutes(action: ScheduledAction) -> int:
    raw = (action.schedule_config or {}).get("snooze_minutes", 10)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 10
    return max(1, min(value, 1440))


def _log_callback_used(action: ScheduledAction, context: SessionContext, sub_action: str) -> None:
    logger.info(
        "scheduled_action_callback_used action_id=%s user_id=%s family_id=%s "
        "sub_action=%s status=%s",
        action.id,
        context.user_id,
        context.family_id,
        sub_action,
        action.status,
    )


async def handle_sched_callback(
    *,
    sub_action: str,
    action_id: str,
    context: SessionContext,
) -> str:
    """Handle sched:* callbacks and return localized response text."""
    language = context.language or "en"

    try:
        action_uuid = uuid.UUID(action_id)
    except ValueError:
        return t("sched_invalid", language)

    async with async_session() as session:
        action = await session.scalar(
            select(ScheduledAction).where(
                ScheduledAction.id == action_uuid,
                ScheduledAction.family_id == uuid.UUID(context.family_id),
                ScheduledAction.user_id == uuid.UUID(context.user_id),
            )
        )
        if not action:
            # Avoid leaking ownership details.
            return t("sched_not_found", language)

        now = now_utc()

        if sub_action == "snooze":
            minutes = _extract_snooze_minutes(action)
            base = action.next_run_at or now
            action.next_run_at = max(base, now) + timedelta(minutes=minutes)
            action.status = ActionStatus.active
            await session.commit()
            _log_callback_used(action, context, sub_action)
            return t("sched_snoozed", language, minutes=minutes)

        if sub_action == "pause":
            action.status = ActionStatus.paused
            await session.commit()
            _log_callback_used(action, context, sub_action)
            return t("sched_paused", language, title=action.title)

        if sub_action == "resume":
            action.status = ActionStatus.active
            if not action.next_run_at or action.next_run_at <= now:
                action.next_run_at = compute_next_run(action, after=now)
            await session.commit()
            _log_callback_used(action, context, sub_action)
            return t("sched_resumed", language, title=action.title)

        if sub_action == "run":
            action.status = ActionStatus.active
            action.next_run_at = now
            await session.commit()
            _log_callback_used(action, context, sub_action)
            return t("sched_run_now", language, title=action.title)

        if sub_action in {"del", "delete"}:
            action.status = ActionStatus.deleted
            action.next_run_at = None
            await session.commit()
            _log_callback_used(action, context, sub_action)
            return t("sched_deleted", language, title=action.title)

    return t("sched_invalid", language)
