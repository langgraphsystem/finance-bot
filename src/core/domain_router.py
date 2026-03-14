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
    Phase 3+: individual intents get intent-level orchestrators (deep agents).
    """

    def __init__(self, agent_router: AgentRouter):
        self._agent_router = agent_router
        self._orchestrators: dict[Domain, object] = {}
        # Intent-level orchestrators take priority over domain-level ones.
        # Used for selective deep-agent routing (e.g., generate_program, tax_report).
        self._intent_orchestrators: dict[str, object] = {}

    @property
    def agent_router(self) -> AgentRouter:
        """Access the underlying AgentRouter."""
        return self._agent_router

    def register_orchestrator(self, domain: Domain, orchestrator: object) -> None:
        """Register a LangGraph orchestrator for a complex domain."""
        self._orchestrators[domain] = orchestrator
        logger.info("Registered orchestrator for domain=%s", domain)

    def register_intent_orchestrator(self, intent: str, orchestrator: object) -> None:
        """Register a per-intent orchestrator (deep agents).

        Intent-level orchestrators are checked BEFORE domain-level ones.
        The orchestrator's invoke() method receives the full context and
        is responsible for any internal complexity classification.
        """
        self._intent_orchestrators[intent] = orchestrator
        logger.info("Registered intent orchestrator for intent=%s", intent)

    def get_domain(self, intent: str) -> Domain:
        """Resolve intent to its domain."""
        return INTENT_DOMAIN_MAP.get(intent, Domain.general)

    def describe_route(self, intent: str) -> dict[str, str]:
        """Return a stable description of the route plan for an intent."""
        domain = self.get_domain(intent)
        intent_orch = self._intent_orchestrators.get(intent)
        if intent_orch:
            return {
                "intent": intent,
                "domain": domain.value,
                "route_kind": "intent_orchestrator",
                "handler": type(intent_orch).__name__,
            }

        orchestrator = self._orchestrators.get(domain)
        if orchestrator:
            return {
                "intent": intent,
                "domain": domain.value,
                "route_kind": "domain_orchestrator",
                "handler": type(orchestrator).__name__,
            }

        return {
            "intent": intent,
            "domain": domain.value,
            "route_kind": "agent_router",
            "handler": type(self._agent_router).__name__,
        }

    @observe(name="domain_route")
    async def route(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Route intent through domain → orchestrator or AgentRouter.

        Priority order:
        1. Intent-level orchestrators (deep agents, selective routing)
        2. Domain-level orchestrators (email, brief, booking, document)
        3. AgentRouter fallback
        """
        domain = self.get_domain(intent)
        intent_data["_domain"] = domain.value

        # Check intent-level orchestrators first (deep agents)
        intent_orch = self._intent_orchestrators.get(intent)
        if intent_orch:
            logger.debug("Routing intent=%s to intent-level orchestrator", intent)
            return await intent_orch.invoke(intent, message, context, intent_data)

        orchestrator = self._orchestrators.get(domain)
        if orchestrator:
            logger.debug("Routing intent=%s to %s orchestrator", intent, domain)
            return await orchestrator.invoke(intent, message, context, intent_data)

        # Fallback: delegate to existing AgentRouter (Phase 1 default path)
        return await self._agent_router.route(intent, message, context, intent_data)
