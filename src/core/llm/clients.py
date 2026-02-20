import instructor
from anthropic import AsyncAnthropic
from google import genai
from openai import AsyncOpenAI

from src.core.config import settings


def get_anthropic_client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


def get_google_client() -> genai.Client:
    return genai.Client(api_key=settings.google_ai_api_key)


def get_instructor_anthropic():
    """Instructor-wrapped Anthropic client for structured output."""
    return instructor.from_anthropic(get_anthropic_client())


def get_instructor_openai():
    """Instructor-wrapped OpenAI client for structured output."""
    return instructor.from_openai(get_openai_client())


# Singleton clients (lazy initialization)
_anthropic: AsyncAnthropic | None = None
_openai: AsyncOpenAI | None = None
_google: genai.Client | None = None


def anthropic_client() -> AsyncAnthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = get_anthropic_client()
    return _anthropic


def openai_client() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = get_openai_client()
    return _openai


def google_client() -> genai.Client:
    global _google
    if _google is None:
        _google = get_google_client()
    return _google


async def generate_text(
    model: str,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int = 1024,
) -> str:
    """Unified LLM call — routes to the correct SDK based on model ID.

    Supports OpenAI (gpt-*), Anthropic (claude-*), and Google (gemini-*) models.
    Returns the generated text content.
    """
    from src.core.llm.prompts import PromptAdapter

    if model.startswith("gpt-"):
        client = openai_client()
        resp = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            **PromptAdapter.for_openai(system, messages),
        )
        return resp.choices[0].message.content or ""
    elif model.startswith("claude-"):
        client = anthropic_client()
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            **PromptAdapter.for_claude(system, messages),
        )
        return resp.content[0].text
    elif model.startswith("gemini-"):
        from google.genai import types

        client = google_client()
        resp = await client.aio.models.generate_content(
            model=model,
            contents=messages[-1]["content"] if messages else "",
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
        return resp.text or ""
    else:
        raise ValueError(f"Unknown model prefix: {model}")
