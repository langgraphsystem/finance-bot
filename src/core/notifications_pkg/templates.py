"""Centralized i18n templates for all notification types."""  # noqa: E501

from src.core.locale_resolution import normalize_language

# ---------------------------------------------------------------------------
# Life-tracking notification texts (moved from life_tasks.py)
# ---------------------------------------------------------------------------

LIFE_TEXTS: dict[str, dict[str, str]] = {  # noqa: E501
    "en": {
        "weekly_title": "Weekly Digest",
        "weekly_period": "Period",
        "weekly_entries": "Entries",
        "weekly_avg_mood": "Average mood",
        "weekly_tasks": "Tasks: {done}/{total} completed",
        "weekly_insights": "Insights",
        "morning_title": "☀️ <b>Good morning!</b>",
        "morning_body": (
            "You don't have a day plan yet.\n"
            "Write your tasks and I'll save them as your plan."
        ),
        "evening_title": "🌙 <b>Time to reflect</b>",
        "evening_body": (
            "What went well today? What would you like to improve?\n"
            "Just write freely."
        ),
        "evening_logged": "Logged {n} events today.",
        "evening_tasks": "✅ Tasks: {n}",
        "digest_system": (
            "You analyze weekly life-tracking data. "
            "Give 2-3 short insights: patterns, trends, recommendations. "
            "Format: bullet points. English. No preamble."
        ),
    },
    "es": {
        "weekly_title": "Resumen semanal",
        "weekly_period": "Periodo",
        "weekly_entries": "Registros",
        "weekly_avg_mood": "Ánimo promedio",
        "weekly_tasks": "Tareas: {done}/{total} completadas",
        "weekly_insights": "Ideas",
        "morning_title": "☀️ <b>¡Buenos días!</b>",
        "morning_body": (
            "Aún no tienes un plan para hoy.\n"
            "Escribe tus tareas y las guardaré como tu plan del día."
        ),
        "evening_title": "🌙 <b>Hora de reflexionar</b>",
        "evening_body": (
            "¿Qué salió bien hoy? "
            "¿Qué te gustaría mejorar?\n"
            "Escribe libremente."
        ),
        "evening_logged": "Registraste {n} eventos hoy.",
        "evening_tasks": "✅ Tareas: {n}",
        "digest_system": (
            "Analizas datos de life-tracking de la semana. "
            "Da 2-3 ideas cortas: patrones, tendencias, recomendaciones. "
            "Formato: viñetas. Español. Sin introducción."
        ),
    },
    "zh": {
        "weekly_title": "每周总结",
        "weekly_period": "时间段",
        "weekly_entries": "记录",
        "weekly_avg_mood": "平均心情",
        "weekly_tasks": "任务：{done}/{total} 已完成",
        "weekly_insights": "洞察",
        "morning_title": "☀️ <b>早上好！</b>",
        "morning_body": (
            "你还没有今天的计划。\n"
            "写下你的任务，我会保存为今日计划。"
        ),
        "evening_title": "🌙 <b>反思时间</b>",
        "evening_body": (
            "今天什么做得好？哪些可以改进？\n"
            "随便写写。"
        ),
        "evening_logged": "今天记录了 {n} 个事件。",
        "evening_tasks": "✅ 任务：{n}",
        "digest_system": (
            "你分析每周生活跟踪数据。"
            "给出2-3个简短洞察：模式、趋势、建议。"
            "格式：要点。中文。无开场白。"
        ),
    },
    "ru": {
        "weekly_title": "Еженедельный дайджест",
        "weekly_period": "Период",
        "weekly_entries": "Записей",
        "weekly_avg_mood": "Средний mood",
        "weekly_tasks": (
            "Задачи: {done}/{total} выполнено"
        ),
        "weekly_insights": "Инсайты",
        "morning_title": "☀️ <b>Доброе утро!</b>",
        "morning_body": (
            "У вас пока нет плана на сегодня.\n"
            "Напишите задачи, и я сохраню их как план дня."
        ),
        "evening_title": (
            "🌙 <b>Время для рефлексии</b>"
        ),
        "evening_body": (
            "Что получилось сегодня? "
            "Что хотите улучшить?\n"
            "Напишите свободным текстом."
        ),
        "evening_logged": "Сегодня записано {n} событий.",
        "evening_tasks": "✅ Задачи: {n}",
        "digest_system": (
            "Ты анализируешь данные life-tracking за неделю. "
            "Дай 2-3 коротких инсайта: паттерны, тренды, "
            "рекомендации. "
            "Формат: bullet points. Русский язык. "
            "Без вступлений."
        ),
    },
}

