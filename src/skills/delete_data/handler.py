"""Delete data skill — selective deletion of user data with confirmation."""

import logging
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from src.core.audit import log_action
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.conversation import ConversationMessage
from src.core.models.enums import LifeEventType, TransactionType
from src.core.models.life_event import LifeEvent
from src.core.models.shopping_list import ShoppingListItem
from src.core.models.task import Task
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.core.pending_actions import store_pending_action
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

# Mapping of user-facing scope names to internal scope keys
SCOPE_ALIASES: dict[str, str] = {
    "expenses": "expenses",
    "расходы": "expenses",
    "income": "income",
    "доходы": "income",
    "transactions": "transactions",
    "транзакции": "transactions",
    "финансы": "transactions",
    "food": "food",
    "еда": "food",
    "питание": "food",
    "drinks": "drinks",
    "напитки": "drinks",
    "mood": "mood",
    "настроение": "mood",
    "notes": "notes",
    "заметки": "notes",
    "life_events": "life_events",
    "life": "life_events",
    "жизнь": "life_events",
    "tasks": "tasks",
    "задачи": "tasks",
    "shopping": "shopping",
    "покупки": "shopping",
    "список покупок": "shopping",
    "messages": "messages",
    "сообщения": "messages",
    "история": "messages",
    "all": "all",
    "всё": "all",
    "все": "all",
    "все данные": "all",
}

SCOPE_LABELS: dict[str, str] = {
    "expenses": "расходы",
    "income": "доходы",
    "transactions": "транзакции (расходы + доходы)",
    "food": "записи о еде",
    "drinks": "записи о напитках",
    "mood": "записи настроения",
    "notes": "заметки",
    "life_events": "life-записи (еда, напитки, настроение, заметки)",
    "tasks": "задачи",
    "shopping": "элементы списка покупок",
    "messages": "историю сообщений",
    "all": "все данные",
}

VALID_SCOPES = set(SCOPE_LABELS.keys())


def _resolve_date_range(
    period: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[date | None, date | None]:
    """Convert period/date_from/date_to into a concrete (start, end) range."""
    today = date.today()

    if period == "today":
        return today, today
    elif period == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    elif period == "week":
        return today - timedelta(days=7), today
    elif period == "month":
        return today.replace(day=1), today
    elif period == "year":
        return today.replace(month=1, day=1), today
    elif period == "custom" and date_from:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to) if date_to else today
        return start, end
    elif date_from:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to) if date_to else today
        return start, end

    return None, None


async def _count_records(
    scope: str,
    user_id: str,
    family_id: str,
    start: date | None,
    end: date | None,
) -> int:
    """Count records matching the scope and date range."""
    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)

    if scope == "all":
        total = 0
        for sub_scope in ["transactions", "life_events", "tasks", "shopping", "messages"]:
            total += await _count_records(sub_scope, user_id, family_id, start, end)
        return total

    async with async_session() as session:
        if scope == "expenses":
            q = select(func.count()).select_from(Transaction).where(
                Transaction.user_id == uid,
                Transaction.type == TransactionType.expense,
            )
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)

        elif scope == "income":
            q = select(func.count()).select_from(Transaction).where(
                Transaction.user_id == uid,
                Transaction.type == TransactionType.income,
            )
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)

        elif scope == "transactions":
            q = select(func.count()).select_from(Transaction).where(
                Transaction.user_id == uid,
            )
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)

        elif scope == "food":
            q = select(func.count()).select_from(LifeEvent).where(
                LifeEvent.user_id == uid,
                LifeEvent.type == LifeEventType.food,
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)

        elif scope == "drinks":
            q = select(func.count()).select_from(LifeEvent).where(
                LifeEvent.user_id == uid,
                LifeEvent.type == LifeEventType.drink,
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)

        elif scope == "mood":
            q = select(func.count()).select_from(LifeEvent).where(
                LifeEvent.user_id == uid,
                LifeEvent.type == LifeEventType.mood,
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)

        elif scope == "notes":
            q = select(func.count()).select_from(LifeEvent).where(
                LifeEvent.user_id == uid,
                LifeEvent.type == LifeEventType.note,
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)

        elif scope == "life_events":
            q = select(func.count()).select_from(LifeEvent).where(
                LifeEvent.user_id == uid,
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)

        elif scope == "tasks":
            q = select(func.count()).select_from(Task).where(
                Task.user_id == uid,
            )
            if start and end:
                q = q.where(func.date(Task.created_at) >= start, func.date(Task.created_at) <= end)

        elif scope == "shopping":
            q = select(func.count()).select_from(ShoppingListItem).where(
                ShoppingListItem.family_id == fid,
            )
            # ShoppingListItem has no date column, skip date filtering

        elif scope == "messages":
            q = select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.user_id == uid,
            )
            if start and end:
                q = q.where(
                    func.date(ConversationMessage.created_at) >= start,
                    func.date(ConversationMessage.created_at) <= end,
                )

        else:
            return 0

        result = await session.execute(q)
        return result.scalar() or 0


