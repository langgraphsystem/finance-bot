"""Day plan skill — create a prioritized list of tasks for the day."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.life_helpers import get_communication_mode, save_life_event
from src.core.llm.clients import generate_text
from src.core.models.enums import LifeEventType
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

DAY_PLAN_SYSTEM_PROMPT = """You help the user plan their day.
Extract the list of tasks from the message. First task = top1 (top priority),
the rest = normal. Respond in the user's language."""

COACHING_SYSTEM_PROMPT = """\
You help create a meaningful day plan.
The user listed tasks. Help prioritize them.
Consider the number of tasks — if many, suggest deferring unimportant ones.
Be realistic about time. Brief advice, 2-3 sentences.
Use HTML tags for Telegram (<b>, <i>). Respond in the user's language."""

_STRINGS = {
    "en": {
        "ask_tasks": "What's on your plate today? List tasks separated by commas or line by line.",
        "plan_title": "Day plan:",
        "tip_fallback": "💡 Focus on the first task — the rest can wait.",
    },
    "ru": {
        "ask_tasks": "Какие задачи на сегодня? Перечислите через запятую или по строкам.",
        "plan_title": "План на день:",
        "tip_fallback": "💡 Фокус на первой задаче — остальное подождёт.",
    },
    "es": {
        "ask_tasks": "¿Qué tareas tienes para hoy? Enuméralas separadas por comas o línea por línea.",
        "plan_title": "Plan del día:",
        "tip_fallback": "💡 Enfócate en la primera tarea — el resto puede esperar.",
    },
    "uk": {
        "ask_tasks": "Які задачі на сьогодні? Перерахуйте через кому або по рядках.",
        "plan_title": "План на день:",
        "tip_fallback": "💡 Фокус на першому завданні — решта почекає.",
    },
    "fr": {
        "ask_tasks": "Quelles sont vos tâches pour aujourd'hui ? Listez-les séparées par des virgules ou ligne par ligne.",
        "plan_title": "Plan de la journée :",
        "tip_fallback": "💡 Concentrez-vous sur la première tâche — le reste peut attendre.",
    },
    "de": {
        "ask_tasks": "Was steht heute an? Listen Sie Aufgaben durch Kommas oder zeilenweise.",
        "plan_title": "Tagesplan:",
        "tip_fallback": "💡 Fokus auf die erste Aufgabe — der Rest kann warten.",
    },
    "pt": {
        "ask_tasks": "Quais são suas tarefas de hoje? Liste-as separadas por vírgulas ou linha por linha.",
        "plan_title": "Plano do dia:",
        "tip_fallback": "💡 Foque na primeira tarefa — o resto pode esperar.",
    },
    "ar": {
        "ask_tasks": "ما هي مهامك اليوم؟ اذكرها مفصولة بفواصل أو سطراً بسطر.",
        "plan_title": "خطة اليوم:",
        "tip_fallback": "💡 ركز على المهمة الأولى — الباقي يمكن الانتظار.",
    },
    "tr": {
        "ask_tasks": "Bugün yapacaklarınız neler? Virgülle veya satır satır listeleyin.",
        "plan_title": "Günlük plan:",
        "tip_fallback": "💡 İlk göreve odaklanın — gerisi bekleyebilir.",
    },
    "ky": {
        "ask_tasks": "Бүгүн кандай тапшырмалар бар? Үтүр менен же ар бир сапта жазыңыз.",
        "plan_title": "Күндүк пландар:",
        "tip_fallback": "💡 Биринчи тапшырмага көңүл буруңуз — калганы күтө алат.",
    },
    "kk": {
        "ask_tasks": "Бүгін қандай тапсырмалар бар? Үтірмен немесе жол бойынша тізіңіз.",
        "plan_title": "Күндік жоспар:",
        "tip_fallback": "💡 Бірінші тапсырмаға назар аударыңыз — қалғаны күте алады.",
    },
    "it": {
        "ask_tasks": "Quali sono le tue attività per oggi? Elencale separate da virgole o riga per riga.",
        "plan_title": "Piano giornaliero:",
        "tip_fallback": "💡 Concentrati sul primo compito — il resto può aspettare.",
    },
}

