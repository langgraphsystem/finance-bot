"""Adapter: wraps existing BaseSkill handlers as LangChain tools for deepagents."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool
from pydantic import Field

if TYPE_CHECKING:
    from src.core.context import SessionContext
    from src.gateway.types import IncomingMessage
    from src.skills.base import SkillRegistry, SkillResult

logger = logging.getLogger(__name__)


class SkillTool(BaseTool):
    """Wraps a BaseSkill as a LangChain BaseTool for deepagents consumption.

    The tool accepts intent_data as a JSON string, calls skill.execute(),
    and returns the response text. The full SkillResult (buttons, documents,
    etc.) is captured in ``last_result`` for the orchestrator to extract.
    """

    name: str = ""
    description: str = ""
    skill: Any = Field(exclude=True)
    context: Any = Field(exclude=True)
    message: Any = Field(exclude=True)
    last_result: Any = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, intent_data_json: str = "{}") -> str:
        raise NotImplementedError("Use async _arun")

    async def _arun(self, intent_data_json: str = "{}") -> str:
        """Execute the wrapped skill and return response text."""
        try:
            intent_data: dict[str, Any] = json.loads(intent_data_json)
        except (json.JSONDecodeError, TypeError):
            intent_data = {}

        result: SkillResult = await self.skill.execute(self.message, self.context, intent_data)
        self.last_result = result
        return result.response_text


def build_skill_tools(
    skill_names: list[str],
    registry: SkillRegistry,
    context: SessionContext,
    message: IncomingMessage,
) -> list[SkillTool]:
    """Build a list of SkillTools for the given skill/intent names.

    ``skill_names`` can contain either skill names or intent strings —
    the registry resolves both via ``registry.get(intent)``.
    """
    tools: list[SkillTool] = []
    seen: set[str] = set()

    for name in skill_names:
        skill = registry.get(name)
        if skill is None or skill.name in seen:
            continue
        seen.add(skill.name)

        description = (
            f"Execute the '{skill.name}' skill. "
            f"Handles intents: {', '.join(skill.intents)}. "
            f"Pass intent_data as a JSON string with relevant fields."
        )
        tools.append(
            SkillTool(
                name=skill.name,
                description=description,
                skill=skill,
                context=context,
                message=message,
            )
        )

    return tools


def extract_last_skill_result(tools: list[SkillTool]) -> SkillResult | None:
    """Return the most recent SkillResult from any tool that was invoked."""
    for tool in reversed(tools):
        if tool.last_result is not None:
            return tool.last_result
    return None
