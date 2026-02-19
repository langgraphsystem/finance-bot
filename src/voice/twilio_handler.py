"""Twilio Voice webhook handlers and WebSocket media stream bridge.

Handles:
- POST /webhook/voice/inbound — TwiML response to connect to media stream
- POST /webhook/voice/outbound — initiate outbound call
- WebSocket /ws/voice/{call_type}/{call_id} — bridge Twilio <-> OpenAI Realtime
"""

import logging
import uuid
from typing import Any

from src.voice.config import voice_config

logger = logging.getLogger(__name__)

# System prompts for different call types
INBOUND_SYSTEM_PROMPT = """\
You are {owner_name}'s AI assistant answering a phone call.
Be professional, friendly, and concise.
Your job: answer questions, book appointments, take messages.

Business info:
- Name: {business_name}
- Services: {services}
- Available hours: {hours}

IMPORTANT:
- Start with: "Hi, thanks for calling {business_name}. {owner_name} is \
unavailable right now — I can help you schedule an appointment. How can I help?"
- Always confirm booking details before finalizing.
- If unsure, take a message and promise {owner_name} will call back.
- Be clear that you are an AI assistant."""

OUTBOUND_SYSTEM_PROMPT = """\
You are calling {contact_name} on behalf of {owner_name}.
Purpose: {call_purpose}

IMPORTANT:
- Start with: "Hi {contact_name}, this is {owner_name}'s assistant calling to \
{call_purpose_short}."
- Be brief and professional.
- Confirm any changes and say goodbye politely."""


def generate_inbound_twiml(ws_url: str) -> str:
    """Generate TwiML to connect inbound call to WebSocket media stream."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Connect><Stream url="' + ws_url + '" /></Connect>'
        "</Response>"
    )


def generate_outbound_twiml(ws_url: str) -> str:
    """Generate TwiML for outbound call with media stream."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Connect><Stream url="' + ws_url + '" /></Connect>'
        "</Response>"
    )


async def initiate_outbound_call(
    to_phone: str,
    owner_name: str,
    contact_name: str,
    call_purpose: str,
    family_id: str,
) -> dict[str, Any]:
    """Start an outbound call via Twilio REST API.

    Returns call metadata (call_sid, status).
    Requires twilio package installed.
    """
    if not voice_config.twilio_configured:
        return {"error": "Twilio not configured. Set TWILIO_ACCOUNT_SID, AUTH_TOKEN, VOICE_NUMBER."}

    try:
        from twilio.rest import Client

        client = Client(voice_config.twilio_account_sid, voice_config.twilio_auth_token)

        call_id = str(uuid.uuid4())
        ws_url = f"{voice_config.ws_base_url}/ws/voice/outbound/{call_id}"
        twiml = generate_outbound_twiml(ws_url)

        call = client.calls.create(
            to=to_phone,
            from_=voice_config.twilio_voice_number,
            twiml=twiml,
            status_callback=f"{voice_config.ws_base_url}/webhook/voice/status",
            status_callback_event=["completed", "failed", "no-answer"],
        )

        return {
            "call_sid": call.sid,
            "call_id": call_id,
            "status": call.status,
            "to": to_phone,
            "contact_name": contact_name,
        }
    except ImportError:
        logger.warning("twilio package not installed")
        return {"error": "twilio package not installed"}
    except Exception as e:
        logger.error("Failed to initiate outbound call: %s", e)
        return {"error": str(e)}


def build_inbound_tools() -> list[dict[str, Any]]:
    """Tools available to the AI during inbound calls."""
    return [
        {
            "type": "function",
            "name": "create_booking",
            "description": "Book an appointment for the caller",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string", "description": "Caller's name"},
                    "service": {"type": "string", "description": "Service requested"},
                    "date": {"type": "string", "description": "Date (YYYY-MM-DD)"},
                    "time": {"type": "string", "description": "Time (HH:MM)"},
                    "phone": {"type": "string", "description": "Caller's phone"},
                    "address": {"type": "string", "description": "Service address"},
                },
                "required": ["client_name", "service", "date", "time"],
            },
        },
        {
            "type": "function",
            "name": "find_available_slots",
            "description": "Check available appointment slots for a date",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date to check (YYYY-MM-DD)"},
                },
                "required": ["date"],
            },
        },
        {
            "type": "function",
            "name": "take_message",
            "description": "Record a message for the business owner",
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {"type": "string"},
                    "message": {"type": "string"},
                    "callback_number": {"type": "string"},
                },
                "required": ["message"],
            },
        },
    ]


def build_outbound_tools() -> list[dict[str, Any]]:
    """Tools available to the AI during outbound calls."""
    return [
        {
            "type": "function",
            "name": "confirm_booking",
            "description": "Confirm that the client will attend their appointment",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "confirmed": {"type": "boolean"},
                },
                "required": ["confirmed"],
            },
        },
        {
            "type": "function",
            "name": "reschedule_booking",
            "description": "Reschedule the appointment to a new time",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "new_date": {"type": "string"},
                    "new_time": {"type": "string"},
                },
                "required": ["new_date", "new_time"],
            },
        },
    ]
