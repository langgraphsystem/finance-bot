"""Manage scheduled action skill — pause, resume, delete, reschedule."""

import logging
import re
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import ActionStatus, ScheduleKind
from src.core.models.scheduled_action import ScheduledAction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import fmt_date, register_strings
from src.skills.base import SkillResult
from src.skills.schedule_action.handler import (
    _compute_recurring_next_run,
    _normalize_sources,
    _parse_once_run_at,
    _parse_schedule_kind,
    _parse_time_parts,
    _parse_weekday,
)

logger = logging.getLogger(__name__)

MANAGE_SCHEDULED_ACTION_PROMPT = """\
You help users manage scheduled actions.
Supported operations: pause, resume, delete, reschedule, edit.
ALWAYS respond in the same language as the user's message/query.
If no preference is set, detect and match the language of their message."""

_STRINGS = {
    "en": {
        "disabled": "Scheduled actions are not enabled yet.",
        "ask_operation": "What should I do: pause, resume, delete, reschedule, or edit?",
        "ask_target": "Which scheduled action should I manage?",
        "not_found": 'No scheduled action matching "{query}".',
        "already_paused": 'Already paused: <b>{title}</b>.',
        "already_active": 'Already active: <b>{title}</b>.',
        "paused": '⏸ Paused: <b>{title}</b>.',
        "resumed": '▶️ Resumed: <b>{title}</b>. Next run: {next_run}.',
        "deleted": '🗑 Deleted: <b>{title}</b>.',
        "need_time": "What new time should I use?",
        "cannot_resume_once": "This one-time action is in the past. Please reschedule it.",
        "rescheduled": "🕒 Rescheduled: <b>{title}</b>.\n{old_time} → {new_time}",
        "edited": (
            "✏️ <b>Action evolved!</b> <i>Updated</i>\n"
            "📌 {title}\n\n"
            "{changes}\n\n"
            "Before:\n{before}\n"
            "After:\n{after}\n\n"
            "Next run: {next_run}"
        ),
        "change_item": "• {label}: {old} → <b>{new}</b>",
    },
    "ru": {
        "disabled": "Запланированные действия пока не включены.",
        "ask_operation": "Что сделать: пауза, возобновить, удалить, перенести или изменить?",
        "ask_target": "Какое запланированное действие изменить?",
        "not_found": 'Не нашёл запланированное действие «{query}».',
        "already_paused": 'Уже на паузе: <b>{title}</b>.',
        "already_active": 'Уже активно: <b>{title}</b>.',
        "paused": '⏸ Пауза: <b>{title}</b>.',
        "resumed": '▶️ Возобновлено: <b>{title}</b>. Следующий запуск: {next_run}.',
        "deleted": '🗑 Удалено: <b>{title}</b>.',
        "need_time": "На какое новое время перенести?",
        "cannot_resume_once": "Разовый запуск уже в прошлом. Перенесите его на новое время.",
        "rescheduled": "🕒 Перенесено: <b>{title}</b>.\n{old_time} → {new_time}",
        "edited": (
            "✏️ <b>Настройка обновлена!</b>\n"
            "📌 {title}\n\n"
            "{changes}\n\n"
            "До:\n{before}\n"
            "После:\n{after}\n\n"
            "Запуск: {next_run}"
        ),
        "change_item": "• {label}: {old} → <b>{new}</b>",
    },
    "es": {
        "disabled": "Las acciones programadas aun no estan habilitadas.",
        "ask_operation": "Que debo hacer: pausar, reanudar, eliminar, reprogramar o editar?",
        "ask_target": "Que accion programada debo gestionar?",
        "not_found": 'No encontre una accion programada con "{query}".',
        "already_paused": 'Ya esta en pausa: <b>{title}</b>.',
        "already_active": 'Ya esta activa: <b>{title}</b>.',
        "paused": '⏸ Pausado: <b>{title}</b>.',
        "resumed": '▶️ Reanudado: <b>{title}</b>. Proxima ejecucion: {next_run}.',
        "deleted": '🗑 Eliminado: <b>{title}</b>.',
        "need_time": "Que nueva hora debo usar?",
        "cannot_resume_once": "Esta accion unica ya paso. Reprogramala con nueva hora.",
        "rescheduled": "🕒 Reprogramado: <b>{title}</b>.\n{old_time} → {new_time}",
        "edited": (
            "✏️ <b>¡Acción actualizada!</b>\n"
            "📌 {title}\n\n"
            "{changes}\n\n"
            "Antes:\n{before}\n"
            "Después:\n{after}\n\n"
            "Próximo: {next_run}"
        ),
        "change_item": "• {label}: {old} → <b>{new}</b>",
    },
}
register_strings("manage_scheduled_action", _STRINGS)

