"""Delete data skill — selective deletion of user data with confirmation."""

import logging
import re
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

DRINK_ITEM_ALIASES: dict[str, tuple[str, ...]] = {
    "water": ("water", "вода"),
    "coffee": ("coffee", "кофе"),
    "tea": ("tea", "чай"),
    "juice": ("juice", "сок"),
    "smoothie": ("smoothie", "смузи"),
}

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
    "drink": "drinks",
    "напитки": "drinks",
    "напиток": "drinks",
    "вода": "drinks",
    "кофе": "drinks",
    "чай": "drinks",
    "mood": "mood",
    "настроение": "mood",
    "notes": "notes",
    "заметки": "notes",
    "заметка": "notes",
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


def _safe_int(value: Any) -> int | None:
    """Best-effort int conversion for JSON payload fields."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_drink_volume_ml(text: str) -> int | None:
    """Extract drink volume from text; supports ml and liters."""
    match_ml = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:ml|мл)\b", text)
    if match_ml:
        return int(float(match_ml.group(1).replace(",", ".")))

    match_liters = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:l|л|литр|литра|литров)\b", text)
    if match_liters:
        liters = float(match_liters.group(1).replace(",", "."))
        return int(liters * 1000)

    return None


def _canonical_drink_key(text: str | None) -> str | None:
    """Normalize drink aliases (RU/EN) to one canonical key."""
    if not text:
        return None

    lowered = text.lower().strip()
    for key, aliases in DRINK_ITEM_ALIASES.items():
        if any(alias == lowered or alias in lowered for alias in aliases):
            return key
    return None


def _extract_drink_key(text: str) -> str | None:
    """Extract drink name from raw user text."""
    return _canonical_drink_key(text)


def _is_specific_drink_delete_request(
    scope: str,
    raw_text: str,
    period: str | None,
    date_from: str | None,
    date_to: str | None,
) -> bool:
    """Detect whether user asks to remove one specific drink entry."""
    if scope != "drinks":
        return False
    if period or date_from or date_to:
        return False
    text = raw_text.lower().strip()
    if not text:
        return False

    if _extract_drink_volume_ml(text) is not None:
        return True
    if _extract_drink_key(text) is not None:
        return True
    return "напиток" in text or "drink" in text


def _format_single_drink_preview(event: LifeEvent) -> str:
    """Human-readable preview text for deleting one drink entry."""
    data = event.data if isinstance(event.data, dict) else {}
    item = str(data.get("item") or event.text or "drink")
    count = _safe_int(data.get("count")) or 1
    volume_ml = _safe_int(data.get("volume_ml"))

    line = item
    if count > 1:
        line += f" x{count}"
    if volume_ml:
        line += f" ({volume_ml * count}ml)"

    timestamp = event.created_at.strftime("%Y-%m-%d %H:%M")
    return f"Напиток: {line}\nДата: {timestamp}"


async def _find_single_drink_event(
    user_id: str,
    family_id: str,
    raw_text: str,
) -> LifeEvent | None:
    """Find one matching drink event from recent records."""
    text = raw_text.lower().strip()
    target_volume_ml = _extract_drink_volume_ml(text)
    target_drink_key = _extract_drink_key(text)

    if target_volume_ml is None and target_drink_key is None:
        return None

    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)

    async with async_session() as session:
        result = await session.execute(
            select(LifeEvent)
            .where(
                LifeEvent.user_id == uid,
                LifeEvent.family_id == fid,
                LifeEvent.type == LifeEventType.drink,
            )
            .order_by(LifeEvent.created_at.desc())
            .limit(50)
        )
        events = list(result.scalars().all())

    for event in events:
        data = event.data if isinstance(event.data, dict) else {}

        event_item_key = _canonical_drink_key(str(data.get("item") or event.text or ""))
        event_count = _safe_int(data.get("count")) or 1
        event_per_unit_ml = _safe_int(data.get("volume_ml"))
        event_total_ml = event_per_unit_ml * event_count if event_per_unit_ml else None

        if target_drink_key and event_item_key and event_item_key != target_drink_key:
            continue
        if target_drink_key and not event_item_key:
            continue
        if target_volume_ml and event_total_ml and event_total_ml != target_volume_ml:
            continue
        if target_volume_ml and event_total_ml is None:
            continue
        return event

    return None


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


async def _delete_single_life_event(
    life_event_id: str,
    user_id: str,
    family_id: str,
) -> int:
    """Delete one life event by id (scoped to user + family)."""
    try:
        event_uuid = uuid.UUID(life_event_id)
    except (TypeError, ValueError):
        return 0

    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)

    async with async_session() as session:
        result = await session.execute(
            delete(LifeEvent).where(
                LifeEvent.id == event_uuid,
                LifeEvent.user_id == uid,
                LifeEvent.family_id == fid,
            )
        )
        await session.commit()
        return result.rowcount or 0


async def execute_delete(action_data: dict, user_id: str, family_id: str) -> str:
    """Execute confirmed deletion. Called from router's _execute_pending_action."""
    scope = action_data["scope"]
    period = action_data.get("period")
    date_from = action_data.get("date_from")
    date_to = action_data.get("date_to")
    single_life_event_id = action_data.get("single_life_event_id")
    single_life_event_preview = action_data.get("single_life_event_preview")

    if single_life_event_id:
        deleted = await _delete_single_life_event(single_life_event_id, user_id, family_id)
        start, end = None, None
    else:
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

    if single_life_event_id:
        if deleted == 0:
            return "Запись не найдена или уже удалена."
        suffix = f"\n{single_life_event_preview}" if single_life_event_preview else ""
        return f"Удалена 1 запись ({label}).{suffix}"

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
        raw_text = message.text or ""

        # If user references a concrete drink entry (e.g. "Напиток вода (250ml)"),
        # delete exactly one matching record instead of wiping the whole scope.
        if _is_specific_drink_delete_request(scope, raw_text, period, date_from, date_to):
            event = await _find_single_drink_event(
                user_id=context.user_id,
                family_id=context.family_id,
                raw_text=raw_text,
            )
            if event:
                preview = _format_single_drink_preview(event)
                pending_id = await store_pending_action(
                    intent="delete_data",
                    user_id=context.user_id,
                    family_id=context.family_id,
                    action_data={
                        "scope": scope,
                        "single_life_event_id": str(event.id),
                        "single_life_event_preview": preview,
                    },
                )
                return SkillResult(
                    response_text=f"Удалить запись?\n\n{preview}",
                    buttons=[
                        {"text": "🗑 Удалить", "callback": f"confirm_action:{pending_id}"},
                        {"text": "❌ Отмена", "callback": f"cancel_action:{pending_id}"},
                    ],
                )

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
