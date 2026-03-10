"""Tests for LLM API improvements: Extended Thinking, Responses API,
Structured Outputs, Token Counting, Gemini thinking_level."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. Anthropic Extended Thinking
# ---------------------------------------------------------------------------


async def test_thinking_param_passed_to_claude():
    """generate_text() passes thinking dict to Claude messages.create()."""
    with patch("src.core.llm.clients.anthropic_client") as mock_factory:
        mock_client = AsyncMock()
        mock_factory.return_value = mock_client

        thinking_block = MagicMock()
        thinking_block.type = "thinking"
        thinking_block.thinking = "Let me reason..."

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Final answer"

        mock_client.messages.create.return_value = MagicMock(
            content=[thinking_block, text_block],
            usage=MagicMock(
                input_tokens=50,
                output_tokens=100,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
            model="claude-sonnet-4-6",
        )

        from src.core.llm.clients import generate_text

        result = await generate_text(
            model="claude-sonnet-4-6",
            system="You are helpful.",
            prompt="Explain quantum computing",
            max_tokens=4096,
            thinking={"type": "enabled", "budget_tokens": 2000},
        )

        assert result == "Final answer"
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2000}


async def test_thinking_adjusts_max_tokens():
    """generate_text() auto-increases max_tokens when thinking budget exceeds it."""
    with patch("src.core.llm.clients.anthropic_client") as mock_factory:
        mock_client = AsyncMock()
        mock_factory.return_value = mock_client

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "result"

        mock_client.messages.create.return_value = MagicMock(
            content=[text_block],
            usage=MagicMock(
                input_tokens=50, output_tokens=100,
                cache_read_input_tokens=0, cache_creation_input_tokens=0,
            ),
            model="claude-sonnet-4-6",
        )

        from src.core.llm.clients import generate_text

        await generate_text(
            model="claude-sonnet-4-6",
            system="test",
            prompt="test",
            max_tokens=500,
            thinking={"type": "enabled", "budget_tokens": 5000},
        )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] >= 5000 + 1024


async def test_no_thinking_uses_original_path():
    """generate_text() without thinking returns content[0].text as before."""
    with patch("src.core.llm.clients.anthropic_client") as mock_factory:
        mock_client = AsyncMock()
        mock_factory.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="direct result")],
            usage=MagicMock(
                input_tokens=10, output_tokens=20,
                cache_read_input_tokens=0, cache_creation_input_tokens=0,
            ),
            model="claude-sonnet-4-6",
        )

        from src.core.llm.clients import generate_text

        result = await generate_text(
            model="claude-sonnet-4-6",
            system="test",
            prompt="test",
        )
        assert result == "direct result"


# ---------------------------------------------------------------------------
# 2. Gemini thinking_level
# ---------------------------------------------------------------------------


async def test_thinking_level_passed_to_gemini():
    """generate_text() passes thinking_level to Gemini config."""
    with patch("src.core.llm.clients.google_client") as mock_factory:
        mock_client = MagicMock()
        mock_factory.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.text = "gemini result"
        mock_resp.usage_metadata = MagicMock(
            prompt_token_count=20, candidates_token_count=30,
            cached_content_token_count=0,
        )
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

        from src.core.llm.clients import generate_text

        result = await generate_text(
            model="gemini-3.1-flash-lite-preview",
            system="test",
            prompt="test",
            thinking_level="minimal",
        )

        assert result == "gemini result"
        call_kwargs = mock_client.aio.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        assert config.thinking_config is not None
        assert str(config.thinking_config.thinking_level).lower().endswith("minimal")


async def test_thinking_level_rejects_unsupported_gemini_model():
    """Gemini 3 Pro does not support the Flash-only thinking levels."""
    from src.core.llm.clients import generate_text

    with pytest.raises(ValueError, match="Allowed values: high, low"):
        await generate_text(
            model="gemini-3.1-pro-preview",
            system="test",
            prompt="test",
            thinking_level="minimal",
        )


async def test_gemini_no_thinking_level():
    """generate_text() without thinking_level omits ThinkingConfig."""
    with patch("src.core.llm.clients.google_client") as mock_factory:
        mock_client = MagicMock()
        mock_factory.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.text = "result"
        mock_resp.usage_metadata = MagicMock(
            prompt_token_count=10, candidates_token_count=15,
            cached_content_token_count=0,
        )
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

        from src.core.llm.clients import generate_text

        await generate_text(
            model="gemini-3.1-flash-lite-preview",
            system="test",
            prompt="test",
        )

        call_kwargs = mock_client.aio.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        assert config.thinking_config is None


# ---------------------------------------------------------------------------
# 3. OpenAI Responses API
# ---------------------------------------------------------------------------


async def test_generate_text_responses_calls_responses_api():
    """generate_text_responses() uses client.responses.create()."""
    with patch("src.core.llm.clients.openai_client") as mock_factory:
        mock_client = AsyncMock()
        mock_factory.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.output_text = "responses result"
        mock_resp.usage = MagicMock(
            input_tokens=30, output_tokens=40,
            input_tokens_details=None, output_tokens_details=None,
        )
        mock_client.responses.create.return_value = mock_resp

        from src.core.llm.clients import generate_text_responses

        result = await generate_text_responses(
            model="gpt-5.2",
            system="You are helpful.",
            prompt="Hello",
        )

        assert result == "responses result"
        mock_client.responses.create.assert_called_once()
        call_kwargs = mock_client.responses.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-5.2"
        assert call_kwargs["instructions"] == "You are helpful."
        input_msgs = call_kwargs["input"]
        assert input_msgs[0]["role"] == "user"


async def test_generate_text_responses_fallback_for_non_gpt():
    """generate_text_responses() falls back to generate_text() for non-gpt models."""
    with patch("src.core.llm.clients.anthropic_client") as mock_factory:
        mock_client = AsyncMock()
        mock_factory.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="claude fallback")],
            usage=MagicMock(
                input_tokens=10, output_tokens=20,
                cache_read_input_tokens=0, cache_creation_input_tokens=0,
            ),
            model="claude-sonnet-4-6",
        )

        from src.core.llm.clients import generate_text_responses

        result = await generate_text_responses(
            model="claude-sonnet-4-6",
            system="test",
            prompt="test",
        )
        assert result == "claude fallback"


# ---------------------------------------------------------------------------
# 4. OpenAI Structured Outputs
# ---------------------------------------------------------------------------


async def test_generate_structured_returns_parsed():
    """generate_structured() returns parsed Pydantic model instance."""
    with patch("src.core.llm.clients.openai_client") as mock_factory:
        mock_client = AsyncMock()
        mock_factory.return_value = mock_client

        parsed_obj = {"name": "Test", "value": 42}
        mock_resp = MagicMock()
        mock_resp.output_parsed = parsed_obj
        mock_resp.usage = MagicMock(
            input_tokens=20,
            output_tokens=30,
            input_tokens_details=None,
            output_tokens_details=None,
        )
        mock_client.responses.parse.return_value = mock_resp

        from src.core.llm.clients import generate_structured

        result = await generate_structured(
            model="gpt-5.2",
            system="Extract data",
            prompt="Name is Test, value is 42",
            response_format=dict,  # In real usage, a Pydantic model class
        )

        assert result == parsed_obj
        mock_client.responses.parse.assert_called_once()
        call_kwargs = mock_client.responses.parse.call_args.kwargs
        assert call_kwargs["text_format"] is dict
        assert call_kwargs["instructions"] == "Extract data"


async def test_generate_structured_rejects_non_gpt_model():
    """generate_structured() should fail fast for non-OpenAI models."""
    from src.core.llm.clients import generate_structured

    with pytest.raises(ValueError, match="only supports gpt-\\* models"):
        await generate_structured(
            model="claude-sonnet-4-6",
            system="Extract data",
            prompt="Name is Test",
            response_format=dict,
        )


# ---------------------------------------------------------------------------
# 5. Anthropic Token Counting
# ---------------------------------------------------------------------------


async def test_count_tokens_anthropic_basic():
    """count_tokens_anthropic() returns input token count."""
    with patch("src.core.llm.clients.anthropic_client") as mock_factory:
        mock_client = AsyncMock()
        mock_factory.return_value = mock_client
        mock_client.messages.count_tokens.return_value = MagicMock(input_tokens=1500)

        from src.core.llm.clients import count_tokens_anthropic

        result = await count_tokens_anthropic(
            model="claude-sonnet-4-6",
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hello world"}],
        )

        assert result == 1500
        call_kwargs = mock_client.messages.count_tokens.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert "tools" not in call_kwargs


async def test_count_tokens_anthropic_with_tools():
    """count_tokens_anthropic() converts and passes tools."""
    with patch("src.core.llm.clients.anthropic_client") as mock_factory:
        mock_client = AsyncMock()
        mock_factory.return_value = mock_client
        mock_client.messages.count_tokens.return_value = MagicMock(input_tokens=2500)

        from src.core.llm.clients import count_tokens_anthropic

        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

        result = await count_tokens_anthropic(
            model="claude-sonnet-4-6",
            system="You are helpful.",
            messages=[{"role": "user", "content": "What's the weather?"}],
            tools=tools,
        )

        assert result == 2500
        call_kwargs = mock_client.messages.count_tokens.call_args.kwargs
        assert "tools" in call_kwargs
        assert call_kwargs["tools"][0]["name"] == "get_weather"


# ---------------------------------------------------------------------------
# Handler kwargs fix verification
# ---------------------------------------------------------------------------


async def test_tax_estimate_uses_correct_kwargs():
    """tax_estimate handler uses system= and prompt= (not system_prompt=)."""
    import inspect

    from src.skills.tax_estimate.handler import TaxEstimateSkill

    source = inspect.getsource(TaxEstimateSkill.execute)
    assert "system_prompt=" not in source
    assert "user_message=" not in source
    assert "assembled_context=" not in source


async def test_cash_flow_uses_correct_kwargs():
    """cash_flow_forecast handler uses system= and prompt= (not system_prompt=)."""
    import inspect

    from src.skills.cash_flow_forecast.handler import CashFlowForecastSkill

    source = inspect.getsource(CashFlowForecastSkill.execute)
    assert "system_prompt=" not in source
    assert "user_message=" not in source
    assert "assembled_context=" not in source


async def test_receptionist_uses_correct_kwargs():
    """receptionist handler uses system= and prompt= (not system_prompt=)."""
    import inspect

    from src.skills.receptionist.handler import ReceptionistSkill

    source = inspect.getsource(ReceptionistSkill.execute)
    assert "system_prompt=" not in source
    assert "user_message=" not in source
    assert "assembled_context=" not in source
