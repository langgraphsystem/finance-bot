"""Shared clarification helpers — period/type selection before skill execution.

Skills call these helpers to check if user intent is ambiguous and show
inline buttons for disambiguation. Pending state is stored in Redis.
"""

import json
import uuid

from src.core.db import redis
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

PENDING_CLARIFY_TTL = 600  # 10 minutes

_STRINGS = {
    "en": {
        "ask_period": "Which period?",
        "this_month": "This month",
        "last_month": "Last month",
        "this_week": "This week",
        "this_year": "This year",
        "ask_export_type": "What should I export?",
        "expenses": "Expenses",
        "tasks": "Tasks",
        "contacts": "Contacts",
        "expired": "Selection expired. Please try again.",
    },
    "ru": {
        "ask_period": "За какой период?",
        "this_month": "Этот месяц",
        "last_month": "Прошлый месяц",
        "this_week": "Эта неделя",
        "this_year": "Этот год",
        "ask_export_type": "Что экспортировать?",
        "expenses": "Расходы",
        "tasks": "Задачи",
        "contacts": "Контакты",
        "expired": "Выбор истёк. Попробуйте снова.",
    },
    "es": {
        "ask_period": "¿Para qué período?",
        "this_month": "Este mes",
        "last_month": "Mes pasado",
        "this_week": "Esta semana",
        "this_year": "Este año",
        "ask_export_type": "¿Qué debo exportar?",
        "expenses": "Gastos",
        "tasks": "Tareas",
        "contacts": "Contactos",
        "expired": "La selección expiró. Inténtelo de nuevo.",
    },
}
register_strings("clarification", _STRINGS)

# ── Period keywords for detecting explicit period in user message ──

_PERIOD_KEYWORDS = {
    "month", "месяц", "mes",
    "week", "недел", "semana",
    "year", "год", "año",
    "quarter", "квартал", "trimestre",
    "today", "сегодня", "hoy",
    "yesterday", "вчера", "ayer",
    "январ", "феврал", "март", "апрел", "май", "июн",
    "июл", "август", "сентябр", "октябр", "ноябр", "декабр",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
}

_EXPORT_TYPE_KEYWORDS = {
    "expense", "расход", "трат", "gasto",
    "task", "задач", "tarea", "todo", "дела",
    "contact", "контакт", "client", "клиент", "contacto",
}


# ── Helpers ──


def _has_period_hint(intent_data: dict, text: str) -> bool:
    """Return True if user already specified a period."""
    if intent_data.get("period") or intent_data.get("date_from") or intent_data.get("date_to"):
        return True
    text_lower = (text or "").lower()
    return any(kw in text_lower for kw in _PERIOD_KEYWORDS)


def _has_export_type_hint(intent_data: dict, text: str) -> bool:
    """Return True if user already specified an export type."""
    if intent_data.get("export_type"):
        return True
    text_lower = (text or "").lower()
    return any(kw in text_lower for kw in _EXPORT_TYPE_KEYWORDS)


# ── Redis pending storage ──


async def store_pending(skill: str, user_id: str, text: str, intent_data: dict) -> str:
    """Store pending clarification in Redis. Returns pending_id."""
    pending_id = uuid.uuid4().hex[:8]
    payload = {
        "skill": skill,
        "user_id": user_id,
        "text": text,
        "intent_data": intent_data,
    }
    await redis.set(
        f"skill_clarify:{pending_id}",
        json.dumps(payload, default=str),
        ex=PENDING_CLARIFY_TTL,
    )
    return pending_id


async def get_pending(pending_id: str) -> dict | None:
    """Retrieve pending clarification from Redis."""
    raw = await redis.get(f"skill_clarify:{pending_id}")
    if not raw:
        return None
    return json.loads(raw)


async def delete_pending(pending_id: str) -> None:
    """Delete pending clarification from Redis."""
    await redis.delete(f"skill_clarify:{pending_id}")


# ── Public API ──


async def maybe_ask_period(
    skill_name: str,
    intent_data: dict,
    message_text: str,
    user_id: str,
    lang: str,
) -> SkillResult | None:
    """If no period specified in a short/ambiguous request, return period buttons.

    Returns None if period is already clear (caller should proceed).
    """
    if _has_period_hint(intent_data, message_text):
        return None
    # Only ask if the message is short (< 40 chars) — long messages likely have context
    if len(message_text or "") > 40:
        return None

    pending_id = await store_pending(skill_name, user_id, message_text or "", intent_data)
    ns = "clarification"
    return SkillResult(
        response_text=t_cached(_STRINGS, "ask_period", lang, namespace=ns),
        buttons=[
            {
                "text": t_cached(_STRINGS, "this_month", lang, namespace=ns),
                "callback": f"period_select:{pending_id}:month",
            },
            {
                "text": t_cached(_STRINGS, "last_month", lang, namespace=ns),
                "callback": f"period_select:{pending_id}:prev_month",
            },
            {
                "text": t_cached(_STRINGS, "this_week", lang, namespace=ns),
                "callback": f"period_select:{pending_id}:week",
            },
            {
                "text": t_cached(_STRINGS, "this_year", lang, namespace=ns),
                "callback": f"period_select:{pending_id}:year",
            },
        ],
    )


async def maybe_ask_export_type(
    intent_data: dict,
    message_text: str,
    user_id: str,
    lang: str,
) -> SkillResult | None:
    """If no export type specified, return export type buttons.

    Returns None if type is already clear (caller should proceed).
    """
    if _has_export_type_hint(intent_data, message_text):
        return None

    pending_id = await store_pending("export_excel", user_id, message_text or "", intent_data)
    ns = "clarification"
    return SkillResult(
        response_text=t_cached(_STRINGS, "ask_export_type", lang, namespace=ns),
        buttons=[
            {
                "text": f"\U0001f4b0 {t_cached(_STRINGS, 'expenses', lang, namespace=ns)}",
                "callback": f"export_select:{pending_id}:expenses",
            },
            {
                "text": f"\u2705 {t_cached(_STRINGS, 'tasks', lang, namespace=ns)}",
                "callback": f"export_select:{pending_id}:tasks",
            },
            {
                "text": f"\U0001f465 {t_cached(_STRINGS, 'contacts', lang, namespace=ns)}",
                "callback": f"export_select:{pending_id}:contacts",
            },
        ],
    )
