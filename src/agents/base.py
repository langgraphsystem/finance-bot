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

_SKILL_ONLY_INTENTS = {
    # Relative/one-shot reminders are handled more reliably by the dedicated skill.
    "set_reminder",
    # query_stats has proper period resolution, comparison data, and chart generation
    # that the generic data_tools path lacks (it only sees current-month sql_stats context).
    "query_stats",
    # query_report generates PDF reports with dedicated period parsing.
    "query_report",
    # set_user_rule uses dedicated handler for identity/rules DB writes.
    "set_user_rule",
    # memory_vault intents use dedicated Mem0/identity handlers — must NOT go through
    # data_tools LLM path (which would ignore the structured rule/identity logic).
    "memory_show",
    "memory_forget",
    "memory_save",
    # dialog_history searches session_summaries directly.
    "dialog_history",
    # memory_update uses dedicated Mem0 search+delete+add flow.
    "memory_update",
    # Project management uses dedicated DB handlers.
    "set_project",
    "create_project",
    "list_projects",
    "shopping_list_add",
    "shopping_list_view",
    "shopping_list_remove",
    "shopping_list_clear",
    # Life tracking handlers are more reliable than generic data tools.
    "quick_capture",
    "track_food",
    "track_drink",
    "mood_checkin",
    "day_plan",
    "day_reflection",
    "life_search",
    "set_comm_mode",
    "evening_recap",
    # Booking/CRM handlers have richer DB semantics than generic query_data calls.
    "create_booking",
    "list_bookings",
    "cancel_booking",
    "reschedule_booking",
    "add_contact",
    "list_contacts",
    "find_contact",
    "send_to_client",
    "receptionist",
}
_TOOL_ROUND_EXHAUSTED_RESPONSE = "I needed more steps to complete this request."


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
    def _add_specialist_knowledge(system_prompt: str, context: SessionContext) -> str:
        """Inject specialist knowledge from profile_config into the system prompt."""
        if not context.profile_config or not context.profile_config.specialist:
            return system_prompt
        from src.core.specialist import build_specialist_system_block

        block = build_specialist_system_block(
            specialist=context.profile_config.specialist,
            language=context.language or "en",
            business_name=context.profile_config.name,
        )
        if block:
            return system_prompt + "\n\n" + block
        return system_prompt

    @staticmethod
    def _add_personality_instruction(
        system_prompt: str, context: SessionContext
    ) -> str:
        """Append user-specific personality cues (2-4 sentences max)."""
        profile = context.user_profile
        if not profile:
            return system_prompt

        personality = profile.get("personality")
        if not personality:
            return system_prompt

        cues: list[str] = []

        verbosity = personality.get("verbosity", "concise")
        if verbosity == "detailed":
            cues.append("This user prefers detailed explanations.")
        elif verbosity == "concise":
            cues.append("Keep responses brief and to-the-point.")

        formality = personality.get("formality", "neutral")
        if formality == "formal":
            cues.append("Use a professional tone.")
        elif formality == "casual":
            cues.append("Keep a casual, friendly tone.")

        emoji_usage = personality.get("emoji_usage", "light")
        if emoji_usage == "none":
            cues.append("Avoid using emoji.")
        elif emoji_usage == "heavy":
            cues.append("Feel free to use emoji.")

        occupation = profile.get("occupation")
        if occupation:
            cues.append(f"User's occupation: {occupation}.")

        if not cues:
            return system_prompt

        return system_prompt + "\n\nUser personality: " + " ".join(cues)

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
        from src.core.observability import update_trace_user
        from src.core.prompt_registry import prompt_registry
        from src.tools.data_tool_schemas import get_schemas_for_domain
        from src.tools.tool_executor import execute_tool_call

        update_trace_user(context.user_id)
        pv = prompt_registry.get_version(intent)

        agent = self.get_agent(intent)
        if not agent:
            agent = self._intent_to_agent.get("general_chat")

        # Build system prompt with data tools context
        prompt = agent.system_prompt if agent else ""
        prompt = self._add_specialist_knowledge(prompt, context)
        prompt = self._add_personality_instruction(prompt, context)
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

        model = agent.default_model if agent else "gpt-5.4-2026-03-05"
        agent_name = agent.name if agent else None
        tool_schemas = get_schemas_for_domain(agent_name)

        # Check plan cache for a previously successful tool-call sequence
        from src.core.plan_cache import TOOL_PLAN_TTL, plan_cache

        plan_params = dict(agent=agent_name, intent=intent)
        cached_plan = await plan_cache.get("tools", **plan_params)
        if cached_plan and cached_plan.get("tool_hint"):
            # Inject cached plan as a hint so the LLM reuses the same tools
            hint = cached_plan["tool_hint"]
            system_prompt += (
                f"\n\nFor this type of request, you previously used these tools "
                f"in this order: {hint}. Use the same approach if appropriate."
            )

        response_text, tool_log = await generate_text_with_tools(
            model=model,
            system=system_prompt,
            messages=[m for m in messages if m.get("role") in ("user", "assistant")],
            tools=tool_schemas,
            tool_executor=_tool_executor,
            prompt_version=pv,
        )
        if response_text.strip() == _TOOL_ROUND_EXHAUSTED_RESPONSE:
            raise RuntimeError("Tool-calling exhausted maximum rounds")

        # Cache the tool-call sequence for future reuse
        if tool_log:
            tool_names = [entry.get("name", "") for entry in tool_log if entry.get("name")]
            if tool_names:
                await plan_cache.put(
                    "tools",
                    {"tool_hint": ", ".join(tool_names)},
                    ttl=TOOL_PLAN_TTL,
                    **plan_params,
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
        from src.core.observability import update_trace_user

        update_trace_user(context.user_id)
        agent = self.get_agent(intent)
        if not agent:
            # Fallback to onboarding agent (handles general_chat)
            agent = self._intent_to_agent.get("general_chat")

        # Tool-augmented path: LLM decides which tools to call.
        # Some intents are intentionally kept on deterministic skill handlers.
        if agent and agent.data_tools_enabled and intent not in _SKILL_ONLY_INTENTS:
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
                prompt = self._add_specialist_knowledge(agent.system_prompt, context)
                prompt = self._add_personality_instruction(prompt, context)
                prompt = self._add_language_instruction(prompt, context)
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

        # Expose the resolved intent so skill handlers can branch by intent name.
        intent_data["_intent"] = intent

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
                system_prompt = self._add_personality_instruction(system_prompt, context)
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
