"""Agent configurations for Finance Bot.

Defines specialized agents, each with a narrow system prompt,
model selection, and context configuration. This yields 60-70%
token savings compared to a monolith approach.
"""

from src.agents.base import AgentConfig

# --- System prompts (kept short and focused per agent) ---

RECEIPT_AGENT_PROMPT = """\
Ты — агент обработки чеков и документов.
Твоя задача: извлечь данные из фото чека (OCR).
Извлекай: магазин, сумму, дату, список товаров.
Валидируй данные: сумма > 0, дата не в будущем.
Формат ответа: структурированные данные для записи транзакции.
Если данные нечитаемы — попроси пользователя прислать фото лучшего качества."""

ANALYTICS_AGENT_PROMPT = """\
Ты — аналитический агент финансового бота.
Тебе передаются ГОТОВЫЕ числа из SQL. НИКОГДА не считай сам.
Оформи данные красиво и кратко (2-4 предложения).
Добавь сравнения и проценты, если данные позволяют.
Используй эмодзи для визуализации трендов: 📈📉.
Отвечай на русском языке."""

CHAT_AGENT_PROMPT = """\
Ты — агент записи финансовых операций.
Задача: распознать расход/доход из текста пользователя.
Извлекай: сумму, категорию, магазин/описание.
Если уверенность < 85% — переспроси.
Подтверждай записи кратко.
Отвечай на русском языке."""

ONBOARDING_AGENT_PROMPT = """\
Ты — агент онбординга финансового бота.
Помоги новому пользователю настроить бота.
Определи тип деятельности по описанию пользователя.
Будь дружелюбным и кратким.
Для общих вопросов — объясни возможности бота.
Отвечай на русском языке."""

LIFE_AGENT_PROMPT = """\
Ты персональный life-assistant в Telegram-боте.
Задача: фиксировать заметки, отслеживать еду/напитки/настроение, \
планировать день и проводить рефлексию.
Будь краток. Уважай режим общения пользователя (silent/receipt/coaching).
Отвечай на русском. Используй HTML-теги для Telegram.
НИКОГДА не выдумывай данные — записывай только то, что пользователь явно сказал."""

# --- Agent configurations ---

RESEARCH_AGENT_PROMPT = """\
You answer questions, search the web, and compare options.
Lead with the answer. Be concise: 1-5 sentences for facts, bullet points for comparisons.
Use HTML tags for Telegram (<b>bold</b>, <i>italic</i>). No Markdown.
Respond in the user's preferred language (from context.language). Default: English."""

TASKS_AGENT_PROMPT = """\
You help users manage tasks, reminders, to-do lists, and shopping lists.
Create tasks, show the task list, mark tasks done, set reminders.
Manage shopping lists: add items, view lists, check off items, clear lists.
Be concise: one-line confirmations, structured lists.
Respond in the user's preferred language (from context.language). Default: English."""

WRITING_AGENT_PROMPT = """\
You help users write: draft messages, translate text, write posts/reviews, and proofread.
Match the tone to the context (formal email vs casual text vs professional review response).
Write the content directly — no preamble. Use HTML tags for Telegram (<b>bold</b>). No Markdown.
Respond in the user's preferred language (from context.language). Default: English."""

EMAIL_AGENT_PROMPT = """\
You are an email assistant. Help the user manage their Gmail inbox.
Read, summarize, draft, reply, and send emails.
Show email content in a clean format. For sending: ALWAYS ask for user confirmation.
Use HTML tags for Telegram (<b>bold</b>). No Markdown.
Respond in the user's preferred language (from context.language). Default: English."""

CALENDAR_AGENT_PROMPT = """\
You are a calendar assistant. Help the user manage their Google Calendar.
Show schedule, create events, find free slots, reschedule. Check for conflicts before creating.
For creating/modifying: confirm the details. Use HTML tags for Telegram (<b>bold</b>). No Markdown.
Respond in the user's preferred language (from context.language). Default: English."""

