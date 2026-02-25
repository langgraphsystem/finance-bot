"""Onboarding domain orchestrator — new user setup."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You are the onboarding agent for AI Assistant.
Help new users set up AI Assistant. Determine business type from the user's description.
Be friendly and concise.
For general questions — explain AI Assistant capabilities.
Use HTML tags for Telegram (<b>, <i>). No Markdown."""

onboarding_orchestrator = DeepAgentOrchestrator(
    domain=Domain.onboarding,
    model="claude-sonnet-4-6",
    skill_names=[
        "onboarding",
        "general_chat",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": "profile", "hist": 10, "sql": False, "sum": False},
)
