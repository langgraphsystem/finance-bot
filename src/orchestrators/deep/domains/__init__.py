"""Register all deepagents-powered domain orchestrators."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domains import Domain
from src.orchestrators.deep.domains.booking import booking_orchestrator
from src.orchestrators.deep.domains.brief import brief_orchestrator
from src.orchestrators.deep.domains.calendar import calendar_orchestrator
from src.orchestrators.deep.domains.contacts import contacts_orchestrator
from src.orchestrators.deep.domains.email import email_orchestrator
from src.orchestrators.deep.domains.finance import finance_orchestrator
from src.orchestrators.deep.domains.general import general_orchestrator
from src.orchestrators.deep.domains.monitor import monitor_orchestrator
from src.orchestrators.deep.domains.onboarding import onboarding_orchestrator
from src.orchestrators.deep.domains.research import research_orchestrator
from src.orchestrators.deep.domains.tasks import tasks_orchestrator
from src.orchestrators.deep.domains.web import web_orchestrator
from src.orchestrators.deep.domains.writing import writing_orchestrator

if TYPE_CHECKING:
    from src.core.domain_router import DomainRouter

logger = logging.getLogger(__name__)

DOMAIN_ORCHESTRATORS = {
    Domain.finance: finance_orchestrator,
    Domain.email: email_orchestrator,
    Domain.calendar: calendar_orchestrator,
    Domain.brief: brief_orchestrator,
    Domain.tasks: tasks_orchestrator,
    Domain.research: research_orchestrator,
    Domain.writing: writing_orchestrator,
    Domain.contacts: contacts_orchestrator,
    Domain.booking: booking_orchestrator,
    Domain.web: web_orchestrator,
    Domain.monitor: monitor_orchestrator,
    Domain.general: general_orchestrator,
    Domain.onboarding: onboarding_orchestrator,
}


def register_all_orchestrators(router: DomainRouter) -> None:
    """Register deepagents orchestrators for all 13 domains."""
    for domain, orchestrator in DOMAIN_ORCHESTRATORS.items():
        router.register_orchestrator(domain, orchestrator)
    logger.info("Registered %d deepagents domain orchestrators", len(DOMAIN_ORCHESTRATORS))
