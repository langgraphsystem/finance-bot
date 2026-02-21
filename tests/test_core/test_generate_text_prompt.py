"""Tests for generate_text() prompt shorthand parameter."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_prompt_shorthand_converts_to_messages():
    """generate_text(prompt='...') converts to messages format."""
    with patch(
        "src.core.llm.clients.anthropic_client"
    ) as mock_factory:
        mock_client = AsyncMock()
        mock_factory.return_value = mock_client
        mock_client.messages.create.return_value = AsyncMock(
            content=[AsyncMock(text="result")]
        )

        from src.core.llm.clients import generate_text

        result = await generate_text(
            model="claude-sonnet-4-6",
            system="You are helpful.",
            prompt="Hello",
            max_tokens=100,
        )

        assert result == "result"
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 100


@pytest.mark.asyncio
async def test_messages_param_still_works():
    """generate_text(messages=[...]) continues to work."""
    with patch(
        "src.core.llm.clients.anthropic_client"
    ) as mock_factory:
        mock_client = AsyncMock()
        mock_factory.return_value = mock_client
        mock_client.messages.create.return_value = AsyncMock(
            content=[AsyncMock(text="result")]
        )

        from src.core.llm.clients import generate_text

        result = await generate_text(
            model="claude-sonnet-4-6",
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
        )

        assert result == "result"


@pytest.mark.asyncio
async def test_no_prompt_no_messages_raises():
    """generate_text() with neither prompt nor messages raises ValueError."""
    from src.core.llm.clients import generate_text

    with pytest.raises(ValueError, match="Either messages or prompt"):
        await generate_text(
            model="claude-sonnet-4-6",
            system="test",
        )
