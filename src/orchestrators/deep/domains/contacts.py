"""Contacts domain orchestrator — add, find, list contacts."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You are a contacts assistant. Help the user manage their contact book.
Add new contacts, find existing ones, and list all contacts.
Be concise with confirmations. Show contact details in a structured format.
Use HTML tags for Telegram (<b>, <i>). No Markdown."""

contacts_orchestrator = DeepAgentOrchestrator(
    domain=Domain.contacts,
    model="gpt-5.2",
    skill_names=[
        "add_contact",
        "list_contacts",
        "find_contact",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
)