_LABELS = {
    "en": {
        "kind": "Frequency",
        "time": "Time",
        "sources": "Sources",
        "instruction": "Instructions",
    },
    "ru": {
        "kind": "Частота",
        "time": "Время",
        "sources": "Источники",
        "instruction": "Инструкции",
    },
    "es": {
        "kind": "Frecuencia",
        "time": "Hora",
        "sources": "Fuentes",
        "instruction": "Instrucciones",
    },
}

_KIND_LABELS = {
    "en": {
        "once": "one-time",
        "daily": "daily",
        "weekly": "weekly",
        "monthly": "monthly",
        "weekdays": "weekdays",
        "cron": "cron",
        "sources": "sources",
    },
    "ru": {
        "once": "разово",
        "daily": "ежедневно",
        "weekly": "еженедельно",
        "monthly": "ежемесячно",
        "weekdays": "по будням",
        "cron": "cron",
        "sources": "источники",
    },
    "es": {
        "once": "una vez",
        "daily": "diario",
        "weekly": "semanal",
        "monthly": "mensual",
        "weekdays": "dias laborables",
        "cron": "cron",
        "sources": "fuentes",
    },
}

_SOURCE_LABELS = {
    "en": {
        "calendar": "calendar",
        "tasks": "tasks",
        "money_summary": "money",
        "email_highlights": "email",
        "outstanding": "outstanding",
    },
    "ru": {
        "calendar": "календарь",
        "tasks": "задачи",
        "money_summary": "финансы",
        "email_highlights": "почта",
        "outstanding": "неоплаченные",
    },
    "es": {
        "calendar": "calendario",
        "tasks": "tareas",
        "money_summary": "finanzas",
        "email_highlights": "correo",
        "outstanding": "pendientes",
    },
}


def _t(key: str, language: str, **kwargs: str) -> str:
    strings = _STRINGS.get(language, _STRINGS["en"])
    return strings[key].format(**kwargs)


def _detect_operation(intent_data: dict[str, Any], text: str) -> str | None:
    raw = (intent_data.get("manage_operation") or "").strip().lower()
    if raw in {"pause", "resume", "delete", "reschedule", "edit", "modify"}:
        # Keep backward compatibility with existing "reschedule" operation while
        # allowing a dedicated edit flow for delta updates.
        return "edit" if raw in {"edit", "modify"} else raw

    text_lower = text.lower()
    if any(word in text_lower for word in ("edit", "измени", "обнов", "actualiza", "editar")):
        return "edit"
    if any(word in text_lower for word in ("add", "добав", "agrega", "añade")):
        return "edit"
    if any(word in text_lower for word in ("pause", "пауза", "поставь на паузу", "pausa")):
        return "pause"
    if any(word in text_lower for word in ("resume", "возобнов", "reanudar")):
        return "resume"
    if any(word in text_lower for word in ("delete", "удали", "remove", "eliminar")):
        return "delete"
    if any(word in text_lower for word in ("reschedule", "перенес", "move to", "reprogram")):
        return "reschedule"
    if any(intent_data.get(key) for key in ("schedule_frequency", "schedule_sources")):
        return "edit"
    return None


def _is_add_sources_request(text: str) -> bool:
    text_lower = text.lower()
    return any(word in text_lower for word in ("add", "добав", "agrega", "añade", "include"))


