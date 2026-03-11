"""FastAPI routes for Twilio voice webhooks and media streaming."""

import asyncio
import json
import logging
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from src.core.context import SessionContext
from src.gateway.types import OutgoingMessage
from src.voice.call_manager import record_call_summary
from src.voice.channel_adapter import build_voice_context
from src.voice.config import voice_config
from src.voice.evals import evaluate_voice_call
from src.voice.ops import build_voice_ops_overview
from src.voice.pilot import build_voice_pilot_readiness
from src.voice.realtime import RealtimeSession
from src.voice.review_store import VoiceCallReview, voice_review_store
from src.voice.session_store import VoiceCallMetadata, voice_session_store
from src.voice.simulations import builtin_voice_simulations, run_voice_simulation
from src.voice.summary import summarize_voice_call
from src.voice.tool_adapter import VoiceToolAdapter
from src.voice.trace import voice_trace_store
from src.voice.twilio_handler import (
    build_inbound_prompt,
    build_inbound_tools,
    build_outbound_prompt,
    build_outbound_tools,
    generate_inbound_twiml,
    generate_outbound_twiml,
    generate_voice_unavailable_twiml,
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
        owner_telegram_id=(
            form.get("owner_telegram_id") or voice_config.default_owner_telegram_id
        ),
        from_phone=form.get("From", ""),
        to_phone=form.get("To", ""),
        call_sid=form.get("CallSid", ""),
        contact_id=form.get("contact_id", ""),
        contact_name=form.get("contact_name", ""),
        call_purpose=form.get("call_purpose", ""),
        call_purpose_short=form.get("call_purpose_short", "") or form.get("call_purpose", ""),
        family_id=form.get("family_id", ""),
        status="initiated",
    )


@router.post("/webhook/voice/inbound")
async def inbound_voice_webhook(request: Request) -> Response:
    """Return TwiML that connects an inbound call to the websocket media bridge."""
    if not voice_config.enabled:
        return Response(
            content=generate_voice_unavailable_twiml(
                "Voice assistant is temporarily unavailable. Please try again later."
            ),
            media_type="application/xml",
        )
    form = dict(await request.form())
    call_id = form.get("CallSid") or form.get("call_id") or "inbound-call"
    metadata = _metadata_from_form("inbound", call_id, form)
    await voice_session_store.save(metadata)
    ws_url = voice_config.build_websocket_url("inbound", call_id)
    return Response(content=generate_inbound_twiml(ws_url), media_type="application/xml")


@router.post("/webhook/voice/outbound/{call_id}")
async def outbound_voice_webhook(call_id: str) -> Response:
    """Return TwiML for an outbound call created through Twilio REST API."""
    if not voice_config.enabled or not voice_config.allow_outbound:
        return Response(
            content=generate_voice_unavailable_twiml(
                "Outbound voice is temporarily unavailable."
            ),
            media_type="application/xml",
        )
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


@router.get("/voice/review/recent")
async def recent_voice_reviews(limit: int = 20) -> dict[str, Any]:
    """Return recent QA review snapshots for dashboard-style inspection."""
    reviews = await voice_review_store.recent(limit=max(1, min(limit, 50)))
    return {"items": [asdict(review) for review in reviews]}


@router.get("/voice/ops/switches")
async def voice_ops_switches() -> dict[str, bool]:
    """Return active rollout switches for voice operations."""
    return voice_config.rollout_state()


@router.get("/voice/ops/overview")
async def voice_ops_overview(limit: int = 20) -> dict[str, Any]:
    """Return aggregated voice metrics for operator review."""
    reviews = await voice_review_store.recent(limit=max(1, min(limit, 100)))
    overview = build_voice_ops_overview(reviews, voice_config)
    return asdict(overview)


@router.get("/voice/ops/readiness")
async def voice_ops_readiness() -> dict[str, Any]:
    """Return pilot readiness status for the current voice environment."""
    report = build_voice_pilot_readiness(voice_config)
    return asdict(report)


