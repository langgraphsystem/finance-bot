import json
import logging
from datetime import date

from src.core.llm.clients import get_instructor_anthropic, google_client
from src.core.observability import observe
from src.core.schemas.intent import IntentDetectionResult

logger = logging.getLogger(__name__)

INTENT_DETECTION_PROMPT = """Определи намерение пользователя из сообщения.

Возможные интенты:
- add_expense: запись расхода ("заправился на 50", "купил продукты 87.50")
- add_income: запись дохода С СУММОЙ ("заработал 185", "получил зарплату", \
"получил оплату за рейс 2500", "доход 3000", "мне заплатили 500")
- scan_receipt: пользователь отправил фото чека
- scan_document: пользователь отправил фото документа, инвойса, \
rate confirmation, или другого изображения
- query_stats: запрос статистики ("сколько потратил за неделю", "сравни с прошлым месяцем")
- query_report: генерация PDF-отчёта ("отчёт", "report", \
"покажи итоги", "PDF", "сгенерируй отчёт", "месячный отчёт")
- correct_category: исправление категории ("это не продукты, а бензин")
- undo_last: отмена последней операции ("отмени последнюю", "undo", "верни обратно")
- mark_paid: ТОЛЬКО изменить статус груза на "оплачен", БЕЗ суммы \
("оплатили груз", "mark paid", "груз оплачен", "отметь рейс оплаченным"). \
ВАЖНО: если в сообщении есть СУММА — это add_income, НЕ mark_paid!
- onboarding: первый контакт, знакомство
- set_budget: установить бюджет или лимит ("бюджет на продукты \
30000", "лимит 5000 в неделю", "set budget")
- add_recurring: добавить регулярный платёж ("подписка", \
"recurring", "каждый месяц плачу", "аренда 50000")
- complex_query: сложный аналитический запрос ("сложный анализ", \
"сравни с бюджетом", "полный отчёт", \
"анализ трат за 3 месяца", "что происходит с финансами")
- quick_capture: заметка, идея, мысль ("идея: ...", "заметка: ...", "запомни: ...", \
"мысль: ...", текст-заметка без финансового контекста и без суммы)
- track_food: запись еды БЕЗ суммы ("съел пиццу", "завтрак: каша", \
"обед: суп и салат", "поел", "ужин: стейк")
- track_drink: напиток БЕЗ суммы ("кофе", "вода", "чай", \
"выпил воду", "2 кофе", "вода 500мл")
- mood_checkin: чек-ин состояния ("настроение 7", "энергия 5", "стресс 3", \
"спал 7 часов", "устал", "feeling great", "checkin")
- day_plan: план дня ("план: ...", "топ задача: ...", \
"сегодня: задеплоить MVP", "план дня")
- day_reflection: рефлексия дня ("рефлексия", "итоги дня", \
"что получилось сегодня", "review", "вечерний обзор")
- life_search: поиск по памяти/заметкам ("что я писал про X?", \
"идеи за неделю", "мои заметки о...", "что я ел вчера?", "поиск: ...")
- set_comm_mode: режим общения ("тихий режим", "coaching mode", \
"молча сохраняй", "режим: квитанция", "silent mode")
- create_task: создать задачу/дело ("add task: ...", "задача: ...", \
"to-do: ...", "добавь в список: ...", "нужно сделать: ...")
- list_tasks: показать список задач ("мои задачи", "что мне нужно сделать", \
"my tasks", "список дел", "what's on my list")
- set_reminder: установить напоминание ("remind me ...", "напомни ...", \
"напоминание: ...", "remind me to pick up Emma at 3:15")
- complete_task: отметить задачу выполненной ("done with ...", "готово: ...", \
"выполнил ...", "задача выполнена", "mark done: ...")
- general_chat: общий вопрос, не связанный с финансами напрямую

Правила приоритета (задачи vs life-tracking):
- "задача: ..." или "add task: ..." → create_task (всегда)
- "напомни ..." или "remind me ..." → set_reminder (всегда)
- "мои задачи" или "what's on my list" → list_tasks
- "готово" или "done with ..." → complete_task
- "план дня" (без конкретной задачи) → day_plan (life-tracking)

Правила приоритета (финансы vs life-tracking):
- Если в сообщении есть СУММА + финансовый контекст -> add_expense / add_income (приоритет)
- "съел пиццу" (без суммы) -> track_food
- "купил пиццу 500" (с суммой) -> add_expense
- "кофе" (без суммы) -> track_drink; "кофе 150р" -> add_expense
- "настроение 7" -> mood_checkin (число -- шкала, не сумма)
- "идея: ..." или "заметка: ..." -> quick_capture (всегда, даже если в тексте есть число)

Правила извлечения даты:
- Сегодня: {today}
- "вчера" → вчерашняя дата
- "позавчера" → позавчерашняя дата
- "в понедельник", "во вторник" и т.д. → ближайший прошедший день недели
- "10 февраля", "February 10" → конкретная дата
- Если дата НЕ указана в тексте → null (НЕ подставляй сегодня, это сделает код)

Правила извлечения периода (для query_stats, query_report, complex_query, life_search):
- "сегодня", "за сегодня" → period: "today"
- "за неделю", "эту неделю", "на этой неделе" → period: "week"
- "за месяц", "этот месяц", "в этом месяце" → period: "month"
- "за год", "этот год", "в этом году" → period: "year"
- "вчера", "за вчера" → period: "day", date: вчерашняя дата
- "за 15 января", "10 февраля" (конкретный день) → period: "day", date: дата
- "с 1 по 15 февраля", "за первую неделю марта" → period: "custom", \
date_from: "YYYY-MM-DD", date_to: "YYYY-MM-DD"
- "последние N дней" → period: "custom", date_from: today-N, date_to: today
- "между ДАТА1 и ДАТА2" → period: "custom", date_from: ДАТА1, date_to: ДАТА2
- "за прошлый месяц", "прошлую неделю" → period: "prev_month" / "prev_week"
- Если период НЕ указан → period: null (код подставит "month")

Правила извлечения типа записи (для life_search):
- "что я ел", "еда", "питание" → life_event_type: "food"
- "кофе", "вода", "чай", "напитки", "что пил" → life_event_type: "drink"
- "настроение", "mood", "как себя чувствовал" → life_event_type: "mood"
- "задачи", "план", "планы", "tasks" → life_event_type: "task"
- "рефлексия", "итоги", "дневник" → life_event_type: "reflection"
- "заметки", "идеи", "мысли", "notes" → life_event_type: "note"
- Если тип не очевиден → life_event_type: null (искать все типы)

Ответь ТОЛЬКО валидным JSON:
{{
  "intent": "имя_интента",
  "confidence": 0.0-1.0,
  "data": {{
    "amount": число или null,
    "merchant": "название" или null,
    "category": "предполагаемая категория" или null,
    "scope": "business" или "family" или null,
    "date": "YYYY-MM-DD" или null,
    "description": "описание" или null,
    "currency": "валюта" или null,
    "period": "today" или "day" или "week" или "month" или "year" \
или "prev_week" или "prev_month" или "custom" или null,
    "date_from": "YYYY-MM-DD" или null,
    "date_to": "YYYY-MM-DD" или null,
    "tags": ["тег1", "тег2"] или null,
    "project": "название проекта" или null,
    "note": "текст заметки/идеи" или null,
    "reflection": "текст рефлексии" или null,
    "food_item": "что съел" или null,
    "meal_type": "breakfast" или "lunch" или "dinner" или "snack" или null,
    "drink_type": "кофе" или "чай" или "вода" или null,
    "drink_count": число или null,
    "drink_volume_ml": объём в мл или null,
    "mood": 1-10 или null,
    "energy": 1-10 или null,
    "stress": 1-10 или null,
    "sleep_hours": число часов или null,
    "tasks": ["задача1", "задача2"] или null,
    "comm_mode": "receipt" или "silent" или "coaching" или null,
    "search_query": "текст поиска" или null,
    "life_event_type": "food" или "drink" или "mood" или "task" \
или "reflection" или "note" или null,
    "task_title": "название задачи" или null,
    "task_deadline": "YYYY-MM-DDTHH:MM:SS" или null,
    "task_priority": "low" или "medium" или "high" или "urgent" или null
  }},
  "response": "краткий ответ для пользователя"
}}"""


