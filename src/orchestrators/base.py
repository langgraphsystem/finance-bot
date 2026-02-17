"""Base orchestrator protocol for LangGraph-based complex domains."""

from typing import Any, Protocol

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult


class Orchestrator(Protocol):
    """Protocol for domain orchestrators (email, research, writing, browser)."""

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult: ...