# ---------------------------------------------------------------------------
# Reminder labels (moved from reminder_tasks.py)
# ---------------------------------------------------------------------------

REMINDER_LABELS: dict[str, str] = {
    "en": "Reminder",
    "es": "Recordatorio",
    "zh": "提醒",
    "ru": "Напоминание",
}

# ---------------------------------------------------------------------------
# Financial notification texts
# ---------------------------------------------------------------------------

FINANCIAL_TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "header": "📊 Financial notifications:\n\n",
        "anomaly": (
            "⚠️ Unusual: {category} ${amount:.2f} "
            "(usually ~${avg:.2f}/day, x{ratio:.1f})"
        ),
        "budget_exceeded": (
            "🔴 Budget «{category}» exceeded: "
            "${spent:.2f} / ${budget:.2f}"
        ),
        "budget_warning": (
            "🟡 {pct}% of budget «{category}» used: "
            "${spent:.2f} / ${budget:.2f}"
        ),
        "total": "Total",
        "category_fallback": "Category",
    },
    "es": {
        "header": "📊 Notificaciones financieras:\n\n",
        "anomaly": (
            "⚠️ Inusual: {category} ${amount:.2f} "
            "(normalmente ~${avg:.2f}/día, x{ratio:.1f})"
        ),
        "budget_exceeded": (
            "🔴 Presupuesto «{category}» excedido: "
            "${spent:.2f} / ${budget:.2f}"
        ),
        "budget_warning": (
            "🟡 {pct}% del presupuesto «{category}» "
            "usado: ${spent:.2f} / ${budget:.2f}"
        ),
        "total": "Total",
        "category_fallback": "Categoría",
    },
    "zh": {
        "header": "📊 财务通知：\n\n",
        "anomaly": (
            "⚠️ 异常：{category} ${amount:.2f}"
            "（通常 ~${avg:.2f}/天，x{ratio:.1f}）"
        ),
        "budget_exceeded": (
            "🔴 预算「{category}」已超支："
            "${spent:.2f} / ${budget:.2f}"
        ),
        "budget_warning": (
            "🟡 预算「{category}」已使用 {pct}%："
            "${spent:.2f} / ${budget:.2f}"
        ),
        "total": "总计",
        "category_fallback": "类别",
    },
    "ru": {
        "header": "📊 Финансовые уведомления:\n\n",
        "anomaly": (
            "⚠️ Необычно: {category} ${amount:.2f} "
            "(обычно ~${avg:.2f}/день, x{ratio:.1f})"
        ),
        "budget_exceeded": (
            "🔴 Бюджет «{category}» превышен: "
            "${spent:.2f} / ${budget:.2f}"
        ),
        "budget_warning": (
            "🟡 {pct}% бюджета «{category}» "
            "использовано: ${spent:.2f} / ${budget:.2f}"
        ),
        "total": "Общий",
        "category_fallback": "Категория",
    },
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_life_text(lang: str | None) -> dict[str, str]:
    """Get life-tracking texts for a language."""
    return LIFE_TEXTS.get(normalize_language(lang), LIFE_TEXTS["en"])


def get_reminder_label(lang: str | None) -> str:
    """Get the localized 'Reminder' label."""
    return REMINDER_LABELS.get(
        normalize_language(lang), REMINDER_LABELS["en"]
    )


def get_financial_text(lang: str | None) -> dict[str, str]:
    """Get financial notification texts for a language."""
    return FINANCIAL_TEXTS.get(
        normalize_language(lang), FINANCIAL_TEXTS["en"]
    )
