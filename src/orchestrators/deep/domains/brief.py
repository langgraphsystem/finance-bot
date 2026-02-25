"""Brief domain orchestrator — replaces the old LangGraph BriefOrchestrator.

Uses deepagents subagents for parallel data collection across domains:
calendar, tasks, finance, email, outstanding payments.
Main agent synthesizes collected data into a coherent message.
"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend

from src.core.context import SessionContext
from src.core.domains import Domain
from src.core.plugin_loader import plugin_loader
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

MORNING_SYSTEM = """\
You are generating a morning brief for the user.
Collect data from all connected domains using your subagents, then synthesize
it into one scannable message.

Rules:
- Start with a time-appropriate greeting.
- Use section headers with emoji for each domain that has data.
- Bullet points, short lines — scannable, not dense paragraphs.
- Skip sections that have no data (don't say "no data available").
- End with one actionable question.
- Max 12 bullet points total across all sections.
- Use HTML tags for Telegram (<b>, <i>). No Markdown.
- Respond in: {language}."""

EVENING_SYSTEM = """\
You are generating an evening recap for the user.
Collect data about completed tasks, spending, and events using your subagents,
then synthesize it into a short wrap-up message.

Rules:
- Warm wrap-up tone — not action items, just a summary.
- Bullet points, short lines.
- Skip sections that have no data.
- End with something encouraging if it was productive.
- Max 8 bullet points total.
- Use HTML tags for Telegram (<b>, <i>). No Markdown.
- Respond in: {language}."""

COLLECTOR_PROMPT = """\
You are a data collector. Use the available tools to gather {domain_name} data.
Return a concise summary of the data found. If no data is available, return "".
Do not add commentary — just return the raw data summary."""


class BriefOrchestrator(DeepAgentOrchestrator):
    """Morning brief / evening recap with subagent-based data collection."""

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Run brief with data collection subagents."""
        plugin = plugin_loader.load(context.business_type)

        if intent == "evening_recap":
            sections = plugin.evening_recap_sections
            system = EVENING_SYSTEM.format(language=context.language or "en")
        else:
            sections = plugin.morning_brief_sections
            system = MORNING_SYSTEM.format(language=context.language or "en")

        registry = get_registry()
        tools = build_skill_tools(self.skill_names, registry, context, message)

        middleware = [
            SessionContextMiddleware(context),
            FinanceBotMemoryMiddleware(context, self.context_config),
            ObservabilityMiddleware("brief"),
        ]

        # Define collector subagents
        subagents = [
            {
                "name": "calendar_collector",
                "description": "Collects today's calendar events",
                "tools": [t for t in tools if t.name in ("list_events",)],
                "model": "claude-haiku-4-5",
                "system_prompt": COLLECTOR_PROMPT.format(domain_name="calendar"),
            },
            {
                "name": "tasks_collector",
                "description": "Collects open or completed tasks",
                "tools": [t for t in tools if t.name in ("list_tasks",)],
                "model": "claude-haiku-4-5",
                "system_prompt": COLLECTOR_PROMPT.format(domain_name="tasks"),
            },
            {
                "name": "email_collector",
                "description": "Collects unread important emails",
                "tools": [t for t in tools if t.name in ("read_inbox",)],
                "model": "claude-haiku-4-5",
                "system_prompt": COLLECTOR_PROMPT.format(domain_name="email"),
            },
        ]

        agent = create_deep_agent(
            model="claude-sonnet-4-6",
            tools=tools,
            system_prompt=system,
            middleware=middleware,
            subagents=subagents,
            backend=StateBackend,
        )

        active_sections_str = ", ".join(sections) if sections else "all"
        user_content = (
            f"Generate my {'evening recap' if intent == 'evening_recap' else 'morning brief'}.\n"
            f"Active sections: {active_sections_str}\n"
            f"[Intent: {intent}]"
        )

        try:
            result = await agent.ainvoke({"messages": [{"role": "user", "content": user_content}]})
        except Exception as e:
            logger.exception("Brief orchestrator failed: %s", e)
            if intent == "evening_recap":
                return SkillResult(response_text="Couldn't prepare your evening recap.")
            return SkillResult(
                response_text="Couldn't prepare your morning brief. Try again later."
            )

        return _extract_result(result, tools)


brief_orchestrator = BriefOrchestrator(
    domain=Domain.brief,
    model="claude-sonnet-4-6",
    skill_names=[
        "morning_brief",
        "evening_recap",
        "list_events",
        "list_tasks",
        "read_inbox",
        "query_stats",
    ],
    system_prompt=MORNING_SYSTEM.format(language="en"),
    context_config={"mem": "profile", "hist": 0, "sql": True, "sum": False},
)