register_strings("day_plan", _STRINGS)

# Keywords that indicate user is asking ABOUT the feature, not planning tasks
_HELP_KEYWORDS = {
    "plan out your day", "day plan --", "day plan**", "plan out", "what is day plan",
    "план на день --", "план на день**", "что такое план",
}


def _t(key: str, language: str) -> str:
    lang = (language or "en")[:2].lower()
    strings = _STRINGS.get(lang, _STRINGS["en"])
    return strings.get(key, _STRINGS["en"][key])


def _is_help_query(text: str) -> bool:
    """Return True if user is asking about the feature, not submitting tasks."""
    lower = text.lower().strip()
    if any(kw in lower for kw in _HELP_KEYWORDS):
        return True
    # Bare single-word commands like "день" / "plan" / "день план"
    if lower in {"day plan", "план дня", "план на день", "day", "plan", "күндүк план", "күндік жоспар"}:
        return True
    return False


class DayPlanSkill:
    name = "day_plan"
    intents = ["day_plan"]
    model = "claude-sonnet-4-6"

    @observe(name="day_plan")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        text = message.text or ""
        language = context.language or "en"

        # If user sent a help/description query — ask for actual tasks
        if _is_help_query(text):
            return SkillResult(response_text=_t("ask_tasks", language))

        # Extract tasks from intent_data or parse from text
        tasks: list[str] = intent_data.get("tasks", [])

        if not tasks and text.strip():
            raw = text.strip()
            lines = [line.strip() for line in raw.split("\n") if line.strip()]
            if len(lines) > 1:
                tasks = self._clean_task_lines(lines)
            else:
                parts = [p.strip() for p in raw.split(",") if p.strip()]
                if len(parts) > 1:
                    tasks = parts
                else:
                    tasks = [raw]

        if not tasks:
            return SkillResult(response_text=_t("ask_tasks", language))

        # Save each task as a separate LifeEvent
        saved_tasks: list[str] = []
        for i, task_text in enumerate(tasks):
            priority = "top1" if i == 0 else "normal"
            data = {"priority": priority, "order": i + 1, "done": False}

            await save_life_event(
                family_id=context.family_id,
                user_id=context.user_id,
                event_type=LifeEventType.task,
                text=task_text,
                data=data,
            )

            marker = "\U0001f525" if priority == "top1" else "\u2022"
            saved_tasks.append(f"{marker} {task_text}")

        plan_text = "\n".join(saved_tasks)
        title = _t("plan_title", language)

        mode = await get_communication_mode(context.user_id)
        if mode == "silent":
            return SkillResult(response_text="")
        elif mode == "coaching":
            try:
                tip = await generate_text(
                    model=self.model,
                    system=COACHING_SYSTEM_PROMPT,
                    prompt=f"Tasks for the day (language={language}):\n{plan_text}",
                    max_tokens=200,
                )
            except Exception:
                logger.exception("LLM coaching call failed for day_plan")
                tip = _t("tip_fallback", language)
            return SkillResult(response_text=f"<b>{title}</b>\n{plan_text}\n\n{tip}")
        else:
            return SkillResult(response_text=f"<b>{title}</b>\n{plan_text}")

    @staticmethod
    def _clean_task_lines(lines: list[str]) -> list[str]:
        """Remove numbering prefixes like '1.', '1)', '- ' from task lines."""
        cleaned: list[str] = []
        for line in lines:
            stripped = line.lstrip("0123456789.-) ").strip()
            if stripped:
                cleaned.append(stripped)
        return cleaned

    def get_system_prompt(self, context: SessionContext) -> str:
        return DAY_PLAN_SYSTEM_PROMPT


skill = DayPlanSkill()
