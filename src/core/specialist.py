"""Specialist configuration for business-specific receptionist behavior.

Each business profile can optionally include a `specialist:` section
that defines services, staff, working hours, greetings, and extra
system prompt instructions. This turns the generic booking agent into
a business-specific receptionist without code changes — only YAML.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SpecialistService(BaseModel):
    """A service offered by the business."""

    name: str
    duration_min: int = 60
    price: float | None = None
    currency: str | None = None  # inherits from profile if None
    description: str | None = None


class SpecialistStaff(BaseModel):
    """A staff member / specialist."""

    name: str
    specialties: list[str] = []
    schedule: str | None = None  # e.g. "Mon-Fri 10:00-18:00"


class WorkingHours(BaseModel):
    """Business working hours. Keys: default, mon, tue, ... sun."""

    default: str | None = None
    mon: str | None = None
    tue: str | None = None
    wed: str | None = None
    thu: str | None = None
    fri: str | None = None
    sat: str | None = None
    sun: str | None = None

    def for_day(self, weekday: int) -> str | None:
        """Get hours for a weekday (0=Mon). Returns None if closed."""
        day_map = {0: self.mon, 1: self.tue, 2: self.wed, 3: self.thu,
                   4: self.fri, 5: self.sat, 6: self.sun}
        specific = day_map.get(weekday)
        if specific is not None:
            return specific if specific != "closed" else None
        return self.default


class SpecialistConfig(BaseModel):
    """Business-specific specialist configuration loaded from YAML."""

    greeting: dict[str, str] = Field(default_factory=dict)
    services: list[SpecialistService] = []
    staff: list[SpecialistStaff] = []
    working_hours: WorkingHours = Field(default_factory=WorkingHours)
    capabilities: list[str] = Field(
        default_factory=lambda: ["booking", "price_inquiry", "faq", "reminder"],
    )
    faq: list[dict[str, str]] = []  # [{"q": "...", "a": "..."}]
    system_prompt_extra: str | None = None

    def get_greeting(self, language: str) -> str | None:
        """Get greeting in the requested language, falling back to first available."""
        if language in self.greeting:
            return self.greeting[language]
        if self.greeting:
            return next(iter(self.greeting.values()))
        return None

    def build_knowledge_context(self, language: str = "en") -> str:
        """Build a knowledge base string for injection into system prompts."""
        parts: list[str] = []

        # Services
        if self.services:
            lines = ["Available services:"]
            for s in self.services:
                line = f"- {s.name} ({s.duration_min} min"
                if s.price is not None:
                    cur = s.currency or ""
                    line += f", {s.price} {cur}".rstrip()
                line += ")"
                if s.description:
                    line += f" — {s.description}"
                lines.append(line)
            parts.append("\n".join(lines))

        # Staff
        if self.staff:
            lines = ["Staff:"]
            for m in self.staff:
                line = f"- {m.name}"
                if m.specialties:
                    line += f" [{', '.join(m.specialties)}]"
                if m.schedule:
                    line += f" ({m.schedule})"
                lines.append(line)
            parts.append("\n".join(lines))

        # Working hours
        wh = self.working_hours
        if wh.default:
            hours_parts = [f"Working hours: {wh.default} (default)"]
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            for i, name in enumerate(day_names):
                specific = [wh.mon, wh.tue, wh.wed, wh.thu,
                            wh.fri, wh.sat, wh.sun][i]
                if specific is not None:
                    val = "closed" if specific is None or specific == "closed" else specific
                    hours_parts.append(f"  {name}: {val}")
            parts.append("\n".join(hours_parts))

        # FAQ
        if self.faq:
            lines = ["FAQ:"]
            for item in self.faq[:10]:  # limit to 10
                lines.append(f"Q: {item.get('q', '')}")
                lines.append(f"A: {item.get('a', '')}")
            parts.append("\n".join(lines))

        # Extra prompt
        if self.system_prompt_extra:
            parts.append(self.system_prompt_extra)

        return "\n\n".join(parts)


def build_specialist_system_block(
    specialist: SpecialistConfig,
    language: str,
    business_name: str | None = None,
) -> str:
    """Build the full specialist context block for system prompt injection.

    Returns an empty string if no specialist config is available.
    """
    sections: list[str] = []

    header = "SPECIALIST KNOWLEDGE"
    if business_name:
        header += f" — {business_name}"
    sections.append(f"--- {header} ---")

    greeting = specialist.get_greeting(language)
    if greeting:
        sections.append(f"Default greeting: \"{greeting}\"")

    knowledge = specialist.build_knowledge_context(language)
    if knowledge:
        sections.append(knowledge)

    if specialist.capabilities:
        sections.append(f"Capabilities: {', '.join(specialist.capabilities)}")

    sections.append("--- END SPECIALIST KNOWLEDGE ---")
    return "\n\n".join(sections)
