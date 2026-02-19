"""Tests for proactivity triggers."""

from src.proactivity.triggers import (
    DATA_TRIGGERS,
    TIME_TRIGGERS,
    BudgetAlert,
    DataTrigger,
    DeadlineWarning,
    OverdueInvoice,
    TimeTrigger,
)


def test_time_trigger_fields():
    t = TimeTrigger(name="morning", hour=7, action="send_morning")
    assert t.name == "morning"
    assert t.hour == 7
    assert t.action == "send_morning"


def test_data_trigger_base():
    d = DataTrigger(name="test", action="test_action")
    assert d.name == "test"
    assert d.action == "test_action"


async def test_data_trigger_base_returns_empty():
    d = DataTrigger(name="test", action="test_action")
    result = await d.check("uid", "fid")
    assert result == {}


def test_data_triggers_registered():
    assert len(DATA_TRIGGERS) == 3
    names = {t.name for t in DATA_TRIGGERS}
    assert names == {"task_deadline", "budget_alert", "overdue_invoice"}


def test_time_triggers_registered():
    assert len(TIME_TRIGGERS) == 2
    names = {t.name for t in TIME_TRIGGERS}
    assert names == {"morning_brief", "evening_recap"}


def test_deadline_warning_instance():
    d = DeadlineWarning()
    assert d.name == "task_deadline"
    assert d.action == "deadline_warning"


def test_budget_alert_instance():
    b = BudgetAlert()
    assert b.name == "budget_alert"
    assert b.action == "budget_warning"


def test_overdue_invoice_instance():
    o = OverdueInvoice()
    assert o.name == "overdue_invoice"
    assert o.action == "invoice_reminder"
