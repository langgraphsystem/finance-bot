"""Multi-agent routing system.

Routes intents to specialized agents with narrow system prompts
and context configs. Each agent handles a subset of intents with
its own model and context configuration for token savings.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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
    data_tools_enabled: bool = False  # enable LLM function calling with data tools


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

    @staticmethod
    def _add_language_instruction(system_prompt: str, context: SessionContext) -> str:
        """Append a language instruction to the system prompt."""
        lang = context.language or "en"
        instruction = (
            f"\n\nIMPORTANT: Always respond in the same language as the user's message. "
            f"User's preferred language: {lang}. "
            f"If the user writes in Kyrgyz, respond in Kyrgyz. "
            f"If in Russian, respond in Russian. "
            f"If in English, respond in English. "
            f"Match the language of their last message."
        )
        return system_prompt + instruction

    @staticmethod
    def _add_date_instruction(system_prompt: str, context: SessionContext) -> str:
        """Append current date/time so the LLM knows today's date."""
        try:
            tz = ZoneInfo(context.timezone)
        except Exception:
            tz = ZoneInfo("America/New_York")
        now = datetime.now(tz)
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        block = (
            f"\n\nCurrent date/time: {now.strftime('%Y-%m-%d %H:%M')} ({context.timezone}). "
            f"Today: {now.strftime('%Y-%m-%d')}. "
            f"Tomorrow: {(now + timedelta(days=1)).strftime('%Y-%m-%d')}. "
            f"Day of week: {days[now.weekday()]}."
        )
        return system_prompt + block

    @observe(name="agent_route_with_tools")
    async def route_with_tools(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Route intent using LLM function calling with data tools.

        The LLM receives the user message + data tool schemas and decides
        whether to call tools or respond directly. This replaces the need
        for individual skill handlers for basic CRUD operations.
        """
        from src.core.llm.clients import generate_text_with_tools
        from src.tools.data_tool_schemas import DATA_TOOL_SCHEMAS
        from src.tools.tool_executor import execute_tool_call

        agent = self.get_agent(intent)
        if not agent:
            agent = self._intent_to_agent.get("general_chat")

        # Build system prompt with data tools context
        prompt = agent.system_prompt if agent else ""
        prompt = self._add_language_instruction(prompt, context)
        prompt = self._add_date_instruction(prompt, context)
        prompt += (
            "\n\nYou have access to database tools. Use them to look up, create, "
            "update, or delete the user's records as needed. Always query first "
            "before answering questions about the user's data. "
            "For deletions of important data, you'll get a pending_id — "
            "ask the user to confirm via the button."
        )

        # Assemble context (memories, history, etc.)
        try:
            assembled = await assemble_context(
                user_id=context.user_id,
                family_id=context.family_id,
                current_message=message.text or ".",
                intent=intent,
                system_prompt=prompt,
            )
            system_prompt = assembled.system_prompt if assembled else prompt
            messages = assembled.messages if assembled else []
        except Exception as e:
            logger.warning("Tool agent context assembly failed: %s", e)
            system_prompt = prompt
            messages = []

        # Ensure we have at least the user message
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if not user_msgs:
            messages.append({"role": "user", "content": message.text or "."})

        async def _tool_executor(name: str, args: dict) -> dict:
            return await execute_tool_call(name, args, context)

        model = agent.default_model if agent else "gpt-5.2"
        response_text, tool_log = await generate_text_with_tools(
            model=model,
            system=system_prompt,
            messages=[m for m in messages if m.get("role") in ("user", "assistant")],
            tools=DATA_TOOL_SCHEMAS,
            tool_executor=_tool_executor,
        )

        # Check tool results for pending actions (delete confirmations)
        buttons = None
        for entry in tool_log:
            result = entry.get("result", {})
            if isinstance(result, dict) and "pending_id" in result:
                pending_id = result["pending_id"]
                buttons = [
                    {"text": "\u2705 Confirm", "callback": f"confirm_action:{pending_id}"},
                    {"text": "\u274c Cancel", "callback": f"cancel_action:{pending_id}"},
                ]

        return SkillResult(response_text=response_text, buttons=buttons)

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
        2. If agent has data_tools_enabled, use tool-augmented LLM flow.
        3. Otherwise, assemble context and execute the skill from the registry.

        If the agent-based routing fails at any step, falls back to
        direct skill dispatch for backward compatibility.
        """
        agent = self.get_agent(intent)
        if not agent:
            # Fallback to onboarding agent (handles general_chat)
            agent = self._intent_to_agent.get("general_chat")

        # Tool-augmented path: LLM decides which tools to call
        if agent and agent.data_tools_enabled:
            try:
                return await self.route_with_tools(intent, message, context, intent_data)
            except Exception as e:
                logger.warning(
                    "Tool-augmented route failed for %s, falling back to skill: %s",
                    intent,
                    e,
                )
                # Fall through to standard skill dispatch

        if agent:
            # Assemble context with agent-specific system prompt
            try:
                prompt = self._add_language_instruction(agent.system_prompt, context)
                prompt = self._add_date_instruction(prompt, context)
                assembled = await assemble_context(
                    user_id=context.user_id,
                    family_id=context.family_id,
                    current_message=message.text or ".",
                    intent=intent,
                    system_prompt=prompt,
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
                system_prompt = self._add_language_instruction(system_prompt, context)
                system_prompt = self._add_date_instruction(system_prompt, context)
                assembled = await assemble_context(
                    user_id=context.user_id,
                    family_id=context.family_id,
                    current_message=message.text or ".",
                    intent=intent,
                    system_prompt=system_prompt,
                )
                intent_data["_assembled"] = assembled
            except Exception as e:
                logger.warning("Fallback context assembly also failed: %s", e)
