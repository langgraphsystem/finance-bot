"""Message and button helpers for scheduled action delivery."""

from __future__ import annotations

from src.core.config import settings
from src.core.models.enums import ActionStatus
from src.core.models.scheduled_action import ScheduledAction
from src.core.scheduled_actions.i18n import t
from src.gateway.factory import get_gateway
from src.gateway.types import OutgoingMessage


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
    """Send scheduled action message via TelegramGateway transport."""
    _ = settings.telegram_bot_token  # Ensures token is configured for telegram gateway.
    gateway = get_gateway("telegram")
    message = OutgoingMessage(
        text=text,
        chat_id=str(telegram_id),
        buttons=buttons,
        parse_mode="HTML",
        channel="telegram",
    )
    try:
        await gateway.send(message)
    finally:
        bot = getattr(gateway, "bot", None)
        session = getattr(bot, "session", None)
        if session is not None and hasattr(session, "close"):
            await session.close()
