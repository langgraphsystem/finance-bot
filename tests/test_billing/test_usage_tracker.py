"""Tests for usage tracker."""

from decimal import Decimal

from src.billing.usage_tracker import _estimate_cost


def test_estimate_cost_claude_haiku():
    cost = _estimate_cost("claude-haiku-4-5", tokens_in=1000, tokens_out=500)
    assert isinstance(cost, Decimal)
    assert cost > 0
    assert cost < Decimal("0.01")


def test_estimate_cost_claude_opus():
    cost = _estimate_cost("claude-opus-4-6", tokens_in=1000, tokens_out=500)
    assert cost > _estimate_cost("claude-haiku-4-5", tokens_in=1000, tokens_out=500)


def test_estimate_cost_unknown_model():
    cost = _estimate_cost("unknown-model", tokens_in=1000, tokens_out=1000)
    assert cost > 0


def test_estimate_cost_zero_tokens():
    cost = _estimate_cost("claude-haiku-4-5", tokens_in=0, tokens_out=0)
    assert cost == Decimal("0")
