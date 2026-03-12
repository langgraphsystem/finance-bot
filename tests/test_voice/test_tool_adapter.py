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
    mock_skill.execute = AsyncMock(
        return_value=SkillResult(response_text="Business hours are 9 to 5")
    )
    mock_registry = MagicMock()
    mock_registry.get.return_value = mock_skill

    with (
        patch("src.core.router.get_registry", return_value=mock_registry),
        patch.multiple(
            "src.voice.policy.voice_config",
            enabled=True,
            allow_write_tools=True,
            receptionist_only=False,
            force_callback_mode=False,
        ),
    ):
        result = await adapter.handle_tool_call(
            "receptionist",
            {"question": "What are your business hours?", "receptionist_topic": "hours"},
        )

    assert result == {"ok": True, "message": "Business hours are 9 to 5"}
    message_arg = mock_skill.execute.await_args.args[0]
    assert message_arg.channel == "voice"
    assert message_arg.text == "What are your business hours?"


async def test_handle_tool_call_sends_telegram_confirmation_for_pending_action():
    adapter = VoiceToolAdapter(context=_build_context(), metadata=_build_metadata())
    mock_gateway = SimpleNamespace(send=AsyncMock())

    with (
        patch("src.voice.tool_adapter.store_pending_action", new_callable=AsyncMock) as mock_store,
        patch("api.main.gateway", mock_gateway),
        patch.multiple(
            "src.voice.policy.voice_config",
            enabled=True,
            allow_write_tools=True,
            receptionist_only=False,
            force_callback_mode=False,
        ),
    ):
        mock_store.return_value = "abc123"
        result = await adapter.handle_tool_call(
            "create_event",
            {"event_title": "Team call", "date": "2026-03-11", "time": "10:00"},
        )

    assert result["ok"] is True
    assert result["approval_requested"] is True
    assert "Telegram" in str(result["message"])
    mock_store.assert_awaited_once()
    mock_gateway.send.assert_awaited_once()
    outgoing = mock_gateway.send.await_args.args[0]
    assert outgoing.chat_id == "123456"
    assert outgoing.buttons[0]["callback"] == "confirm_action:abc123"


async def test_handle_tool_call_without_bound_context_returns_error():
    adapter = VoiceToolAdapter(context=None, metadata=_build_metadata())

    result = await adapter.handle_tool_call("create_task", {"task_title": "Call back"})

    assert result["ok"] is False
    assert "not linked" in str(result["message"])


async def test_execute_pending_voice_tool_runs_without_policy():
    from src.voice.tool_adapter import execute_pending_voice_tool

    mock_skill = MagicMock()
    mock_skill.execute = AsyncMock(return_value=SkillResult(response_text="Task created"))
    mock_registry = MagicMock()
    mock_registry.get.return_value = mock_skill

    with patch("src.core.router.get_registry", return_value=mock_registry):
        message = await execute_pending_voice_tool(
            {
                "tool_name": "create_task",
                "arguments": {
                    "task_title": "Call back John",
                    "description": "Call back John tomorrow",
                },
                "metadata": _build_metadata().__dict__,
            },
            _build_context(),
        )

    assert message == "Task created"


async def test_request_verification_sends_sms_and_updates_auth_state():
    context = _build_context()
    context.voice_auth_state = "anonymous"
    adapter = VoiceToolAdapter(context=context, metadata=_build_metadata())

    with (
        patch(
            "src.voice.tool_adapter.voice_verification_store.create",
            new_callable=AsyncMock,
        ) as mock_create,
        patch("src.voice.tool_adapter.SMSGateway") as mock_gateway_cls,
        patch.multiple(
            "src.voice.policy.voice_config",
            enabled=True,
            allow_write_tools=True,
            receptionist_only=False,
            force_callback_mode=False,
        ),
    ):
        mock_create.return_value = SimpleNamespace(code="123456")
        mock_gateway = mock_gateway_cls.return_value
        mock_gateway.is_configured = True
        mock_gateway.send = AsyncMock()
        mock_gateway.close = AsyncMock()

        result = await adapter.handle_tool_call("request_verification", {})

    assert result["ok"] is True
    assert "verification code" in str(result["message"])
    assert context.voice_auth_state == "verification_pending"
    mock_gateway.send.assert_awaited_once()
    mock_gateway.close.assert_awaited_once()


async def test_verify_caller_promotes_auth_state():
    context = _build_context()
    context.voice_auth_state = "verification_pending"
    adapter = VoiceToolAdapter(context=context, metadata=_build_metadata())

    with patch(
        "src.voice.tool_adapter.voice_verification_store.verify",
        new_callable=AsyncMock,
        return_value=True,
    ), patch.multiple(
        "src.voice.policy.voice_config",
        enabled=True,
        allow_write_tools=True,
        receptionist_only=False,
        force_callback_mode=False,
    ):
        result = await adapter.handle_tool_call("verify_caller", {"code": "123456"})

    assert result["ok"] is True
    assert context.voice_auth_state == "verified_by_sms"


async def test_handoff_to_owner_falls_back_to_callback_task_when_telegram_unavailable():
    adapter = VoiceToolAdapter(context=_build_context(), metadata=_build_metadata())

    with (
        patch.object(adapter, "_send_telegram_message", new_callable=AsyncMock, return_value=False),
        patch.object(adapter, "_run_skill", new_callable=AsyncMock) as mock_run_skill,
        patch.object(adapter, "_send_sms_message", new_callable=AsyncMock, return_value=True),
        patch.multiple(
            "src.voice.policy.voice_config",
            enabled=True,
            allow_write_tools=True,
            receptionist_only=False,
            force_callback_mode=False,
        ),
    ):
        mock_run_skill.return_value = {"ok": True, "message": "Task created"}
        result = await adapter.handle_tool_call(
            "handoff_to_owner",
            {"reason": "Caller needs manual pricing"},
        )

    assert result["ok"] is True
    assert "callback confirmation" in str(result["message"])
    mock_run_skill.assert_awaited_once()
