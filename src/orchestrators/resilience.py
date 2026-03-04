"""Orchestrator resilience — timeout, retry, and dead-letter queue.

Provides decorators for LangGraph node functions:
- ``@with_timeout(seconds)`` — cancels node if it exceeds time limit.
- ``@with_retry(max_retries, backoff_base)`` — exponential backoff retry.
- ``save_to_dlq()`` — persist failed graph state for later recovery.
"""

import asyncio
import functools
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from src.core.observability import observe

logger = logging.getLogger(__name__)

T = TypeVar("T")


def with_timeout(seconds: float) -> Callable:
    """Decorator: cancel a LangGraph node if it exceeds *seconds*.

    On timeout, raises ``asyncio.TimeoutError`` which the graph
    catches as a regular exception.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)
            except TimeoutError:
                node_name = func.__name__
                logger.warning(
                    "Node '%s' timed out after %.1fs", node_name, seconds
                )
                raise

        return wrapper

    return decorator


def with_retry(
    max_retries: int = 2,
    backoff_base: float = 1.0,
    retryable: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator: retry a LangGraph node with exponential backoff.

    Parameters
    ----------
    max_retries:
        How many times to retry *after* the initial failure.
    backoff_base:
        Base seconds for exponential backoff (``base * 2**attempt``).
    retryable:
        Tuple of exception types to retry on.  Defaults to ``Exception``
        (excluding ``KeyboardInterrupt`` and ``SystemExit``).
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            node_name = func.__name__
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        delay = backoff_base * (2**attempt)
                        logger.warning(
                            "Node '%s' failed (attempt %d/%d), retrying in %.1fs: %s",
                            node_name,
                            attempt + 1,
                            max_retries + 1,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "Node '%s' exhausted %d retries: %s",
                            node_name,
                            max_retries + 1,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


@observe(name="save_to_dlq")
async def save_to_dlq(
    graph_name: str,
    thread_id: str,
    user_id: str,
    family_id: str,
    error: str,
    state: dict[str, Any] | None = None,
) -> str | None:
    """Persist a failed graph execution to the dead-letter queue.

    Returns the DLQ record ID on success, ``None`` on failure.
    """
    try:
        from src.core.db import async_session
        from src.core.models.orchestrator_dlq import OrchestratorDLQ

        dlq_id = uuid.uuid4()
        record = OrchestratorDLQ(
            id=dlq_id,
            graph_name=graph_name,
            thread_id=thread_id,
            user_id=uuid.UUID(user_id),
            family_id=uuid.UUID(family_id),
            error=error[:2000],  # cap error text
            state=_sanitize_state(state),
            retried=False,
            created_at=datetime.now(UTC),
        )
        async with async_session() as session:
            session.add(record)
            await session.commit()
        logger.info(
            "DLQ record created: graph=%s thread=%s id=%s",
            graph_name, thread_id, dlq_id,
        )
        return str(dlq_id)
    except Exception as e:
        logger.error("Failed to save to DLQ: %s", e)
        return None


def _sanitize_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove non-serializable values from graph state before DLQ storage."""
    if state is None:
        return None
    sanitized: dict[str, Any] = {}
    for key, value in state.items():
        if key.startswith("__"):
            continue
        if isinstance(value, str | int | float | bool | None):
            sanitized[key] = value
        elif isinstance(value, list | dict):
            try:
                import json

                json.dumps(value)
                sanitized[key] = value
            except (TypeError, ValueError):
                sanitized[key] = str(value)[:500]
        else:
            sanitized[key] = str(value)[:500]
    return sanitized