async def _delete_records(
    scope: str,
    user_id: str,
    family_id: str,
    start: date | None,
    end: date | None,
) -> int:
    """Delete records matching the scope and date range. Returns count deleted."""
    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)

    if scope == "all":
        total = 0
        for sub_scope in ["messages", "tasks", "shopping", "life_events", "transactions"]:
            total += await _delete_records(sub_scope, user_id, family_id, start, end)
        return total

    async with async_session() as session:
        if scope == "expenses":
            q = delete(Transaction).where(
                Transaction.user_id == uid,
                Transaction.type == TransactionType.expense,
            )
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)

        elif scope == "income":
            q = delete(Transaction).where(
                Transaction.user_id == uid,
                Transaction.type == TransactionType.income,
            )
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)

        elif scope == "transactions":
            q = delete(Transaction).where(Transaction.user_id == uid)
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)

        elif scope == "food":
            q = delete(LifeEvent).where(
                LifeEvent.user_id == uid,
                LifeEvent.type == LifeEventType.food,
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)

        elif scope == "drinks":
            q = delete(LifeEvent).where(
                LifeEvent.user_id == uid,
                LifeEvent.type == LifeEventType.drink,
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)

        elif scope == "mood":
            q = delete(LifeEvent).where(
                LifeEvent.user_id == uid,
                LifeEvent.type == LifeEventType.mood,
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)

        elif scope == "notes":
            q = delete(LifeEvent).where(
                LifeEvent.user_id == uid,
                LifeEvent.type == LifeEventType.note,
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)

        elif scope == "life_events":
            q = delete(LifeEvent).where(LifeEvent.user_id == uid)
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)

        elif scope == "tasks":
            q = delete(Task).where(Task.user_id == uid)
            if start and end:
                q = q.where(func.date(Task.created_at) >= start, func.date(Task.created_at) <= end)

        elif scope == "shopping":
            q = delete(ShoppingListItem).where(ShoppingListItem.family_id == fid)

        elif scope == "messages":
            q = delete(ConversationMessage).where(ConversationMessage.user_id == uid)
            if start and end:
                q = q.where(
                    func.date(ConversationMessage.created_at) >= start,
                    func.date(ConversationMessage.created_at) <= end,
                )

        else:
            return 0

        result = await session.execute(q)
        deleted = result.rowcount
        await session.commit()
        return deleted


async def execute_delete(action_data: dict, user_id: str, family_id: str) -> str:
    """Execute confirmed deletion. Called from router's _execute_pending_action."""
    scope = action_data["scope"]
    period = action_data.get("period")
    date_from = action_data.get("date_from")
    date_to = action_data.get("date_to")

    start, end = _resolve_date_range(period, date_from, date_to)
    deleted = await _delete_records(scope, user_id, family_id, start, end)

    # Audit log
    try:
        async with async_session() as session:
            await log_action(
                session=session,
                family_id=family_id,
                user_id=user_id,
                action="delete_data",
                entity_type=scope,
                entity_id=str(uuid.uuid4()),
                old_data={
                    "count": deleted,
                    "period": period,
                    "date_from": date_from,
                    "date_to": date_to,
                },
            )
            await session.commit()
    except Exception as e:
        logger.warning("Audit log for delete_data failed: %s", e)

    label = SCOPE_LABELS.get(scope, scope)
    period_text = ""
    if start and end:
        period_text = f" за {start.isoformat()} — {end.isoformat()}"

    return f"Удалено {deleted} записей ({label}){period_text}."


class DeleteDataSkill:
    name = "delete_data"
    intents = ["delete_data"]
    model = "gpt-5.2"

    @observe(name="delete_data")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        raw_scope = intent_data.get("delete_scope") or ""
        scope = SCOPE_ALIASES.get(raw_scope.lower().strip(), raw_scope.lower().strip())

        if scope not in VALID_SCOPES:
            return SkillResult(
                response_text=(
                    "Укажите, что именно удалить:\n\n"
                    "• <b>расходы</b> / <b>доходы</b> / <b>транзакции</b>\n"
                    "• <b>еда</b> / <b>напитки</b> / <b>настроение</b> / <b>заметки</b>\n"
                    "• <b>задачи</b> / <b>покупки</b> / <b>сообщения</b>\n"
                    "• <b>все данные</b>\n\n"
                    "Пример: «удали расходы за январь» или «очисти записи о еде за неделю»"
                ),
            )

        period = intent_data.get("period")
        date_from = intent_data.get("date_from")
        date_to = intent_data.get("date_to")
        start, end = _resolve_date_range(period, date_from, date_to)

        count = await _count_records(scope, context.user_id, context.family_id, start, end)

        if count == 0:
            label = SCOPE_LABELS.get(scope, scope)
            return SkillResult(response_text=f"Нет записей для удаления ({label}).")

        # Build confirmation message
        label = SCOPE_LABELS.get(scope, scope)
        period_text = ""
        if start and end:
            period_text = f" за {start.isoformat()} — {end.isoformat()}"

        confirm_text = (
            f"Вы хотите удалить <b>{count}</b> записей ({label}){period_text}.\n\n"
            "Это действие <b>необратимо</b>. Подтвердите удаление:"
        )

        pending_id = await store_pending_action(
            intent="delete_data",
            user_id=context.user_id,
            family_id=context.family_id,
            action_data={
                "scope": scope,
                "period": period,
                "date_from": date_from,
                "date_to": date_to,
                "count": count,
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
            },
        )

        return SkillResult(
            response_text=confirm_text,
            buttons=[
                {"text": f"🗑 Удалить ({count})", "callback": f"confirm_action:{pending_id}"},
                {"text": "❌ Отмена", "callback": f"cancel_action:{pending_id}"},
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return "Ты помогаешь пользователю удалить данные. Всегда спрашивай подтверждение."


skill = DeleteDataSkill()
