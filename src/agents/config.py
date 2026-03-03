"""Agent configurations for Finance Bot.

Defines specialized agents, each with a narrow system prompt,
model selection, and context configuration. This yields 60-70%
token savings compared to a monolith approach.
"""

from src.agents.base import AgentConfig

# --- System prompts (kept short and focused per agent) ---

RECEIPT_AGENT_PROMPT = """\
You are a receipt and document processing agent.
Your task: extract data from receipt photos (OCR).
Extract: store name, amount, date, item list.
Validate: amount > 0, date not in the future.
Output: structured data for recording a transaction.
If unreadable — ask the user to send a better quality photo.
Use HTML tags for Telegram (<b>bold</b>). No Markdown."""

ANALYTICS_AGENT_PROMPT = """\
You are an analytics agent for AI Assistant.
You handle: spending statistics, complex analytical queries, and PDF reports.
You receive READY numbers from SQL. NEVER calculate yourself.
Format data clearly and concisely (2-4 sentences).
Add comparisons and percentages when data allows.
Use emoji for trend visualization: 📈📉.
If data is unavailable, say "no data for this period" — never mention database errors.
Use HTML tags for Telegram (<b>bold</b>). No Markdown. No tables."""

CHAT_AGENT_PROMPT = """\
You are a financial transaction recording agent.
You handle: expenses, income, category corrections, undo last action, \
budgets, recurring payments, mark paid, delete data.
Extract: amount, category, merchant/description.
If confidence < 85% — ask for clarification.
Confirm records concisely.
Use HTML tags for Telegram (<b>bold</b>). No Markdown."""

ONBOARDING_AGENT_PROMPT = """\
You are the onboarding agent for AI Assistant.
Help new users set up AI Assistant.
Determine business type from the user's description.
Be friendly and concise.
For general questions — explain AI Assistant capabilities:
Finance (expenses, income, receipts, budgets, analytics, invoices, tax estimates), \
Email & Calendar (inbox, send, events, morning brief), \
Tasks & Shopping (to-dos, reminders, lists), \
Life Tracking (food, drinks, mood, notes, memory vault), \
Research (web, maps, YouTube, price checks), \
Writing & Media (messages, posts, translation, images, code generation), \
Documents (scan, convert, fill forms, PDFs, spreadsheets, presentations), \
Clients & Bookings (contacts, appointments, CRM), \
Browser (web actions, price alerts, news monitoring).
Use HTML tags for Telegram (<b>bold</b>). No Markdown."""

LIFE_AGENT_PROMPT = """\
You are a personal life-assistant in Telegram AI Assistant.
You handle: notes, food/drink tracking, mood check-ins, day plans, reflections, \
life journal search, evening recaps, price alerts, news monitoring, \
and memory vault (remember/forget personal facts).
Be concise. Respect the user's communication mode (silent/receipt/coaching).
Use HTML tags for Telegram (<b>bold</b>). No Markdown.
NEVER make up data — only record what the user explicitly said."""

# --- Agent configurations ---

RESEARCH_AGENT_PROMPT = """\
You answer questions, search the web, and compare options.
You also handle: maps search, YouTube search, price checks, \
and browser actions (automated web tasks on user's behalf).
Lead with the answer. Be concise: 1-5 sentences for facts, bullet points for comparisons.
Use HTML tags for Telegram (<b>bold</b>, <i>italic</i>). No Markdown."""

TASKS_AGENT_PROMPT = """\
You help users manage tasks, reminders, to-do lists, and shopping lists.
Create tasks, show the task list, mark tasks done, set reminders.
Manage shopping lists: add items, view lists, check off items, clear lists.
Be concise: one-line confirmations, structured lists.
Use HTML tags for Telegram (<b>bold</b>). No Markdown."""

WRITING_AGENT_PROMPT = """\
You help users write: draft messages, translate text, write posts/reviews, and proofread.
You also handle: generate images (AI art), generate greeting cards, \
generate code programs, and modify existing programs.
Match the tone to the context (formal email vs casual text vs professional review response).
Write the content directly — no preamble. Use HTML tags for Telegram (<b>bold</b>). No Markdown."""

EMAIL_AGENT_PROMPT = """\
You are an email assistant. Help the user manage their Gmail inbox.
Read, summarize, draft, reply, and send emails.
Show email content in a clean format. For sending: ALWAYS ask for user confirmation.
Use HTML tags for Telegram (<b>bold</b>). No Markdown."""

