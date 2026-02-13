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
