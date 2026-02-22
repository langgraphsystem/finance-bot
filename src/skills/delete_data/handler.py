"""Delete data skill — AI-powered deletion with confirmation.

Uses Claude Sonnet 4.6 as a fallback when rule-based scope matching fails.
The AI analyzes the user's natural language request, searches across all data tables,
and presents found records for confirmation before deletion.
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from src.core.audit import log_action
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.llm.clients import generate_text
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DRINK_ITEM_ALIASES: dict[str, tuple[str, ...]] = {
    "water": ("water", "вода"),
    "coffee": ("coffee", "кофе"),
    "tea": ("tea", "чай"),
    "juice": ("juice", "сок"),
    "smoothie": ("smoothie", "смузи"),
}

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
    "reminders": "reminders",
    "напоминания": "reminders",
    "напоминание": "reminders",
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
    "reminders": "напоминания",
    "shopping": "элементы списка покупок",
    "messages": "историю сообщений",
    "all": "все данные",
    "ai_search": "найденные записи",
}

VALID_SCOPES = set(SCOPE_LABELS.keys())

# ---------------------------------------------------------------------------
# AI Delete Search — system prompt for Claude Sonnet 4.6
# ---------------------------------------------------------------------------

AI_DELETE_SEARCH_PROMPT = """\
You are a data search assistant. The user wants to delete specific records.
Analyze the message and determine which table(s) to search and what filters to apply.

Available tables:
1. life_events — Notes, food logs, drink logs, mood check-ins, reflections
   Searchable: type (note/food/drink/mood/task/reflection), date, text
2. transactions — Financial records (expenses and income)
   Searchable: type (expense/income), amount, merchant, description, date
3. tasks — To-do items and reminders
   Searchable: title, description, status (pending/in_progress/done/cancelled), due_at
4. shopping_list_items — Shopping list entries
   Searchable: name
5. conversation_messages — Chat history
   Searchable: content, created_at

Today: {today}

Respond with ONLY valid JSON (no markdown):
{{
  "tables": ["life_events"],
  "search_text": "keywords to search in text/title/description fields",
  "life_event_type": null,
  "transaction_type": null,
  "date_from": null,
  "date_to": null,
  "merchant": null,
  "amount_min": null,
  "amount_max": null,
  "task_status": null,
  "confidence": 0.9,
  "explanation_ru": "short Russian explanation of what we are looking for"
}}

