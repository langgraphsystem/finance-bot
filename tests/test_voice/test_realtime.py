"""Tests for OpenAI realtime voice session handling."""

import json
from unittest.mock import AsyncMock, patch

from src.voice.realtime import RealtimeSession


async def test_connect_uses_ga_session_update():
    mock_ws = AsyncMock()

    with (
        patch("src.voice.realtime.voice_config.openai_api_key", "test-key"),
        patch("src.voice.realtime.voice_config.openai_realtime_voice", "marin"),
        patch(
            "src.voice.realtime.voice_config.openai_realtime_fallback_model",
            "gpt-realtime-mini",
        ),
        patch(
            "src.voice.realtime.websockets.connect",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ) as mock_connect,
    ):
        session = RealtimeSession(system_prompt="Test prompt")
        await session.connect()

    mock_connect.assert_awaited_once()
    sent_event = json.loads(mock_ws.send.await_args_list[0].args[0])
    assert sent_event["type"] == "session.update"
    assert sent_event["session"]["type"] == "realtime"
    assert sent_event["session"]["model"] == "gpt-realtime-1.5"
    assert sent_event["session"]["output_modalities"] == ["audio"]
    assert sent_event["session"]["audio"]["input"]["format"]["type"] == "audio/pcmu"
    assert sent_event["session"]["audio"]["output"]["voice"] == "marin"


async def test_receive_events_executes_function_calls_from_response_done():
    events = [
        json.dumps(
            {
                "type": "response.done",
                "response": {
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "take_message",
                            "arguments": '{"message": "Please call me back"}',
                        }
                    ]
                },
            }
        )
    ]
    mock_ws = AsyncMock()
    mock_ws.__aiter__.return_value = iter(events)

    on_tool_call = AsyncMock(return_value={"ok": True})
    session = RealtimeSession(system_prompt="Test prompt", on_tool_call=on_tool_call)
    session._ws = mock_ws

    yielded = [event async for event in session.receive_events()]

    assert yielded[0]["type"] == "response.done"
    on_tool_call.assert_awaited_once_with("take_message", {"message": "Please call me back"})
    sent_payloads = [json.loads(call.args[0]) for call in mock_ws.send.await_args_list]
    assert sent_payloads[0]["type"] == "conversation.item.create"
    assert sent_payloads[1]["type"] == "response.create"


async def test_start_response_sends_response_create():
    mock_ws = AsyncMock()
    session = RealtimeSession(system_prompt="Test prompt")
    session._ws = mock_ws

    await session.start_response()

    mock_ws.send.assert_awaited_once_with('{"type": "response.create"}')


async def test_connect_falls_back_to_secondary_realtime_model():
    primary_error = RuntimeError("primary model unavailable")
    fallback_ws = AsyncMock()

    with (
        patch("src.voice.realtime.voice_config.openai_api_key", "test-key"),
        patch(
            "src.voice.realtime.voice_config.openai_realtime_fallback_model",
            "gpt-realtime-mini",
        ),
        patch(
            "src.voice.realtime.websockets.connect",
            new_callable=AsyncMock,
            side_effect=[primary_error, fallback_ws],
        ) as mock_connect,
    ):
        session = RealtimeSession(system_prompt="Test prompt", model="gpt-realtime-1.5")
        await session.connect()

    assert session.model == "gpt-realtime-mini"
    assert mock_connect.await_count == 2
    first_url = mock_connect.await_args_list[0].args[0]
    second_url = mock_connect.await_args_list[1].args[0]
    assert first_url.endswith("model=gpt-realtime-1.5")
    assert second_url.endswith("model=gpt-realtime-mini")
    sent_event = json.loads(fallback_ws.send.await_args_list[0].args[0])
    assert sent_event["session"]["model"] == "gpt-realtime-mini"
