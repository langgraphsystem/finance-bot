"""Tests for onboarding callback handling in router."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import ConversationState
from src.gateway.types import IncomingMessage, MessageType

MODULE = "src.core.router"


@pytest.fixture
def sample_ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


@pytest.mark.asyncio
async def test_onboard_new_callback_sets_activity_state(sample_ctx):
    """onboard:new should set awaiting_activity state and prompt for activity."""
    msg = IncomingMessage(
        id="cb-1",
        user_id="123456789",
        chat_id="chat-1",
        type=MessageType.callback,
        callback_data="onboard:new",
    )

    with (
        patch(
            f"{MODULE}.check_rate_limit",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            f"{MODULE}._set_onboarding_state",
            new_callable=AsyncMock,
        ) as mock_set_state,
    ):
        from src.core.router import handle_message

        result = await handle_message(msg, sample_ctx)

    assert "деятельности" in (result.text or "").lower()
    mock_set_state.assert_awaited_once_with(
        msg.user_id, ConversationState.onboarding_awaiting_activity
    )


@pytest.mark.asyncio
async def test_onboard_join_callback_sets_invite_code_state(sample_ctx):
    """onboard:join should set awaiting_invite_code state and prompt for code."""
    msg = IncomingMessage(
        id="cb-2",
        user_id="123456789",
        chat_id="chat-1",
        type=MessageType.callback,
        callback_data="onboard:join",
    )

    with (
        patch(
            f"{MODULE}.check_rate_limit",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            f"{MODULE}._set_onboarding_state",
            new_callable=AsyncMock,
        ) as mock_set_state,
    ):
        from src.core.router import handle_message

        result = await handle_message(msg, sample_ctx)

    assert "код приглашения" in (result.text or "").lower()
    mock_set_state.assert_awaited_once_with(
        msg.user_id, ConversationState.onboarding_awaiting_invite_code
    )

