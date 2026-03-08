"""Langfuse observability — tracing and monitoring.

When LANGFUSE_PUBLIC_KEY is not set, provides a no-op `observe` decorator
so the rest of the codebase doesn't need conditional imports.

Enhanced with:
- traced_llm_call() context manager for per-call token/cost/cache tracking
- update_trace_user() for tagging traces with user_id
- LLMUsage dataclass for structured token usage extraction
"""

import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import wraps
from numbers import Integral
from typing import Any

from src.core.config import settings

logger = logging.getLogger(__name__)

_langfuse = None

# Suppress Langfuse SDK's repeated WARNING about missing keys
logging.getLogger("langfuse").setLevel(logging.ERROR)


@dataclass
class LLMUsage:
    """Structured token usage from an LLM call."""

    tokens_input: int = 0
    tokens_output: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    model: str = ""
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0


def extract_usage_anthropic(response: Any) -> LLMUsage:
    """Extract token usage from Anthropic response."""
    usage = getattr(response, "usage", None)
    if not usage:
        return LLMUsage()
    return LLMUsage(
        tokens_input=getattr(usage, "input_tokens", 0),
        tokens_output=getattr(usage, "output_tokens", 0),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0),
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0),
        model=getattr(response, "model", ""),
    )


def extract_usage_openai(response: Any) -> LLMUsage:
    """Extract token usage from OpenAI response.

    Handles both Chat Completions API (prompt_tokens / completion_tokens)
    and Responses API (input_tokens / output_tokens).
    """
    usage = getattr(response, "usage", None)
    if not usage:
        return LLMUsage()

    def _int_attr(obj: Any, attr: str) -> int | None:
        value = getattr(obj, attr, None)
        if isinstance(value, Integral):
            return int(value)
        return None

    # Responses API uses input_tokens/output_tokens;
    # Chat Completions uses prompt_tokens/completion_tokens.
    tokens_input = _int_attr(usage, "input_tokens")
    if tokens_input is None:
        tokens_input = _int_attr(usage, "prompt_tokens") or 0
    tokens_output = _int_attr(usage, "output_tokens")
    if tokens_output is None:
        tokens_output = _int_attr(usage, "completion_tokens") or 0

    cached = 0
    # Responses API: input_tokens_details.cached_tokens
    details = getattr(usage, "input_tokens_details", None)
    cached = _int_attr(details, "cached_tokens") or 0
    if not cached:
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        cached = _int_attr(prompt_details, "cached_tokens") or 0

    return LLMUsage(
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        cache_read_tokens=cached,
        model=getattr(response, "model", ""),
    )


def extract_usage_gemini(response: Any) -> LLMUsage:
    """Extract token usage from Gemini response."""
    meta = getattr(response, "usage_metadata", None)
    if not meta:
        return LLMUsage()
    return LLMUsage(
        tokens_input=getattr(meta, "prompt_token_count", 0),
        tokens_output=getattr(meta, "candidates_token_count", 0),
        cache_read_tokens=getattr(meta, "cached_content_token_count", 0),
    )


def get_langfuse():
    global _langfuse
    if _langfuse is None and settings.langfuse_public_key:
        try:
            from langfuse import Langfuse

            _langfuse = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
        except Exception as e:
            logger.warning("Failed to init Langfuse: %s", e)
    return _langfuse


def update_trace_user(user_id: str) -> None:
    """Tag the current Langfuse trace with a user_id."""
    if not settings.langfuse_public_key:
        return
    try:
        from langfuse import langfuse_context

        langfuse_context.update_current_trace(user_id=user_id)
    except Exception:
        pass  # Non-critical, don't break the flow


@asynccontextmanager
async def traced_llm_call(
    name: str,
    *,
    user_id: str = "",
    model: str = "",
    intent: str = "",
    prompt_version: str = "",
    metadata: dict[str, Any] | None = None,
):
    """Context manager wrapping an LLM call with Langfuse span + timing.

    Yields an LLMUsage object that the caller populates after the API call.
    On exit, logs the span to Langfuse with token counts and cache metrics.

    Usage:
        async with traced_llm_call("generate_text", model="claude-sonnet-4-6") as usage:
            resp = await client.messages.create(...)
            usage_data = extract_usage_anthropic(resp)
            usage.tokens_input = usage_data.tokens_input
            usage.tokens_output = usage_data.tokens_output
            usage.cache_read_tokens = usage_data.cache_read_tokens
    """
    langfuse = get_langfuse()
    start = time.monotonic()
    usage = LLMUsage(model=model)
    span = None

    if langfuse:
        try:
            trace_meta = {"model": model, "intent": intent, **(metadata or {})}
            if prompt_version:
                trace_meta["prompt_version"] = prompt_version
            trace = langfuse.trace(
                name=name,
                user_id=user_id or None,
                metadata=trace_meta,
            )
            span = trace.span(name=f"{name}_llm", metadata={"model": model})
        except Exception:
            pass  # Non-critical

    try:
        yield usage
    finally:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        usage.duration_ms = elapsed_ms

        if span:
            try:
                span.end(
                    metadata={
                        "duration_ms": elapsed_ms,
                        "tokens_input": usage.tokens_input,
                        "tokens_output": usage.tokens_output,
                        "cache_read_tokens": usage.cache_read_tokens,
                        "cache_creation_tokens": usage.cache_creation_tokens,
                        "cache_hit": usage.cache_hit,
                        "model": usage.model or model,
                    },
                )
            except Exception:
                pass


if settings.langfuse_public_key:
    from langfuse import observe
else:

    def observe(name: str = "", **kwargs) -> Callable:  # type: ignore[misc]
        """No-op decorator when Langfuse is not configured."""

        def decorator(fn: Callable) -> Callable:
            if _is_coroutine(fn):

                @wraps(fn)
                async def async_wrapper(*args, **kw):
                    return await fn(*args, **kw)

                return async_wrapper
            else:

                @wraps(fn)
                def sync_wrapper(*args, **kw):
                    return fn(*args, **kw)

                return sync_wrapper

        return decorator


def _is_coroutine(fn: Callable) -> bool:
    """Check if a function is a coroutine function."""
    import asyncio

    return asyncio.iscoroutinefunction(fn)


__all__ = [
    "LLMUsage",
    "extract_usage_anthropic",
    "extract_usage_gemini",
    "extract_usage_openai",
    "get_langfuse",
    "observe",
    "traced_llm_call",
    "update_trace_user",
]
