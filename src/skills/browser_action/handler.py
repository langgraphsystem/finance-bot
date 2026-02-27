"""Browser action skill — authenticated browser automation.

Handles interactive web tasks (booking, purchasing, ordering) that require
user authentication. Uses saved browser sessions (encrypted cookies) to
avoid re-login on every request.

Flow:
1. Check for active hotel booking flow → handle_text_input
2. Check for active login flow → handle_step
3. Hotel search / booking request → multi-step flow with real browser search
4. Non-booking payment task → approval buttons
5. Check saved session → execute_with_session
6. No session → suggest extension login
"""

import logging
import re
from typing import Any

from src.core.approval import approval_manager
from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.tools import browser_booking, browser_login, browser_service

logger = logging.getLogger(__name__)

_FORMAT_PROMPT = """\
The user asked: "{task}"
Browser returned this raw data:

{raw}

Extract the key information and respond concisely in the same language as the user's message.
Use Telegram HTML (<b>, <i>). If the data is not useful, say what happened."""


class BrowserActionSkill:
    name = "browser_action"
    intents = ["browser_action"]
    model = "claude-sonnet-4-6"

    _BOOKING_DOMAINS = (
        "booking.com", "airbnb.com", "hotels.com", "expedia.com",
        "agoda.com", "trivago.com", "kayak.com", "aviasales.ru",
        "skyscanner.com", "ostrovok.ru",
    )
    _BOOKING_VERBS = (
        "забронир", "бронир", "book ", "reserve", "заказа", "order ",
        "купи", "buy ",
    )
    _HOTEL_KEYWORDS = (
        "отель", "гостиниц", "hotel", "hostel", "хостел",
        "жильё", "жилье", "accommodation", "lodging",
        "найди отель", "find a hotel", "найти отель",
        "search hotel", "ищу отель", "нужен отель",
    )

    def get_system_prompt(self, context: SessionContext) -> str:
        return (
            "You are a browser automation assistant that helps users perform "
            "authenticated actions on websites (booking, ordering, purchasing). "
            "You can log into websites on behalf of the user using saved sessions. "
            "For payment actions, always ask for user confirmation first. "
            f"Respond in the user's language ({context.language or 'en'})."
        )

    @observe(name="browser_action")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        task = intent_data.get("browser_task") or message.text or ""
        site = intent_data.get("browser_target_site") or ""

        if not task:
            return SkillResult(
                response_text="What would you like me to do? "
                "Tell me the website and the task."
            )

        # 1. Check for active hotel booking flow — handle text input
        booking_state = await browser_booking.get_booking_state(context.user_id)
        if booking_state:
            result = await browser_booking.handle_text_input(
                context.user_id, message.text or ""
            )
            if result:
                return SkillResult(
                    response_text=result["text"],
                    buttons=result.get("buttons"),
                )

        # 2. Check for active login flow — handle the next step
        login_state = await browser_login.get_login_state(context.user_id)
        if login_state:
            result = await browser_login.handle_step(
                user_id=context.user_id,
                family_id=context.family_id,
                message_text=message.text or "",
                gateway=getattr(message, "_gateway", None),
                chat_id=message.chat_id,
                message_id=message.id,
            )
            return self._login_step_to_result(result)

        # 3. Extract domain from task if not provided
        if not site:
            site = self._extract_site_from_task(task)

        domain = browser_service.extract_domain(site) if site else ""

        # 4. Hotel search / booking request → new multi-step flow
        if self._is_hotel_request(task, domain):
            # Start new hotel search flow (Gemini preview + platform selection)
            search_result = await browser_booking.start_flow(
                user_id=context.user_id,
                family_id=context.family_id,
                task=task,
                language=context.language or "en",
            )
            return SkillResult(
                response_text=search_result["text"],
                buttons=search_result.get("buttons"),
            )

        # Need a domain for non-hotel tasks
        if not domain:
            return SkillResult(
                response_text="Which website should I use? "
                "Please include the site name (e.g., booking.com)."
            )

        # 5. Check if task is too vague (shopping sites only now)
        missing = self._check_missing_details(task, domain)
        if missing:
            return SkillResult(response_text=missing)

        # 6. Check if this is a payment task requiring approval (non-booking sites)
        if self._is_payment_task(task):
            return await approval_manager.request_approval(
                user_id=context.user_id,
                action="browser_action",
                data={"task": task, "site": domain},
                summary=(
                    f"I'll perform this action on <b>{domain}</b>:\n"
                    f"<i>{task}</i>\n\n"
                    "This may involve a payment or purchase."
                ),
            )

        # 7. Check for saved session
        storage_state = await browser_service.get_storage_state(
            context.user_id, domain
        )

        if storage_state:
            result = await browser_service.execute_with_session(
                user_id=context.user_id,
                family_id=context.family_id,
                site=domain,
                task=task,
            )

            if result["success"]:
                return await self._format_result(task, result["result"])

            error_text = result.get("result", "").lower()
            if "login" in error_text or "sign in" in error_text or "auth" in error_text:
                await browser_service.delete_session(context.user_id, domain)
                return SkillResult(
                    response_text=(
                        f"Session expired for <b>{domain}</b>.\n\n"
                        "Please log in again in your browser and use the "
                        "Finance Bot extension to save the new session.\n\n"
                        "Send /extension if you need to set it up."
                    ),
                )

            return SkillResult(
                response_text=f"Browser task failed: {result['result']}"
            )

        # 8. No saved session — suggest browser extension
        return SkillResult(
            response_text=(
                f"I don't have a session for <b>{domain}</b>.\n\n"
                "To save your login:\n"
                "1. Log into the site in your browser\n"
                "2. Click the Finance Bot extension → Save Session\n\n"
                "Don't have the extension? Send /extension to get started."
            ),
        )

    def _is_hotel_request(self, task: str, domain: str) -> bool:
        """Check if this is a hotel search/booking request.

        True if:
        - Task contains hotel keywords (even without a specific site)
        - OR task targets a booking site with a booking verb
        """
        task_lower = task.lower()

        # Hotel keywords in task text
        if any(kw in task_lower for kw in self._HOTEL_KEYWORDS):
            return True

        # Booking site + booking action
        if domain and self._is_booking_site(domain) and self._is_booking_action(task):
            return True

        return False

    async def _start_login_flow(
        self, user_id: str, family_id: str, site: str, task: str
    ) -> SkillResult:
        """Initiate the interactive login flow."""
        result = await browser_login.start_login(
            user_id=user_id,
            family_id=family_id,
            site=site,
            task=task,
        )

        if result["action"] == "error":
            return SkillResult(response_text=result["text"])

        screenshot_bytes = result.get("screenshot_bytes")
        return SkillResult(
            response_text=result["text"],
            photo_bytes=screenshot_bytes,
        )

    def _login_step_to_result(self, result: dict[str, Any]) -> SkillResult:
        """Convert a login flow step result to a SkillResult."""
        action = result.get("action", "error")
        text = result.get("text", "")
        screenshot = result.get("screenshot_bytes")

        if action == "no_flow":
            return SkillResult(
                response_text="No active login flow. What would you like to do?"
            )

        if action == "login_success":
            return SkillResult(response_text=text)

        return SkillResult(
            response_text=text,
            photo_bytes=screenshot,
        )

    async def _format_result(self, task: str, raw: str) -> SkillResult:
        """Format browser output through LLM for clean response."""
        try:
            prompt = _FORMAT_PROMPT.format(task=task, raw=raw[:3000])
            answer = await generate_text(
                "gemini-3.1-flash-preview",
                "You format browser data into concise answers.",
                [{"role": "user", "content": prompt}],
                max_tokens=512,
            )
            return SkillResult(response_text=answer)
        except Exception as e:
            logger.warning("Failed to format browser result: %s", e)
            return SkillResult(response_text=raw)

    def _check_missing_details(self, task: str, domain: str) -> str | None:
        """Check if a purchase task has enough details (shopping sites only).

        Hotel booking validation is now handled by browser_booking.parse_booking_request().
        """
        task_lower = task.lower()

        shopping_domains = (
            "amazon.com", "ebay.com", "aliexpress.com", "ozon.ru",
            "wildberries.ru", "walmart.com",
        )
        is_shopping_site = any(d in domain for d in shopping_domains)

        purchase_verbs = ("купи", "закажи", "buy ", "order ", "purchase")
        is_purchase_action = any(v in task_lower for v in purchase_verbs)
        if is_shopping_site and is_purchase_action:
            words = re.sub(r"[a-zA-Z0-9-]+\.\w{2,}", "", task)
            words = re.sub(
                r"\b(купи|закажи|найди|buy|order|get|на|on|from|с)\b",
                "", words, flags=re.IGNORECASE,
            )
            if len(words.strip()) < 3:
                return (
                    f"What would you like me to find on <b>{domain}</b>?\n\n"
                    "Example: <i>\"купи наушники Sony WH-1000XM5 "
                    "на amazon.com\"</i>"
                )

        return None

    def _is_booking_site(self, domain: str) -> bool:
        """Check if domain is a booking/hotel/travel site."""
        return any(d in domain for d in self._BOOKING_DOMAINS)

    def _is_booking_action(self, task: str) -> bool:
        """Check if task text contains booking action verbs."""
        task_lower = task.lower()
        return any(v in task_lower for v in self._BOOKING_VERBS)

    def _is_payment_task(self, task: str) -> bool:
        """Check if the task involves payment/purchase."""
        task_lower = task.lower()
        ru_payment = ("оплат", "купи", "покуп", "заказа", "оформ", "бронир", "забронир")
        if any(kw in task_lower for kw in ru_payment):
            return True
        text_no_domains = re.sub(r"[a-zA-Z0-9-]+\.\w{2,}", "", task_lower)
        return bool(re.search(
            r"\b(pay|payment|checkout|purchase|buy|book|reserve|order)\b",
            text_no_domains,
        ))

    def _extract_site_from_task(self, task: str) -> str | None:
        """Try to extract a website domain from the task text."""
        url_match = re.search(r"https?://[^\s]+", task)
        if url_match:
            return url_match.group(0)

        domain_match = re.search(
            r"\b([a-zA-Z0-9-]+\.(?:com|org|net|io|co|ru|uk|de|fr|es|it|"
            r"co\.uk|co\.jp|com\.br|com\.au))\b",
            task,
            re.IGNORECASE,
        )
        if domain_match:
            return domain_match.group(1)

        return None


skill = BrowserActionSkill()
