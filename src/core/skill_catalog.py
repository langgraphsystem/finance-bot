"""Progressive Skill Loading — YAML catalog + lazy domain resolution.

Instead of stuffing 68+ skill descriptions into the intent prompt (~40K tokens),
the supervisor first resolves the domain via keyword triggers (~500 tokens),
then loads only the relevant skill group (~2K tokens).

This enables scaling to 200+ skills without intent prompt overload.
"""

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "skill_catalog.yaml"


@dataclass(frozen=True)
class DomainGroup:
    """A group of skills under one domain."""

    name: str
    description: str
    triggers: tuple[str, ...]
    agent: str
    skills: tuple[str, ...]


@dataclass
class SkillCatalog:
    """Loaded skill catalog with fast domain lookup."""

    domains: dict[str, DomainGroup] = field(default_factory=dict)
    _intent_to_domain: dict[str, str] = field(default_factory=dict)

    def resolve_domain(self, text: str) -> str | None:
        """Resolve domain from user text using keyword triggers.

        Returns the domain name with the most trigger matches,
        or None if no triggers match.
        """
        text_lower = text.lower()
        scores: dict[str, int] = {}
        for name, group in self.domains.items():
            score = sum(1 for t in group.triggers if t in text_lower)
            if score > 0:
                scores[name] = score

        if not scores:
            return None
        return max(scores, key=scores.get)  # type: ignore[arg-type]

    def get_domain(self, domain_name: str) -> DomainGroup | None:
        """Get a domain group by name."""
        return self.domains.get(domain_name)

    def get_domain_for_intent(self, intent: str) -> str | None:
        """Look up which domain owns a given intent."""
        return self._intent_to_domain.get(intent)

    def get_skills_for_domain(self, domain_name: str) -> list[str]:
        """Get skill names for a domain."""
        group = self.domains.get(domain_name)
        return list(group.skills) if group else []

    def get_agent_for_domain(self, domain_name: str) -> str | None:
        """Get the agent name for a domain."""
        group = self.domains.get(domain_name)
        return group.agent if group else None

    def supervisor_prompt_section(self) -> str:
        """Generate a compact domain list for the supervisor prompt.

        Returns ~500 tokens instead of ~40K for full skill descriptions.
        """
        lines = []
        for name, group in self.domains.items():
            lines.append(f"- **{name}**: {group.description}")
        return "\n".join(lines)

    @property
    def all_domains(self) -> list[str]:
        return list(self.domains.keys())


@lru_cache(maxsize=1)
def load_catalog(path: str | None = None) -> SkillCatalog:
    """Load the skill catalog from YAML."""
    catalog_path = Path(path) if path else _CATALOG_PATH
    if not catalog_path.exists():
        logger.warning("Skill catalog not found at %s", catalog_path)
        return SkillCatalog()

    with open(catalog_path) as f:
        raw = yaml.safe_load(f)

    domains_raw = raw.get("domains", {})
    catalog = SkillCatalog()

    for name, data in domains_raw.items():
        group = DomainGroup(
            name=name,
            description=data.get("description", ""),
            triggers=tuple(data.get("triggers", [])),
            agent=data.get("agent", ""),
            skills=tuple(data.get("skills", [])),
        )
        catalog.domains[name] = group
        for skill in group.skills:
            catalog._intent_to_domain[skill] = name

    logger.info(
        "Skill catalog loaded: %d domains, %d skills",
        len(catalog.domains),
        len(catalog._intent_to_domain),
    )
    return catalog
