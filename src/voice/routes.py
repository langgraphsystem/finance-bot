"""FastAPI routes for Twilio voice webhooks and media streaming."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from src.voice.config import voice_config
from src.voice.realtime import RealtimeSession
from src.voice.session_store import VoiceCallMetadata, voice_session_store
from src.voice.twilio_handler import (
    build_inbound_prompt,
    build_inbound_tools,
    build_outbound_prompt,
    build_outbound_tools,
    generate_inbound_twiml,
    generate_outbound_twiml,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])


def _metadata_from_form(call_type: str, call_id: str, form: dict[str, Any]) -> VoiceCallMetadata:
    """Build call metadata from webhook form data with safe defaults."""
    owner_name = form.get("owner_name") or voice_config.default_owner_name
    business_name = form.get("business_name") or voice_config.default_business_name
    services = form.get("services") or voice_config.default_services
    hours = form.get("hours") or voice_config.default_business_hours
    return VoiceCallMetadata(
        call_id=call_id,
        call_type=call_type,
        owner_name=owner_name,
        business_name=business_name,
        services=services,
        hours=hours,
        from_phone=form.get("From", ""),
        to_phone=form.get("To", ""),
        call_sid=form.get("CallSid", ""),
        contact_name=form.get("contact_name", ""),
        call_purpose=form.get("call_purpose", ""),
        call_purpose_short=form.get("call_purpose_short", "") or form.get("call_purpose", ""),
        family_id=form.get("family_id", ""),
        status="initiated",
    )


async def _handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Temporary tool executor for Phase 1-2 route wiring."""
    logger.info("Voice tool requested: %s %s", name, arguments)
    return {
        "ok": False,
        "tool": name,
        "message": (
            "Voice tools are connected to the realtime bridge, "
            "but backend execution is not wired yet."
        ),
    }


@router.post("/webhook/voice/inbound")
async def inbound_voice_webhook(request: Request) -> Response:
    """Return TwiML that connects an inbound call to the websocket media bridge."""
    form = dict(await request.form())
    call_id = form.get("CallSid") or form.get("call_id") or "inbound-call"
    metadata = _metadata_from_form("inbound", call_id, form)
    await voice_session_store.save(metadata)
    ws_url = voice_config.build_websocket_url("inbound", call_id)
    return Response(content=generate_inbound_twiml(ws_url), media_type="application/xml")


@router.post("/webhook/voice/outbound/{call_id}")
async def outbound_voice_webhook(call_id: str) -> Response:
    """Return TwiML for an outbound call created through Twilio REST API."""
    metadata = await voice_session_store.get(call_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Unknown voice call session")
    ws_url = voice_config.build_websocket_url("outbound", call_id)
    return Response(content=generate_outbound_twiml(ws_url), media_type="application/xml")


@router.post("/webhook/voice/status")
async def voice_status_webhook(request: Request) -> dict[str, bool]:
    """Persist the latest Twilio call status when the callback fires."""
    form = dict(await request.form())
    call_id = request.query_params.get("call_id") or form.get("CallSid", "")
    status = form.get("CallStatus", "")
    if call_id and status:
        await voice_session_store.update_status(call_id, status)
    return {"ok": True}


@router.websocket("/ws/voice/{call_type}/{call_id}")
async def voice_media_bridge(websocket: WebSocket, call_type: str, call_id: str) -> None:
    """Bridge a Twilio media stream websocket to OpenAI Realtime."""
    await websocket.accept()

    metadata = await voice_session_store.get(call_id)
    if metadata is None:
        metadata = VoiceCallMetadata(
            call_id=call_id,
            call_type=call_type,
            owner_name=voice_config.default_owner_name,
            business_name=voice_config.default_business_name,
            services=voice_config.default_services,
            hours=voice_config.default_business_hours,
        )

    if not voice_config.realtime_configured:
        await websocket.close(code=1011, reason="Voice realtime is not configured")
        return

    prompt = (
        build_inbound_prompt(metadata)
        if call_type == "inbound"
        else build_outbound_prompt(metadata)
    )
    tools = build_inbound_tools() if call_type == "inbound" else build_outbound_tools()
    session = RealtimeSession(system_prompt=prompt, tools=tools, on_tool_call=_handle_tool_call)
    await session.connect()
    await session.start_response()

    stream_sid = ""

    async def twilio_to_openai() -> None:
        nonlocal stream_sid
        while True:
            payload = await websocket.receive_text()
            event = json.loads(payload)
            event_type = event.get("event", "")

            if event_type == "start":
                stream_sid = event.get("start", {}).get("streamSid", "")
                continue

            if event_type == "media":
                audio_payload = event.get("media", {}).get("payload")
                if audio_payload:
                    await session.send_audio(audio_payload)
                continue

            if event_type == "stop":
                break

    async def openai_to_twilio() -> None:
        async for event in session.receive_events():
            event_type = event.get("type", "")
            if event_type not in {"response.audio.delta", "response.output_audio.delta"}:
                continue
            audio_payload = event.get("delta")
            if audio_payload and stream_sid:
                await websocket.send_json(
                    {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": audio_payload},
                    }
                )

    try:
        await asyncio.gather(twilio_to_openai(), openai_to_twilio())
    except WebSocketDisconnect:
        logger.info("Twilio voice websocket disconnected for call %s", call_id)
    finally:
        await session.close()
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.close()
