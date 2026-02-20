from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.core.context import SessionContext
    from src.gateway.types import IncomingMessage


@dataclass
class SkillResult:
    """Result of skill execution."""

    response_text: str
    buttons: list[dict] | None = None
    document: bytes | None = None
    document_name: str | None = None
    photo_url: str | None = None
    photo_bytes: bytes | None = None
    chart_url: str | None = None
    background_tasks: list[Callable] = field(default_factory=list)
    reply_keyboard: list[dict] | None = None


class BaseSkill(Protocol):
    """Interface for all skill modules."""

    name: str
    intents: list[str]
    model: str

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult: ...

    def get_system_prompt(self, context: SessionContext) -> str: ...


class SkillRegistry:
    """Skill registry with auto-discovery."""

    def __init__(self):
        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        for intent in skill.intents:
            self._skills[intent] = skill

    def get(self, intent: str) -> BaseSkill | None:
        return self._skills.get(intent)

    def all_skills(self) -> list[BaseSkill]:
        return list({id(s): s for s in self._skills.values()}.values())

    def auto_discover(self, skills_dir: str = "src/skills") -> None:
        """Auto-import and register all skills from directory."""
        for skill_path in Path(skills_dir).iterdir():
            if skill_path.is_dir() and (skill_path / "handler.py").exists():
                module = importlib.import_module(f"src.skills.{skill_path.name}.handler")
                if hasattr(module, "skill"):
                    self.register(module.skill)
