"""Domain-level router — sits between master_router and AgentRouter.

Phase 1: thin wrapper around AgentRouter.
Phase 2+: complex domains get LangGraph orchestrators.
"""

import logging
from typing import Any

from src.agents.base import AgentRouter
from src.core.context import SessionContext
from src.core.domains import INTENT_DOMAIN_MAP, Domain
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


class DomainRouter:
    """Routes intents through domain → agent → skill pipeline.

    Phase 1: thin wrapper around AgentRouter.
    Phase 2+: complex domains get LangGraph orchestrators.
    """

    def __init__(self, agent_router: AgentRouter):
        self._agent_router = agent_router
        self._orchestrators: dict[Domain, object] = {}

    @property
    def agent_router(self) -> AgentRouter:
        """Access the underlying AgentRouter."""
        return self._agent_router

    def register_orchestrator(self, domain: Domain, orchestrator: object) -> None:
        """Register a LangGraph orchestrator for a complex domain."""
        self._orchestrators[domain] = orchestrator
        logger.info("Registered orchestrator for domain=%s", domain)

    def get_domain(self, intent: str) -> Domain:
        """Resolve intent to its domain."""
        return INTENT_DOMAIN_MAP.get(intent, Domain.general)

    @observe(name="domain_route")
    async def route(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Route intent through domain → orchestrator or AgentRouter."""
        domain = self.get_domain(intent)
        intent_data["_domain"] = domain.value

        orchestrator = self._orchestrators.get(domain)
        if orchestrator:
            logger.debug("Routing intent=%s to %s orchestrator", intent, domain)
            return await orchestrator.invoke(intent, message, context, intent_data)

        # Fallback: delegate to existing AgentRouter (Phase 1 default path)
        return await self._agent_router.route(intent, message, context, intent_data)
