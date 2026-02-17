"""Langfuse observability — tracing and monitoring.

When LANGFUSE_PUBLIC_KEY is not set, provides a no-op `observe` decorator
so the rest of the codebase doesn't need conditional imports.
"""

import logging
from collections.abc import Callable
from functools import wraps

from src.core.config import settings

logger = logging.getLogger(__name__)

_langfuse = None

# Suppress Langfuse SDK's repeated WARNING about missing keys
logging.getLogger("langfuse").setLevel(logging.ERROR)


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


__all__ = ["observe", "get_langfuse"]
