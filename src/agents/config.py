"""Agent configurations for Finance Bot.

Defines 4 specialized agents, each with a narrow system prompt,
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

# --- Agent configurations ---

AGENTS: list[AgentConfig] = [
    AgentConfig(
        name="receipt",
        system_prompt=RECEIPT_AGENT_PROMPT,
        skills=["scan_receipt"],
        default_model="gemini-2.0-flash",
        context_config={"mem": "mappings", "hist": 2, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="analytics",
        system_prompt=ANALYTICS_AGENT_PROMPT,
        skills=["query_stats", "complex_query"],
        default_model="claude-sonnet-4-5-20250929",
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
        default_model="claude-haiku-4-5-20251001",
        context_config={"mem": "mappings", "hist": 5, "sql": False, "sum": False},
    ),
    AgentConfig(
        name="onboarding",
        system_prompt=ONBOARDING_AGENT_PROMPT,
        skills=["onboarding", "general_chat"],
        default_model="claude-sonnet-4-5-20250929",
        context_config={"mem": "profile", "hist": 10, "sql": False, "sum": False},
    ),
]