@observe(name="detect_intent")
async def detect_intent(
    text: str,
    categories: list[dict] | None = None,
    language: str = "ru",
) -> IntentDetectionResult:
    """Detect user intent using Gemini Flash (primary) with Claude Haiku fallback."""
    categories_str = ""
    if categories:
        categories_str = "\n".join(
            f"- {c.get('name', '')} ({c.get('scope', '')})" for c in categories
        )

    user_prompt = (
        f"Категории пользователя:\n{categories_str}\n\nСообщение: {text}"
        if categories_str
        else f"Сообщение: {text}"
    )

    system_prompt = INTENT_DETECTION_PROMPT.format(today=date.today().isoformat())

    # Primary: Gemini Flash
    try:
        return await _detect_with_gemini(system_prompt, user_prompt, language)
    except Exception as e:
        logger.warning("Gemini intent detection failed: %s, falling back to Claude", e)

    # Fallback: Claude Haiku
    try:
        return await _detect_with_claude(system_prompt, user_prompt, language)
    except Exception as e:
        logger.error("Claude intent detection also failed: %s", e)
        return IntentDetectionResult(
            intent="general_chat",
            confidence=0.5,
            response="Не удалось определить намерение. Попробуйте переформулировать.",
        )


@observe(name="intent_gemini")
async def _detect_with_gemini(
    system_prompt: str, user_prompt: str, language: str
) -> IntentDetectionResult:
    client = google_client()
    response = await client.aio.models.generate_content(
        model="gemini-3-flash-preview",
        contents=f"{system_prompt}\n\nЯзык ответа: {language}\n\n{user_prompt}",
        config={"response_mime_type": "application/json"},
    )
    data = json.loads(response.text)
    return IntentDetectionResult(**data)