Rules:
- "tables": array of table names to search. Usually one.
- Set only relevant fields. Leave others as null.
- "search_text": extract meaningful keywords (drop delete/remove/удали verbs).
- Dates in YYYY-MM-DD format.
- "confidence": 0.0-1.0. Set < 0.3 if request is too vague.
- "напоминание" / "reminder" → search "tasks" table.
- "заметка" / "note" / "запись" → search "life_events" with type "note".
- Financial terms (расход, доход, трата) → search "transactions"."""


@dataclass
class FoundRecord:
    """A record found by AI search, ready for preview and deletion."""

    table: str
    record_id: str
    preview_text: str
    created_at: datetime | None


# ---------------------------------------------------------------------------
# Helpers (drink, emoji, date)
# ---------------------------------------------------------------------------


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_drink_volume_ml(text: str) -> int | None:
    match_ml = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:ml|мл)\b", text)
    if match_ml:
        return int(float(match_ml.group(1).replace(",", ".")))
    match_liters = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:l|л|литр|литра|литров)\b", text)
    if match_liters:
        return int(float(match_liters.group(1).replace(",", ".")) * 1000)
    return None


_SCOPE_NOISE_WORDS = {
    "удали", "удалить", "удалите", "delete", "remove", "убери",
    "очисти", "сотри", "clear",
    "заметк", "заметку", "заметки", "notes", "note",
    "еда", "еду", "food", "напитк", "напитки", "drinks", "drink",
    "настроен", "mood", "записи", "записей", "запись",
    "life", "жизн", "мои", "мою", "все",
    "на", "за", "от", "про", "о", "об",
    "пожалуйста", "please",
}


def _has_specific_content(text: str, scope: str) -> bool:
    """Check if the message has meaningful content beyond delete verb + scope keyword."""
    words = re.findall(r"[а-яёa-z]+", text.lower())
    meaningful = [w for w in words if w not in _SCOPE_NOISE_WORDS and len(w) > 1]
    # If there are meaningful words beyond the standard delete/scope keywords,
    # the user is targeting specific content (e.g. "пароль", "blender", "банк")
    return len(meaningful) >= 1


def _canonical_drink_key(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower().strip()
    for key, aliases in DRINK_ITEM_ALIASES.items():
        if any(alias == lowered or alias in lowered for alias in aliases):
            return key
    return None


def _extract_drink_key(text: str) -> str | None:
    return _canonical_drink_key(text)


# --- Life event reference parsing (from timeline format) ---

_EMOJI_TO_TYPE: dict[str, LifeEventType] = {
    "\U0001f4dd": LifeEventType.note,
    "\U0001f37d": LifeEventType.food,
    "\u2615": LifeEventType.drink,
    "\U0001f60a": LifeEventType.mood,
    "\u2705": LifeEventType.task,
    "\U0001f319": LifeEventType.reflection,
    "\U0001f4cc": None,
}

_LIFE_REF_PATTERN = re.compile(
    r"(\d{1,2}\.\d{1,2}\.\d{4})?"
    r"\s*"
    r"(\d{1,2}:\d{2})?"
    r"\s*"
    r"([\U0001f4dd\U0001f37d\u2615\U0001f60a\u2705\U0001f319\U0001f4cc])"
    r"\s*"
    r"(.+)",
    re.UNICODE,
)


def _parse_life_event_ref(text: str) -> dict[str, Any] | None:
    m = _LIFE_REF_PATTERN.search(text)
    if not m:
        return None
    date_str, time_str, emoji, event_text = m.groups()
    event_type = _EMOJI_TO_TYPE.get(emoji)
    parsed_date = None
    if date_str:
        try:
            parsed_date = datetime.strptime(date_str, "%d.%m.%Y").date()
        except ValueError:
            pass
    parsed_time = None
    if time_str:
        try:
            parts = time_str.split(":")
            parsed_time = (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass
    return {
        "date": parsed_date,
        "time": parsed_time,
        "type": event_type,
        "text": event_text.strip(),
    }


async def _find_life_event_by_ref(
    user_id: str, family_id: str, ref: dict[str, Any]
) -> LifeEvent | None:
    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)
    async with async_session() as session:
        stmt = select(LifeEvent).where(LifeEvent.user_id == uid, LifeEvent.family_id == fid)
        if ref["type"]:
            stmt = stmt.where(LifeEvent.type == ref["type"])
        if ref["date"]:
            stmt = stmt.where(LifeEvent.date == ref["date"])
        stmt = stmt.order_by(LifeEvent.created_at.desc()).limit(50)
        result = await session.execute(stmt)
        events = list(result.scalars().all())
    ref_text = ref["text"].lower().strip()
    for event in events:
        if ref["time"] and event.created_at:
            if (event.created_at.hour, event.created_at.minute) != ref["time"]:
                continue
        event_text = (event.text or "").lower().strip()
        if ref_text and event_text and (ref_text in event_text or event_text in ref_text):
            return event
    return None


# --- Preview formatters ---


def _format_life_event_preview(event: LifeEvent) -> str:
    from src.core.life_helpers import _TYPE_LABELS, _type_icon

    icon = _type_icon(event.type)
    label = _TYPE_LABELS.get(event.type, "Запись")
    text = (event.text or "")[:100]
    timestamp = event.created_at.strftime("%d.%m.%Y %H:%M") if event.created_at else ""
    return f"{icon} <b>{label}</b>\n{text}\nДата: {timestamp}"


def _format_transaction_preview(tx: Transaction) -> str:
    icon = "\U0001f4c9" if tx.type == TransactionType.expense else "\U0001f4c8"
    merchant = tx.merchant or tx.description or "—"
    ts = tx.date.strftime("%d.%m.%Y") if tx.date else ""
    return f"{icon} <b>{merchant}</b> — ${tx.amount}\nДата: {ts}"


def _format_task_preview(task: Task) -> str:
    icons = {
        "pending": "\u2b1c",
        "in_progress": "\U0001f504",
        "done": "\u2705",
        "cancelled": "\u274c",
    }
    icon = icons.get(
        task.status.value if hasattr(task.status, "value") else str(task.status), "\U0001f4cc"
    )
    ts = task.created_at.strftime("%d.%m.%Y %H:%M") if task.created_at else ""
    return f"{icon} <b>{task.title}</b>\nДата: {ts}"


def _format_shopping_preview(item: ShoppingListItem) -> str:
    check = "\u2705" if item.is_checked else "\u2b1c"
    qty = f" ({item.quantity})" if item.quantity else ""
    return f"{check} {item.name}{qty}"


def _format_message_preview(msg: ConversationMessage) -> str:
    short = (msg.content or "")[:80]
    ts = msg.created_at.strftime("%d.%m %H:%M") if msg.created_at else ""
    return f"\U0001f4ac {ts} {short}"


def _format_single_drink_preview(event: LifeEvent) -> str:
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


# --- Drink-specific helpers ---


def _is_specific_drink_delete_request(
    scope: str, raw_text: str, period: str | None, date_from: str | None, date_to: str | None
) -> bool:
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


async def _find_single_drink_event(user_id: str, family_id: str, raw_text: str) -> LifeEvent | None:
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


# --- Date range helpers ---


def _resolve_date_range(
    period: str | None, date_from: str | None, date_to: str | None
) -> tuple[date | None, date | None]:
    today = date.today()
    if period == "today":
        return today, today
    elif period == "yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
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


# ---------------------------------------------------------------------------
# Batch count / delete (existing rule-based path)
# ---------------------------------------------------------------------------


async def _count_records(
    scope: str, user_id: str, family_id: str, start: date | None, end: date | None
) -> int:
    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)
    if scope == "all":
        total = 0
        for sub in ["transactions", "life_events", "tasks", "shopping", "messages"]:
            total += await _count_records(sub, user_id, family_id, start, end)
        return total
    async with async_session() as session:
        if scope == "expenses":
            q = (
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.user_id == uid, Transaction.type == TransactionType.expense)
            )
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)
        elif scope == "income":
            q = (
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.user_id == uid, Transaction.type == TransactionType.income)
            )
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)
        elif scope == "transactions":
            q = select(func.count()).select_from(Transaction).where(Transaction.user_id == uid)
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)
        elif scope == "food":
            q = (
                select(func.count())
                .select_from(LifeEvent)
                .where(LifeEvent.user_id == uid, LifeEvent.type == LifeEventType.food)
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)
        elif scope == "drinks":
            q = (
                select(func.count())
                .select_from(LifeEvent)
                .where(LifeEvent.user_id == uid, LifeEvent.type == LifeEventType.drink)
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)
        elif scope == "mood":
            q = (
                select(func.count())
                .select_from(LifeEvent)
                .where(LifeEvent.user_id == uid, LifeEvent.type == LifeEventType.mood)
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)
        elif scope == "notes":
            q = (
                select(func.count())
                .select_from(LifeEvent)
                .where(LifeEvent.user_id == uid, LifeEvent.type == LifeEventType.note)
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)
        elif scope == "life_events":
            q = select(func.count()).select_from(LifeEvent).where(LifeEvent.user_id == uid)
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)
        elif scope == "tasks":
            q = select(func.count()).select_from(Task).where(Task.user_id == uid)
            if start and end:
                q = q.where(func.date(Task.created_at) >= start, func.date(Task.created_at) <= end)
        elif scope == "shopping":
            q = (
                select(func.count())
                .select_from(ShoppingListItem)
                .where(ShoppingListItem.family_id == fid)
            )
        elif scope == "messages":
            q = (
                select(func.count())
                .select_from(ConversationMessage)
                .where(ConversationMessage.user_id == uid)
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
    scope: str, user_id: str, family_id: str, start: date | None, end: date | None
) -> int:
    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)
    if scope == "all":
        total = 0
        for sub in ["messages", "tasks", "shopping", "life_events", "transactions"]:
            total += await _delete_records(sub, user_id, family_id, start, end)
        return total
    async with async_session() as session:
        if scope == "expenses":
            q = delete(Transaction).where(
                Transaction.user_id == uid, Transaction.type == TransactionType.expense
            )
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)
        elif scope == "income":
            q = delete(Transaction).where(
                Transaction.user_id == uid, Transaction.type == TransactionType.income
            )
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)
        elif scope == "transactions":
            q = delete(Transaction).where(Transaction.user_id == uid)
            if start and end:
                q = q.where(Transaction.date >= start, Transaction.date <= end)
        elif scope == "food":
            q = delete(LifeEvent).where(
                LifeEvent.user_id == uid, LifeEvent.type == LifeEventType.food
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)
        elif scope == "drinks":
            q = delete(LifeEvent).where(
                LifeEvent.user_id == uid, LifeEvent.type == LifeEventType.drink
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)
        elif scope == "mood":
            q = delete(LifeEvent).where(
                LifeEvent.user_id == uid, LifeEvent.type == LifeEventType.mood
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)
        elif scope == "notes":
            q = delete(LifeEvent).where(
                LifeEvent.user_id == uid, LifeEvent.type == LifeEventType.note
            )
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)
        elif scope == "life_events":
            q = delete(LifeEvent).where(LifeEvent.user_id == uid)
            if start and end:
                q = q.where(LifeEvent.date >= start, LifeEvent.date <= end)
        elif scope == "reminders":
            q = delete(Task).where(Task.user_id == uid, Task.reminder_at.isnot(None))
            if start and end:
                q = q.where(func.date(Task.created_at) >= start, func.date(Task.created_at) <= end)
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


async def _delete_single_life_event(life_event_id: str, user_id: str, family_id: str) -> int:
    try:
        event_uuid = uuid.UUID(life_event_id)
    except (TypeError, ValueError):
        return 0
    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)
    async with async_session() as session:
        result = await session.execute(
            delete(LifeEvent).where(
                LifeEvent.id == event_uuid, LifeEvent.user_id == uid, LifeEvent.family_id == fid
            )
        )
        await session.commit()
        return result.rowcount or 0


# ---------------------------------------------------------------------------
# AI-powered search & delete-by-IDs
# ---------------------------------------------------------------------------

_VALID_AI_TABLES = {
    "life_events",
    "transactions",
    "tasks",
    "shopping_list_items",
    "conversation_messages",
}


def _parse_ai_search_result(raw: str) -> dict[str, Any] | None:
    """Parse LLM JSON response into search parameters dict."""
    # Direct JSON
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "tables" in data:
            return data
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    # Fallback: extract from markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and "tables" in data:
                return data
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return None


async def _search_life_events(
    session: Any, uid: uuid.UUID, fid: uuid.UUID, params: dict, limit: int
) -> list[FoundRecord]:
    stmt = select(LifeEvent).where(LifeEvent.user_id == uid, LifeEvent.family_id == fid)
    if params.get("life_event_type"):
        try:
            stmt = stmt.where(LifeEvent.type == LifeEventType(params["life_event_type"]))
        except ValueError:
            pass
    if params.get("date_from"):
        try:
            stmt = stmt.where(LifeEvent.date >= date.fromisoformat(params["date_from"]))
        except ValueError:
            pass
    if params.get("date_to"):
        try:
            stmt = stmt.where(LifeEvent.date <= date.fromisoformat(params["date_to"]))
        except ValueError:
            pass
    if params.get("search_text"):
        stmt = stmt.where(LifeEvent.text.ilike(f"%{params['search_text']}%"))
    stmt = stmt.order_by(LifeEvent.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return [
        FoundRecord(
            table="life_events",
            record_id=str(ev.id),
            preview_text=_format_life_event_preview(ev),
            created_at=ev.created_at,
        )
        for ev in result.scalars().all()
    ]


async def _search_transactions(
    session: Any, uid: uuid.UUID, fid: uuid.UUID, params: dict, limit: int
) -> list[FoundRecord]:
    stmt = select(Transaction).where(Transaction.user_id == uid)
    if params.get("transaction_type"):
        try:
            stmt = stmt.where(Transaction.type == TransactionType(params["transaction_type"]))
        except ValueError:
            pass
    if params.get("merchant"):
        stmt = stmt.where(Transaction.merchant.ilike(f"%{params['merchant']}%"))
    if params.get("search_text") and not params.get("merchant"):
        text = params["search_text"]
        stmt = stmt.where(
            Transaction.merchant.ilike(f"%{text}%") | Transaction.description.ilike(f"%{text}%")
        )
    if params.get("amount_min") is not None:
        stmt = stmt.where(Transaction.amount >= params["amount_min"])
    if params.get("amount_max") is not None:
        stmt = stmt.where(Transaction.amount <= params["amount_max"])
    if params.get("date_from"):
        try:
            stmt = stmt.where(Transaction.date >= date.fromisoformat(params["date_from"]))
        except ValueError:
            pass
    if params.get("date_to"):
        try:
            stmt = stmt.where(Transaction.date <= date.fromisoformat(params["date_to"]))
        except ValueError:
            pass
    stmt = stmt.order_by(Transaction.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return [
        FoundRecord(
            table="transactions",
            record_id=str(tx.id),
            preview_text=_format_transaction_preview(tx),
            created_at=tx.created_at,
        )
        for tx in result.scalars().all()
    ]


async def _search_tasks(
    session: Any, uid: uuid.UUID, fid: uuid.UUID, params: dict, limit: int
) -> list[FoundRecord]:
    stmt = select(Task).where(Task.user_id == uid)
    if params.get("search_text"):
        text = params["search_text"]
        stmt = stmt.where(Task.title.ilike(f"%{text}%") | Task.description.ilike(f"%{text}%"))
    if params.get("task_status"):
        stmt = stmt.where(Task.status == params["task_status"])
    if params.get("date_from"):
        try:
            stmt = stmt.where(func.date(Task.created_at) >= date.fromisoformat(params["date_from"]))
        except ValueError:
            pass
    if params.get("date_to"):
        try:
            stmt = stmt.where(func.date(Task.created_at) <= date.fromisoformat(params["date_to"]))
        except ValueError:
            pass
    stmt = stmt.order_by(Task.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return [
        FoundRecord(
            table="tasks",
            record_id=str(t.id),
            preview_text=_format_task_preview(t),
            created_at=t.created_at,
        )
        for t in result.scalars().all()
    ]


async def _search_shopping(
    session: Any, fid: uuid.UUID, params: dict, limit: int
) -> list[FoundRecord]:
    stmt = select(ShoppingListItem).where(ShoppingListItem.family_id == fid)
    if params.get("search_text"):
        stmt = stmt.where(ShoppingListItem.name.ilike(f"%{params['search_text']}%"))
    stmt = stmt.order_by(ShoppingListItem.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return [
        FoundRecord(
            table="shopping_list_items",
            record_id=str(si.id),
            preview_text=_format_shopping_preview(si),
            created_at=si.created_at,
        )
        for si in result.scalars().all()
    ]


async def _search_messages(
    session: Any, uid: uuid.UUID, params: dict, limit: int
) -> list[FoundRecord]:
    stmt = select(ConversationMessage).where(ConversationMessage.user_id == uid)
    if params.get("search_text"):
        stmt = stmt.where(ConversationMessage.content.ilike(f"%{params['search_text']}%"))
    if params.get("date_from"):
        try:
            stmt = stmt.where(
                func.date(ConversationMessage.created_at) >= date.fromisoformat(params["date_from"])
            )
        except ValueError:
            pass
    if params.get("date_to"):
        try:
            stmt = stmt.where(
                func.date(ConversationMessage.created_at) <= date.fromisoformat(params["date_to"])
            )
        except ValueError:
            pass
    stmt = stmt.order_by(ConversationMessage.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return [
        FoundRecord(
            table="conversation_messages",
            record_id=str(m.id),
            preview_text=_format_message_preview(m),
            created_at=m.created_at,
        )
        for m in result.scalars().all()
    ]


async def _search_records_for_deletion(
    params: dict, user_id: str, family_id: str, limit: int = 20
) -> list[FoundRecord]:
    """Search across tables based on AI-parsed search parameters."""
    results: list[FoundRecord] = []
    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)
    async with async_session() as session:
        for table_name in params.get("tables", []):
            if table_name == "life_events":
                results.extend(await _search_life_events(session, uid, fid, params, limit))
            elif table_name == "transactions":
                results.extend(await _search_transactions(session, uid, fid, params, limit))
            elif table_name == "tasks":
                results.extend(await _search_tasks(session, uid, fid, params, limit))
            elif table_name == "shopping_list_items":
                results.extend(await _search_shopping(session, fid, params, limit))
            elif table_name == "conversation_messages":
                results.extend(await _search_messages(session, uid, params, limit))
    return results[:limit]


def _format_found_records_preview(records: list[FoundRecord], explanation: str) -> str:
    count = len(records)
    lines = [f"<b>Найдено: {count}</b>"]
    if explanation:
        lines.append(f"<i>{explanation}</i>\n")
    for i, rec in enumerate(records[:10], 1):
        lines.append(f"{i}. {rec.preview_text}")
    if count > 10:
        lines.append(f"\n<i>... и ещё {count - 10}</i>")
    lines.append("\n<b>Это действие необратимо.</b> Удалить?")
    return "\n\n".join(lines)


async def _delete_records_by_ids(records: list[dict], user_id: str, family_id: str) -> int:
    """Delete specific records by their IDs across multiple tables."""
    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)
    total = 0

    # Group by table
    by_table: dict[str, list[str]] = {}
    for rec in records:
        by_table.setdefault(rec["table"], []).append(rec["id"])

    async with async_session() as session:
        for table_name, ids in by_table.items():
            if table_name == "life_events":
                id_vals = [uuid.UUID(i) for i in ids]
                q = delete(LifeEvent).where(
                    LifeEvent.id.in_(id_vals), LifeEvent.user_id == uid, LifeEvent.family_id == fid
                )
            elif table_name == "transactions":
                id_vals = [uuid.UUID(i) for i in ids]
                q = delete(Transaction).where(
                    Transaction.id.in_(id_vals), Transaction.user_id == uid
                )
            elif table_name == "tasks":
                id_vals = [uuid.UUID(i) for i in ids]
                q = delete(Task).where(Task.id.in_(id_vals), Task.user_id == uid)
            elif table_name == "shopping_list_items":
                id_vals = [uuid.UUID(i) for i in ids]
                q = delete(ShoppingListItem).where(
                    ShoppingListItem.id.in_(id_vals), ShoppingListItem.family_id == fid
                )
            elif table_name == "conversation_messages":
                int_ids = [int(i) for i in ids]
                q = delete(ConversationMessage).where(
                    ConversationMessage.id.in_(int_ids), ConversationMessage.user_id == uid
                )
            else:
                continue
            result = await session.execute(q)
            total += result.rowcount or 0
        await session.commit()
    return total


# ---------------------------------------------------------------------------
# execute_delete (called from router on confirm button click)
# ---------------------------------------------------------------------------


async def execute_delete(action_data: dict, user_id: str, family_id: str) -> str:
    """Execute confirmed deletion. Called from router's _execute_pending_action."""
    scope = action_data["scope"]
    found_records = action_data.get("found_records")
    single_life_event_id = action_data.get("single_life_event_id")
    single_life_event_preview = action_data.get("single_life_event_preview")

    # AI search path: delete by specific record IDs
    if found_records:
        deleted = await _delete_records_by_ids(found_records, user_id, family_id)
        try:
            async with async_session() as session:
                await log_action(
                    session=session,
                    family_id=family_id,
                    user_id=user_id,
                    action="delete_data",
                    entity_type="ai_search",
                    entity_id=str(uuid.uuid4()),
                    old_data={
                        "count": deleted,
                        "explanation": action_data.get("explanation", ""),
                        "tables": list({r["table"] for r in found_records}),
                    },
                )
                await session.commit()
        except Exception as e:
            logger.warning("Audit log for ai_search delete failed: %s", e)
        return f"Удалено {deleted} записей."

    # Single life event path
    if single_life_event_id:
        deleted = await _delete_single_life_event(single_life_event_id, user_id, family_id)
        label = SCOPE_LABELS.get(scope, scope)
        try:
            async with async_session() as session:
                await log_action(
                    session=session,
                    family_id=family_id,
                    user_id=user_id,
                    action="delete_data",
                    entity_type=scope,
                    entity_id=str(uuid.uuid4()),
                    old_data={"count": deleted},
                )
                await session.commit()
        except Exception as e:
            logger.warning("Audit log for delete_data failed: %s", e)
        if deleted == 0:
            return "Запись не найдена или уже удалена."
        suffix = f"\n{single_life_event_preview}" if single_life_event_preview else ""
        return f"Удалена 1 запись ({label}).{suffix}"

    # Batch scope + date range path
    period = action_data.get("period")
    date_from = action_data.get("date_from")
    date_to = action_data.get("date_to")
    start, end = _resolve_date_range(period, date_from, date_to)
    deleted = await _delete_records(scope, user_id, family_id, start, end)

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
    period_text = f" за {start.isoformat()} — {end.isoformat()}" if start and end else ""
    return f"Удалено {deleted} записей ({label}){period_text}."


