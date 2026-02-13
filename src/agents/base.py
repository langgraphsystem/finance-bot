"""Multi-agent routing system.

Routes intents to specialized agents with narrow system prompts
and context configs. Each agent handles a subset of intents with
its own model and context configuration for token savings.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from src.core.context import SessionContext
from src.core.memory.context import assemble_context
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillRegistry, SkillResult

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for a specialized agent."""

    name: str
    system_prompt: str
    skills: list[str]  # intents this agent handles
    default_model: str
    context_config: dict = field(default_factory=dict)  # which memory layers to load


class AgentRouter:
    """Routes intent -> agent -> skill with optimized context.

    The AgentRouter wraps SkillRegistry and adds agent-level
    system prompts and context configuration. If routing fails,
    it falls back to direct skill dispatch via the registry.
    """

    def __init__(self, agents: list[AgentConfig], skill_registry: SkillRegistry):
        self._intent_to_agent: dict[str, AgentConfig] = {}
        for agent in agents:
            for intent in agent.skills:
                self._intent_to_agent[intent] = agent
        self._registry = skill_registry
        self._agents = {a.name: a for a in agents}

    @property
    def registry(self) -> SkillRegistry:
        """Access the underlying skill registry."""
        return self._registry

    def get_agent(self, intent: str) -> AgentConfig | None:
        """Get the agent config for a given intent."""
        return self._intent_to_agent.get(intent)

    def list_agents(self) -> list[AgentConfig]:
        """Return all registered agent configs."""
        return list(self._agents.values())

    @observe(name="agent_route")
    async def route(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Route intent to the appropriate agent and skill.

        1. Find the agent for the intent (fallback: onboarding/general_chat).
        2. Assemble context with the agent's system prompt.
        3. Execute the skill from the registry.

        If the agent-based routing fails at any step, falls back to
        direct skill dispatch for backward compatibility.
        """
        agent = self.get_agent(intent)
        if not agent:
            # Fallback to onboarding agent (handles general_chat)
            agent = self._intent_to_agent.get("general_chat")

        if agent:
            # Assemble context with agent-specific system prompt
            try:
                assembled = await assemble_context(
                    user_id=context.user_id,
                    family_id=context.family_id,
                    current_message=message.text or "",
                    intent=intent,
                    system_prompt=agent.system_prompt,
                )
                intent_data["_assembled"] = assembled
                intent_data["_agent"] = agent.name
                intent_data["_model"] = agent.default_model
                logger.debug(
                    "Agent %s assembled context for intent=%s",
                    agent.name,
                    intent,
                )
            except Exception as e:
                logger.warning(
                    "Agent %s context assembly failed: %s, falling back to skill prompt",
                    agent.name,
                    e,
                )
                # Fall back to skill-level context assembly
                await self._fallback_context(intent, message, context, intent_data)
        else:
            # No agent found at all — use skill-level context
            logger.warning("No agent found for intent=%s, using skill fallback", intent)
            await self._fallback_context(intent, message, context, intent_data)

        # Find and execute skill from registry
        skill = self._registry.get(intent)
        if not skill:
            skill = self._registry.get("general_chat")

        if not skill:
            return SkillResult(response_text="Произошла ошибка маршрутизации. Попробуйте ещё раз.")

        return await skill.execute(message, context, intent_data)

    async def _fallback_context(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> None:
        """Fallback: assemble context using the skill's own system prompt."""
        skill = self._registry.get(intent)
        if not skill:
            skill = self._registry.get("general_chat")
        if skill:
            try:
                system_prompt = skill.get_system_prompt(context)
                assembled = await assemble_context(
                    user_id=context.user_id,
                    family_id=context.family_id,
                    current_message=message.text or "",
                    intent=intent,
                    system_prompt=system_prompt,
                )
                intent_data["_assembled"] = assembled
            except Exception as e:
                logger.warning("Fallback context assembly also failed: %s", e)
