"""Tests for PluginLoader."""

from pathlib import Path

from src.core.plugin_loader import PluginConfig, PluginLoader

PLUGINS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "plugins"


def test_load_household_plugin():
    loader = PluginLoader(PLUGINS_DIR)
    plugin = loader.load("household")
    assert plugin.name == "household"
    assert isinstance(plugin.categories, list)
    assert len(plugin.categories) > 0
    assert isinstance(plugin.morning_brief_sections, list)


def test_load_plumber_plugin():
    loader = PluginLoader(PLUGINS_DIR)
    plugin = loader.load("plumber")
    assert plugin.name == "plumber"
    assert plugin.display_name == "Plumbing & Trades"
    assert "Materials" in [c["name"] for c in plugin.categories]
    assert "jobs_today" in plugin.morning_brief_sections


def test_load_restaurant_plugin():
    loader = PluginLoader(PLUGINS_DIR)
    plugin = loader.load("restaurant")
    assert plugin.name == "restaurant"
    assert "Food Cost" in [c["name"] for c in plugin.categories]


def test_load_taxi_plugin():
    loader = PluginLoader(PLUGINS_DIR)
    plugin = loader.load("taxi")
    assert plugin.name == "taxi"
    assert "Gas" in [c["name"] for c in plugin.categories]


def test_fallback_to_household():
    loader = PluginLoader(PLUGINS_DIR)
    plugin = loader.load("nonexistent_business")
    assert plugin.name == "household"


def test_none_falls_back_to_household():
    loader = PluginLoader(PLUGINS_DIR)
    plugin = loader.load(None)
    assert plugin.name == "household"


def test_get_morning_brief_sections():
    loader = PluginLoader(PLUGINS_DIR)
    sections = loader.get_morning_brief_sections("plumber")
    assert "jobs_today" in sections
    assert "money_summary" in sections


def test_get_evening_recap_sections():
    loader = PluginLoader(PLUGINS_DIR)
    sections = loader.get_evening_recap_sections("plumber")
    assert "completed_jobs" in sections
    assert "spending_total" in sections


def test_get_categories():
    loader = PluginLoader(PLUGINS_DIR)
    categories = loader.get_categories("plumber")
    names = [c["name"] for c in categories]
    assert "Materials" in names
    assert "Vehicle" in names


def test_get_prompt_override_exists():
    loader = PluginLoader(PLUGINS_DIR)
    override = loader.get_prompt_override("plumber", "add_expense")
    assert override is not None
    assert "Materials" in override


def test_get_prompt_override_missing():
    loader = PluginLoader(PLUGINS_DIR)
    override = loader.get_prompt_override("household", "add_expense")
    assert override is None


def test_caching():
    loader = PluginLoader(PLUGINS_DIR)
    first = loader.load("household")
    second = loader.load("household")
    assert first is second


def test_clear_cache():
    loader = PluginLoader(PLUGINS_DIR)
    loader.load("household")
    loader.clear_cache()
    # After clear, loading again works
    plugin = loader.load("household")
    assert plugin.name == "household"


def test_plugin_config_defaults():
    config = PluginConfig(name="test")
    assert config.display_name == ""
    assert config.categories == []
    assert isinstance(config.morning_brief_sections, list)
    assert isinstance(config.evening_recap_sections, list)
    assert config.disabled_skills == []
