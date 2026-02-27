"""Compare general chat responses from 3 LLMs: Claude Haiku, GPT-5.2, Gemini 3 Flash."""

import asyncio
import os
import sys
import time

# Load .env BEFORE importing anything else (override system env vars)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from src.core.llm.clients import anthropic_client, google_client, openai_client

SYSTEM_PROMPT = """Ты — финансовый помощник в Telegram-боте.
Отвечай на русском языке. Будь дружелюбным и кратким (2-4 предложения).
Если вопрос не связан с финансами, можешь ответить кратко и мягко
перевести тему к финансовым возможностям бота."""

QUESTIONS = [
    "Привет! Как дела?",
    "Что ты умеешь?",
    "Какая погода сегодня?",
    "Посоветуй как сэкономить деньги",
    "Расскажи анекдот",
]


async def ask_claude(question: str) -> tuple[str, float]:
    client = anthropic_client()
    start = time.time()
    resp = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )
    elapsed = time.time() - start
    return resp.content[0].text, elapsed


async def ask_gpt(question: str) -> tuple[str, float]:
    client = openai_client()
    start = time.time()
    resp = await client.responses.create(
        model="gpt-5.2",
        instructions=SYSTEM_PROMPT,
        input=question,
        max_output_tokens=256,
    )
    elapsed = time.time() - start
    return resp.output_text, elapsed


async def ask_gemini(question: str) -> tuple[str, float]:
    client = google_client()
    start = time.time()
    resp = await client.aio.models.generate_content(
        model="gemini-3-flash-preview",
        contents=f"{SYSTEM_PROMPT}\n\nПользователь: {question}",
    )
    elapsed = time.time() - start
    return resp.text, elapsed


async def compare(question: str) -> None:
    print(f"\n{'='*70}")
    print(f"ВОПРОС: {question}")
    print(f"{'='*70}")

    results = await asyncio.gather(
        ask_claude(question),
        ask_gpt(question),
        ask_gemini(question),
        return_exceptions=True,
    )

    models = ["Claude Haiku 4.5", "GPT-5.2", "Gemini 3 Flash"]
    for model, result in zip(models, results):
        print(f"\n--- {model} ---")
        if isinstance(result, Exception):
            print(f"  ОШИБКА: {result}")
        else:
            text, elapsed = result
            print(f"  [{elapsed:.1f}s] {text}")


async def main() -> None:
    print("Сравнение ответов 3 LLM на общие вопросы")
    print(f"System prompt: {SYSTEM_PROMPT[:80]}...")

    for q in QUESTIONS:
        await compare(q)

    print(f"\n{'='*70}")
    print("ГОТОВО")


if __name__ == "__main__":
    asyncio.run(main())
