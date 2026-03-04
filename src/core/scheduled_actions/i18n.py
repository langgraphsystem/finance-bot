"""i18n helpers for Scheduled Intelligence Actions."""

from datetime import datetime
from zoneinfo import ZoneInfo

SUPPORTED_LANGS = {"en", "ru", "es"}

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "greeting_morning": "Good morning",
        "greeting_afternoon": "Good afternoon",
        "greeting_evening": "Good evening",
        "section_calendar": "Today",
        "section_tasks": "Tasks",
        "section_money_summary": "Money",
        "section_email_highlights": "Email",
        "section_outstanding": "Outstanding",
        "empty_payload_fallback": "No new source updates right now.",
        "closing_question": "What should I handle first?",
        "btn_snooze": "⏰ +{minutes} min",
        "btn_run_now": "▶️ Run now",
        "btn_pause": "⏸ Pause",
        "btn_resume": "▶️ Resume",
        "btn_delete": "🗑 Delete",
        "btn_done": "✅ Done",
        "degraded_footer": "⚠️ {sources} temporarily unavailable",
        "trust_footer": "📡 {ok}/{total} sources • {time}",
        "sched_not_found": "Scheduled action not found.",
        "sched_forbidden": "You cannot manage this scheduled action.",
        "sched_snoozed": "Snoozed — will run in {minutes} min.",
        "sched_paused": "Paused — <b>{title}</b>.",
        "sched_resumed": "Resumed — <b>{title}</b>.",
        "sched_run_now": "Queued — <b>{title}</b> will run now.",
        "sched_deleted": "Deleted — <b>{title}</b>.",
        "sched_done": "✅ Completed — <b>{title}</b>.",
        "sched_auto_completed": "✅ Auto-completed — <b>{title}</b>.",
        "sched_auto_paused": (
            "⚠️ <b>{title}</b> paused after {failures} failures."
            " Use /manage to resume."
        ),
        "sched_invalid": "Invalid scheduled action ID.",
        "source_calendar": "calendar",
        "source_tasks": "tasks",
        "source_money_summary": "money",
        "source_email_highlights": "email",
        "source_outstanding": "outstanding",
        "budget_usage": "Budget usage",
        "budget_trend_up": "Spending trend is up vs monthly average",
        "budget_trend_down": "Spending trend is down vs monthly average",
        "outcome_badge": "Persistent",
    },
    "ru": {
        "greeting_morning": "Доброе утро",
        "greeting_afternoon": "Добрый день",
        "greeting_evening": "Добрый вечер",
        "section_calendar": "Сегодня",
        "section_tasks": "Задачи",
        "section_money_summary": "Финансы",
        "section_email_highlights": "Почта",
        "section_outstanding": "Неоплаченные",
        "empty_payload_fallback": "Сейчас нет новых данных из источников.",
        "closing_question": "Что сделать в первую очередь?",
        "btn_snooze": "⏰ +{minutes} мин",
        "btn_run_now": "▶️ Запустить",
        "btn_pause": "⏸ Пауза",
        "btn_resume": "▶️ Возобновить",
        "btn_delete": "🗑 Удалить",
        "btn_done": "✅ Готово",
        "degraded_footer": "⚠️ Источники временно недоступны: {sources}",
        "trust_footer": "📡 {ok}/{total} источников • {time}",
        "sched_not_found": "Запланированное действие не найдено.",
        "sched_forbidden": "Нельзя управлять этим действием.",
        "sched_snoozed": "Отложено — запущу через {minutes} мин.",
        "sched_paused": "Пауза — <b>{title}</b>.",
        "sched_resumed": "Возобновлено — <b>{title}</b>.",
        "sched_run_now": "Поставил в очередь — <b>{title}</b> запущу сейчас.",
        "sched_deleted": "Удалено — <b>{title}</b>.",
        "sched_done": "✅ Завершено — <b>{title}</b>.",
        "sched_auto_completed": "✅ Автозавершено — <b>{title}</b>.",
        "sched_auto_paused": (
            "⚠️ <b>{title}</b> на паузе после {failures} сбоев."
            " Используйте /manage чтобы возобновить."
        ),
        "sched_invalid": "Неверный ID запланированного действия.",
        "source_calendar": "календарь",
        "source_tasks": "задачи",
        "source_money_summary": "финансы",
        "source_email_highlights": "почта",
        "source_outstanding": "неоплаченные",
        "budget_usage": "Использование бюджета",
        "budget_trend_up": "Траты выше среднего за месяц",
        "budget_trend_down": "Траты ниже среднего за месяц",
        "outcome_badge": "До результата",
    },
    "es": {
        "greeting_morning": "Buenos dias",
        "greeting_afternoon": "Buenas tardes",
        "greeting_evening": "Buenas noches",
        "section_calendar": "Hoy",
        "section_tasks": "Tareas",
        "section_money_summary": "Finanzas",
        "section_email_highlights": "Correo",
        "section_outstanding": "Pendientes",
        "empty_payload_fallback": "Ahora no hay actualizaciones nuevas de fuentes.",
        "closing_question": "Que deberia atender primero?",
        "btn_snooze": "⏰ +{minutes} min",
        "btn_run_now": "▶️ Ejecutar",
        "btn_pause": "⏸ Pausar",
        "btn_resume": "▶️ Reanudar",
        "btn_delete": "🗑 Eliminar",
        "btn_done": "✅ Hecho",
        "degraded_footer": "⚠️ Fuentes no disponibles temporalmente: {sources}",
        "trust_footer": "📡 {ok}/{total} fuentes • {time}",
        "sched_not_found": "No se encontro la accion programada.",
        "sched_forbidden": "No puedes gestionar esta accion programada.",
        "sched_snoozed": "Pospuesto — se ejecutara en {minutes} min.",
        "sched_paused": "Pausado — <b>{title}</b>.",
        "sched_resumed": "Reanudado — <b>{title}</b>.",
        "sched_run_now": "En cola — <b>{title}</b> se ejecutara ahora.",
        "sched_deleted": "Eliminado — <b>{title}</b>.",
        "sched_done": "✅ Completado — <b>{title}</b>.",
        "sched_auto_completed": "✅ Completado automaticamente — <b>{title}</b>.",
        "sched_auto_paused": (
            "⚠️ <b>{title}</b> pausado tras {failures} fallos."
            " Usa /manage para reanudar."
        ),
        "sched_invalid": "ID de accion programada invalido.",
        "source_calendar": "calendario",
        "source_tasks": "tareas",
        "source_money_summary": "finanzas",
        "source_email_highlights": "correo",
        "source_outstanding": "pendientes",
        "budget_usage": "Uso de presupuesto",
        "budget_trend_up": "El gasto sube frente al promedio mensual",
        "budget_trend_down": "El gasto baja frente al promedio mensual",
        "outcome_badge": "Persistente",
    },
}