def _is_remove_sources_request(text: str) -> bool:
    text_lower = text.lower()
    return any(word in text_lower for word in ("remove", "убери", "удали", "quita", "exclude"))


def _extract_sources_for_edit(intent_data: dict[str, Any], text: str) -> list[str]:
    raw_sources = (
        intent_data.get("schedule_sources")
        or intent_data.get("added_sources")
        or intent_data.get("removed_sources")
    )
    source_hint = any(
        word in text.lower()
        for word in (
            "calendar", "task", "money", "finance", "email", "mail", "outstanding",
            "календар", "задач", "финанс", "почт", "неопла",
            "calendario", "tarea", "finanz", "correo", "pendiente",
        )
    )
    if raw_sources is None and not source_hint:
        return []
    normalized = _normalize_sources(raw_sources, text)
    return normalized


def _apply_sources_delta(action: ScheduledAction, intent_data: dict[str, Any], text: str) -> bool:
    added = _normalize_sources(intent_data.get("added_sources"), text, use_defaults=False)
    removed = _normalize_sources(intent_data.get("removed_sources"), text, use_defaults=False)
    explicit = _normalize_sources(intent_data.get("schedule_sources"), text, use_defaults=False)

    existing = list(action.sources or [])
    merged = existing[:]

    # 1. If explicit list is provided, it's an overwrite
    if explicit:
        merged = explicit
    # 2. If added/removed are provided via Pydantic/IntentData, apply them to existing
    elif added or removed:
        if added:
            for s in added:
                if s not in merged:
                    merged.append(s)
        if removed:
            merged = [s for s in merged if s not in removed]
    # 3. Fallback to NL extraction from text only if no structured fields were found
    else:
        extracted = _extract_sources_for_edit(intent_data, text)
        if extracted:
            if _is_remove_sources_request(text):
                merged = [s for s in merged if s not in extracted]
            elif _is_add_sources_request(text):
                for s in extracted:
                    if s not in merged:
                        merged.append(s)
            else:
                # Direct instruction like "use calendar" -> overwrite
                merged = extracted

    if set(merged) == set(existing):
        return False
    action.sources = merged
    return True


def _apply_instruction_delta(action: ScheduledAction, intent_data: dict[str, Any]) -> bool:
    new_inst = intent_data.get("new_instruction") or intent_data.get("schedule_instruction")
    if not new_inst:
        return False
    if action.instruction == new_inst:
        return False
    action.instruction = new_inst
    return True


def _format_action_snapshot(action: ScheduledAction, language: str) -> str:
    labels = _KIND_LABELS.get(language, _KIND_LABELS["en"])
    source_labels = _SOURCE_LABELS.get(language, _SOURCE_LABELS["en"])
    cfg = action.schedule_config or {}
    kind_key = action.schedule_kind.value
    kind_text = labels.get(kind_key, kind_key)

    if action.schedule_kind == ScheduleKind.cron:
        time_part = str(cfg.get("cron_expr", "cron"))
    elif action.schedule_kind == ScheduleKind.once:
        time_part = str(cfg.get("run_at") or cfg.get("time") or "—")
    else:
        time_part = str(cfg.get("time") or "—")

    localized_sources = ", ".join(source_labels.get(item, item) for item in (action.sources or []))
    return f"{kind_text} {time_part}; {labels['sources']}: {localized_sources or '—'}"


def _extract_target_query(intent_data: dict[str, Any], text: str) -> str:
    return (
        intent_data.get("managed_action_title")
        or intent_data.get("task_title")
        or intent_data.get("description")
        or text
        or ""
    ).strip()


