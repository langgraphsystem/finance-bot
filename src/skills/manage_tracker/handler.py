"""manage_tracker skill — create, list, and log entries for user trackers via chat."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.tracker import Tracker, TrackerEntry
from src.core.observability import observe
from src.core.context import SessionContext
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

# ── i18n ─────────────────────────────────────────────────────────────────────

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "created":              "✅ <b>{name}</b> tracker created!\n\nOpen the app to log entries and see your progress.",
        "logged":               "✅ Logged {emoji} <b>{name}</b> — {val}",
        "logged_note":          "✅ Logged {emoji} <b>{name}</b> — {val}\n<i>{note}</i>",
        "no_trackers":          "You don't have any trackers yet.\n\nSay <b>«create a water tracker»</b> to start!",
        "not_found":            "I couldn't find that tracker. Here are yours:\n\n{list}",
        "list_header":          "📊 <b>Your Trackers</b>\n\n",
        "streak":               "🔥 {n}d streak",
        "no_streak":            "No entries yet",
        "open_app":             "Open App",
        "log_btn":              "Log {emoji}",
        "ask_value":            "What value should I log for <b>{name}</b>?\n\nSend a number (e.g. <b>7</b> for mood, <b>6</b> for glasses of water).",
        "ask_type":             "What type of tracker?\n\n<b>mood</b> 😊 · <b>water</b> 💧 · <b>habit</b> 🔥 · <b>sleep</b> 🌙 · <b>weight</b> ⚖️ · <b>workout</b> 💪 · <b>nutrition</b> 🥗 · <b>gratitude</b> 🙏 · <b>medication</b> 💊 · <b>custom</b> ✨",
        "deleted":              "🗑️ <b>{name}</b> tracker deleted.",
        "remind_on":            "🔔 Reminder set for {emoji} <b>{name}</b> at <b>{time}</b> daily.\n\nI'll ping you if you haven't logged it yet.",
        "remind_on_repeat":     "🔔 Reminder set for {emoji} <b>{name}</b> at <b>{time}</b>.\n\n🔁 I'll remind you every <b>{interval} min</b> until you log it.",
        "remind_on_enabled":    "🔔 Reminder re-enabled for {emoji} <b>{name}</b> at <b>{time}</b>.",
        "remind_off":           "🔕 Reminder turned off for {emoji} <b>{name}</b>.",
        "remind_no_time":       "What time should I remind you?\n\nSend a time like <b>21:00</b> or <b>9pm</b>.",
        "remind_no_time_set":   "No reminder time configured for {emoji} <b>{name}</b>.\n\nSend a time like <b>21:00</b> or <b>9pm</b>.",
        "remind_not_found":     "I couldn't find that tracker. Here are yours:\n\n{list}",
    },
    "ru": {
        "created":              "✅ Трекер <b>{name}</b> создан!\n\nОткройте приложение, чтобы записывать и отслеживать прогресс.",
        "logged":               "✅ Записано {emoji} <b>{name}</b> — {val}",
        "logged_note":          "✅ Записано {emoji} <b>{name}</b> — {val}\n<i>{note}</i>",
        "no_trackers":          "У вас ещё нет трекеров.\n\nСкажите <b>«создай трекер воды»</b>, чтобы начать!",
        "not_found":            "Такой трекер не найден. Ваши трекеры:\n\n{list}",
        "list_header":          "📊 <b>Мои трекеры</b>\n\n",
        "streak":               "🔥 {n} дней подряд",
        "no_streak":            "Ещё нет записей",
        "open_app":             "Открыть приложение",
        "log_btn":              "Записать {emoji}",
        "ask_value":            "Какое значение записать для <b>{name}</b>?\n\nОтправьте число (например <b>7</b> для настроения, <b>6</b> для стаканов воды).",
        "ask_type":             "Какой тип трекера?\n\n<b>mood</b> 😊 · <b>water</b> 💧 · <b>habit</b> 🔥 · <b>sleep</b> 🌙 · <b>weight</b> ⚖️ · <b>workout</b> 💪 · <b>nutrition</b> 🥗 · <b>gratitude</b> 🙏 · <b>medication</b> 💊 · <b>custom</b> ✨",
        "deleted":              "🗑️ Трекер <b>{name}</b> удалён.",
        "remind_on":            "🔔 Напоминание для {emoji} <b>{name}</b> установлено на <b>{time}</b>.\n\nПришлю напоминание, если не запишете.",
        "remind_on_repeat":     "🔔 Напоминание для {emoji} <b>{name}</b> установлено на <b>{time}</b>.\n\n🔁 Буду напоминать каждые <b>{interval} мин</b>, пока не запишете.",
        "remind_on_enabled":    "🔔 Напоминание для {emoji} <b>{name}</b> включено (в <b>{time}</b>).",
        "remind_off":           "🔕 Напоминание для {emoji} <b>{name}</b> отключено.",
        "remind_no_time":       "В какое время напоминать?\n\nОтправьте время, например <b>21:00</b>.",
        "remind_no_time_set":   "Для {emoji} <b>{name}</b> не задано время напоминания.\n\nОтправьте время, например <b>21:00</b>.",
        "remind_not_found":     "Такой трекер не найден. Ваши трекеры:\n\n{list}",
    },
    "es": {
        "created":              "✅ Tracker <b>{name}</b> creado!\n\nAbre la app para registrar entradas y ver tu progreso.",
        "logged":               "✅ Registrado {emoji} <b>{name}</b> — {val}",
        "logged_note":          "✅ Registrado {emoji} <b>{name}</b> — {val}\n<i>{note}</i>",
        "no_trackers":          "Aún no tienes trackers.\n\nDi <b>«crear tracker de agua»</b> para empezar!",
        "not_found":            "No encontré ese tracker. Tus trackers:\n\n{list}",
        "list_header":          "📊 <b>Mis Trackers</b>\n\n",
        "streak":               "🔥 {n} días seguidos",
        "no_streak":            "Sin entradas aún",
        "open_app":             "Abrir App",
        "log_btn":              "Registrar {emoji}",
        "ask_value":            "¿Qué valor debo registrar para <b>{name}</b>?\n\nEnvía un número (ej. <b>7</b> para estado de ánimo, <b>6</b> vasos de agua).",
        "ask_type":             "¿Qué tipo de tracker?\n\n<b>mood</b> 😊 · <b>water</b> 💧 · <b>habit</b> 🔥 · <b>sleep</b> 🌙 · <b>weight</b> ⚖️ · <b>workout</b> 💪 · <b>nutrition</b> 🥗 · <b>gratitude</b> 🙏 · <b>medication</b> 💊 · <b>custom</b> ✨",
        "deleted":              "🗑️ Tracker <b>{name}</b> eliminado.",
        "remind_on":            "🔔 Recordatorio para {emoji} <b>{name}</b> a las <b>{time}</b> cada día.\n\nTe aviso si no lo registras.",
        "remind_on_repeat":     "🔔 Recordatorio para {emoji} <b>{name}</b> a las <b>{time}</b>.\n\n🔁 Te recordaré cada <b>{interval} min</b> hasta que lo registres.",
        "remind_on_enabled":    "🔔 Recordatorio reactivado para {emoji} <b>{name}</b> a las <b>{time}</b>.",
        "remind_off":           "🔕 Recordatorio desactivado para {emoji} <b>{name}</b>.",
        "remind_no_time":       "¿A qué hora debo recordarte?\n\nEnvía una hora como <b>21:00</b>.",
        "remind_no_time_set":   "Sin hora configurada para {emoji} <b>{name}</b>.\n\nEnvía una hora como <b>21:00</b>.",
        "remind_not_found":     "No encontré ese tracker. Tus trackers:\n\n{list}",
    },
}

_TRACKER_META = {
    "mood":       {"emoji": "😊", "unit": "/ 10",   "default_name_en": "Mood",       "default_name_ru": "Настроение"},
    "habit":      {"emoji": "🔥", "unit": "",        "default_name_en": "Habit",      "default_name_ru": "Привычка"},
    "water":      {"emoji": "💧", "unit": "glasses", "default_name_en": "Water",      "default_name_ru": "Вода"},
    "sleep":      {"emoji": "🌙", "unit": "h",       "default_name_en": "Sleep",      "default_name_ru": "Сон"},
    "weight":     {"emoji": "⚖️", "unit": "kg",      "default_name_en": "Weight",     "default_name_ru": "Вес"},
    "workout":    {"emoji": "💪", "unit": "session", "default_name_en": "Workout",    "default_name_ru": "Тренировка"},
    "nutrition":  {"emoji": "🥗", "unit": "kcal",    "default_name_en": "Nutrition",  "default_name_ru": "Питание"},
    "gratitude":  {"emoji": "🙏", "unit": "items",   "default_name_en": "Gratitude",  "default_name_ru": "Благодарность"},
    "medication": {"emoji": "💊", "unit": "dose",    "default_name_en": "Medication", "default_name_ru": "Лекарство"},
    "custom":     {"emoji": "✨", "unit": "times",   "default_name_en": "Custom",     "default_name_ru": "Свой"},
}

# Keyword → tracker_type mapping for fast detection (no LLM needed)
_TYPE_KEYWORDS: dict[str, list[str]] = {
    "mood":       ["mood", "настроени", "emotion", "чувств", "состояни"],
    "habit":      ["habit", "привычк", "routine", "рутин"],
    "water":      ["water", "вод", "hydrat", "гидрац", "питьё", "пить"],
    "sleep":      ["sleep", "сон", "спать", "засыпани"],
    "weight":     ["weight", "вес", "похудени", "масс тел"],
    "workout":    ["workout", "тренировк", "exercise", "упражнени", "спорт", "фитнес"],
    "nutrition":  ["nutrition", "питани", "калори", "calori", "ккал", "kcal", "еда", "food"],
    "gratitude":  ["gratitude", "благодарн", "grateful"],
    "medication": ["medication", "лекарств", "таблетк", "pill", "medicin", "препарат"],
    "custom":     ["custom", "свой", "другой"],
}


def _t(key: str, lang: str, **kw: Any) -> str:
    strings = _STRINGS.get(lang, _STRINGS["en"])
    tmpl = strings.get(key, _STRINGS["en"].get(key, key))
    return tmpl.format(**kw) if kw else tmpl


def _detect_type(text: str) -> str | None:
    low = text.lower()
    for t_type, keywords in _TYPE_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return t_type
    return None


def _default_name(t_type: str, lang: str) -> str:
    meta = _TRACKER_META.get(t_type, {})
    if lang == "ru":
        return meta.get("default_name_ru", t_type.title())
    return meta.get("default_name_en", t_type.title())


def _fmt_val(value: int | None, t_type: str) -> str:
    if value is None:
        return "✅"
    unit = _TRACKER_META.get(t_type, {}).get("unit", "")
    if t_type == "mood":
        faces = ["😭","😢","😔","🙁","😐","🙂","😊","😄","🤩","🥳"]
        face = faces[min(value - 1, 9)] if 1 <= value <= 10 else ""
        return f"{face} {value}/10"
    if t_type == "habit":
        return "✅ Done"
    return f"{value} {unit}".strip()


async def _get_trackers(user_id, family_id) -> list[Tracker]:
    async with async_session() as session:
        rows = (await session.scalars(
            select(Tracker).where(
                Tracker.family_id == family_id,
                Tracker.user_id == user_id,
                Tracker.is_active == True,
            ).order_by(Tracker.created_at)
        )).all()
    return list(rows)


async def _get_streak(tracker_id, session) -> int:
    today = date.today()
    streak = 0
    check = today
    for _ in range(366):
        exists = await session.scalar(
            select(TrackerEntry.id).where(
                TrackerEntry.tracker_id == tracker_id,
                TrackerEntry.date == check,
            ).limit(1)
        )
        if not exists:
            break
        streak += 1
        # go back one day
        from datetime import timedelta
        check = check - timedelta(days=1)
    return streak


def _tracker_list_text(trackers: list[Tracker], lang: str) -> str:
    lines = []
    for t in trackers:
        emoji = t.emoji or _TRACKER_META.get(t.tracker_type, {}).get("emoji", "📊")
        lines.append(f"{emoji} <b>{t.name}</b>")
    return "\n".join(lines) if lines else ""


def _find_tracker_by_name(trackers: list[Tracker], query: str) -> Tracker | None:
    """Fuzzy match tracker by name."""
    q = query.lower().strip()
    # Exact match
    for t in trackers:
        if t.name.lower() == q:
            return t
    # Type keyword match
    t_type = _detect_type(q)
    if t_type:
        for t in trackers:
            if t.tracker_type == t_type:
                return t
    # Partial name match
    for t in trackers:
        if q in t.name.lower() or t.name.lower() in q:
            return t
    return None


# ── Skill class ───────────────────────────────────────────────────────────────

import re as _re


def _parse_reminder_time(text: str) -> str | None:
    """Extract HH:MM from free text. Returns '21:00' style string or None."""
    if not text:
        return None
    text = text.strip().lower()
    # HH:MM or H:MM
    m = _re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return f"{h:02d}:{mn:02d}"
    # "9pm", "21pm", "9 pm", "9am"
    m = _re.search(r"\b(\d{1,2})\s*(am|pm)\b", text)
    if m:
        h = int(m.group(1))
        if m.group(2) == "pm" and h != 12:
            h += 12
        elif m.group(2) == "am" and h == 12:
            h = 0
        if 0 <= h <= 23:
            return f"{h:02d}:00"
    # bare hour like "в 21", "at 9"
    m = _re.search(r"\b(?:в|at|в\s+)(\d{1,2})\b", text)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"
    return None


def _parse_repeat_interval(text: str) -> int | None:
    """Extract repeat interval in minutes from free text.

    Examples:
        "every 30 minutes"      → 30
        "каждые 30 минут"       → 30
        "every hour"            → 60
        "каждый час"            → 60
        "every 2 hours"         → 120
        "каждые 2 часа"         → 120
        "каждые полчаса"        → 30
    Returns minutes (int) or None if not found.
    """
    if not text:
        return None
    low = text.lower()

    # "every N minutes" / "каждые N минут" / "cada N minutos"
    m = _re.search(
        r"(?:every|каждые?|каждую|cada)\s+(\d+)\s*(?:min(?:ute)?s?|мин(?:ут)?[аы]?|minutos?)",
        low,
    )
    if m:
        mins = int(m.group(1))
        if 1 <= mins <= 1440:
            return mins

    # "every N hours" / "каждые N часа/часов"
    m = _re.search(
        r"(?:every|каждые?|каждый|каждую|cada)\s+(\d+)\s*(?:hours?|час(?:а|ов)?|horas?)",
        low,
    )
    if m:
        hours = int(m.group(1))
        if 1 <= hours <= 24:
            return hours * 60

    # "every hour" / "каждый час" / "cada hora"
    if _re.search(r"\b(?:every\s+hour|каждый\s+час|cada\s+hora)\b", low):
        return 60

    # "every half hour" / "каждые полчаса" / "каждые 30"
    if _re.search(r"\b(?:every\s+half\s+hour|каждые?\s+полчаса|every\s+30)\b", low):
        return 30

    return None


class ManageTrackerSkill:
    name = "manage_tracker"
    intents = ["create_tracker", "list_trackers", "log_tracker", "set_tracker_reminder"]
    model = "gpt-5.2"

    @observe(name="manage_tracker")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        intent = intent_data.get("_intent", "")
        lang = context.language or "en"

        if intent == "create_tracker":
            return await self._create(message, context, intent_data, lang)
        elif intent == "list_trackers":
            return await self._list(context, lang)
        elif intent == "log_tracker":
            return await self._log(message, context, intent_data, lang)
        elif intent == "set_tracker_reminder":
            return await self._set_reminder(message, context, intent_data, lang)

        return SkillResult(response_text=_t("no_trackers", lang))

    # ── Create ────────────────────────────────────────────────────────────────

    async def _create(self, message, context, intent_data, lang) -> SkillResult:
        text = message.text or ""

        # Detect tracker type from message
        t_type = intent_data.get("tracker_type") or _detect_type(text) or "custom"
        name = intent_data.get("tracker_name") or _default_name(t_type, lang)

        meta = _TRACKER_META.get(t_type, {})
        emoji = meta.get("emoji", "✨")

        from src.core.db import async_session as _session
        async with _session() as session:
            tracker = Tracker(
                family_id=context.family_id,
                user_id=context.user_id,
                tracker_type=t_type,
                name=name,
                emoji=emoji,
                config={
                    "unit": meta.get("unit", "times"),
                    "goal": 1,
                    "emoji": emoji,
                },
            )
            session.add(tracker)
            await session.commit()

        buttons = [
            {"text": _t("open_app", lang), "url": "https://t.me/FinanceAssistBot/app"},
            {"text": _t("log_btn", lang, emoji=emoji), "callback_data": f"tracker_log:{tracker.id}:{t_type}"},
        ]

        return SkillResult(
            response_text=_t("created", lang, name=name),
            buttons=buttons,
        )

    # ── List ──────────────────────────────────────────────────────────────────

    async def _list(self, context, lang) -> SkillResult:
        trackers = await _get_trackers(context.user_id, context.family_id)

        if not trackers:
            return SkillResult(response_text=_t("no_trackers", lang))

        lines = []
        async with async_session() as session:
            for t in trackers:
                emoji = t.emoji or _TRACKER_META.get(t.tracker_type, {}).get("emoji", "📊")
                streak = await _get_streak(t.id, session)
                streak_str = _t("streak", lang, n=streak) if streak > 0 else _t("no_streak", lang)
                lines.append(f"{emoji} <b>{t.name}</b> — {streak_str}")

        text = _t("list_header", lang) + "\n".join(lines)
        buttons = [{"text": _t("open_app", lang), "url": "https://t.me/FinanceAssistBot/app"}]

        return SkillResult(response_text=text, buttons=buttons)

    # ── Log ───────────────────────────────────────────────────────────────────

    async def _log(self, message, context, intent_data, lang) -> SkillResult:
        text = message.text or ""
        trackers = await _get_trackers(context.user_id, context.family_id)

        if not trackers:
            return SkillResult(response_text=_t("no_trackers", lang))

        # Find which tracker
        tracker_name = intent_data.get("tracker_name") or intent_data.get("description") or text
        tracker = _find_tracker_by_name(trackers, tracker_name)

        if not tracker:
            list_text = _tracker_list_text(trackers, lang)
            return SkillResult(response_text=_t("not_found", lang, list=list_text))

        # Get value
        value = intent_data.get("tracker_value") or intent_data.get("mood") or intent_data.get("sleep_hours")
        if isinstance(value, float):
            value = round(value)

        # For habit trackers — value is always 1 (done)
        if tracker.tracker_type == "habit":
            value = 1

        # If no value and not habit, ask
        if value is None and tracker.tracker_type not in ("habit", "gratitude"):
            return SkillResult(response_text=_t("ask_value", lang, name=tracker.name))

        note = intent_data.get("note")
        emoji = tracker.emoji or _TRACKER_META.get(tracker.tracker_type, {}).get("emoji", "📊")

        async with async_session() as session:
            entry = TrackerEntry(
                tracker_id=tracker.id,
                family_id=context.family_id,
                user_id=context.user_id,
                date=date.today(),
                value=int(value) if value is not None else None,
                note=note,
            )
            session.add(entry)
            await session.commit()

        val_str = _fmt_val(int(value) if value is not None else None, tracker.tracker_type)
        key = "logged_note" if note else "logged"
        resp = _t(key, lang, emoji=emoji, name=tracker.name, val=val_str, note=note or "")

        return SkillResult(response_text=resp)

    # ── Set / toggle reminder ──────────────────────────────────────────────

    async def _set_reminder(self, message, context, intent_data, lang) -> SkillResult:
        text = message.text or ""
        trackers = await _get_trackers(context.user_id, context.family_id)

        if not trackers:
            return SkillResult(response_text=_t("no_trackers", lang))

        # Find tracker by name/type from intent_data or message text
        tracker_name = (
            intent_data.get("tracker_name")
            or intent_data.get("description")
            or text
        )
        tracker = _find_tracker_by_name(trackers, tracker_name)
        if not tracker:
            list_text = _tracker_list_text(trackers, lang)
            return SkillResult(response_text=_t("remind_not_found", lang, list=list_text))

        emoji = tracker.emoji or _TRACKER_META.get(tracker.tracker_type, {}).get("emoji", "📊")
        existing_config = dict(tracker.config or {})

        # ── Detect disable intent ─────────────────────────────────────────────
        disable_keywords = [
            "выключи", "отключи", "disable", "turn off", "off", "stop",
            "desactiv", "apaga", "убери напоминание", "удали напоминание",
        ]
        is_disable = any(kw in text.lower() for kw in disable_keywords)

        if is_disable:
            existing_config["reminder_enabled"] = False
            async with async_session() as session:
                db_tracker = await session.get(Tracker, tracker.id)
                if db_tracker:
                    db_tracker.config = existing_config
                    await session.commit()
            return SkillResult(response_text=_t("remind_off", lang, emoji=emoji, name=tracker.name))

        # ── Detect enable-only intent (no new time, no disable) ───────────────
        enable_keywords = [
            "включи", "включить", "enable", "turn on", "on", "activ",
            "включи напоминание", "включи напоминани",
        ]
        is_enable_only = any(kw in text.lower() for kw in enable_keywords)

        # ── Parse repeat interval from intent_data or raw text ────────────────
        repeat_minutes: int | None = (
            intent_data.get("reminder_repeat_minutes")
            or _parse_repeat_interval(intent_data.get("schedule_time") or "")
            or _parse_repeat_interval(text)
        )
        if isinstance(repeat_minutes, int) and repeat_minutes <= 0:
            repeat_minutes = None

        # ── Parse reminder time ───────────────────────────────────────────────
        reminder_time: str | None = (
            _parse_reminder_time(intent_data.get("schedule_time") or "")
            or _parse_reminder_time(text)
        )

        # If enable-only and tracker already has a time configured → just enable
        if is_enable_only and not reminder_time:
            existing_time = existing_config.get("reminder_time")
            if existing_time:
                existing_config["reminder_enabled"] = True
                if repeat_minutes:
                    existing_config["reminder_repeat_minutes"] = repeat_minutes
                async with async_session() as session:
                    db_tracker = await session.get(Tracker, tracker.id)
                    if db_tracker:
                        db_tracker.config = existing_config
                        await session.commit()
                return SkillResult(
                    response_text=_t("remind_on_enabled", lang, emoji=emoji, name=tracker.name, time=existing_time),
                    buttons=[{"text": _t("open_app", lang), "url": "https://t.me/FinanceAssistBot/app"}],
                )
            # No existing time → ask for it
            return SkillResult(response_text=_t("remind_no_time_set", lang, emoji=emoji, name=tracker.name))

        if not reminder_time:
            # Check if tracker already has time → just update repeat or enable
            existing_time = existing_config.get("reminder_time")
            if existing_time and (repeat_minutes is not None):
                # User said "remind every 30 min" without specifying a new clock time
                existing_config["reminder_enabled"] = True
                existing_config["reminder_repeat_minutes"] = repeat_minutes
                async with async_session() as session:
                    db_tracker = await session.get(Tracker, tracker.id)
                    if db_tracker:
                        db_tracker.config = existing_config
                        await session.commit()
                return SkillResult(
                    response_text=_t(
                        "remind_on_repeat", lang,
                        emoji=emoji, name=tracker.name,
                        time=existing_time, interval=repeat_minutes,
                    ),
                    buttons=[{"text": _t("open_app", lang), "url": "https://t.me/FinanceAssistBot/app"}],
                )
            return SkillResult(response_text=_t("remind_no_time", lang))

        # ── Enable / update reminder ──────────────────────────────────────────
        existing_config["reminder_enabled"] = True
        existing_config["reminder_time"] = reminder_time

        if repeat_minutes:
            existing_config["reminder_repeat_minutes"] = repeat_minutes
        else:
            # Explicitly clear repeat if user didn't request it (clean update)
            existing_config.pop("reminder_repeat_minutes", None)

        async with async_session() as session:
            db_tracker = await session.get(Tracker, tracker.id)
            if db_tracker:
                db_tracker.config = existing_config
                await session.commit()

        if repeat_minutes:
            resp = _t(
                "remind_on_repeat", lang,
                emoji=emoji, name=tracker.name,
                time=reminder_time, interval=repeat_minutes,
            )
        else:
            resp = _t("remind_on", lang, emoji=emoji, name=tracker.name, time=reminder_time)

        return SkillResult(
            response_text=resp,
            buttons=[{"text": _t("open_app", lang), "url": "https://t.me/FinanceAssistBot/app"}],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return ""


skill = ManageTrackerSkill()