# ---------------------------------------------------------------------------
# Skill class
# ---------------------------------------------------------------------------


def _disambiguation_prompt() -> SkillResult:
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


class DeleteDataSkill:
    name = "delete_data"
    intents = ["delete_data"]
    model = "claude-sonnet-4-6"

    @observe(name="delete_data")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        raw_text = message.text or ""

        # Fast-path 1: user pasted a specific life event from timeline
        ref = _parse_life_event_ref(raw_text)
        if ref:
            event = await _find_life_event_by_ref(context.user_id, context.family_id, ref)
            if event:
                preview = _format_life_event_preview(event)
                scope_key = {
                    LifeEventType.note: "notes",
                    LifeEventType.food: "food",
                    LifeEventType.drink: "drinks",
                    LifeEventType.mood: "mood",
                }.get(event.type, "life_events")
                pending_id = await store_pending_action(
                    intent="delete_data",
                    user_id=context.user_id,
                    family_id=context.family_id,
                    action_data={
                        "scope": scope_key,
                        "single_life_event_id": str(event.id),
                        "single_life_event_preview": preview,
                    },
                )
                return SkillResult(
                    response_text=f"Удалить запись?\n\n{preview}",
                    buttons=[
                        {"text": "\U0001f5d1 Удалить", "callback": f"confirm_action:{pending_id}"},
                        {"text": "\u274c Отмена", "callback": f"cancel_action:{pending_id}"},
                    ],
                )

        # All delete requests go through AI search (Claude Sonnet 4.6)
        # for precise record matching by content, date, and type.
        return await self._ai_search_and_delete(raw_text, context)

    async def _ai_search_and_delete(self, raw_text: str, context: SessionContext) -> SkillResult:
        """AI-powered fallback: use Sonnet 4.6 to parse request, search DB, show preview."""
        # Call LLM
        try:
            system = AI_DELETE_SEARCH_PROMPT.format(today=date.today().isoformat())
            llm_response = await generate_text(
                "claude-sonnet-4-6",
                system,
                [{"role": "user", "content": raw_text}],
                max_tokens=512,
            )
        except Exception as e:
            logger.warning("AI delete search LLM failed: %s", e)
            return _disambiguation_prompt()

        # Parse structured output
        params = _parse_ai_search_result(llm_response)
        if not params or params.get("confidence", 0) < 0.3:
            return _disambiguation_prompt()

        # Validate tables
        tables = [t for t in params.get("tables", []) if t in _VALID_AI_TABLES]
        if not tables:
            return _disambiguation_prompt()
        params["tables"] = tables

        # Search database
        found = await _search_records_for_deletion(
            params, context.user_id, context.family_id, limit=51
        )

        explanation = params.get("explanation_ru", "")

        if not found:
            return SkillResult(
                response_text=(
                    f"По запросу <i>«{explanation}»</i> ничего не найдено.\n"
                    "Попробуйте уточнить запрос."
                )
            )

        if len(found) > 50:
            return SkillResult(
                response_text=(
                    f"Найдено слишком много записей ({len(found)}+). "
                    "Уточните запрос — добавьте дату или ключевые слова."
                )
            )

        # Build preview and store pending action
        preview = _format_found_records_preview(found, explanation)
        pending_id = await store_pending_action(
            intent="delete_data",
            user_id=context.user_id,
            family_id=context.family_id,
            action_data={
                "scope": "ai_search",
                "found_records": [{"table": r.table, "id": r.record_id} for r in found],
                "explanation": explanation,
            },
        )

        count = len(found)
        return SkillResult(
            response_text=preview,
            buttons=[
                {
                    "text": f"\U0001f5d1 Удалить ({count})",
                    "callback": f"confirm_action:{pending_id}",
                },
                {"text": "\u274c Отмена", "callback": f"cancel_action:{pending_id}"},
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return "Ты помогаешь пользователю удалить данные. Всегда спрашивай подтверждение."


skill = DeleteDataSkill()