CALENDAR_AGENT_PROMPT = """\
You are a calendar assistant. Help the user manage their Google Calendar.
Show schedule, create events, find free slots, reschedule, \
and provide morning briefs (daily schedule + tasks + finance summary).
Check for conflicts before creating. For creating/modifying: confirm the details.
Use HTML tags for Telegram (<b>bold</b>). No Markdown."""

FINANCE_SPECIALIST_PROMPT = """\
You are a financial specialist assistant.
You handle: financial summaries, invoice generation (PDF), tax estimates, and cash flow forecasts.
You receive READY data from SQL. NEVER calculate yourself — use the provided numbers.
Provide clear, actionable financial intelligence. Use HTML tags for Telegram (<b>bold</b>).
For tax estimates, always add: "This is an estimate, not professional tax advice."
Lead with the key number, then break down details. Max 8 lines for summaries."""

DOCUMENT_AGENT_PROMPT = """\
You are a document specialist — a smart capable friend who handles all document work.
Scan and OCR documents (invoices, contracts, forms — receipts go to receipt agent).
Convert formats, extract tables, fill templates, generate invoices/spreadsheets/presentations.
Analyze documents with page citations. PDF ops: split, merge, rotate, encrypt, watermark.
Work with Google Sheets: read, write, append rows, create spreadsheets.
Lead with the result. Use HTML tags for Telegram (<b>bold</b>). No Markdown."""

BOOKING_AGENT_PROMPT = """\
You are a booking and CRM assistant. Help the user manage appointments, clients, and outreach.
Create/cancel/reschedule bookings. Add and find contacts. Send messages to clients.
Check for scheduling conflicts. Use HTML tags for Telegram (<b>bold</b>). No Markdown."""

AGENTS: list[AgentConfig] = [
    AgentConfig(
        name="receipt",
        system_prompt=RECEIPT_AGENT_PROMPT,
        skills=["scan_receipt"],
        default_model="gemini-3-flash-preview",
        context_config={"mem": "mappings", "hist": 2, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="document",
        system_prompt=DOCUMENT_AGENT_PROMPT,
        skills=[
            "scan_document",
            "convert_document",
            "list_documents",
            "search_documents",
            "extract_table",
            "fill_template",
            "fill_pdf_form",
            "analyze_document",
            "merge_documents",
            "pdf_operations",
            "generate_spreadsheet",
            "compare_documents",
            "summarize_document",
            "generate_document",
            "generate_presentation",
            "read_sheets",
            "write_sheets",
            "append_sheets",
            "create_sheets",
        ],
        default_model="claude-sonnet-4-6",
        context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="analytics",
        system_prompt=ANALYTICS_AGENT_PROMPT,
        skills=["query_stats", "complex_query", "query_report", "export_excel"],
        default_model="claude-sonnet-4-6",
        context_config={"mem": "budgets", "hist": 0, "sql": True, "sum": True},
        data_tools_enabled=True,
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
            "delete_data",
        ],
        default_model="gpt-5.2",
        context_config={"mem": "mappings", "hist": 5, "sql": False, "sum": False},
        data_tools_enabled=True,
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
            "schedule_action",
            "list_scheduled_actions",
            "manage_scheduled_action",
            "complete_task",
            "shopping_list_add",
            "shopping_list_view",
            "shopping_list_remove",
            "shopping_list_clear",
        ],
        default_model="gpt-5.2",
        context_config={"mem": "profile", "hist": 5, "sql": False, "sum": False},
        data_tools_enabled=True,
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
            "browser_action",
        ],
        default_model="gemini-3-flash-preview",
        context_config={"mem": False, "hist": 3, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="writing",
        system_prompt=WRITING_AGENT_PROMPT,
        skills=[
            "draft_message",
            "translate_text",
            "write_post",
            "proofread",
            "generate_image",
            "generate_card",
            "generate_program",
            "modify_program",
        ],
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
        default_model="gpt-5.2",
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
            "memory_show",
            "memory_forget",
            "memory_save",
        ],
        default_model="gpt-5.2",
        context_config={"mem": "life", "hist": 5, "sql": False, "sum": False},
        data_tools_enabled=True,
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
            "receptionist",
        ],
        default_model="gpt-5.2",
        context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
        data_tools_enabled=True,
    ),
    AgentConfig(
        name="finance_specialist",
        system_prompt=FINANCE_SPECIALIST_PROMPT,
        skills=[
            "financial_summary",
            "generate_invoice",
            "tax_estimate",
            "cash_flow_forecast",
        ],
        default_model="claude-sonnet-4-6",
        context_config={"mem": "budgets", "hist": 3, "sql": True, "sum": True},
        data_tools_enabled=True,
    ),
]
