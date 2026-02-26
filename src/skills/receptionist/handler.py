"""Universal receptionist skill — config-driven business front desk.

Reads specialist config from the user's profile to answer questions
about services, pricing, working hours, staff, and FAQ.
Adapts to any business type via YAML config — no code changes needed.
"""

import logging
from datetime import date
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.core.specialist import SpecialistConfig
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_NAMES_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

RECEPTIONIST_SYSTEM_PROMPT = """\
You are a business receptionist assistant. You help the business owner
answer questions about their services, pricing, hours, and availability.

You receive READY data from the business configuration — services, prices,
staff, working hours, and FAQ. Use ONLY this data. Never invent prices,
services, or hours that aren't in the config.

Rules:
- Answer in the user's language ({language}).
- Lead with the answer, then context. Max 5 sentences.
- If asked about a service not in the list, say so and show what IS available.
- For booking requests, suggest using the booking feature.
- Use <b>bold</b> for key info (prices, hours). Telegram HTML format.
- Be warm and professional — you're the front desk."""


class ReceptionistSkill:
    name = "receptionist"
    intents = ["receptionist"]
    model = "gpt-5.2"

    def get_system_prompt(self, context: SessionContext) -> str:
        return RECEPTIONIST_SYSTEM_PROMPT.format(language=context.language or "en")

    @observe(name="skill_receptionist")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        specialist = self._get_specialist(context)
        if not specialist:
            return SkillResult(
                response_text=(
                    "Receptionist features need a business profile with services configured. "
                    "Set your business type during onboarding to get started."
                )
            )

        language = context.language or "en"
        topic = intent_data.get("receptionist_topic", "general")

        # Direct data responses for structured queries
        if topic == "services":
            return self._handle_services(specialist, language, context.currency)
        if topic == "hours":
            return self._handle_hours(specialist, language)
        if topic == "faq":
            return self._handle_faq(specialist, language)

        # LLM-assisted response for open-ended questions
        data_text = self._build_data_context(specialist, language, context)
        assembled = intent_data.get("_assembled")
        model = intent_data.get("_model", self.model)

        response = await generate_text(
            model=model,
            system_prompt=RECEPTIONIST_SYSTEM_PROMPT.format(language=language),
            user_message=(
                f"{message.text}\n\n--- BUSINESS DATA ---\n{data_text}\n\n"
                "Answer the question using ONLY the business data above."
            ),
            assembled_context=assembled,
        )

        buttons = self._build_quick_buttons(specialist, language)
        return SkillResult(response_text=response, buttons=buttons)

    @staticmethod
    def _get_specialist(context: SessionContext) -> SpecialistConfig | None:
        if not context.profile_config:
            return None
        return context.profile_config.specialist

    def _handle_services(
        self, specialist: SpecialistConfig, language: str, currency: str,
    ) -> SkillResult:
        if not specialist.services:
            return SkillResult(response_text="No services configured yet.")

        lines = ["<b>Services:</b>" if language != "ru" else "<b>Услуги:</b>"]
        for s in specialist.services:
            cur = s.currency or currency or ""
            line = f"• {s.name} — {s.duration_min} min"
            if s.price is not None:
                line += f", <b>{s.price:.0f} {cur}</b>"
            if s.description:
                line += f"\n  {s.description}"
            lines.append(line)

        buttons = []
        if "booking" in specialist.capabilities:
            label = "Book appointment" if language != "ru" else "Записаться"
            buttons.append({"text": label, "callback_data": "intent:create_booking"})

        return SkillResult(response_text="\n".join(lines), buttons=buttons or None)

    def _handle_hours(
        self, specialist: SpecialistConfig, language: str,
    ) -> SkillResult:
        wh = specialist.working_hours
        if not wh.default and not any(
            [wh.mon, wh.tue, wh.wed, wh.thu, wh.fri, wh.sat, wh.sun]
        ):
            return SkillResult(response_text="Working hours not configured yet.")

        is_ru = language == "ru"
        names = DAY_NAMES_RU if is_ru else DAY_NAMES
        header = "<b>Часы работы:</b>" if is_ru else "<b>Working hours:</b>"
        lines = [header]

        today_weekday = date.today().weekday()

        for i, name in enumerate(names):
            hours = wh.for_day(i)
            if hours:
                marker = " ← today" if i == today_weekday else ""
                if is_ru and marker:
                    marker = " ← сегодня"
                lines.append(f"  {name}: {hours}{marker}")
            else:
                closed = "закрыто" if is_ru else "closed"
                marker = " ← today" if i == today_weekday else ""
                if is_ru and marker:
                    marker = " ← сегодня"
                lines.append(f"  {name}: {closed}{marker}")

        # Show current status
        today_hours = wh.for_day(today_weekday)
        if today_hours:
            status = f"Open today: {today_hours}" if not is_ru else f"Сегодня: {today_hours}"
        else:
            status = "Closed today" if not is_ru else "Сегодня закрыто"
        lines.append(f"\n{status}")

        return SkillResult(response_text="\n".join(lines))

    def _handle_faq(
        self, specialist: SpecialistConfig, language: str,
    ) -> SkillResult:
        if not specialist.faq:
            return SkillResult(response_text="No FAQ configured yet.")

        is_ru = language == "ru"
        header = "<b>Частые вопросы:</b>" if is_ru else "<b>FAQ:</b>"
        lines = [header]
        for item in specialist.faq[:10]:
            lines.append(f"\n<b>Q:</b> {item.get('q', '')}")
            lines.append(f"<b>A:</b> {item.get('a', '')}")

        return SkillResult(response_text="\n".join(lines))

    def _build_data_context(
        self, specialist: SpecialistConfig, language: str, context: SessionContext,
    ) -> str:
        parts: list[str] = []

        business_name = context.profile_config.name if context.profile_config else "Business"
        parts.append(f"Business: {business_name}")
        parts.append(f"Currency: {context.currency}")

        # Add all specialist knowledge
        knowledge = specialist.build_knowledge_context(language)
        if knowledge:
            parts.append(knowledge)

        # Greeting
        greeting = specialist.get_greeting(language)
        if greeting:
            parts.append(f"Default greeting: {greeting}")

        # Today's status
        today = date.today()
        today_hours = specialist.working_hours.for_day(today.weekday())
        names = DAY_NAMES_RU if language == "ru" else DAY_NAMES
        if today_hours:
            parts.append(f"Today ({names[today.weekday()]}): open {today_hours}")
        else:
            parts.append(f"Today ({names[today.weekday()]}): closed")

        return "\n\n".join(parts)

    @staticmethod
    def _build_quick_buttons(
        specialist: SpecialistConfig, language: str,
    ) -> list[dict[str, str]] | None:
        buttons = []
        is_ru = language == "ru"

        if specialist.services:
            buttons.append({
                "text": "Услуги" if is_ru else "Services",
                "callback_data": "intent:receptionist:services",
            })
        if specialist.working_hours.default:
            buttons.append({
                "text": "Часы работы" if is_ru else "Hours",
                "callback_data": "intent:receptionist:hours",
            })
        if specialist.faq:
            buttons.append({
                "text": "FAQ",
                "callback_data": "intent:receptionist:faq",
            })
        if "booking" in specialist.capabilities:
            buttons.append({
                "text": "Записать" if is_ru else "Book",
                "callback_data": "intent:create_booking",
            })

        return buttons if buttons else None


skill = ReceptionistSkill()
