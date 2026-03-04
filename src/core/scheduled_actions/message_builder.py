"""Message and button helpers for scheduled action delivery."""

from __future__ import annotations

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.core.config import settings
from src.core.formatting import md_to_telegram_html
from src.core.models.enums import ActionStatus
from src.core.models.scheduled_action import ScheduledAction
from src.core.scheduled_actions.i18n import t
from src.gateway.telegram import _split_message


def _snooze_minutes(action: ScheduledAction) -> int:
    raw = (action.schedule_config or {}).get("snooze_minutes", 10)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 10
    return max(1, min(value, 1440))


def build_action_buttons(action: ScheduledAction) -> list[dict]:
    language = action.language or "en"
    action_id = str(action.id)
    snooze = _snooze_minutes(action)

    if action.status == ActionStatus.paused:
        return [
            {"text": t("btn_resume", language), "callback": f"sched:resume:{action_id}"},
            {"text": t("btn_run_now", language), "callback": f"sched:run:{action_id}"},
        ]

    if action.status == ActionStatus.active:
        return [
            {
                "text": t("btn_snooze", language, minutes=snooze),
                "callback": f"sched:snooze:{action_id}",
            },
            {"text": t("btn_run_now", language), "callback": f"sched:run:{action_id}"},
            {"text": t("btn_pause", language), "callback": f"sched:pause:{action_id}"},
        ]

    return []


async def send_action_message(
    telegram_id: int,
    text: str,
    *,
    buttons: list[dict] | None = None,
) -> None:
    """Send an HTML message with optional inline buttons."""
    builder = InlineKeyboardBuilder()
    for btn in buttons or []:
        callback = btn.get("callback")
        if callback:
            builder.button(text=btn.get("text", "Button"), callback_data=callback)
    reply_markup = None
    if buttons:
        builder.adjust(2)
        reply_markup = builder.as_markup()

    final_text = md_to_telegram_html(text)
    chunks = _split_message(final_text, max_len=4000)

    bot = Bot(token=settings.telegram_bot_token)
    try:
        for idx, chunk in enumerate(chunks):
            chunk_markup = reply_markup if idx == len(chunks) - 1 else None
            await bot.send_message(
                chat_id=telegram_id,
                text=chunk,
                parse_mode="HTML",
                reply_markup=chunk_markup,
            )
    finally:
        await bot.session.close()

