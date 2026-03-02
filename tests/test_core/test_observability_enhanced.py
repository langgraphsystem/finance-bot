"""Tests for enhanced observability — LLMUsage, extract functions, traced_llm_call."""

from unittest.mock import MagicMock, patch

from src.core.observability import (
    LLMUsage,
    extract_usage_anthropic,
    extract_usage_gemini,
    extract_usage_openai,
    traced_llm_call,
    update_trace_user,
)


def test_llm_usage_defaults():
    usage = LLMUsage()
    assert usage.tokens_input == 0
    assert usage.tokens_output == 0
    assert usage.cache_read_tokens == 0
    assert usage.cache_hit is False
    assert usage.duration_ms == 0


def test_llm_usage_cache_hit():
    usage = LLMUsage(cache_read_tokens=100)
    assert usage.cache_hit is True


def test_extract_usage_anthropic():
    resp = MagicMock()
    resp.usage.input_tokens = 500
    resp.usage.output_tokens = 200
    resp.usage.cache_read_input_tokens = 400
    resp.usage.cache_creation_input_tokens = 100
    resp.model = "claude-sonnet-4-6"

    usage = extract_usage_anthropic(resp)
    assert usage.tokens_input == 500
    assert usage.tokens_output == 200
    assert usage.cache_read_tokens == 400
    assert usage.cache_creation_tokens == 100
    assert usage.cache_hit is True
    assert usage.model == "claude-sonnet-4-6"


def test_extract_usage_anthropic_no_usage():
    resp = MagicMock(spec=[])
    usage = extract_usage_anthropic(resp)
    assert usage.tokens_input == 0


def test_extract_usage_openai():
    resp = MagicMock()
    resp.usage.prompt_tokens = 300
    resp.usage.completion_tokens = 150
    resp.usage.prompt_tokens_details.cached_tokens = 200
    resp.model = "gpt-5.2"

    usage = extract_usage_openai(resp)
    assert usage.tokens_input == 300
    assert usage.tokens_output == 150
    assert usage.cache_read_tokens == 200
    assert usage.model == "gpt-5.2"


def test_extract_usage_openai_no_details():
    resp = MagicMock()
    resp.usage.prompt_tokens = 300
    resp.usage.completion_tokens = 150
    resp.usage.prompt_tokens_details = None
    resp.model = "gpt-5.2"

    usage = extract_usage_openai(resp)
    assert usage.cache_read_tokens == 0


def test_extract_usage_gemini():
    resp = MagicMock()
    resp.usage_metadata.prompt_token_count = 400
    resp.usage_metadata.candidates_token_count = 100
    resp.usage_metadata.cached_content_token_count = 0

    usage = extract_usage_gemini(resp)
    assert usage.tokens_input == 400
    assert usage.tokens_output == 100
    assert usage.cache_hit is False


def test_extract_usage_gemini_no_metadata():
    resp = MagicMock(spec=[])
    usage = extract_usage_gemini(resp)
    assert usage.tokens_input == 0


async def test_traced_llm_call_yields_usage():
    with patch("src.core.observability.get_langfuse", return_value=None):
        async with traced_llm_call("test_call", model="test-model") as usage:
            usage.tokens_input = 100
            usage.tokens_output = 50

        assert usage.tokens_input == 100
        assert usage.tokens_output == 50
        assert usage.duration_ms >= 0


async def test_traced_llm_call_with_langfuse():
    mock_langfuse = MagicMock()
    mock_trace = MagicMock()
    mock_span = MagicMock()
    mock_langfuse.trace.return_value = mock_trace
    mock_trace.span.return_value = mock_span

    with patch("src.core.observability.get_langfuse", return_value=mock_langfuse):
        async with traced_llm_call(
            "test_call", user_id="u1", model="claude-sonnet-4-6", intent="add_expense"
        ) as usage:
            usage.tokens_input = 500
            usage.tokens_output = 200
            usage.cache_read_tokens = 300

    mock_langfuse.trace.assert_called_once()
    mock_span.end.assert_called_once()
    call_kwargs = mock_span.end.call_args[1]
    assert call_kwargs["metadata"]["tokens_input"] == 500
    assert call_kwargs["metadata"]["cache_hit"] is True


def test_update_trace_user_no_langfuse():
    # Should not raise when Langfuse is not configured
    with patch("src.core.observability.settings") as mock_settings:
        mock_settings.langfuse_public_key = ""
        update_trace_user("user123")
