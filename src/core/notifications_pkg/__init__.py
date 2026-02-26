"""Unified notification service — templates, dispatch, and financial alerts."""

from src.core.notifications_pkg.dispatch import (
    is_send_window,
    mark_daily_once,
    normalize_timezone,
    now_in_timezone,
    send_telegram_message,
)
from src.core.notifications_pkg.templates import (
    get_financial_text,
    get_life_text,
    get_reminder_label,
)

__all__ = [
    "get_financial_text",
    "get_life_text",
    "get_reminder_label",
    "is_send_window",
    "mark_daily_once",
    "normalize_timezone",
    "now_in_timezone",
    "send_telegram_message",
]
