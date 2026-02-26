"""Tests for pre/post model hooks."""

from src.core.hooks import (
    HookContext,
    HookRegistry,
    HookResult,
    get_hook_registry,
    routing_telemetry_hook,
    supervisor_pre_routing_hook,
)


def test_hook_registry_pre_routing():
    """Pre-routing hooks should run in order."""
    registry = HookRegistry()
    calls = []

    def hook1(ctx):
        calls.append("hook1")
        return None

    def hook2(ctx):
        calls.append("hook2")
        return None

    registry.add_pre_routing(hook1)
    registry.add_pre_routing(hook2)

    ctx = HookContext(user_id="test", text="hello")
    result = registry.run_pre_routing(ctx)

    assert result.should_continue is True
    assert calls == ["hook1", "hook2"]


def test_hook_registry_pre_routing_short_circuit():
    """Pre-routing hook can short-circuit by returning should_continue=False."""
    registry = HookRegistry()
    calls = []

    def blocker(ctx):
        calls.append("blocker")
        return HookResult(should_continue=False)

    def never_called(ctx):
        calls.append("never")
        return None

    registry.add_pre_routing(blocker)
    registry.add_pre_routing(never_called)

    ctx = HookContext(user_id="test", text="hello")
    result = registry.run_pre_routing(ctx)

    assert result.should_continue is False
    assert calls == ["blocker"]


def test_hook_registry_post_routing():
    """Post-routing hooks should run and can modify results."""
    registry = HookRegistry()

    def add_metadata(ctx, result):
        return {"original": result, "enriched": True}

    registry.add_post_routing(add_metadata)

    ctx = HookContext(user_id="test", text="hello")
    result = registry.run_post_routing(ctx, "original_result")

    assert result == {"original": "original_result", "enriched": True}


def test_hook_registry_failing_hook_continues():
    """A failing hook should be logged and skipped, not crash."""
    registry = HookRegistry()
    calls = []

    def failing_hook(ctx):
        raise ValueError("Intentional error")

    def ok_hook(ctx):
        calls.append("ok")
        return None

    registry.add_pre_routing(failing_hook)
    registry.add_pre_routing(ok_hook)

    ctx = HookContext(user_id="test", text="hello")
    result = registry.run_pre_routing(ctx)

    assert result.should_continue is True
    assert calls == ["ok"]


def test_supervisor_pre_routing_hook_resolves_domain():
    """Supervisor hook should resolve domain via keyword matching."""
    ctx = HookContext(user_id="test", text="add expense 50 lunch")
    result = supervisor_pre_routing_hook(ctx)

    # Hook returns None (does not block)
    assert result is None
    # Domain should be resolved
    assert ctx.domain == "finance"
    assert "supervisor_skills" in ctx.metadata
    assert len(ctx.metadata["supervisor_skills"]) > 0
    assert "supervisor_resolve_ms" in ctx.metadata


def test_supervisor_pre_routing_hook_no_match():
    """Supervisor hook should leave domain as None when no match."""
    ctx = HookContext(user_id="test", text="xyzzy plugh")
    supervisor_pre_routing_hook(ctx)

    assert ctx.domain is None
    assert ctx.metadata["supervisor_skills"] == []


def test_routing_telemetry_hook():
    """Telemetry hook should not crash and return None."""
    ctx = HookContext(
        user_id="test-user-123",
        text="hello",
        domain="general",
        intent="general_chat",
        agent="onboarding",
        confidence=0.9,
    )
    result = routing_telemetry_hook(ctx, "some_result")
    assert result is None  # telemetry hook doesn't modify result


def test_get_hook_registry_returns_singleton():
    """Global registry should have default hooks registered."""
    registry = get_hook_registry()
    assert isinstance(registry, HookRegistry)
    # Should have at least supervisor pre-routing and telemetry post-routing
    assert len(registry._pre_routing) >= 1
    assert len(registry._post_routing) >= 1


def test_hook_context_defaults():
    """HookContext should have sensible defaults."""
    ctx = HookContext(user_id="u1", text="test")
    assert ctx.domain is None
    assert ctx.intent is None
    assert ctx.agent is None
    assert ctx.confidence == 0.0
    assert ctx.metadata == {}


def test_pre_routing_modifies_text():
    """Pre-routing hook can modify the input text."""
    registry = HookRegistry()

    def normalizer(ctx):
        return HookResult(modified_text=ctx.text.lower().strip())

    registry.add_pre_routing(normalizer)

    ctx = HookContext(user_id="test", text="  HELLO WORLD  ")
    registry.run_pre_routing(ctx)

    assert ctx.text == "hello world"


def test_pre_model_hooks():
    """Pre-model hooks should work the same way as pre-routing."""
    registry = HookRegistry()
    calls = []

    def model_guard(ctx):
        calls.append("guard")
        return None

    registry.add_pre_model(model_guard)

    ctx = HookContext(user_id="test", text="hello")
    result = registry.run_pre_model(ctx)

    assert result.should_continue is True
    assert calls == ["guard"]


def test_post_model_hooks():
    """Post-model hooks should work and can modify results."""
    registry = HookRegistry()

    def sanitizer(ctx, result):
        if isinstance(result, str):
            return result.replace("bad_word", "***")
        return None

    registry.add_post_model(sanitizer)

    ctx = HookContext(user_id="test", text="hello")
    result = registry.run_post_model(ctx, "this has bad_word in it")

    assert result == "this has *** in it"
