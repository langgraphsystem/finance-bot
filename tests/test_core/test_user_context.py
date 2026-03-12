import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.memory.user_context import (
    SESSION_IDLE_TIMEOUT,
    SESSION_MAX_MESSAGES,
    ensure_active_session,
    get_current_session_id,
    should_rotate_session,
)


def _make_context(
    *,
    session_id: uuid.UUID | None = None,
    message_count: int = 1,
    updated_at: datetime | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.session_id = session_id or uuid.uuid4()
    ctx.message_count = message_count
    ctx.updated_at = updated_at or datetime.now(UTC)
    return ctx


def test_should_rotate_session_after_idle_timeout():
    stale_ctx = _make_context(
        updated_at=datetime.now(UTC) - SESSION_IDLE_TIMEOUT - timedelta(minutes=1),
    )

    assert should_rotate_session(stale_ctx) is True


def test_should_rotate_session_after_message_cap():
    capped_ctx = _make_context(message_count=SESSION_MAX_MESSAGES)

    assert should_rotate_session(capped_ctx) is True


def test_should_keep_recent_small_session():
    fresh_ctx = _make_context(message_count=5, updated_at=datetime.now(UTC))

    assert should_rotate_session(fresh_ctx) is False


async def test_ensure_active_session_rotates_stale_context():
    old_session_id = uuid.uuid4()
    stale_ctx = _make_context(
        session_id=old_session_id,
        updated_at=datetime.now(UTC) - SESSION_IDLE_TIMEOUT - timedelta(minutes=1),
    )
    mock_session = AsyncMock()

    with patch(
        "src.core.memory.user_context.get_user_context",
        new_callable=AsyncMock,
        return_value=stale_ctx,
    ):
        result = await ensure_active_session(
            mock_session,
            str(uuid.uuid4()),
            str(uuid.uuid4()),
        )

    assert result is stale_ctx
    assert result.message_count == 0
    assert result.session_id != old_session_id
    mock_session.flush.assert_awaited_once()


async def test_get_current_session_id_returns_none_for_stale_context():
    stale_ctx = _make_context(
        updated_at=datetime.now(UTC) - SESSION_IDLE_TIMEOUT - timedelta(minutes=1),
    )

    with patch(
        "src.core.memory.user_context.get_user_context",
        new_callable=AsyncMock,
        return_value=stale_ctx,
    ):
        result = await get_current_session_id(AsyncMock(), str(uuid.uuid4()))

    assert result is None
