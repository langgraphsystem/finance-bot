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
    messages: list[dict[str, str]] | None = None,
    max_tokens: int = 1024,
    *,
    prompt: str | None = None,
) -> str:
    """Unified LLM call — routes to the correct SDK based on model ID.

    Supports OpenAI (gpt-*), Anthropic (claude-*), and Google (gemini-*) models.
    Returns the generated text content.

    Pass either ``messages`` (list of dicts) or ``prompt`` (single string).
    """
    if prompt is not None and messages is None:
        messages = [{"role": "user", "content": prompt}]
    if not messages:
        raise ValueError("Either messages or prompt is required")

    from src.core.llm.prompts import PromptAdapter

    if model.startswith("gpt-"):
        client = openai_client()
        resp = await client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
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
        # Single message → pass as plain string; multi-turn → structured contents
        if len(messages) == 1:
            contents = messages[0]["content"]
        else:
            contents = [
                {
                    "role": ("user" if m["role"] == "user" else "model"),
                    "parts": [{"text": m["content"]}],
                }
                for m in messages
            ]
        resp = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
        return resp.text or ""
    else:
        raise ValueError(f"Unknown model prefix: {model}")
