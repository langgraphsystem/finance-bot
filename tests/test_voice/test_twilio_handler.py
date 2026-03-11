"""Tests for Twilio voice handler utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.voice.twilio_handler import (
    build_inbound_prompt,
    build_inbound_tools,
    build_outbound_prompt,
    build_outbound_tools,
    generate_inbound_twiml,
    generate_outbound_twiml,
    initiate_outbound_call,
)


def test_generate_inbound_twiml():
    ws_url = "wss://example.com/ws/voice/inbound"
    twiml = generate_inbound_twiml(ws_url)

    assert "<Response>" in twiml
    assert "<Connect>" in twiml
    assert "<Stream" in twiml
    assert ws_url in twiml


def test_generate_outbound_twiml():
    ws_url = "wss://example.com/ws/voice/outbound/123"
    twiml = generate_outbound_twiml(ws_url)

    assert "<Response>" in twiml
    assert "<Stream" in twiml
    assert ws_url in twiml


def test_inbound_tools_has_required_functions():
    tools = build_inbound_tools()

    names = {tool["name"] for tool in tools}
    assert "create_booking" in names
    assert "find_available_slots" in names
    assert "take_message" in names
    assert "request_verification" in names
    assert "verify_caller" in names
    assert "handoff_to_owner" in names
    assert "schedule_callback" in names


def test_outbound_tools_has_required_functions():
    tools = build_outbound_tools()

    names = {tool["name"] for tool in tools}
    assert "confirm_booking" in names
    assert "reschedule_booking" in names
    assert "handoff_to_owner" in names
    assert "schedule_callback" in names


def test_inbound_tools_have_parameters():
    tools = build_inbound_tools()
    for tool in tools:
        assert "parameters" in tool
        assert "properties" in tool["parameters"]


def test_outbound_tools_have_parameters():
    tools = build_outbound_tools()
    for tool in tools:
        assert "parameters" in tool
        assert "properties" in tool["parameters"]


def test_build_prompts_use_metadata():
    metadata = MagicMock()
    metadata.owner_name = "David"
    metadata.business_name = "North Star Plumbing"
    metadata.services = "plumbing, drain cleaning"
    metadata.hours = "Mon-Fri 9-5"
    metadata.contact_name = "John"
    metadata.call_purpose = "confirm tomorrow's appointment"
    metadata.call_purpose_short = "confirm your appointment"

    inbound = build_inbound_prompt(metadata)
    outbound = build_outbound_prompt(metadata)

    assert "North Star Plumbing" in inbound
    assert "AI assistant" in inbound
    assert "John" in outbound
    assert "confirm your appointment" in outbound


async def test_initiate_outbound_call_uses_twilio_rest_api():
    response = MagicMock()
    response.status_code = 201
    response.json.return_value = {"sid": "CA123", "status": "queued"}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False
    mock_client.post.return_value = response

    with (
        patch("src.voice.twilio_handler.voice_config.twilio_account_sid", "AC123"),
        patch("src.voice.twilio_handler.voice_config.twilio_auth_token", "token"),
        patch("src.voice.twilio_handler.voice_config.twilio_voice_number", "+15551234567"),
        patch("src.voice.twilio_handler.voice_config.public_base_url", "https://example.com"),
        patch("src.voice.twilio_handler.voice_config.ws_base_url", "wss://example.com"),
        patch(
            "src.voice.twilio_handler.voice_session_store.save",
            new_callable=AsyncMock,
        ) as mock_save,
        patch("src.voice.twilio_handler.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await initiate_outbound_call(
            to_phone="+15557654321",
            owner_name="David",
            contact_name="John",
            call_purpose="confirm tomorrow's appointment",
            family_id="family-123",
        )

    assert result["call_sid"] == "CA123"
    mock_save.assert_called_once()
    mock_client.post.assert_awaited_once()
    payload = mock_client.post.await_args.kwargs["data"]
    assert payload["Url"].startswith("https://example.com/webhook/voice/outbound/")
    assert payload["StatusCallback"].startswith("https://example.com/webhook/voice/status")
