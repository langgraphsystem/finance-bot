"""Tests for generic computer-use prompt selection and keyboard handling."""

from src.tools.computer_use_service import (
    _classify_task,
    _key_combo,
    build_system_prompt,
)


def test_classify_task_shopping():
    assert _classify_task("amazon.com", "buy paper towels from my cart") == "shopping"


def test_classify_task_food_delivery():
    assert _classify_task("doordash.com", "order sushi for dinner") == "food_delivery"


def test_classify_task_taxi():
    assert _classify_task("uber.com", "book a ride to the airport") == "taxi"


def test_classify_task_travel():
    assert _classify_task("booking.com", "check my reservation status") == "travel"


def test_classify_task_account_lookup_without_known_domain():
    assert _classify_task("example.com", "check order status and refunds") == "account"


def test_build_system_prompt_shopping_includes_checkout_fields():
    prompt = build_system_prompt("amazon.com", "buy Sony WH-1000XM5 headphones")

    assert "Task type: shopping / product purchase." in prompt
    assert "Checkout state:" in prompt
    assert "Price:" in prompt


def test_build_system_prompt_food_includes_eta_and_fees():
    prompt = build_system_prompt("ubereats.com", "order tacos for dinner")

    assert "Task type: food / grocery delivery." in prompt
    assert "Fees/Tip:" in prompt
    assert "ETA:" in prompt


def test_build_system_prompt_taxi_includes_fare_and_confirmation():
    prompt = build_system_prompt("lyft.com", "call a ride home")

    assert "Task type: taxi / ride-hailing." in prompt
    assert "Fare:" in prompt
    assert "Confirmation state:" in prompt


def test_blocked_key_combo_returns_none():
    assert _key_combo(["CTRL", "L"]) is None


def test_key_combo_maps_known_keys():
    assert _key_combo(["CTRL", "SHIFT", "N"]) == "Control+Shift+N"
