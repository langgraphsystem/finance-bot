import json
import logging

from src.core.llm.clients import get_instructor_anthropic, google_client
from src.core.observability import observe
from src.core.schemas.intent import IntentDetectionResult

logger = logging.getLogger(__name__)

INTENT_DETECTION_PROMPT = """Определи намерение пользователя из сообщения.

Возможные интенты:
- add_expense: запись расхода ("заправился на 50", "купил продукты 87.50")
- add_income: запись дохода ("заработал 185", "получил зарплату")
- scan_receipt: пользователь отправил фото чека
- scan_document: пользователь отправил фото документа, инвойса, \
rate confirmation, или другого изображения
- query_stats: запрос статистики ("сколько потратил за неделю", "сравни с прошлым месяцем")
- query_report: генерация PDF-отчёта ("отчёт", "report", \
"покажи итоги", "PDF", "сгенерируй отчёт", "месячный отчёт")
- correct_category: исправление категории ("это не продукты, а бензин")
- undo_last: отмена последней операции ("отмени последнюю", "undo", "верни обратно")
- mark_paid: отметить груз как оплаченный ("оплатили груз", \
"mark paid", "груз оплачен", "получил оплату за рейс")
- onboarding: первый контакт, знакомство
- set_budget: установить бюджет или лимит ("бюджет на продукты \
30000", "лимит 5000 в неделю", "set budget")
- add_recurring: добавить регулярный платёж ("подписка", \
"recurring", "каждый месяц плачу", "аренда 50000")
- complex_query: сложный аналитический запрос ("сложный анализ", \
"сравни с бюджетом", "полный отчёт", \
"анализ трат за 3 месяца", "что происходит с финансами")
- general_chat: общий вопрос, не связанный с финансами напрямую

Ответь ТОЛЬКО валидным JSON:
{
  "intent": "имя_интента",
  "confidence": 0.0-1.0,
  "data": {
    "amount": число или null,
    "merchant": "название" или null,
    "category": "предполагаемая категория" или null,
    "scope": "business" или "family" или null,
    "date": "YYYY-MM-DD" или null,
    "description": "описание" или null,
    "currency": "валюта" или null
  },
  "response": "краткий ответ для пользователя"
}"""


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

    # Primary: Gemini Flash
    try:
        return await _detect_with_gemini(user_prompt, language)
    except Exception as e:
        logger.warning("Gemini intent detection failed: %s, falling back to Claude", e)

    # Fallback: Claude Haiku
    try:
        return await _detect_with_claude(user_prompt, language)
    except Exception as e:
        logger.error("Claude intent detection also failed: %s", e)
        return IntentDetectionResult(
            intent="general_chat",
            confidence=0.5,
            response="Не удалось определить намерение. Попробуйте переформулировать.",
        )


@observe(name="intent_gemini")
async def _detect_with_gemini(user_prompt: str, language: str) -> IntentDetectionResult:
    client = google_client()
    response = await client.aio.models.generate_content(
        model="gemini-3-flash-preview",
        contents=f"{INTENT_DETECTION_PROMPT}\n\nЯзык ответа: {language}\n\n{user_prompt}",
        config={"response_mime_type": "application/json"},
    )
    data = json.loads(response.text)
    return IntentDetectionResult(**data)


@observe(name="intent_claude")
async def _detect_with_claude(user_prompt: str, language: str) -> IntentDetectionResult:
    client = get_instructor_anthropic()
    result = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        response_model=IntentDetectionResult,
        max_retries=2,
        system=f"{INTENT_DETECTION_PROMPT}\n\nЯзык ответа: {language}",
        messages=[{"role": "user", "content": user_prompt}],
    )
    return result
