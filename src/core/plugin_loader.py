"""Plugin bundle loader for business profiles.

Each plugin is a directory under ``config/plugins/`` with a ``plugin.yaml``
manifest and optional ``prompts/`` overrides for individual skills.

Usage::

    from src.core.plugin_loader import plugin_loader

    plugin = plugin_loader.load("plumber")
    sections = plugin_loader.get_morning_brief_sections("plumber")
    override = plugin_loader.get_prompt_override("plumber", "add_expense")
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PLUGINS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "plugins"
DEFAULT_PLUGIN = "household"
_DEFAULT_MORNING = ["schedule", "tasks", "money_summary", "email_highlights"]
_DEFAULT_EVENING = ["completed_tasks", "spending_total"]


@dataclass
class PluginConfig:
    """Parsed plugin manifest."""

    name: str
    display_name: str = ""
    description: str = ""
    categories: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    morning_brief_sections: list[str] = field(default_factory=lambda: list(_DEFAULT_MORNING))
    evening_recap_sections: list[str] = field(default_factory=lambda: list(_DEFAULT_EVENING))
    disabled_skills: list[str] = field(default_factory=list)


class PluginLoader:
    """Loads and caches plugin bundles from ``config/plugins/``."""

    def __init__(self, plugins_dir: Path | None = None) -> None:
        self._dir = plugins_dir or PLUGINS_DIR
        self._cache: dict[str, PluginConfig] = {}

    def load(self, plugin_name: str | None) -> PluginConfig:
        """Load *plugin_name*. Falls back to ``household`` if not found."""
        name = plugin_name or DEFAULT_PLUGIN
        if name in self._cache:
            return self._cache[name]

        yaml_path = self._dir / name / "plugin.yaml"
        if not yaml_path.exists():
            if name != DEFAULT_PLUGIN:
                logger.warning("Plugin '%s' not found, falling back to '%s'", name, DEFAULT_PLUGIN)
                return self.load(DEFAULT_PLUGIN)
            # Even default doesn't exist — return bare config
            config = PluginConfig(name=DEFAULT_PLUGIN)
            self._cache[name] = config
            return config

        try:
            raw = yaml.safe_load(yaml_path.read_text()) or {}
        except yaml.YAMLError as exc:
            logger.error("Failed to parse %s: %s", yaml_path, exc)
            config = PluginConfig(name=name)
            self._cache[name] = config
            return config

        config = PluginConfig(
            name=raw.get("name", name),
            display_name=raw.get("display_name", ""),
            description=raw.get("description", ""),
            categories=raw.get("categories", []),
            metrics=raw.get("metrics", []),
            morning_brief_sections=raw.get("morning_brief_sections", list(_DEFAULT_MORNING)),
            evening_recap_sections=raw.get("evening_recap_sections", list(_DEFAULT_EVENING)),
            disabled_skills=raw.get("disabled_skills", []),
        )
        self._cache[name] = config
        return config

    def get_prompt_override(self, plugin_name: str, skill_name: str) -> str | None:
        """Return the system_prompt override for a skill, or ``None``."""
        yaml_path = self._dir / (plugin_name or DEFAULT_PLUGIN) / "prompts" / f"{skill_name}.yaml"
        if not yaml_path.exists():
            return None
        try:
            data = yaml.safe_load(yaml_path.read_text()) or {}
            return data.get("system_prompt")
        except yaml.YAMLError as exc:
            logger.error("Failed to parse prompt override %s: %s", yaml_path, exc)
            return None

    def get_categories(self, plugin_name: str | None) -> list[dict[str, Any]]:
        """Return plugin-specific expense categories."""
        return self.load(plugin_name).categories

    def get_morning_brief_sections(self, plugin_name: str | None) -> list[str]:
        """Return section keys for morning brief."""
        return self.load(plugin_name).morning_brief_sections

    def get_evening_recap_sections(self, plugin_name: str | None) -> list[str]:
        """Return section keys for evening recap."""
        return self.load(plugin_name).evening_recap_sections

    def clear_cache(self) -> None:
        self._cache.clear()


# Module-level singleton
plugin_loader = PluginLoader()
