"""OpenAI Realtime API WebSocket client for voice conversations.

Handles bidirectional audio streaming between Twilio Media Streams
and OpenAI Realtime API. Converts mu-law 8kHz (Twilio) <-> PCM16 16kHz (OpenAI).
"""

import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import websockets

from src.voice.config import voice_config

logger = logging.getLogger(__name__)

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"


class RealtimeSession:
    """Manages a single OpenAI Realtime API session for one call."""

    def __init__(
        self,
        system_prompt: str,
        tools: list[dict[str, Any]] | None = None,
        on_tool_call: Callable[..., Coroutine] | None = None,
    ):
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.on_tool_call = on_tool_call
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._closed = False

    async def connect(self) -> None:
        """Open WebSocket to OpenAI Realtime API."""
        url = f"{OPENAI_REALTIME_URL}?model={voice_config.openai_realtime_model}"
        headers = {
            "Authorization": f"Bearer {voice_config.openai_api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        self._ws = await websockets.connect(url, additional_headers=headers)

        # Configure session
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": self.system_prompt,
                "voice": voice_config.openai_realtime_voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500,
                },
                "tools": self.tools,
            },
        }
        await self._ws.send(json.dumps(session_config))
        logger.info("OpenAI Realtime session configured")

    async def send_audio(self, audio_base64: str) -> None:
        """Send audio chunk to OpenAI Realtime."""
        if not self._ws or self._closed:
            return
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_base64,
        }
        await self._ws.send(json.dumps(event))

    async def receive_events(self):
        """Yield events from OpenAI Realtime until session ends."""
        if not self._ws:
            return
        try:
            async for raw_msg in self._ws:
                if self._closed:
                    break
                event = json.loads(raw_msg)
                event_type = event.get("type", "")

                if event_type == "response.audio.delta":
                    yield event
                elif event_type == "response.function_call_arguments.done":
                    if self.on_tool_call:
                        result = await self.on_tool_call(
                            event.get("name"),
                            json.loads(event.get("arguments", "{}")),
                        )
                        # Send tool result back
                        await self._ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": event.get("call_id"),
                                "output": json.dumps(result),
                            },
                        }))
                        await self._ws.send(json.dumps({
                            "type": "response.create",
                        }))
                elif event_type == "response.done":
                    yield event
                elif event_type == "error":
                    logger.error("OpenAI Realtime error: %s", event)
                    yield event
        except websockets.ConnectionClosed:
            logger.info("OpenAI Realtime connection closed")

    async def close(self) -> None:
        """Close the Realtime session."""
        self._closed = True
        if self._ws:
            await self._ws.close()
