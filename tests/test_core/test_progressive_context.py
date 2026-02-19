"""Tests for Progressive Context Disclosure heuristic."""

from src.core.memory.context import needs_heavy_context


def test_simple_expense_no_heavy_context():
    assert not needs_heavy_context("100 кофе", "add_expense")


def test_simple_amount_no_heavy_context():
    assert not needs_heavy_context("50.5 uber", "add_expense")


def test_confirmation_no_heavy_context():
    assert not needs_heavy_context("ок", "general_chat")
    assert not needs_heavy_context("спасибо", "general_chat")
    assert not needs_heavy_context("thanks", "general_chat")
    assert not needs_heavy_context("да", "general_chat")


def test_greeting_no_heavy_context():
    assert not needs_heavy_context("привет", "general_chat")
    assert not needs_heavy_context("hello", "general_chat")
    assert not needs_heavy_context("hi", "general_chat")


def test_completion_no_heavy_context():
    assert not needs_heavy_context("готово", "complete_task")
    assert not needs_heavy_context("done", "complete_task")


def test_empty_message_no_heavy_context():
    assert not needs_heavy_context("", "general_chat")


def test_always_heavy_for_analytics():
    assert needs_heavy_context("100 кофе", "query_stats")
    assert needs_heavy_context("привет", "complex_query")
    assert needs_heavy_context("ok", "query_report")
    assert needs_heavy_context("test", "deep_research")


def test_complex_signals_trigger_heavy():
    assert needs_heavy_context("сравни расходы за месяц", "add_expense")
    assert needs_heavy_context("бюджет на продукты", "add_expense")
    assert needs_heavy_context("compare this month", "general_chat")
    assert needs_heavy_context("тренд за неделю", "general_chat")
    assert needs_heavy_context("итого за месяц", "general_chat")


def test_normal_messages_default_to_heavy():
    assert needs_heavy_context("запиши расход на продукты в Walmart", "add_expense")
    assert needs_heavy_context("remind me to call Mike at 3pm", "set_reminder")


def test_phone_number_no_heavy_context():
    assert not needs_heavy_context("+1 555-123-4567", "general_chat")