def _find_target(actions: list[ScheduledAction], query: str) -> ScheduledAction | None:
    if not actions:
        return None
    cleaned = query.strip().lower()
    if not cleaned:
        return actions[0] if len(actions) == 1 else None

    num_match = re.search(r"\b(\d{1,2})\b", cleaned)
    if num_match:
        idx = int(num_match.group(1))
        if 1 <= idx <= len(actions):
            return actions[idx - 1]

    exact = next((a for a in actions if a.title.lower() == cleaned), None)
    if exact:
        return exact

    contains = [a for a in actions if cleaned in a.title.lower()]
    if len(contains) == 1:
        return contains[0]
    if len(contains) > 1:
        return contains[0]

    token_hits = [a for a in actions if any(word in a.title.lower() for word in cleaned.split())]
    if token_hits:
        return token_hits[0]
    return None


def _compute_next_run_from_action(action: ScheduledAction) -> datetime | None:
    tz = ZoneInfo(action.timezone)
    now = datetime.now(tz)
    cfg = action.schedule_config or {}

    if action.schedule_kind == ScheduleKind.once:
        run_at = cfg.get("run_at")
        if run_at:
            try:
                dt = datetime.fromisoformat(str(run_at))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
                dt = dt.astimezone(tz)
                return dt if dt > now else None
            except ValueError:
                return None
        if action.next_run_at and action.next_run_at > now:
            return action.next_run_at
        return None

    if "time" in cfg:
        time_parts = _parse_time_parts(str(cfg["time"]))
    elif action.next_run_at:
        local = action.next_run_at.astimezone(tz)
        time_parts = (local.hour, local.minute)
    else:
        time_parts = (9, 0)
    if not time_parts:
        return None

    weekday = int((cfg.get("days") or [now.weekday()])[0])
    day_of_month = int(cfg.get("day_of_month") or now.day)
    return _compute_recurring_next_run(
        schedule_kind=action.schedule_kind,
        now=now,
        hour=time_parts[0],
        minute=time_parts[1],
        weekday=weekday,
        day_of_month=day_of_month,
    )


def _reschedule_action(
    action: ScheduledAction,
    intent_data: dict[str, Any],
    message_text: str,
    *,
    allow_existing_time: bool = False,
) -> datetime | None:
    tz = ZoneInfo(action.timezone)
    now = datetime.now(tz)
    cfg = dict(action.schedule_config or {})

    if action.schedule_kind == ScheduleKind.once:
        next_run_at = _parse_once_run_at(intent_data, action.timezone)
        if not next_run_at:
            return None
        next_run_at = next_run_at.astimezone(tz)
        cfg["run_at"] = next_run_at.isoformat()
        cfg["time"] = next_run_at.strftime("%H:%M")
        action.schedule_config = cfg
        action.next_run_at = next_run_at
        return next_run_at

    time_parts = _parse_time_parts(intent_data.get("schedule_time"))
    if not time_parts:
        fallback = _parse_once_run_at(intent_data, action.timezone)
        if fallback:
            local = fallback.astimezone(tz)
            time_parts = (local.hour, local.minute)
    if allow_existing_time and not time_parts and cfg.get("time"):
        time_parts = _parse_time_parts(str(cfg.get("time")))
    if not time_parts:
        return None

    cfg["time"] = f"{time_parts[0]:02d}:{time_parts[1]:02d}"
    weekday = int((cfg.get("days") or [now.weekday()])[0])
    if action.schedule_kind == ScheduleKind.weekly:
        weekday = _parse_weekday(intent_data, message_text, now)
        cfg["days"] = [weekday]

    day_of_month = int(cfg.get("day_of_month") or now.day)
    if action.schedule_kind == ScheduleKind.monthly:
        try:
            day_of_month = int(intent_data.get("schedule_day_of_month") or day_of_month)
        except (TypeError, ValueError):
            pass
        cfg["day_of_month"] = day_of_month

    next_run_at = _compute_recurring_next_run(
        schedule_kind=action.schedule_kind,
        now=now,
        hour=time_parts[0],
        minute=time_parts[1],
        weekday=weekday,
        day_of_month=day_of_month,
    )
    action.schedule_config = cfg
    action.next_run_at = next_run_at
    return next_run_at


