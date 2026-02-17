from typing import Any

SYSTEM_PROMPT_TEMPLATE = """<role>
Ты — AI-помощник для финансов и жизни в Telegram-боте.
Ты помогаешь {user_name} ({business_type}) вести учёт доходов, расходов,
а также заметки, питание, настроение и планирование дня.
Отвечай на {language}. Валюта по умолчанию: {currency}.
</role>

<rules>
- Отвечай коротко (1-3 предложения) и по делу
- Финансовые суммы — ТОЧНЫЕ числа, НИКОГДА не округляй
- Всегда указывай: сумму, категорию, дату
- Если уверенность < 0.8 — спроси подтверждение через inline-кнопки
- Если пользователь поправляет категорию — запомни навсегда
- НИКОГДА не выдумывай транзакции или суммы
- НИКОГДА не давай инвестиционных советов
- Форматирование: HTML-теги для Telegram (<b>жирный</b>, <i>курсив</i>).
  НЕ используй Markdown (**, *, ```)
</rules>

<categories>
{formatted_categories}
</categories>

<user_memory>
{mem0_memories}
</user_memory>

<current_context>
{analytics_summary}
</current_context>"""


class PromptAdapter:
    """Adapts prompts for different LLM providers with prompt caching."""

    @staticmethod
    def for_claude(
        system: str,
        messages: list[dict[str, str]],
        cache: bool = True,
    ) -> dict[str, Any]:
        """Format for Anthropic Claude API with 1h TTL prompt caching."""
        system_blocks = [{"type": "text", "text": system}]
        if cache:
            system_blocks[0]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}

        return {
            "system": system_blocks,
            "messages": messages,
        }

    @staticmethod
    def for_openai(
        system: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Format for OpenAI API (auto-caching)."""
        return {
            "messages": [
                {"role": "system", "content": system},
                *messages,
            ],
        }

    @staticmethod
    def for_gemini(
        system: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Format for Google Gemini API."""
        return {
            "system_instruction": system,
            "contents": [
                {
                    "role": (m["role"] if m["role"] != "assistant" else "model"),
                    "parts": [{"text": m["content"]}],
                }
                for m in messages
            ],
        }
