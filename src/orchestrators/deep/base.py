"""Base DeepAgent orchestrator — implements the Orchestrator protocol via deepagents."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend

from src.core.context import SessionContext
from src.core.domains import Domain
from src.gateway.types import IncomingMessage
from src.orchestrators.deep.middleware import (
    FinanceBotMemoryMiddleware,
    ObservabilityMiddleware,
    SessionContextMiddleware,
)
from src.orchestrators.deep.skill_tools import (
    build_skill_tools,
    extract_last_skill_result,
)
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


def _get_registry():
    """Lazy import to avoid circular imports at module load time."""
    from src.skills import create_registry

    return create_registry()


_registry = None


def get_registry():
    global _registry
    if _registry is None:
        _registry = _get_registry()
    return _registry


@dataclass
class DeepAgentOrchestrator:
    """Base class for deepagents-powered domain orchestrators.

    Implements the Orchestrator protocol: invoke(intent, message, context, intent_data)
    → SkillResult. Creates a fresh deep agent per request with the domain's skill tools,
    middleware stack, and system prompt.
    """

    domain: Domain
    model: str
    skill_names: list[str]
    system_prompt: str
    context_config: dict[str, Any] = field(default_factory=dict)

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Create a deep agent and invoke it for the given intent."""
        registry = get_registry()

        # Build skill tools for this domain
        tools = build_skill_tools(self.skill_names, registry, context, message)

        # Build middleware stack
        middleware = [
            SessionContextMiddleware(context),
            FinanceBotMemoryMiddleware(context, self.context_config),
            ObservabilityMiddleware(self.domain.value),
        ]

        # Create the deep agent (backend=StateBackend is passed as a factory)
        agent = create_deep_agent(
            model=self.model,
            tools=tools,
            system_prompt=self.system_prompt,
            middleware=middleware,
            backend=StateBackend,
        )

        # Build the user message with intent context
        user_content = _build_user_message(message, intent, intent_data)

        try:
            result = await agent.ainvoke({"messages": [{"role": "user", "content": user_content}]})
        except Exception as e:
            logger.exception("DeepAgent invocation failed for %s/%s: %s", self.domain, intent, e)
            return SkillResult(response_text="Something went wrong. Please try again.")

        return _extract_result(result, tools)


def _build_user_message(
    message: IncomingMessage,
    intent: str,
    intent_data: dict[str, Any],
) -> str:
    """Build the user message string for the deep agent."""
    text = message.text or ""
    parts = [text]

    # Attach intent metadata so the agent knows what skill to invoke
    meta = {"intent": intent}
    # Include non-None intent_data fields
    data_fields = {k: v for k, v in intent_data.items() if v is not None and k != "_domain"}
    if data_fields:
        meta["extracted_data"] = data_fields

    parts.append(f"\n\n[Intent: {intent}]")
    if data_fields:
        parts.append(f"[Extracted data: {json.dumps(data_fields, ensure_ascii=False)}]")

    return "\n".join(parts)


def _extract_result(
    agent_result: dict[str, Any],
    tools: list,
) -> SkillResult:
    """Extract a SkillResult from the deep agent's output.

    Prefers the last SkillResult captured by a SkillTool (preserves
    buttons, documents, etc.). Falls back to the agent's final text.
    """
    # Check if any skill tool was invoked and captured a full result
    skill_result = extract_last_skill_result(tools)
    if skill_result is not None:
        return skill_result

    # Fall back to agent's final message text
    messages = agent_result.get("messages", [])
    if messages:
        last = messages[-1]
        content = getattr(last, "content", "") if hasattr(last, "content") else str(last)
        if content:
            return SkillResult(response_text=content)

    return SkillResult(response_text="Done.")
