"""Web action skill — browser automation for user-requested web tasks.

Uses Browser-Use to navigate websites, extract data, and perform actions.
All actions with side effects require user approval via the approval system.
"""

import logging
from pathlib import Path
from typing import Any

from src.core.approval import approval_manager
from src.core.context import SessionContext
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt
from src.tools.browser import browser_tool

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You are a browser automation assistant. The user asks you to perform
actions on websites. For read-only tasks (check price, look up info),
execute directly. For write tasks (fill form, submit order), require
approval first.

Respond in: {language}."""


class WebActionSkill:
    name = "web_action"
    intents = ["web_action"]
    model = "claude-sonnet-4-6"

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(language=context.language or "en")

    @observe(name="web_action")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        task = message.text or ""
        if not task:
            return SkillResult(response_text="What would you like me to do on the web?")

        # Check if this is a write action that needs approval
        write_signals = ["fill", "submit", "order", "book", "register", "sign up", "buy"]
        is_write = any(signal in task.lower() for signal in write_signals)

        if is_write:
            return await approval_manager.request_approval(
                user_id=context.user_id,
                action="web_action",
                data={"task": task},
                summary=f"I'll execute this web task: <b>{task}</b>",
            )

        # Read-only task — execute directly
        result = await browser_tool.execute_task(task)

        if result["success"]:
            return SkillResult(response_text=result["result"])
        return SkillResult(response_text=f"I couldn't complete that: {result['result']}")


skill = WebActionSkill()
