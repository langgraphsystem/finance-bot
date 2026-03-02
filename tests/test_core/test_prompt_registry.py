"""Tests for PromptRegistry — centralized, versioned prompt management."""

from pathlib import Path

from src.core.prompt_registry import PromptRegistry

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "skills"


class TestPromptRegistry:
    def test_loads_all_prompts(self):
        reg = PromptRegistry()
        count = reg.load_all(SKILLS_DIR)
        assert count >= 80  # at least 80 prompts.yaml files

    def test_get_known_skill(self):
        reg = PromptRegistry()
        reg.load_all(SKILLS_DIR)
        data = reg.get("add_expense")
        assert isinstance(data, dict)
        assert "system_prompt" in data

    def test_get_unknown_skill_returns_empty(self):
        reg = PromptRegistry()
        reg.load_all(SKILLS_DIR)
        assert reg.get("nonexistent_xyz") == {}

    def test_get_version_returns_hash(self):
        reg = PromptRegistry()
        reg.load_all(SKILLS_DIR)
        version = reg.get_version("add_expense")
        assert len(version) == 12
        # SHA-256 hex chars only
        assert all(c in "0123456789abcdef" for c in version)

    def test_get_version_unknown_returns_empty(self):
        reg = PromptRegistry()
        reg.load_all(SKILLS_DIR)
        assert reg.get_version("nonexistent_xyz") == ""

    def test_list_skills(self):
        reg = PromptRegistry()
        reg.load_all(SKILLS_DIR)
        skills = reg.list_skills()
        assert isinstance(skills, list)
        assert "add_expense" in skills
        assert "scan_receipt" in skills
        assert skills == sorted(skills)  # alphabetical order

    def test_len(self):
        reg = PromptRegistry()
        reg.load_all(SKILLS_DIR)
        assert len(reg) >= 80

    def test_reload_refreshes(self):
        reg = PromptRegistry()
        reg.load_all(SKILLS_DIR)
        old_count = len(reg)
        new_count = reg.reload()
        assert new_count == old_count

    def test_version_stable_across_loads(self):
        reg = PromptRegistry()
        reg.load_all(SKILLS_DIR)
        v1 = reg.get_version("scan_receipt")
        reg.reload()
        v2 = reg.get_version("scan_receipt")
        assert v1 == v2

    def test_different_skills_different_versions(self):
        reg = PromptRegistry()
        reg.load_all(SKILLS_DIR)
        v_expense = reg.get_version("add_expense")
        v_receipt = reg.get_version("scan_receipt")
        assert v_expense != v_receipt

    def test_lazy_load_on_get(self):
        """Registry auto-loads on first get() call."""
        reg = PromptRegistry()
        # _loaded is False, but get() triggers load_all
        data = reg.get("add_expense")
        assert "system_prompt" in data

    def test_every_prompt_has_system_prompt(self):
        """All prompts.yaml in the registry must have system_prompt."""
        reg = PromptRegistry()
        reg.load_all(SKILLS_DIR)
        for skill_name in reg.list_skills():
            data = reg.get(skill_name)
            assert "system_prompt" in data, f"{skill_name} missing system_prompt"


class TestSingletonRegistry:
    def test_module_singleton(self):
        from src.core.prompt_registry import prompt_registry

        # Accessing singleton triggers lazy load
        data = prompt_registry.get("add_expense")
        assert "system_prompt" in data
        version = prompt_registry.get_version("add_expense")
        assert len(version) == 12
