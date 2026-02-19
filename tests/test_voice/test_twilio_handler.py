"""Tests for Twilio voice handler utilities."""

from src.voice.twilio_handler import (
    build_inbound_tools,
    build_outbound_tools,
    generate_inbound_twiml,
    generate_outbound_twiml,
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

    names = {t["name"] for t in tools}
    assert "create_booking" in names
    assert "find_available_slots" in names
    assert "take_message" in names


def test_outbound_tools_has_required_functions():
    tools = build_outbound_tools()

    names = {t["name"] for t in tools}
    assert "confirm_booking" in names
    assert "reschedule_booking" in names


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
