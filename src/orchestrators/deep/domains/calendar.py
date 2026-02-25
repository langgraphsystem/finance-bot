"""Calendar domain orchestrator."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You are a calendar assistant for AI Assistant.
Help the user manage their Google Calendar: show schedule, create events,
find free slots, and reschedule.
Check for conflicts before creating events.
For creating/modifying: confirm the details with the user.
Use HTML tags for Telegram (<b>, <i>). No Markdown."""

calendar_orchestrator = DeepAgentOrchestrator(
    domain=Domain.calendar,
    model="gpt-5.2",
    skill_names=[
        "list_events",
        "create_event",
        "find_free_slots",
        "reschedule_event",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
)
