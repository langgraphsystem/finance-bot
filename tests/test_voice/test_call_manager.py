"""Tests for call manager."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.voice.call_manager import record_inbound_call, start_outbound_call


async def test_start_outbound_call_twilio_error():
    """When initiate_outbound_call returns error, no interaction is saved."""
    with patch(
        "src.voice.call_manager.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value={"error": "Twilio not configured"},
    ):
        result = await start_outbound_call(
            contact_id=str(uuid.uuid4()),
            contact_phone="+1234567890",
            contact_name="John",
            owner_name="David",
            call_purpose="confirm appointment",
            family_id=str(uuid.uuid4()),
        )

    assert "error" in result


async def test_start_outbound_call_success():
    """Successful outbound call should save interaction."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    with (
        patch(
            "src.voice.call_manager.initiate_outbound_call",
            new_callable=AsyncMock,
            return_value={"call_sid": "CA123", "call_id": "abc", "status": "queued"},
        ),
        patch(
            "src.voice.call_manager.async_session",
            return_value=mock_session,
        ),
    ):
        result = await start_outbound_call(
            contact_id=str(uuid.uuid4()),
            contact_phone="+1234567890",
            contact_name="John",
            owner_name="David",
            call_purpose="confirm appointment",
            family_id=str(uuid.uuid4()),
        )

    assert result["call_sid"] == "CA123"
    mock_session.add.assert_called_once()


async def test_record_inbound_call():
    """Should save an inbound call interaction."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    with patch(
        "src.voice.call_manager.async_session",
        return_value=mock_session,
    ):
        await record_inbound_call(
            family_id=str(uuid.uuid4()),
            contact_id=str(uuid.uuid4()),
            transcript="Hi, I need a plumber for a leaky faucet.",
            duration_seconds=120,
            caller_phone="+1917555xxxx",
        )

    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
