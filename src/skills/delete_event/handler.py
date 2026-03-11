"""Delete event skill — removes calendar events via Google Calendar API."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

DELETE_EVENT_SYSTEM_PROMPT = """\
You are a calendar assistant. Match the user's delete/cancel request to one of the listed events.

Respond with ONLY a JSON object (no markdown):
{{"event_id": "...", "event_name": "..."}}

If no event matches, respond: {{"event_id": null, "event_name": null}}"""

_STRINGS = {
    "en": {
        "no_events": "No upcoming events to delete.",
        "no_match": (
            "Couldn't find a matching event. Your upcoming events:\n"
            "{events_list}\n\nSpecify which one to delete."
        ),
        "confirm": "<b>Delete event:</b>\n\n📌 {title}\n📅 {dt}",
        "btn_delete": "🗑 Delete",
        "btn_cancel": "❌ Cancel",
        "deleted": "✅ Event «{title}» deleted.",
        "error_connect": "Calendar connection error. Try /connect",
        "error_list": "Error loading calendar.",
        "error_delete": "Error deleting event «{title}».",
    },
    "ru": {
        "no_events": "Нет предстоящих событий для удаления.",
        "no_match": (
            "Не удалось найти подходящее событие. Ваши ближайшие события:\n"
            "{events_list}\n\nУкажите, какое удалить."
        ),
        "confirm": "<b>Удалить событие:</b>\n\n📌 {title}\n📅 {dt}",
        "btn_delete": "🗑 Удалить",
        "btn_cancel": "❌ Отмена",
        "deleted": "✅ Событие «{title}» удалено.",
        "error_connect": "Ошибка подключения к Calendar. Попробуйте /connect",
        "error_list": "Ошибка при загрузке календаря.",
        "error_delete": "Ошибка при удалении события «{title}».",
    },
    "es": {
        "no_events": "No hay eventos próximos para eliminar.",
        "no_match": (
            "No se encontró un evento coincidente. Sus próximos eventos:\n"
            "{events_list}\n\nIndique cuál eliminar."
        ),
        "confirm": "<b>Eliminar evento:</b>\n\n📌 {title}\n📅 {dt}",
        "btn_delete": "🗑 Eliminar",
        "btn_cancel": "❌ Cancelar",
        "deleted": "✅ Evento «{title}» eliminado.",
        "error_connect": "Error de conexión con Calendar. Pruebe /connect",
        "error_list": "Error al cargar el calendario.",
        "error_delete": "Error al eliminar el evento «{title}».",
    },
}


def _t(key: str, lang: str, **kwargs: Any) -> str:
    return _STRINGS.get(lang, _STRINGS["en"]).get(key, _STRINGS["en"][key]).format(**kwargs)


register_strings("delete_event", {k: {} for k in _STRINGS})


class DeleteEventSkill:
    name = "delete_event"
    intents = ["delete_event"]
    model = "gpt-5.2"

    @observe(name="delete_event")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "ru"

        prompt_result = await require_google_or_prompt(context.user_id, service="calendar", lang=context.language or "en", chat_id=message.chat_id)
        if prompt_result:
            return prompt_result

        google = await get_google_client(context.user_id)
        if not google:
            return SkillResult(response_text=_t("error_connect", lang))

        tz = ZoneInfo(context.timezone)
        now_local = datetime.now(tz)
        try:
            events = await google.list_events(now_local, now_local + timedelta(days=30))
        except Exception as e:
            logger.warning("Calendar list failed: %s", e)
            return SkillResult(response_text=_t("error_list", lang))

        if not events:
            return SkillResult(response_text=_t("no_events", lang))

        events_list = "\n".join(
            f"{i}. {e.get('summary', '?')} — {e.get('start', {}).get('dateTime', '')}"
            f" (id: {e.get('id', '')})"
            for i, e in enumerate(events, 1)
        )

        match = await _match_event(message.text or "", events_list, lang)
        try:
            parsed = json.loads(match)
        except (json.JSONDecodeError, TypeError):
            parsed = {}

        event_id = parsed.get("event_id")
        event_name = parsed.get("event_name") or "событие"

        if not event_id:
            display = "\n".join(
                f"• {e.get('summary', '?')} — {e.get('start', {}).get('dateTime', '')}"
                for e in events[:7]
            )
            return SkillResult(response_text=_t("no_match", lang, events_list=display))

        # Find event datetime for preview
        dt_str = ""
        for e in events:
            if e.get("id") == event_id:
                raw = e.get("start", {}).get("dateTime", "")
                if raw:
                    try:
                        dt_str = datetime.fromisoformat(raw).strftime("%d.%m.%Y %H:%M")
                    except ValueError:
                        dt_str = raw
                break

        from src.core.pending_actions import store_pending_action

        pending_id = await store_pending_action(
            intent="delete_event",
            user_id=context.user_id,
            family_id=context.family_id,
            action_data={
                "event_id": event_id,
                "event_name": event_name,
                "language": lang,
            },
        )

        return SkillResult(
            response_text=_t("confirm", lang, title=event_name, dt=dt_str),
            buttons=[
                {"text": _t("btn_delete", lang), "callback": f"confirm_action:{pending_id}"},
                {"text": _t("btn_cancel", lang), "callback": f"cancel_action:{pending_id}"},
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return DELETE_EVENT_SYSTEM_PROMPT


async def _match_event(user_text: str, events_list: str, language: str) -> str:
    """Match user's delete request to a specific event via LLM."""
    system = (
        "Match the user's delete/cancel request to one of these events.\n"
        'Respond with JSON: {"event_id": "...", "event_name": "..."}\n'
        f"Events:\n{events_list}"
    )
    try:
        return await generate_text(
            "gpt-5.2", system, [{"role": "user", "content": user_text}], max_tokens=256
        )
    except Exception as e:
        logger.warning("Delete event match failed: %s", e)
        return "{}"


async def execute_delete_event(action_data: dict, user_id: str) -> str:
    """Actually delete the calendar event. Called after user confirms."""
    google = await get_google_client(user_id)
    lang = action_data.get("language", "ru")
    event_name = action_data.get("event_name", "событие")

    if not google:
        return _t("error_connect", lang)

    event_id = action_data["event_id"]
    try:
        await google.delete_event(event_id)
        return _t("deleted", lang, title=event_name)
    except Exception as e:
        logger.error("Calendar delete_event failed: %s", e)
        return _t("error_delete", lang, title=event_name)


skill = DeleteEventSkill()