@router.get("/voice/review/{call_id}")
async def voice_call_review(call_id: str) -> dict[str, Any]:
    """Return the stored review snapshot and raw trace for one call."""
    review = await voice_review_store.load(call_id)
    metadata = await voice_session_store.get(call_id)
    trace = await voice_trace_store.load(call_id)

    if review is None and metadata is None and not trace:
        raise HTTPException(status_code=404, detail="Unknown voice call review")

    return {
        "call_id": call_id,
        "metadata": asdict(metadata) if metadata else None,
        "review": asdict(review) if review else None,
        "trace": [asdict(event) for event in trace],
    }


@router.get("/voice/simulations")
async def list_voice_simulations() -> dict[str, Any]:
    """List built-in synthetic voice regression scenarios."""
    items = [
        {
            "scenario_id": scenario.scenario_id,
            "description": scenario.description,
            "expected_disposition": scenario.expected_disposition,
            "min_score": scenario.min_score,
        }
        for scenario in builtin_voice_simulations()
    ]
    return {"items": items}


@router.post("/voice/simulations/{scenario_id}")
async def run_voice_simulation_route(scenario_id: str) -> dict[str, Any]:
    """Execute one synthetic voice QA scenario."""
    scenario = next(
        (
            item
            for item in builtin_voice_simulations()
            if item.scenario_id == scenario_id
        ),
        None,
    )
    if scenario is None:
        raise HTTPException(status_code=404, detail="Unknown voice simulation")

    report = run_voice_simulation(scenario)
    return {
        "scenario_id": report.scenario_id,
        "passed": report.passed,
        "failures": report.failures,
        "summary": {
            "disposition": report.summary.disposition,
            "text": report.summary.text,
            "tool_names": report.summary.tool_names,
            "approvals_requested": report.summary.approvals_requested,
        },
        "evaluation": asdict(report.evaluation),
    }


@router.websocket("/ws/voice/{call_type}/{call_id}")
async def voice_media_bridge(websocket: WebSocket, call_type: str, call_id: str) -> None:
    """Bridge a Twilio media stream websocket to OpenAI Realtime."""
    await websocket.accept()

    if not voice_config.enabled:
        await websocket.close(code=1011, reason="Voice is disabled")
        return
    if call_type == "outbound" and not voice_config.allow_outbound:
        await websocket.close(code=1011, reason="Outbound voice is disabled")
        return

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

    context = await build_voice_context(metadata)
    tool_adapter = VoiceToolAdapter(context=context, metadata=metadata)
    started_at = time.monotonic()
    await voice_trace_store.append(
        call_id,
        "call_started",
        {
            "call_type": call_type,
            "from_phone": metadata.from_phone,
            "to_phone": metadata.to_phone,
            "auth_state": context.voice_auth_state if context else "unbound",
        },
    )
    prompt = (
        build_inbound_prompt(metadata)
        if call_type == "inbound"
        else build_outbound_prompt(metadata)
    )
    tools = build_inbound_tools() if call_type == "inbound" else build_outbound_tools()

    async def on_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        await voice_trace_store.append(
            call_id,
            "tool_requested",
            {"tool_name": name, "arguments": arguments},
        )
        result = await tool_adapter.handle_tool_call(name, arguments)
        await voice_trace_store.append(
            call_id,
            "tool_completed",
            {
                "tool_name": name,
                "ok": bool(result.get("ok")),
                "approval_requested": bool(result.get("approval_requested")),
                "message": str(result.get("message") or "")[:400],
            },
        )
        if result.get("approval_requested"):
            await voice_trace_store.append(
                call_id,
                "approval_requested",
                {"tool_name": name},
            )
        return result

    session = RealtimeSession(
        system_prompt=prompt,
        tools=tools,
        on_tool_call=on_tool_call,
    )
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
                await voice_trace_store.append(
                    call_id,
                    "twilio_stream_started",
                    {"stream_sid": stream_sid},
                )
                continue

            if event_type == "media":
                audio_payload = event.get("media", {}).get("payload")
                if audio_payload:
                    await session.send_audio(audio_payload)
                continue

            if event_type == "stop":
                await voice_trace_store.append(call_id, "twilio_stream_stopped", {})
                break

    async def openai_to_twilio() -> None:
        async for event in session.receive_events():
            event_type = event.get("type", "")
            if event_type == "error":
                await voice_trace_store.append(
                    call_id,
                    "realtime_error",
                    {"event": event},
                )
                continue
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
        duration_seconds = int(time.monotonic() - started_at)
        await voice_trace_store.append(
            call_id,
            "call_ended",
            {
                "duration_seconds": duration_seconds,
                "status": "completed",
            },
        )
        events = await voice_trace_store.load(call_id)
        summary = summarize_voice_call(metadata, context, events, duration_seconds)
        evaluation = evaluate_voice_call(metadata, context, events, summary, duration_seconds)
        try:
            await _persist_call_summary(
                metadata=metadata,
                context=context,
                summary_text=summary.text,
                disposition=summary.disposition,
                duration_seconds=duration_seconds,
                tool_names=summary.tool_names,
                approvals_requested=summary.approvals_requested,
            )
        except Exception:
            logger.exception("Failed to persist voice call summary for %s", call_id)
        try:
            await _persist_call_review(
                metadata=metadata,
                context=context,
                summary=summary,
                evaluation=evaluation,
                duration_seconds=duration_seconds,
            )
        except Exception:
            logger.exception("Failed to persist voice review snapshot for %s", call_id)
        try:
            await _send_owner_summary(metadata, summary.text)
        except Exception:
            logger.exception("Failed to send owner voice summary for %s", call_id)
        await session.close()
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.close()


