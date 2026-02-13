"""Tests for RLS (Row Level Security) context propagation."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.core.request_context import (
    get_current_family_id,
    reset_family_context,
    set_family_context,
)


# ---------------------------------------------------------------------------
# 1. request_context module: ContextVar behaviour
# ---------------------------------------------------------------------------


class TestRequestContext:
    """Pure unit tests for the ContextVar helpers — no DB needed."""

    def test_default_is_none(self):
        """When no context has been set, get_current_family_id returns None."""
        assert get_current_family_id() is None

    def test_set_and_get(self):
        family_id = str(uuid.uuid4())
        token = set_family_context(family_id)
        try:
            assert get_current_family_id() == family_id
        finally:
            reset_family_context(token)

    def test_reset_restores_previous(self):
        first = str(uuid.uuid4())
        second = str(uuid.uuid4())

        token1 = set_family_context(first)
        try:
            token2 = set_family_context(second)
            assert get_current_family_id() == second
            reset_family_context(token2)
            assert get_current_family_id() == first
        finally:
            reset_family_context(token1)

        assert get_current_family_id() is None

    def test_reset_to_none(self):
        family_id = str(uuid.uuid4())
        token = set_family_context(family_id)
        reset_family_context(token)
        assert get_current_family_id() is None


# ---------------------------------------------------------------------------
# 2. rls_session: explicit family-scoped session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rls_session_sets_config():
    """rls_session must call set_config with the supplied family_id."""
    family_id = str(uuid.uuid4())

    mock_session = AsyncMock()
    mock_session_factory = MagicMock()

    # Make the factory an async context manager that yields mock_session
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session_factory.return_value = mock_cm

    with patch("src.core.db.async_session", mock_session_factory):
        from src.core.db import rls_session

        async with rls_session(family_id) as session:
            assert session is mock_session

    # Verify set_config was called
    mock_session.execute.assert_called_once()
    executed_stmt = mock_session.execute.call_args
    sql_text = str(executed_stmt[0][0])
    assert "set_config" in sql_text
    assert "app.current_family_id" in sql_text
    assert executed_stmt[1] == {"fid": family_id} or executed_stmt[0][1] == {"fid": family_id}


# ---------------------------------------------------------------------------
# 3. get_session: auto-RLS when context var is set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_applies_rls_when_context_set():
    """get_session should call set_config when family context is active."""
    family_id = str(uuid.uuid4())

    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session_factory = MagicMock(return_value=mock_cm)

    token = set_family_context(family_id)
    try:
        with patch("src.core.db.async_session", mock_session_factory):
            from src.core.db import get_session

            gen = get_session()
            session = await gen.__anext__()
            assert session is mock_session

            # set_config must have been called
            mock_session.execute.assert_called_once()
            sql_text = str(mock_session.execute.call_args[0][0])
            assert "set_config" in sql_text
            assert "app.current_family_id" in sql_text

            # Clean up the generator
            try:
                await gen.__anext__()
            except StopAsyncIteration:
                pass
    finally:
        reset_family_context(token)


@pytest.mark.asyncio
async def test_get_session_skips_rls_when_no_context():
    """get_session should NOT call set_config when no family context."""
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session_factory = MagicMock(return_value=mock_cm)

    # Ensure no family context is set
    assert get_current_family_id() is None

    with patch("src.core.db.async_session", mock_session_factory):
        from src.core.db import get_session

        gen = get_session()
        session = await gen.__anext__()
        assert session is mock_session

        # set_config must NOT have been called
        mock_session.execute.assert_not_called()

        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass


# ---------------------------------------------------------------------------
# 4. handle_message: context var is set/reset around dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_sets_family_context(sample_context):
    """handle_message must bind family context before skill dispatch and reset after."""
    from src.core.request_context import get_current_family_id

    captured_family_ids: list[str | None] = []

    # A spy that captures the family_id visible inside _dispatch_message
    async def fake_dispatch(message, context, registry):
        captured_family_ids.append(get_current_family_id())
        from src.gateway.types import OutgoingMessage
        return OutgoingMessage(text="ok", chat_id=message.chat_id)

    with (
        patch("src.core.router.check_rate_limit", AsyncMock(return_value=True)),
        patch("src.core.router._dispatch_message", side_effect=fake_dispatch),
    ):
        from src.core.router import handle_message
        from src.gateway.types import IncomingMessage, MessageType

        msg = IncomingMessage(
            id="1",
            user_id="u1",
            chat_id="c1",
            type=MessageType.text,
            text="test",
        )
        await handle_message(msg, sample_context)

    # Inside the dispatch the family context must have been set
    assert len(captured_family_ids) == 1
    assert captured_family_ids[0] == sample_context.family_id

    # After handle_message returns the context must be reset
    assert get_current_family_id() is None


@pytest.mark.asyncio
async def test_handle_message_resets_context_on_exception(sample_context):
    """Family context must be reset even if skill dispatch raises."""
    async def failing_dispatch(message, context, registry):
        raise RuntimeError("boom")

    with (
        patch("src.core.router.check_rate_limit", AsyncMock(return_value=True)),
        patch("src.core.router._dispatch_message", side_effect=failing_dispatch),
    ):
        from src.core.router import handle_message
        from src.gateway.types import IncomingMessage, MessageType

        msg = IncomingMessage(
            id="1",
            user_id="u1",
            chat_id="c1",
            type=MessageType.text,
            text="test",
        )

        with pytest.raises(RuntimeError, match="boom"):
            await handle_message(msg, sample_context)

    assert get_current_family_id() is None
