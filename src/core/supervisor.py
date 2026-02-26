"""Hierarchical supervisor — two-level routing for scaling to 200+ skills.

Level 1: Keyword-based domain resolution from the skill catalog (~500 tokens).
Level 2: Intent detection within the resolved domain (~2K tokens).

This replaces the flat intent router when ``ff_supervisor_routing`` is enabled.
When disabled, the existing ``detect_intent()`` path remains active.

Usage::

    from src.core.supervisor import resolve_agent

    agent_name = resolve_agent(message_text, catalog)
    # → "analytics", "chat", "tasks", etc.
"""

import logging

from src.core.skill_catalog import SkillCatalog, load_catalog

logger = logging.getLogger(__name__)


def resolve_agent(text: str, catalog: SkillCatalog | None = None) -> str | None:
    """Resolve the best agent for a message using the skill catalog.

    1. Match user text against domain triggers (keyword scoring).
    2. Return the agent assigned to the highest-scoring domain.

    Returns None if no domain matches (caller should fall back to
    full intent detection).
    """
    if catalog is None:
        catalog = load_catalog()

    domain = catalog.resolve_domain(text)
    if not domain:
        return None

    agent = catalog.get_agent_for_domain(domain)
    logger.debug("Supervisor resolved domain=%s agent=%s", domain, agent)
    return agent


def resolve_domain_and_skills(
    text: str,
    catalog: SkillCatalog | None = None,
) -> tuple[str | None, list[str]]:
    """Resolve domain and its skill list for progressive loading.

    Returns (domain_name, skill_list) or (None, []) if no match.
    Used by the intent detector to narrow the intent search space.
    """
    if catalog is None:
        catalog = load_catalog()

    domain = catalog.resolve_domain(text)
    if not domain:
        return None, []

    skills = catalog.get_skills_for_domain(domain)
    return domain, skills


def build_supervisor_prompt(catalog: SkillCatalog | None = None) -> str:
    """Build a compact supervisor routing prompt (~500 tokens).

    This replaces the full 68-skill intent list in the intent prompt
    with a domain-level summary for the first routing pass.
    """
    if catalog is None:
        catalog = load_catalog()

    return (
        "You are a routing supervisor. Classify the user's message "
        "into ONE of these domains:\n\n"
        + catalog.supervisor_prompt_section()
        + "\n\nReturn ONLY the domain name (e.g., 'finance', 'tasks', 'email')."
    )