DATE_FORMATS = {
    "en": {"date": "%b %d", "time": "%I:%M %p", "datetime": "%b %d, %I:%M %p"},
    "ru": {"date": "%d.%m", "time": "%H:%M", "datetime": "%d.%m в %H:%M"},
    "es": {"date": "%d/%m", "time": "%H:%M", "datetime": "%d/%m a las %H:%M"},
}


def t(key: str, lang: str, **kwargs: str | int) -> str:
    """Translate a key with fallback to English."""
    locale = lang if lang in SUPPORTED_LANGS else "en"
    template = _STRINGS.get(locale, {}).get(key) or _STRINGS["en"].get(key) or key
    return template.format(**kwargs)


def localize_datetime(value: datetime, timezone: str) -> datetime:
    """Convert datetime to requested timezone, defaulting to UTC."""
    try:
        return value.astimezone(ZoneInfo(timezone))
    except Exception:
        return value.astimezone(ZoneInfo("UTC"))


def format_date(value: datetime, lang: str, timezone: str) -> str:
    locale = lang if lang in SUPPORTED_LANGS else "en"
    dt = localize_datetime(value, timezone)
    return dt.strftime(DATE_FORMATS[locale]["date"])


def format_time(value: datetime, lang: str, timezone: str) -> str:
    locale = lang if lang in SUPPORTED_LANGS else "en"
    dt = localize_datetime(value, timezone)
    return dt.strftime(DATE_FORMATS[locale]["time"])


def format_datetime(value: datetime, lang: str, timezone: str) -> str:
    locale = lang if lang in SUPPORTED_LANGS else "en"
    dt = localize_datetime(value, timezone)
    return dt.strftime(DATE_FORMATS[locale]["datetime"])


def greeting_key_for_hour(hour: int) -> str:
    if hour < 12:
        return "greeting_morning"
    if hour < 18:
        return "greeting_afternoon"
    return "greeting_evening"
