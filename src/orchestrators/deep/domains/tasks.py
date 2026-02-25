"""Tasks domain orchestrator — tasks, reminders, shopping lists."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You help users manage tasks, reminders, to-do lists, and shopping lists.
Create tasks, show the task list, mark tasks done, set reminders.
Manage shopping lists: add items, view lists, check off items, clear lists.
Plan the day by organizing priorities and schedules.
Be concise: one-line confirmations, structured lists.
Use HTML tags for Telegram (<b>, <i>). No Markdown."""

tasks_orchestrator = DeepAgentOrchestrator(
    domain=Domain.tasks,
    model="gpt-5.2",
    skill_names=[
        "create_task",
        "list_tasks",
        "set_reminder",
        "complete_task",
        "shopping_list_add",
        "shopping_list_view",
        "shopping_list_remove",
        "shopping_list_clear",
        "day_plan",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": "profile", "hist": 5, "sql": False, "sum": False},
)
