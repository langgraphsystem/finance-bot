"""Tests for the hierarchical supervisor routing."""

from src.core.skill_catalog import load_catalog
from src.core.supervisor import (
    build_supervisor_prompt,
    resolve_agent,
    resolve_domain_and_skills,
)


def test_resolve_agent_finance():
    """Finance message should resolve to the chat agent."""
    catalog = load_catalog.__wrapped__()
    agent = resolve_agent("add expense 50 lunch", catalog)
    assert agent == "chat"


def test_resolve_agent_email():
    """Email message should resolve to the email agent."""
    catalog = load_catalog.__wrapped__()
    agent = resolve_agent("read my email", catalog)
    assert agent == "email"


def test_resolve_agent_unknown():
    """Unknown message returns None."""
    catalog = load_catalog.__wrapped__()
    agent = resolve_agent("xyzzy plugh", catalog)
    assert agent is None


def test_resolve_domain_and_skills():
    """Should return domain name and skills list."""
    catalog = load_catalog.__wrapped__()
    domain, skills = resolve_domain_and_skills("create a task", catalog)
    assert domain == "tasks"
    assert "create_task" in skills
    assert len(skills) == 8  # tasks domain has 8 skills


def test_resolve_domain_and_skills_no_match():
    """No match returns None and empty list."""
    catalog = load_catalog.__wrapped__()
    domain, skills = resolve_domain_and_skills("xyzzy", catalog)
    assert domain is None
    assert skills == []


def test_build_supervisor_prompt():
    """Supervisor prompt should be compact and list all domains."""
    catalog = load_catalog.__wrapped__()
    prompt = build_supervisor_prompt(catalog)
    assert "routing supervisor" in prompt
    assert "finance" in prompt
    assert "tasks" in prompt
    assert "email" in prompt
    # Compact — should be well under 2K chars
    assert len(prompt) < 3000