async def _persist_call_summary(
    *,
    metadata: VoiceCallMetadata,
    context: SessionContext | None,
    summary_text: str,
    disposition: str,
    duration_seconds: int,
    tool_names: list[str],
    approvals_requested: int,
) -> None:
    family_id = metadata.family_id or (context.family_id if context else "")
    contact_id = metadata.contact_id or (context.voice_contact_id if context else None)
    direction = "inbound" if metadata.call_type == "inbound" else "outbound"
    from src.core.models.enums import InteractionDirection

    await record_call_summary(
        family_id=family_id,
        contact_id=contact_id,
        direction=(
            InteractionDirection.inbound
            if direction == "inbound"
            else InteractionDirection.outbound
        ),
        summary_text=summary_text,
        duration_seconds=duration_seconds,
        caller_phone=metadata.from_phone or metadata.to_phone,
        meta={
            "voice_disposition": disposition,
            "voice_tool_names": tool_names,
            "voice_approvals_requested": approvals_requested,
            "voice_auth_state": context.voice_auth_state if context else "unbound",
        },
    )


async def _persist_call_review(
    *,
    metadata: VoiceCallMetadata,
    context: SessionContext | None,
    summary,
    evaluation,
    duration_seconds: int,
) -> None:
    caller = (
        (context.voice_contact_name if context else None)
        or metadata.contact_name
        or metadata.from_phone
        or metadata.to_phone
        or "unknown caller"
    )
    review = VoiceCallReview(
        call_id=metadata.call_id,
        created_at=datetime.now(UTC).isoformat(),
        call_type=metadata.call_type,
        caller=caller,
        duration_seconds=duration_seconds,
        disposition=summary.disposition,
        summary_text=summary.text,
        tool_names=summary.tool_names,
        approvals_requested=summary.approvals_requested,
        auth_state=context.voice_auth_state if context else "unbound",
        qa_score=evaluation.score,
        qa_status=evaluation.qa_status,
        qa_flags=evaluation.flags,
        qa_notes=evaluation.notes,
        event_counts=evaluation.event_counts,
    )
    await voice_review_store.save(review)


async def _send_owner_summary(metadata: VoiceCallMetadata, summary_text: str) -> None:
    owner_telegram_id = metadata.owner_telegram_id
    if not owner_telegram_id:
        return

    from api import main as api_main

    if api_main.gateway is None:
        return

    await api_main.gateway.send(
        OutgoingMessage(
            text=summary_text,
            chat_id=owner_telegram_id,
        )
    )
