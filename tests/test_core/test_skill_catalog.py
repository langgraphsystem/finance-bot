"""Tests for the Progressive Skill Loading catalog."""

from src.core.skill_catalog import DomainGroup, load_catalog


def test_load_catalog():
    """Catalog should load from the default YAML file."""
    catalog = load_catalog.__wrapped__()  # bypass lru_cache
    assert len(catalog.domains) > 0
    assert "finance" in catalog.domains
    assert "email" in catalog.domains
    assert "tasks" in catalog.domains


def test_catalog_domain_count():
    """Catalog should have all 13 domain groups."""
    catalog = load_catalog.__wrapped__()
    assert len(catalog.domains) == 13


def test_all_skills_mapped():
    """Every skill should map to a domain."""
    catalog = load_catalog.__wrapped__()
    total_skills = sum(len(g.skills) for g in catalog.domains.values())
    assert total_skills >= 68


def test_resolve_domain_finance():
    """Finance keywords should resolve to the finance domain."""
    catalog = load_catalog.__wrapped__()
    assert catalog.resolve_domain("add expense 100 coffee") == "finance"
    assert catalog.resolve_domain("set monthly budget") == "finance"


def test_resolve_domain_russian():
    """Russian keywords should also work."""
    catalog = load_catalog.__wrapped__()
    assert catalog.resolve_domain("расходы за месяц") == "finance"
    assert catalog.resolve_domain("напомни купить молоко") == "tasks"


def test_resolve_domain_email():
    """Email keywords should resolve correctly."""
    catalog = load_catalog.__wrapped__()
    assert catalog.resolve_domain("read my email inbox") == "email"
    assert catalog.resolve_domain("send email to john") == "email"


def test_resolve_domain_no_match():
    """Unrecognized text should return None."""
    catalog = load_catalog.__wrapped__()
    result = catalog.resolve_domain("xyzzy plugh")
    assert result is None


def test_get_domain_for_intent():
    """Intent-to-domain lookup should work."""
    catalog = load_catalog.__wrapped__()
    assert catalog.get_domain_for_intent("add_expense") == "finance"
    assert catalog.get_domain_for_intent("create_task") == "tasks"
    assert catalog.get_domain_for_intent("nonexistent") is None


def test_get_agent_for_domain():
    """Agent lookup should match config.py agents."""
    catalog = load_catalog.__wrapped__()
    assert catalog.get_agent_for_domain("finance") == "chat"
    assert catalog.get_agent_for_domain("analytics") == "analytics"
    assert catalog.get_agent_for_domain("finance_specialist") == "finance_specialist"
    assert catalog.get_agent_for_domain("email") == "email"
    assert catalog.get_agent_for_domain("nonexistent") is None


def test_supervisor_prompt_section():
    """Supervisor prompt should be compact."""
    catalog = load_catalog.__wrapped__()
    prompt = catalog.supervisor_prompt_section()
    assert "finance" in prompt
    assert "email" in prompt
    # Should be much shorter than full skill descriptions
    assert len(prompt) < 2000  # ~500 tokens


def test_domain_group_frozen():
    """DomainGroup should be frozen (immutable)."""
    group = DomainGroup(
        name="test",
        description="test",
        triggers=("a", "b"),
        agent="test",
        skills=("s1",),
    )
    try:
        group.name = "changed"  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


def test_catalog_missing_file():
    """Missing catalog file should return empty catalog."""
    catalog = load_catalog.__wrapped__(path="/nonexistent/path.yaml")
    assert len(catalog.domains) == 0
