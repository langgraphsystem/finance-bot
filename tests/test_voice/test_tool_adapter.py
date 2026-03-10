"""Tests for routing voice tools through the existing bot skills."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.context import SessionContext
from src.skills.base import SkillResult
from src.voice.session_store import VoiceCallMetadata
from src.voice.tool_adapter import VoiceToolAdapter


def _build_context() -> SessionContext:
    return SessionContext(
        user_id="11111111-1111-1111-1111-111111111111",
        family_id="22222222-2222-2222-2222-222222222222",
        role="owner",
        language="en",
        currency="USD",
        business_type="plumber",
        categories=[],
        merchant_mappings=[],
        channel="voice",
        channel_user_id="+15551234567",
        timezone="UTC",
    )


def _build_metadata() -> VoiceCallMetadata:
    return VoiceCallMetadata(
        call_id="call-123",
        call_type="inbound",
        owner_name="David",
        business_name="North Star Plumbing",
        services="plumbing",
        hours="Mon-Fri 9-5",
        owner_telegram_id="123456",
        from_phone="+15551234567",
    )


async def test_handle_tool_call_invokes_registered_skill():
    adapter = VoiceToolAdapter(context=_build_context(), metadata=_build_metadata())
    mock_skill = MagicMock()
    mock_skill.execute = AsyncMock(return_value=SkillResult(response_text="Task created"))
    mock_registry = MagicMock()
    mock_registry.get.return_value = mock_skill

    with patch("src.core.router.get_registry", return_value=mock_registry):
        result = await adapter.handle_tool_call(
            "create_task",
            {"task_title": "Call back John", "description": "Call back John tomorrow"},
        )

    assert result == {"ok": True, "message": "Task created"}
    message_arg = mock_skill.execute.await_args.args[0]
    assert message_arg.channel == "voice"
    assert message_arg.text == "Call back John tomorrow"


async def test_handle_tool_call_sends_telegram_confirmation_for_pending_action():
    adapter = VoiceToolAdapter(context=_build_context(), metadata=_build_metadata())
    mock_skill = MagicMock()
    mock_skill.execute = AsyncMock(
        return_value=SkillResult(
            response_text="Preview event",
            buttons=[
                {"text": "Confirm", "callback": "confirm_action:abc123"},
                {"text": "Cancel", "callback": "cancel_action:abc123"},
            ],
        )
    )
    mock_registry = MagicMock()
    mock_registry.get.return_value = mock_skill
    mock_gateway = SimpleNamespace(send=AsyncMock())

    with (
        patch("src.core.router.get_registry", return_value=mock_registry),
        patch("api.main.gateway", mock_gateway),
    ):
        result = await adapter.handle_tool_call(
            "create_event",
            {"event_title": "Team call", "date": "2026-03-11", "time": "10:00"},
        )

    assert result["ok"] is True
    assert result["approval_requested"] is True
    assert "Telegram" in str(result["message"])
    mock_gateway.send.assert_awaited_once()
    outgoing = mock_gateway.send.await_args.args[0]
    assert outgoing.chat_id == "123456"
    assert outgoing.buttons[0]["callback"] == "confirm_action:abc123"


async def test_handle_tool_call_without_bound_context_returns_error():
    adapter = VoiceToolAdapter(context=None, metadata=_build_metadata())

    result = await adapter.handle_tool_call("create_task", {"task_title": "Call back"})

    assert result["ok"] is False
    assert "not linked" in str(result["message"])
