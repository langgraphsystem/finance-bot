"""OpenAI Realtime API websocket client for live voice calls."""

import json
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import websockets

from src.voice.config import voice_config

logger = logging.getLogger(__name__)

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
_AUDIO_EVENT_TYPES = {"response.audio.delta", "response.output_audio.delta"}


class RealtimeSession:
    """Manage a single OpenAI Realtime session for one voice call."""

    def __init__(
        self,
        system_prompt: str,
        tools: list[dict[str, Any]] | None = None,
        on_tool_call: (
            Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]] | None
        ) = None,
        model: str | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.on_tool_call = on_tool_call
        self.model = model or voice_config.openai_realtime_model
        self._ws: Any = None
        self._closed = False

    async def connect(self) -> None:
        """Open the websocket and configure the realtime session."""
        url = f"{OPENAI_REALTIME_URL}?model={self.model}"
        headers = {"Authorization": f"Bearer {voice_config.openai_api_key}"}
        self._ws = await websockets.connect(url, additional_headers=headers)
        await self._ws.send(json.dumps(self._build_session_update()))
        logger.info("OpenAI realtime session configured for model %s", self.model)

    def _build_session_update(self) -> dict[str, Any]:
        """Build the GA `session.update` event for telephony audio."""
        return {
            "type": "session.update",
            "session": {
                "instructions": self.system_prompt,
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcmu"},
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500,
                        },
                    },
                    "output": {
                        "format": {"type": "audio/pcmu"},
                        "voice": voice_config.openai_realtime_voice,
                    },
                },
                "modalities": ["text", "audio"],
                "tool_choice": "auto",
                "tools": self.tools,
            },
        }

    async def start_response(self) -> None:
        """Ask the model to produce an opening response."""
        if not self._ws or self._closed:
            return
        await self._ws.send(json.dumps({"type": "response.create"}))

    async def send_audio(self, audio_base64: str) -> None:
        """Send a telephony audio frame to the realtime session."""
        if not self._ws or self._closed:
            return
        await self._ws.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": audio_base64,
                }
            )
        )

    async def receive_events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield relevant events and execute tool calls when needed."""
        if not self._ws:
            return

        try:
            async for raw_msg in self._ws:
                if self._closed:
                    break

                event = json.loads(raw_msg)
                event_type = event.get("type", "")

                if event_type in _AUDIO_EVENT_TYPES:
                    yield event
                    continue

                if event_type == "response.function_call_arguments.done":
                    await self._complete_tool_call(
                        call_id=event.get("call_id", ""),
                        name=event.get("name", ""),
                        arguments_text=event.get("arguments", "{}"),
                    )
                    continue

                if event_type == "response.done":
                    await self._handle_response_done(event)
                    yield event
                    continue

                if event_type == "error":
                    logger.error("OpenAI realtime error: %s", event)
                    yield event
        except websockets.ConnectionClosed:
            logger.info("OpenAI realtime websocket closed")

    async def _handle_response_done(self, event: dict[str, Any]) -> None:
        """Process function calls embedded in `response.done`."""
        response = event.get("response") or {}
        for item in response.get("output", []):
            if item.get("type") != "function_call":
                continue
            await self._complete_tool_call(
                call_id=item.get("call_id", ""),
                name=item.get("name", ""),
                arguments_text=item.get("arguments", "{}"),
            )

    async def _complete_tool_call(self, call_id: str, name: str, arguments_text: str) -> None:
        """Run a tool callback and send its result back into the session."""
        if not self._ws or not self.on_tool_call or not name:
            return

        try:
            arguments = json.loads(arguments_text or "{}")
        except json.JSONDecodeError:
            arguments = {}

        result = await self.on_tool_call(name, arguments)
        await self._ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result),
                    },
                }
            )
        )
        await self._ws.send(json.dumps({"type": "response.create"}))

    async def close(self) -> None:
        """Close the realtime websocket."""
        self._closed = True
        if self._ws:
            await self._ws.close()
