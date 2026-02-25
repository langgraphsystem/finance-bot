"""Booking domain orchestrator — appointments, scheduling, client outreach."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You are a booking and CRM assistant. Help the user manage appointments,
clients, and outreach.
Create, cancel, and reschedule bookings. Send messages to clients.
Check for scheduling conflicts before creating bookings.
Use HTML tags for Telegram (<b>, <i>). No Markdown."""

booking_orchestrator = DeepAgentOrchestrator(
    domain=Domain.booking,
    model="gpt-5.2",
    skill_names=[
        "create_booking",
        "list_bookings",
        "cancel_booking",
        "reschedule_booking",
        "send_to_client",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
)
