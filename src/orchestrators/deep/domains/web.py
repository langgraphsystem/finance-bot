"""Web domain orchestrator — browser automation, web actions."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You are a web automation assistant. Help the user with browser-based tasks:
navigate websites, fill forms, extract data, check prices.
Use browser_action for complex web interactions and web_action for simpler ones.
Report results clearly and concisely.
Use HTML tags for Telegram (<b>, <i>). No Markdown."""

web_orchestrator = DeepAgentOrchestrator(
    domain=Domain.web,
    model="gemini-3-flash-preview",
    skill_names=[
        "browser_action",
        "web_action",
        "price_check",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": False, "hist": 3, "sql": False, "sum": False},
)
