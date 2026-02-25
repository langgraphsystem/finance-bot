"""Custom deepagents middleware for finance-bot.

Three middleware components:
1. SessionContextMiddleware — injects SessionContext into agent prompts
2. FinanceBotMemoryMiddleware — loads Mem0 + Redis history into context
3. ObservabilityMiddleware — wraps model calls with Langfuse tracing
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import SystemMessage

if TYPE_CHECKING:
    from src.core.context import SessionContext

logger = logging.getLogger(__name__)


class SessionContextMiddleware(AgentMiddleware):
    """Injects SessionContext fields into the system prompt via abefore_model."""

    tools = []

    def __init__(self, context: SessionContext):
        self._context = context

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Append user context to the system message before each model call."""
        ctx = self._context
        context_block = (
            f"\n\n[User Context]\n"
            f"- user_id: {ctx.user_id}\n"
            f"- language: {ctx.language}\n"
            f"- currency: {ctx.currency}\n"
            f"- timezone: {ctx.timezone}\n"
        )
        if ctx.business_type:
            context_block += f"- business_type: {ctx.business_type}\n"
        if ctx.categories:
            cat_names = ", ".join(c.get("name", "") for c in ctx.categories[:10])
            context_block += f"- categories: {cat_names}\n"
        if ctx.merchant_mappings:
            mappings = ", ".join(m.get("merchant_pattern", "") for m in ctx.merchant_mappings[:10])
            context_block += f"- merchant_mappings: {mappings}\n"

        messages = (
            state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
        )
        if messages and hasattr(messages[0], "type") and messages[0].type == "system":
            new_sys = SystemMessage(content=messages[0].content + context_block)
            return {"messages": [new_sys, *messages[1:]]}
        return None


class FinanceBotMemoryMiddleware(AgentMiddleware):
    """Loads Mem0 memories and Redis sliding-window history into context."""

    tools = []

    def __init__(self, context: SessionContext, context_config: dict):
        self._context = context
        self._config = context_config

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Load memory layers and inject as a system message."""
        memory_block = await self._load_memory()
        if not memory_block:
            return None

        messages = (
            state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
        )
        memory_msg = SystemMessage(content=f"\n[Memory Context]\n{memory_block}")

        if messages and hasattr(messages[0], "type") and messages[0].type == "system":
            return {"messages": [messages[0], memory_msg, *messages[1:]]}
        return {"messages": [memory_msg, *messages]}

    async def _load_memory(self) -> str:
        """Load memory layers based on context_config."""
        parts: list[str] = []
        mem_type = self._config.get("mem")
        hist_count = self._config.get("hist", 0)

        if mem_type and mem_type is not False:
            try:
                from src.core.memory import mem0_client

                memories = await mem0_client.search(
                    self._context.user_id,
                    query="",
                    mem_type=mem_type if isinstance(mem_type, str) else "all",
                    limit=10,
                )
                if memories:
                    mem_text = "\n".join(f"- {m}" for m in memories)
                    parts.append(f"[Memories ({mem_type})]\n{mem_text}")
            except Exception as e:
                logger.debug("Memory load skipped: %s", e)

        if hist_count and hist_count > 0:
            try:
                from src.core.memory import sliding_window

                history = await sliding_window.get_recent(self._context.user_id, count=hist_count)
                if history:
                    hist_text = "\n".join(
                        f"- {m.get('role', 'user')}: {m.get('content', '')}" for m in history
                    )
                    parts.append(f"[Recent History]\n{hist_text}")
            except Exception as e:
                logger.debug("History load skipped: %s", e)

        return "\n\n".join(parts)


class ObservabilityMiddleware(AgentMiddleware):
    """Wraps model calls with Langfuse tracing spans."""

    tools = []

    def __init__(self, domain: str):
        self._domain = domain

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        """Trace the model call via Langfuse if available."""
        try:
            from src.core.observability import get_langfuse

            lf = get_langfuse()
            if lf:
                trace = lf.trace(name=f"deep_{self._domain}")
                span = trace.span(name="model_call")
                result = await handler(request)
                span.end()
                return result
        except Exception:
            pass
        return await handler(request)