@observe(name="intent_claude")
async def _detect_with_claude(
    system_prompt: str, user_prompt: str, language: str
) -> IntentDetectionResult:
    client = get_instructor_anthropic()
    result = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        response_model=IntentDetectionResult,
        max_retries=2,
        system=f"{system_prompt}\n\nЯзык ответа: {language}",
        messages=[{"role": "user", "content": user_prompt}],
    )
    return result


# ── Two-stage intent detection (Phase 1 scaffold) ─────────────────
# Activates when total registered intents exceed STAGE2_THRESHOLD.
# Stage 1: classify domain (Gemini Flash) → Stage 2: classify intent within domain.

STAGE2_THRESHOLD = 25

DOMAIN_CLASSIFICATION_PROMPT = """\
Classify the user's message into exactly one domain.

Domains:
- finance: expenses, income, receipts, budgets, reports, recurring payments
- email: inbox, send, reply, draft, follow-up
- calendar: events, schedule, meetings, free slots
- tasks: to-do, reminders, deadlines, planning
- research: search, compare, analyze, investigate
- writing: draft, translate, proofread, compose
- contacts: people, CRM, follow-ups
- general: life tracking, chat, mood, food, drinks, notes, reflections
- onboarding: setup, connect accounts, first use

Respond with JSON: {{"domain": "...", "confidence": 0.0-1.0}}
"""

DOMAIN_INTENT_PROMPTS: dict[str, str] = {
    "finance": "Finance domain intents — placeholder for Phase 2+ expansion.",
    "email": "Email domain intents — placeholder for Phase 2.",
    "calendar": "Calendar domain intents — placeholder for Phase 2.",
    "tasks": "Tasks domain intents — placeholder for Phase 3.",
    "research": "Research domain intents — placeholder for Phase 3.",
    "writing": "Writing domain intents — placeholder for Phase 3.",
    "contacts": "Contacts domain intents — placeholder for Phase 3.",
    "general": "General domain intents — placeholder for Phase 2+ expansion.",
    "onboarding": "Onboarding domain intents — placeholder.",
}


@observe(name="classify_domain")
async def _classify_domain(text: str, language: str = "ru") -> str:
    """Stage 1: classify message into a domain using Gemini Flash."""
    client = google_client()
    prompt = (
        f"{DOMAIN_CLASSIFICATION_PROMPT}\n\nЯзык: {language}\n\nСообщение: {text}"
    )
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(response.text)
        return data.get("domain", "general")
    except Exception as e:
        logger.warning("Domain classification failed: %s, defaulting to general", e)
        return "general"


async def detect_intent_v2(
    text: str,
    categories: list[dict] | None = None,
    language: str = "ru",
) -> IntentDetectionResult:
    """Two-stage intent detection for >25 intents.

    Stage 1: classify domain (fast, cheap).
    Stage 2: classify intent within domain (focused prompt).

    Not yet active — will be enabled when intent count exceeds STAGE2_THRESHOLD.
    Currently falls through to single-stage detect_intent().
    """
    # Stage 1: classify domain
    domain = await _classify_domain(text, language)

    # Stage 2: for now, fall back to single-stage detection
    # In Phase 2+, each domain will have its own focused prompt
    result = await detect_intent(text=text, categories=categories, language=language)

    # Attach domain to result data
    if result.data:
        result.data.domain = domain

    return result
