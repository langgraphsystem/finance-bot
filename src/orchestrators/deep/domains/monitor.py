"""Monitor domain orchestrator — price alerts, news monitoring."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You help users set up and manage monitoring tasks:
price alerts for products and services, news monitoring for topics of interest.
Confirm what's being monitored and at what thresholds.
Be concise with confirmations.
Use HTML tags for Telegram (<b>, <i>). No Markdown."""

monitor_orchestrator = DeepAgentOrchestrator(
    domain=Domain.monitor,
    model="gpt-5.2",
    skill_names=[
        "price_alert",
        "news_monitor",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
)
