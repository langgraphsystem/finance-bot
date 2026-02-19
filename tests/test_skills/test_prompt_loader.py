"""Tests for YAML prompt loader."""

from pathlib import Path

from src.skills.prompt_loader import clear_cache, load_prompt, validate_all_prompts

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "skills"


def test_load_prompt_returns_dict_for_existing_yaml():
    clear_cache()
    result = load_prompt(SKILLS_DIR / "add_expense")
    assert isinstance(result, dict)
    assert "system_prompt" in result
    assert "name" in result
    assert result["name"] == "add_expense"


def test_load_prompt_returns_empty_dict_for_missing_yaml():
    clear_cache()
    result = load_prompt(SKILLS_DIR / "nonexistent_skill_xyz")
    assert result == {}


def test_load_prompt_caches_result():
    clear_cache()
    first = load_prompt(SKILLS_DIR / "add_expense")
    second = load_prompt(SKILLS_DIR / "add_expense")
    assert first is second


def test_validate_all_prompts_no_errors():
    errors = validate_all_prompts(SKILLS_DIR)
    assert errors == [], f"Prompt validation errors: {errors}"


def test_each_prompts_yaml_has_system_prompt():
    """Every prompts.yaml under src/skills/ must have a system_prompt key."""
    for yaml_path in SKILLS_DIR.rglob("prompts.yaml"):
        data = load_prompt(yaml_path.parent)
        assert "system_prompt" in data, f"{yaml_path} missing system_prompt"


def test_clear_cache():
    clear_cache()
    load_prompt(SKILLS_DIR / "add_expense")
    clear_cache()
    # After clear, next load reads from disk again (no crash)
    result = load_prompt(SKILLS_DIR / "add_expense")
    assert "system_prompt" in result
