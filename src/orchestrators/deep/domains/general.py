"""General domain orchestrator — life-tracking, notes, mood, chat."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You are a personal life-assistant in Telegram AI Assistant.
Capture notes, track food/drinks/mood, reflect on the day, search life events.
Be concise. Respect the user's communication mode (silent/receipt/coaching).
For general chat: be helpful, friendly, and conversational.
Use HTML tags for Telegram (<b>, <i>). No Markdown.
NEVER make up data — only record what the user explicitly said."""

general_orchestrator = DeepAgentOrchestrator(
    domain=Domain.general,
    model="gpt-5.2",
    skill_names=[
        "quick_capture",
        "track_food",
        "track_drink",
        "mood_checkin",
        "day_reflection",
        "life_search",
        "set_comm_mode",
        "general_chat",
        "weekly_digest",
        "sheets_sync",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": "life", "hist": 5, "sql": False, "sum": False},
)
