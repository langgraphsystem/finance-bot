"""Pre/Post model hooks for the routing pipeline.

Lightweight hook points that run before and after key stages:
- pre_routing: domain resolution, input validation
- post_routing: telemetry, response quality checks
- pre_model: guardrails, context budget enforcement
- post_model: output sanitization, metrics

Hooks are registered at startup and run synchronously in order.
Any hook can short-circuit by returning a result (for pre-hooks)
or modify the result (for post-hooks).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.core.observability import observe

logger = logging.getLogger(__name__)


@dataclass
class HookContext:
    """Context passed to all hooks."""

    user_id: str
    text: str
    domain: str | None = None
    intent: str | None = None
    agent: str | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    """Result from a hook execution."""

    should_continue: bool = True
    modified_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Hook function signatures
PreHookFn = Callable[[HookContext], HookResult | None]
PostHookFn = Callable[[HookContext, Any], Any]


class HookRegistry:
    """Registry for pre/post hooks in the routing pipeline."""

    def __init__(self) -> None:
        self._pre_routing: list[PreHookFn] = []
        self._post_routing: list[PostHookFn] = []
        self._pre_model: list[PreHookFn] = []
        self._post_model: list[PostHookFn] = []

    def add_pre_routing(self, fn: PreHookFn) -> None:
        """Register a hook that runs before domain/intent routing."""
        self._pre_routing.append(fn)

    def add_post_routing(self, fn: PostHookFn) -> None:
        """Register a hook that runs after routing completes."""
        self._post_routing.append(fn)

    def add_pre_model(self, fn: PreHookFn) -> None:
        """Register a hook that runs before LLM model calls."""
        self._pre_model.append(fn)

    def add_post_model(self, fn: PostHookFn) -> None:
        """Register a hook that runs after LLM model calls."""
        self._post_model.append(fn)

    @observe(name="run_pre_routing_hooks")
    def run_pre_routing(self, ctx: HookContext) -> HookResult:
        """Run all pre-routing hooks. Returns combined result."""
        for fn in self._pre_routing:
            try:
                result = fn(ctx)
                if result and not result.should_continue:
                    return result
                if result and result.modified_text:
                    ctx.text = result.modified_text
            except Exception as e:
                logger.warning("Pre-routing hook %s failed: %s", fn.__name__, e)
        return HookResult(should_continue=True)

    @observe(name="run_post_routing_hooks")
    def run_post_routing(self, ctx: HookContext, result: Any) -> Any:
        """Run all post-routing hooks. Returns potentially modified result."""
        for fn in self._post_routing:
            try:
                modified = fn(ctx, result)
                if modified is not None:
                    result = modified
            except Exception as e:
                logger.warning("Post-routing hook %s failed: %s", fn.__name__, e)
        return result

    @observe(name="run_pre_model_hooks")
    def run_pre_model(self, ctx: HookContext) -> HookResult:
        """Run all pre-model hooks."""
        for fn in self._pre_model:
            try:
                result = fn(ctx)
                if result and not result.should_continue:
                    return result
            except Exception as e:
                logger.warning("Pre-model hook %s failed: %s", fn.__name__, e)
        return HookResult(should_continue=True)

    @observe(name="run_post_model_hooks")
    def run_post_model(self, ctx: HookContext, result: Any) -> Any:
        """Run all post-model hooks."""
        for fn in self._post_model:
            try:
                modified = fn(ctx, result)
                if modified is not None:
                    result = modified
            except Exception as e:
                logger.warning("Post-model hook %s failed: %s", fn.__name__, e)
        return result


# ── Built-in hooks ──────────────────────────────────────────────────


def routing_telemetry_hook(ctx: HookContext, result: Any) -> None:
    """Post-routing hook: log routing decisions for telemetry."""
    logger.info(
        "routing_telemetry: user=%s domain=%s intent=%s agent=%s confidence=%.2f",
        ctx.user_id[:8] if ctx.user_id else "?",
        ctx.domain or "?",
        ctx.intent or "?",
        ctx.agent or "?",
        ctx.confidence,
    )


def supervisor_pre_routing_hook(ctx: HookContext) -> HookResult | None:
    """Pre-routing hook: attach supervisor domain resolution to context."""
    from src.core.supervisor import resolve_domain_and_skills

    start = time.monotonic()
    domain, skills = resolve_domain_and_skills(ctx.text)
    elapsed_ms = (time.monotonic() - start) * 1000

    ctx.domain = domain
    ctx.metadata["supervisor_skills"] = skills
    ctx.metadata["supervisor_resolve_ms"] = round(elapsed_ms, 1)

    if domain:
        logger.debug(
            "Supervisor resolved domain=%s (%d skills) in %.1fms",
            domain,
            len(skills),
            elapsed_ms,
        )
    return None


# ── Global registry ─────────────────────────────────────────────────

_hook_registry: HookRegistry | None = None


def get_hook_registry() -> HookRegistry:
    """Get or create the global hook registry with default hooks."""
    global _hook_registry
    if _hook_registry is None:
        _hook_registry = HookRegistry()
        _hook_registry.add_pre_routing(supervisor_pre_routing_hook)
        _hook_registry.add_post_routing(routing_telemetry_hook)
    return _hook_registry
