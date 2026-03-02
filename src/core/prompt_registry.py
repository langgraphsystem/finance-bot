"""Prompt Template Registry — centralized, versioned prompt management.

Loads all ``prompts.yaml`` files under ``src/skills/`` into a single
registry with SHA-256 versioning.  Each prompt template is hashed so
Langfuse traces can reference the exact prompt version used.

Usage::

    from src.core.prompt_registry import prompt_registry

    data = prompt_registry.get("add_expense")
    version = prompt_registry.get_version("add_expense")
"""

import hashlib
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


class PromptRegistry:
    """Singleton registry for all skill prompt templates.

    Loads every ``prompts.yaml`` found under the skills directory,
    indexes by ``name`` field (or directory name), and computes a
    SHA-256 hash for version tracking.
    """

    def __init__(self) -> None:
        self._prompts: dict[str, dict[str, Any]] = {}
        self._versions: dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Lazy-load all prompts on first access."""
        if not self._loaded:
            self.load_all(_SKILLS_DIR)

    def load_all(self, skills_dir: Path | None = None) -> int:
        """Scan *skills_dir* for ``prompts.yaml`` files and index them.

        Returns the number of prompts loaded.
        """
        root = skills_dir or _SKILLS_DIR
        count = 0
        for yaml_path in root.rglob("prompts.yaml"):
            try:
                raw = yaml_path.read_text(encoding="utf-8")
                data = yaml.safe_load(raw)
                if not isinstance(data, dict):
                    continue
                name = data.get("name") or yaml_path.parent.name
                self._prompts[name] = data
                self._versions[name] = hashlib.sha256(raw.encode()).hexdigest()[:12]
                count += 1
            except Exception as exc:
                logger.warning("Failed to load %s: %s", yaml_path, exc)
        self._loaded = True
        logger.debug("PromptRegistry loaded %d prompts", count)
        return count

    def get(self, skill_name: str) -> dict[str, Any]:
        """Return prompt data for *skill_name*, or ``{}`` if not found."""
        self._ensure_loaded()
        return self._prompts.get(skill_name, {})

    def get_version(self, skill_name: str) -> str:
        """Return SHA-256 version hash (12 chars) for *skill_name*."""
        self._ensure_loaded()
        return self._versions.get(skill_name, "")

    def list_skills(self) -> list[str]:
        """Return all registered skill names."""
        self._ensure_loaded()
        return sorted(self._prompts.keys())

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._prompts)

    def reload(self) -> int:
        """Clear and reload all prompts from disk."""
        self._prompts.clear()
        self._versions.clear()
        self._loaded = False
        return self.load_all()


# Module-level singleton — import and use directly
prompt_registry = PromptRegistry()
