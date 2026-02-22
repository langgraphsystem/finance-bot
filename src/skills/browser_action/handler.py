"""Browser action skill — authenticated browser automation.

Handles interactive web tasks (booking, purchasing, ordering) that require
user authentication. Uses saved browser sessions (encrypted cookies) to
avoid re-login on every request.

Flow:
1. Check for active login flow → handle_step
2. Check saved cookies → execute_with_session
3. No cookies → start_login
4. Payment task → approval buttons
5. Session expired → delete + re-login
"""

import logging
from typing import Any

from src.core.approval import approval_manager
from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.tools import browser_login, browser_service

logger = logging.getLogger(__name__)

_PAYMENT_KEYWORDS = (
    "pay", "payment", "checkout", "purchase", "buy",
    "оплат", "купи", "покуп", "заказ", "оформ",
)

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

        # 1. Check for active login flow — handle the next step
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

        # 2. Extract domain from task if not provided
        if not site:
            site = self._extract_site_from_task(task)
        if not site:
            return SkillResult(
                response_text="Which website should I use? "
                "Please include the site name (e.g., booking.com)."
            )

        domain = browser_service.extract_domain(site)

        # 3. Check if this is a payment task requiring approval
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

        # 4. Check for saved session
        storage_state = await browser_service.get_storage_state(
            context.user_id, domain
        )

        if storage_state:
            # Execute with saved session
            result = await browser_service.execute_with_session(
                user_id=context.user_id,
                family_id=context.family_id,
                site=domain,
                task=task,
            )

            if result["success"]:
                return await self._format_result(task, result["result"])

            # Session might be expired — try re-login
            error_text = result.get("result", "").lower()
            if "login" in error_text or "sign in" in error_text or "auth" in error_text:
                await browser_service.delete_session(context.user_id, domain)
                return await self._start_login_flow(
                    context.user_id, context.family_id, domain, task
                )

            return SkillResult(
                response_text=f"Browser task failed: {result['result']}"
            )

        # 5. No saved session — start login flow
        return await self._start_login_flow(
            context.user_id, context.family_id, domain, task
        )

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
            # Task will be executed by the router on next message
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
                "gemini-3-flash-preview",
                "You format browser data into concise answers.",
                [{"role": "user", "content": prompt}],
                max_tokens=512,
            )
            return SkillResult(response_text=answer)
        except Exception as e:
            logger.warning("Failed to format browser result: %s", e)
            return SkillResult(response_text=raw)

    def _is_payment_task(self, task: str) -> bool:
        """Check if the task involves payment/purchase."""
        task_lower = task.lower()
        return any(kw in task_lower for kw in _PAYMENT_KEYWORDS)

    def _extract_site_from_task(self, task: str) -> str | None:
        """Try to extract a website domain from the task text."""
        import re

        # Match URLs
        url_match = re.search(r"https?://[^\s]+", task)
        if url_match:
            return url_match.group(0)

        # Match bare domains
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