BOOKING_AGENT_PROMPT = """\
You are a booking and CRM assistant. Help the user manage appointments, clients, and outreach.
Create/cancel/reschedule bookings. Add and find contacts. Send messages to clients.
Check for scheduling conflicts. Use HTML tags for Telegram (<b>bold</b>). No Markdown.
Respond in the user's preferred language (from context.language). Default: English."""

AGENTS: list[AgentConfig] = [
    AgentConfig(
        name="receipt",
        system_prompt=RECEIPT_AGENT_PROMPT,
        skills=["scan_receipt", "scan_document"],
        default_model="gemini-3-flash-preview",
        context_config={"mem": "mappings", "hist": 2, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="analytics",
        system_prompt=ANALYTICS_AGENT_PROMPT,
        skills=["query_stats", "complex_query", "query_report"],
        default_model="claude-sonnet-4-6",
        context_config={"mem": "budgets", "hist": 0, "sql": True, "sum": True},
    ),
    AgentConfig(
        name="chat",
        system_prompt=CHAT_AGENT_PROMPT,
        skills=[
            "add_expense",
            "add_income",
            "correct_category",
            "undo_last",
            "set_budget",
            "mark_paid",
            "add_recurring",
        ],
        default_model="claude-haiku-4-5",
        context_config={"mem": "mappings", "hist": 5, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="onboarding",
        system_prompt=ONBOARDING_AGENT_PROMPT,
        skills=["onboarding", "general_chat"],
        default_model="claude-sonnet-4-6",
        context_config={"mem": "profile", "hist": 10, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="tasks",
        system_prompt=TASKS_AGENT_PROMPT,
        skills=[
            "create_task",
            "list_tasks",
            "set_reminder",
            "complete_task",
            "shopping_list_add",
            "shopping_list_view",
            "shopping_list_remove",
            "shopping_list_clear",
        ],
        default_model="claude-haiku-4-5",
        context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="research",
        system_prompt=RESEARCH_AGENT_PROMPT,
        skills=[
            "quick_answer",
            "web_search",
            "compare_options",
            "maps_search",
            "youtube_search",
            "price_check",
            "web_action",
        ],
        default_model="gemini-3-flash-preview",
        context_config={"mem": False, "hist": 3, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="writing",
        system_prompt=WRITING_AGENT_PROMPT,
        skills=["draft_message", "translate_text", "write_post", "proofread"],
        default_model="claude-sonnet-4-6",
        context_config={"mem": "profile", "hist": 5, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="email",
        system_prompt=EMAIL_AGENT_PROMPT,
        skills=[
            "read_inbox",
            "send_email",
            "draft_reply",
            "follow_up_email",
            "summarize_thread",
        ],
        default_model="claude-sonnet-4-6",
        context_config={"mem": "profile", "hist": 5, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="calendar",
        system_prompt=CALENDAR_AGENT_PROMPT,
        skills=[
            "list_events",
            "create_event",
            "find_free_slots",
            "reschedule_event",
            "morning_brief",
        ],
        default_model="claude-haiku-4-5",
        context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="life",
        system_prompt=LIFE_AGENT_PROMPT,
        skills=[
            "quick_capture",
            "track_food",
            "track_drink",
            "mood_checkin",
            "day_plan",
            "day_reflection",
            "life_search",
            "set_comm_mode",
            "evening_recap",
            "price_alert",
            "news_monitor",
        ],
        default_model="claude-haiku-4-5",
        context_config={"mem": "life", "hist": 5, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="booking",
        system_prompt=BOOKING_AGENT_PROMPT,
        skills=[
            "create_booking",
            "list_bookings",
            "cancel_booking",
            "reschedule_booking",
            "add_contact",
            "list_contacts",
            "find_contact",
            "send_to_client",
        ],
        default_model="claude-haiku-4-5",
        context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
    ),
]
