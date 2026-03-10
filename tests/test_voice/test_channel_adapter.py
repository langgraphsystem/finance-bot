"""Tests for binding voice calls to the existing bot context."""

from types import SimpleNamespace

from src.core.context import SessionContext
from src.voice.channel_adapter import build_voice_context
from src.voice.session_store import VoiceCallMetadata


async def test_build_voice_context_uses_owner_telegram_id():
    metadata = VoiceCallMetadata(
        call_id="call-123",
        call_type="inbound",
        owner_name="David",
        business_name="North Star Plumbing",
        services="plumbing",
        hours="Mon-Fri 9-5",
        owner_telegram_id="123456",
        from_phone="+15551234567",
    )
    base_context = SessionContext(
        user_id="user-1",
        family_id="family-1",
        role="owner",
        language="en",
        currency="USD",
        business_type="plumber",
        categories=[],
        merchant_mappings=[],
    )

    from unittest.mock import AsyncMock, patch

    with (
        patch("api.main.build_session_context", new_callable=AsyncMock) as mock_build,
        patch(
            "src.voice.channel_adapter.resolve_caller_identity",
            new_callable=AsyncMock,
        ) as mock_identity,
    ):
        mock_build.return_value = base_context
        mock_identity.return_value = SimpleNamespace(
            auth_state="matched_by_number",
            contact_id="contact-1",
            contact_name="John",
            phone_number="+15551234567",
        )
        context = await build_voice_context(metadata)

    assert context is not None
    assert context.channel == "voice"
    assert context.channel_user_id == "+15551234567"
    assert context.voice_auth_state == "matched_by_number"
    assert context.voice_contact_id == "contact-1"
    mock_build.assert_awaited_once_with("123456")
