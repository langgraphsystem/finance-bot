"""Tests for deepagents middleware."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage, SystemMessage

from src.orchestrators.deep.middleware import (
    FinanceBotMemoryMiddleware,
    ObservabilityMiddleware,
    SessionContextMiddleware,
)


async def test_session_context_middleware_injects_context(sample_context):
    """SessionContextMiddleware injects user context into system message."""
    mw = SessionContextMiddleware(sample_context)

    state = {
        "messages": [
            SystemMessage(content="You are an assistant."),
            HumanMessage(content="Hello"),
        ]
    }

    result = await mw.abefore_model(state, runtime=None)

    assert result is not None
    system_msg = result["messages"][0]
    assert "[User Context]" in system_msg.content
    assert sample_context.language in system_msg.content
    assert sample_context.currency in system_msg.content


async def test_session_context_middleware_includes_business_type(sample_context):
    """SessionContextMiddleware includes business_type when present."""
    mw = SessionContextMiddleware(sample_context)

    state = {
        "messages": [
            SystemMessage(content="Base prompt"),
            HumanMessage(content="test"),
        ]
    }

    result = await mw.abefore_model(state, runtime=None)
    assert result is not None
    assert "trucker" in result["messages"][0].content


async def test_session_context_middleware_no_system_msg(sample_context):
    """SessionContextMiddleware returns None when no system message."""
    mw = SessionContextMiddleware(sample_context)

    state = {
        "messages": [
            HumanMessage(content="Hello"),
        ]
    }

    result = await mw.abefore_model(state, runtime=None)
    assert result is None


async def test_memory_middleware_loads_memories(sample_context):
    """FinanceBotMemoryMiddleware loads Mem0 memories and history."""
    config = {"mem": "mappings", "hist": 3, "sql": False, "sum": False}
    mw = FinanceBotMemoryMiddleware(sample_context, config)

    state = {
        "messages": [
            SystemMessage(content="System prompt"),
            HumanMessage(content="test"),
        ]
    }

    with (
        patch("src.core.memory.mem0_client") as mock_mem0,
        patch("src.core.memory.sliding_window") as mock_sw,
    ):
        mock_mem0.search = AsyncMock(return_value=["User prefers Shell gas station"])
        mock_sw.get_recent = AsyncMock(
            return_value=[{"role": "user", "content": "previous message"}]
        )

        result = await mw.abefore_model(state, runtime=None)

    assert result is not None
    # Should have system + memory + human messages
    assert len(result["messages"]) == 3
    memory_msg = result["messages"][1]
    assert "[Memory Context]" in memory_msg.content


async def test_memory_middleware_skips_when_no_config(sample_context):
    """FinanceBotMemoryMiddleware skips loading when config disables memory."""
    config = {"mem": False, "hist": 0, "sql": False, "sum": False}
    mw = FinanceBotMemoryMiddleware(sample_context, config)

    state = {
        "messages": [
            SystemMessage(content="System prompt"),
            HumanMessage(content="test"),
        ]
    }

    result = await mw.abefore_model(state, runtime=None)
    # No memory to inject → return None
    assert result is None


async def test_observability_middleware_passthrough():
    """ObservabilityMiddleware passes through when Langfuse not configured."""
    mw = ObservabilityMiddleware("finance")

    mock_handler = AsyncMock(return_value="response")
    mock_request = MagicMock()

    with patch("src.core.observability.get_langfuse", return_value=None):
        result = await mw.awrap_model_call(mock_request, mock_handler)

    mock_handler.assert_awaited_once()
    assert result == "response"


def test_middleware_tools_empty():
    """All middleware report empty tools lists."""
    ctx = MagicMock()
    assert SessionContextMiddleware(ctx).tools == []
    assert FinanceBotMemoryMiddleware(ctx, {}).tools == []
    assert ObservabilityMiddleware("test").tools == []
