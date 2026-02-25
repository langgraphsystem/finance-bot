"""Email domain orchestrator — replaces the old LangGraph EmailOrchestrator.

Uses deepagents subagents for the revision loop:
- reader subagent: reads Gmail via skill tools
- writer subagent: drafts email with Claude Sonnet
- reviewer subagent: quality check with revision feedback
"""

from __future__ import annotations

import json
import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend

from src.core.context import SessionContext
from src.core.domains import Domain
from src.gateway.types import IncomingMessage
from src.orchestrators.deep.base import DeepAgentOrchestrator, _extract_result, get_registry
from src.orchestrators.deep.middleware import (
    FinanceBotMemoryMiddleware,
    ObservabilityMiddleware,
    SessionContextMiddleware,
)
from src.orchestrators.deep.skill_tools import build_skill_tools
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an email assistant for AI Assistant.
Help the user manage their Gmail inbox: read, summarize, draft, reply, and send emails.

For composing emails (send_email, draft_reply):
1. Plan the email: understand recipient, subject, tone from the user's request.
2. Read relevant context if replying (use read_inbox or summarize_thread tools).
3. Draft the email using the send_email or draft_reply tool.
4. Review your draft for quality — check tone, completeness, grammar.
5. If the draft needs improvement, revise it (max 2 revisions).

Show email content in a clean format. For sending: ALWAYS ask for user confirmation.
Use HTML tags for Telegram (<b>, <i>). No Markdown."""

# Subagent definitions for the email revision loop
EMAIL_READER_PROMPT = """\
You are an email reader. Your job is to fetch and summarize emails from Gmail.
Use the read_inbox and summarize_thread tools to gather context.
Return a concise summary of the relevant emails."""

EMAIL_WRITER_PROMPT = """\
You are an email writer. Draft professional, clear emails based on the user's intent.
Match the tone to the context (formal/casual/professional).
Write the email directly — no preamble. Return the full draft."""

EMAIL_REVIEWER_PROMPT = """\
You are an email quality reviewer. Check the draft for:
- Tone appropriateness
- Completeness (addresses all points from the user's request)
- Grammar and clarity
- Conciseness
If the draft is good, respond with "APPROVED".
If it needs changes, explain what to fix."""

# Intents that benefit from the multi-step revision flow
_COMPOSE_INTENTS = {"send_email", "draft_reply"}


class EmailOrchestrator(DeepAgentOrchestrator):
    """Email orchestrator with subagent-based revision loop for compose intents."""

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Route email intents — compose intents use subagents, others use base."""
        if intent in _COMPOSE_INTENTS:
            return await self._compose_with_subagents(intent, message, context, intent_data)

        # Simple intents (read_inbox, summarize_thread, follow_up_email) → base flow
        return await super().invoke(intent, message, context, intent_data)

    async def _compose_with_subagents(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Compose emails using subagents for reader/writer/reviewer."""
        registry = get_registry()
        tools = build_skill_tools(self.skill_names, registry, context, message)

        middleware = [
            SessionContextMiddleware(context),
            FinanceBotMemoryMiddleware(context, self.context_config),
            ObservabilityMiddleware("email_compose"),
        ]

        # Define subagents for the revision loop
        subagents = [
            {
                "name": "email_reader",
                "description": "Reads and summarizes emails from Gmail",
                "tools": [t for t in tools if t.name in ("read_inbox", "summarize_thread")],
                "model": "claude-sonnet-4-6",
                "system_prompt": EMAIL_READER_PROMPT,
            },
            {
                "name": "email_writer",
                "description": "Drafts professional emails based on context",
                "tools": [t for t in tools if t.name in ("send_email", "draft_reply")],
                "model": "claude-sonnet-4-6",
                "system_prompt": EMAIL_WRITER_PROMPT,
            },
            {
                "name": "email_reviewer",
                "description": "Reviews email drafts for quality",
                "tools": [],
                "model": "claude-haiku-4-5",
                "system_prompt": EMAIL_REVIEWER_PROMPT,
            },
        ]

        agent = create_deep_agent(
            model=self.model,
            tools=tools,
            system_prompt=self.system_prompt,
            middleware=middleware,
            subagents=subagents,
            backend=StateBackend,
        )

        text = message.text or ""
        data_fields = {k: v for k, v in intent_data.items() if v is not None and k != "_domain"}
        user_content = (
            f"{text}\n\n[Intent: {intent}]"
            f"\n[Extracted data: {json.dumps(data_fields, ensure_ascii=False)}]"
        )

        try:
            result = await agent.ainvoke({"messages": [{"role": "user", "content": user_content}]})
        except Exception as e:
            logger.exception("Email compose failed for %s: %s", intent, e)
            return SkillResult(response_text="Couldn't compose the email. Please try again.")

        return _extract_result(result, tools)


email_orchestrator = EmailOrchestrator(
    domain=Domain.email,
    model="claude-sonnet-4-6",
    skill_names=[
        "read_inbox",
        "send_email",
        "draft_reply",
        "follow_up_email",
        "summarize_thread",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": "profile", "hist": 5, "sql": False, "sum": False},
)