class ManageScheduledActionSkill:
    name = "manage_scheduled_action"
    intents = ["manage_scheduled_action"]
    model = "gpt-5.2"

    @observe(name="manage_scheduled_action")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        if not settings.ff_scheduled_actions:
            return SkillResult(response_text=_t("disabled", lang))

        operation = _detect_operation(intent_data, message.text or "")
        if not operation:
            return SkillResult(response_text=_t("ask_operation", lang))

        actions = await get_manageable_actions(context.family_id, context.user_id)
        if not actions:
            return SkillResult(response_text=_t("ask_target", lang))

        query = _extract_target_query(intent_data, message.text or "")
        target = _find_target(actions, query)
        if not target:
            if not query:
                return SkillResult(response_text=_t("ask_target", lang))
            return SkillResult(response_text=_t("not_found", lang, query=query))

        if operation == "pause":
            if target.status == ActionStatus.paused:
                return SkillResult(response_text=_t("already_paused", lang, title=target.title))
            target.status = ActionStatus.paused
            await save_scheduled_action(target)
            return SkillResult(response_text=_t("paused", lang, title=target.title))

        if operation == "resume":
            if target.status == ActionStatus.active:
                return SkillResult(response_text=_t("already_active", lang, title=target.title))
            next_run = _compute_next_run_from_action(target)
            if next_run is None and target.schedule_kind == ScheduleKind.once:
                return SkillResult(response_text=_t("cannot_resume_once", lang))
            target.status = ActionStatus.active
            target.next_run_at = next_run
            await save_scheduled_action(target)
            next_run_txt = "—"
            if next_run:
                next_run_txt = fmt_date(next_run, lang, timezone=target.timezone)
            return SkillResult(
                response_text=_t("resumed", lang, title=target.title, next_run=next_run_txt)
            )

        if operation == "delete":
            target.status = ActionStatus.deleted
            await save_scheduled_action(target)
            return SkillResult(response_text=_t("deleted", lang, title=target.title))

        if operation == "edit":
            lang_labels = _LABELS.get(lang, _LABELS["en"])
            kind_labels = _KIND_LABELS.get(lang, _KIND_LABELS["en"])
            source_labels = _SOURCE_LABELS.get(lang, _SOURCE_LABELS["en"])

            changes = []
            before_lines: list[str] = []
            after_lines: list[str] = []

            # 1. Frequency
            old_kind = target.schedule_kind
            parsed_kind = _parse_schedule_kind(intent_data, message.text or "")
            if parsed_kind and parsed_kind != target.schedule_kind:
                target.schedule_kind = parsed_kind
                old_k_txt = kind_labels.get(old_kind.value, old_kind.value)
                new_k_txt = kind_labels.get(parsed_kind.value, parsed_kind.value)
                changes.append(
                    _t(
                        "change_item",
                        lang,
                        label=lang_labels["kind"],
                        old=old_k_txt,
                        new=new_k_txt,
                    ),
                )
                before_lines.append(f"• {lang_labels['kind']}: {old_k_txt}")
                after_lines.append(f"• {lang_labels['kind']}: <b>{new_k_txt}</b>")

            # 2. Sources
            old_sources = list(target.sources or [])
            if _apply_sources_delta(target, intent_data, message.text or ""):
                old_s_txt = ", ".join(source_labels.get(s, s) for s in old_sources) or "—"
                new_s_txt = ", ".join(source_labels.get(s, s) for s in target.sources) or "—"
                changes.append(
                    _t(
                        "change_item",
                        lang,
                        label=lang_labels["sources"],
                        old=old_s_txt,
                        new=new_s_txt,
                    ),
                )
                before_lines.append(f"• {lang_labels['sources']}: {old_s_txt}")
                after_lines.append(f"• {lang_labels['sources']}: <b>{new_s_txt}</b>")

            # 3. Instruction
            old_inst = target.instruction or "—"
            if _apply_instruction_delta(target, intent_data):
                new_inst = target.instruction or "—"
                changes.append(
                    _t(
                        "change_item",
                        lang,
                        label=lang_labels["instruction"],
                        old=old_inst,
                        new=new_inst,
                    ),
                )
                before_lines.append(f"• {lang_labels['instruction']}: {old_inst}")
                after_lines.append(f"• {lang_labels['instruction']}: <b>{new_inst}</b>")

            # 4. Time/Next Run
            old_cfg = dict(target.schedule_config or {})
            old_time_value = str(
                old_cfg.get("time") or old_cfg.get("cron_expr") or old_cfg.get("run_at") or "—",
            )
            next_run = _reschedule_action(
                target,
                intent_data,
                message.text or "",
                allow_existing_time=True,
            )

            if next_run is not None:
                new_cfg = target.schedule_config or {}
                new_time_value = str(
                    new_cfg.get("time") or new_cfg.get("cron_expr") or new_cfg.get("run_at") or "—",
                )
                if new_time_value != old_time_value:
                    changes.append(
                        _t(
                            "change_item",
                            lang,
                            label=lang_labels["time"],
                            old=old_time_value,
                            new=new_time_value,
                        ),
                    )
                    before_lines.append(f"• {lang_labels['time']}: {old_time_value}")
                    after_lines.append(f"• {lang_labels['time']}: <b>{new_time_value}</b>")
            elif intent_data.get("schedule_time"):
                return SkillResult(response_text=_t("need_time", lang))

            if not changes:
                return SkillResult(response_text=_t("ask_operation", lang))

            if target.schedule_kind == ScheduleKind.once and target.next_run_at is None:
                target.next_run_at = _compute_next_run_from_action(target)

            await save_scheduled_action(target)

            next_run_at = target.next_run_at or _compute_next_run_from_action(target)
            next_run_txt = (
                fmt_date(next_run_at, lang, timezone=target.timezone) if next_run_at else "—"
            )

            return SkillResult(
                response_text=_t(
                    "edited",
                    lang,
                    title=target.title,
                    changes="\n".join(changes),
                    before="\n".join(before_lines) if before_lines else "—",
                    after="\n".join(after_lines) if after_lines else "—",
                    next_run=next_run_txt,
                )
            )

        old_next_run = target.next_run_at
        old_time_cfg = (target.schedule_config or {}).get("time", "")
        next_run = _reschedule_action(target, intent_data, message.text or "")
        if next_run is None:
            return SkillResult(response_text=_t("need_time", lang))
        await save_scheduled_action(target)
        old_time_txt = (
            fmt_date(old_next_run, lang, timezone=target.timezone)
            if old_next_run
            else old_time_cfg or "—"
        )
        new_time_txt = fmt_date(next_run, lang, timezone=target.timezone)
        return SkillResult(
            response_text=_t(
                "rescheduled", lang,
                title=target.title,
                old_time=old_time_txt,
                new_time=new_time_txt,
            )
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return MANAGE_SCHEDULED_ACTION_PROMPT.format(language=context.language or "en")


async def get_manageable_actions(family_id: str, user_id: str) -> list[ScheduledAction]:
    async with async_session() as session:
        result = await session.execute(
            select(ScheduledAction)
            .where(
                ScheduledAction.family_id == uuid.UUID(family_id),
                ScheduledAction.user_id == uuid.UUID(user_id),
                ScheduledAction.status.in_(
                    [ActionStatus.active, ActionStatus.paused, ActionStatus.completed]
                ),
            )
            .order_by(
                ScheduledAction.next_run_at.asc().nulls_last(),
                ScheduledAction.created_at.asc(),
            )
            .limit(50)
        )
        return list(result.scalars().all())


async def save_scheduled_action(action: ScheduledAction) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(ScheduledAction).where(ScheduledAction.id == action.id)
        )
        db_action = result.scalar_one_or_none()
        if not db_action:
            return
        db_action.status = action.status
        db_action.title = action.title
        db_action.instruction = action.instruction
        db_action.schedule_kind = action.schedule_kind
        db_action.schedule_config = action.schedule_config
        db_action.sources = action.sources
        db_action.next_run_at = action.next_run_at
        await session.commit()


skill = ManageScheduledActionSkill()
