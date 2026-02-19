"""YAML prompt loader with startup validation and caching.

Skills can externalize system prompts into `prompts.yaml` files alongside
their handler modules. The loader reads these at first access and caches
them for the lifetime of the process.

Usage in a skill handler::

    from pathlib import Path
    from src.skills.prompt_loader import load_prompt

    class MySkill:
        def get_system_prompt(self, context):
            prompts = load_prompt(Path(__file__).parent)
            if prompts and "system_prompt" in prompts:
                return prompts["system_prompt"].format(
                    user_name=context.user_profile.get("name", "there"),
                    language=context.language or "en",
                )
            return self._default_system_prompt(context)
"""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_cache: dict[str, dict[str, Any]] = {}


def load_prompt(skill_dir: Path) -> dict[str, Any]:
    """Load ``prompts.yaml`` for a skill directory.

    Returns the parsed dict or ``{}`` when no YAML file exists.
    Results are cached by directory string so each file is read only once.
    """
    key = str(skill_dir)
    if key not in _cache:
        yaml_path = skill_dir / "prompts.yaml"
        if yaml_path.exists():
            try:
                _cache[key] = yaml.safe_load(yaml_path.read_text()) or {}
            except yaml.YAMLError as exc:
                logger.error("Failed to parse %s: %s", yaml_path, exc)
                _cache[key] = {}
        else:
            _cache[key] = {}
    return _cache[key]


def validate_all_prompts(skills_dir: Path) -> list[str]:
    """Validate every ``prompts.yaml`` found under *skills_dir*.

    Returns a list of human-readable error strings (empty = all good).
    Called at application startup to catch typos early.
    """
    errors: list[str] = []
    for yaml_path in skills_dir.rglob("prompts.yaml"):
        try:
            data = yaml.safe_load(yaml_path.read_text())
            if not isinstance(data, dict):
                errors.append(f"{yaml_path}: expected a YAML mapping, got {type(data).__name__}")
                continue
            if "system_prompt" not in data:
                errors.append(f"{yaml_path}: missing required 'system_prompt' key")
        except yaml.YAMLError as exc:
            errors.append(f"{yaml_path}: {exc}")
    return errors


def clear_cache() -> None:
    """Clear the prompt cache (useful for tests)."""
    _cache.clear()
