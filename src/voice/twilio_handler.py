"""Twilio voice utilities for webhooks, call setup, and prompt generation."""

import logging
import uuid
from typing import Any

import httpx

from src.voice.config import voice_config
from src.voice.session_store import VoiceCallMetadata, voice_session_store

logger = logging.getLogger(__name__)

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"

INBOUND_SYSTEM_PROMPT = """\
You are {owner_name}'s AI assistant answering a phone call.
Be professional, friendly, concise, and explicit that you are an AI assistant.
Your job is to answer questions, help with appointment requests, and take clear messages.

Business info:
- Name: {business_name}
- Services: {services}
- Available hours: {hours}

IMPORTANT:
- Start with: "Hi, thanks for calling {business_name}. This is
  {owner_name}'s AI assistant. How can I help?"
- Always confirm key booking or callback details before finalizing.
- If you cannot complete a request, take a message and explain that
  {owner_name} will follow up.
"""

OUTBOUND_SYSTEM_PROMPT = """\
You are calling {contact_name} on behalf of {owner_name}.
Purpose: {call_purpose}

IMPORTANT:
- Start with: "Hi {contact_name}, this is {owner_name}'s AI assistant
  calling to {call_purpose_short}."
- Be brief and professional.
- Confirm any decisions before ending the call.
"""


def generate_inbound_twiml(ws_url: str) -> str:
    """Generate TwiML to connect an inbound call to the websocket bridge."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Connect><Stream url="' + ws_url + '" /></Connect>'
        "</Response>"
    )


def generate_outbound_twiml(ws_url: str) -> str:
    """Generate TwiML to connect an outbound call to the websocket bridge."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Connect><Stream url="' + ws_url + '" /></Connect>'
        "</Response>"
    )


def build_inbound_prompt(metadata: VoiceCallMetadata) -> str:
    """Render the system prompt for inbound calls."""
    return INBOUND_SYSTEM_PROMPT.format(
        owner_name=metadata.owner_name,
        business_name=metadata.business_name,
        services=metadata.services,
        hours=metadata.hours,
    )


def build_outbound_prompt(metadata: VoiceCallMetadata) -> str:
    """Render the system prompt for outbound calls."""
    return OUTBOUND_SYSTEM_PROMPT.format(
        contact_name=metadata.contact_name or "there",
        owner_name=metadata.owner_name,
        call_purpose=metadata.call_purpose or "follow up",
        call_purpose_short=metadata.call_purpose_short or "follow up",
    )


async def initiate_outbound_call(
    to_phone: str,
    owner_name: str,
    contact_name: str,
    call_purpose: str,
    family_id: str,
    contact_id: str = "",
    owner_telegram_id: str | None = None,
) -> dict[str, Any]:
    """Start an outbound call via Twilio REST API."""
    if not voice_config.twilio_configured:
        return {
            "error": "Twilio not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
            "and TWILIO_PHONE_NUMBER."
        }

    call_id = str(uuid.uuid4())
    metadata = VoiceCallMetadata(
        call_id=call_id,
        call_type="outbound",
        owner_name=owner_name,
        business_name=voice_config.default_business_name,
        services=voice_config.default_services,
        hours=voice_config.default_business_hours,
        owner_telegram_id=owner_telegram_id or voice_config.default_owner_telegram_id,
        to_phone=to_phone,
        contact_id=contact_id,
        contact_name=contact_name,
        call_purpose=call_purpose,
        call_purpose_short=call_purpose,
        family_id=family_id,
    )
    await voice_session_store.save(metadata)

    ws_url = voice_config.build_websocket_url("outbound", call_id)
    payload: dict[str, str] = {
        "To": to_phone,
        "From": voice_config.twilio_voice_number,
        "StatusCallback": voice_config.build_status_callback_url(call_id),
        "StatusCallbackEvent": "initiated ringing answered completed failed no-answer busy",
    }
    if voice_config.public_base_url:
        payload["Url"] = voice_config.build_outbound_webhook_url(call_id)
    else:
        payload["Twiml"] = generate_outbound_twiml(ws_url)

    async with httpx.AsyncClient(
        base_url=TWILIO_API_BASE,
        auth=(voice_config.twilio_account_sid, voice_config.twilio_auth_token),
        timeout=10.0,
    ) as client:
        response = await client.post(
            f"/Accounts/{voice_config.twilio_account_sid}/Calls.json",
            data=payload,
        )

    if response.status_code not in (200, 201):
        logger.error(
            "Twilio outbound call failed: %s %s",
            response.status_code,
            response.text[:200],
        )
        return {"error": response.text}

    data = response.json()
    return {
        "call_sid": data.get("sid", ""),
        "call_id": call_id,
        "status": data.get("status", ""),
        "to": to_phone,
        "contact_name": contact_name,
    }


def build_inbound_tools() -> list[dict[str, Any]]:
    """Tools exposed to the realtime model during inbound calls."""
    return [
        {
            "type": "function",
            "name": "receptionist",
            "description": "Answer business questions using the configured profile",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Caller question"},
                    "receptionist_topic": {
                        "type": "string",
                        "description": "Optional topic: services, hours, faq",
                    },
                },
            },
        },
        {
            "type": "function",
            "name": "create_booking",
            "description": "Book an appointment for the caller",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string", "description": "Caller's name"},
                    "service": {"type": "string", "description": "Requested service"},
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD"},
                    "time": {"type": "string", "description": "Time in HH:MM"},
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
                    "date": {"type": "string", "description": "Date to check in YYYY-MM-DD"},
                },
                "required": ["date"],
            },
        },
        {
            "type": "function",
            "name": "find_contact",
            "description": "Look up a contact in the CRM by name or phone",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_query": {"type": "string", "description": "Name or phone"},
                },
                "required": ["search_query"],
            },
        },
        {
            "type": "function",
            "name": "take_message",
            "description": "Record a callback message for the business owner",
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
        {
            "type": "function",
            "name": "create_task",
            "description": "Create a follow-up task for the owner",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_title": {"type": "string", "description": "Task title"},
                    "description": {"type": "string", "description": "Task details"},
                },
                "required": ["task_title"],
            },
        },
        {
            "type": "function",
            "name": "set_reminder",
            "description": "Set a reminder for the owner",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_title": {"type": "string", "description": "Reminder title"},
                    "task_deadline": {
                        "type": "string",
                        "description": "Reminder datetime in ISO format",
                    },
                },
                "required": ["task_title"],
            },
        },
    ]


def build_outbound_tools() -> list[dict[str, Any]]:
    """Tools exposed to the realtime model during outbound calls."""
    return [
        {
            "type": "function",
            "name": "confirm_booking",
            "description": "Confirm whether the client will attend the appointment",
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
            "description": "Reschedule an appointment to a new date and time",
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
        {
            "type": "function",
            "name": "send_to_client",
            "description": "Prepare a follow-up message for a client",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_name": {"type": "string", "description": "Client name"},
                    "description": {"type": "string", "description": "Message to send"},
                },
                "required": ["contact_name", "description"],
            },
        },
    ]
