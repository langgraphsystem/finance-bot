"""Run voice tool calls through the same skill/backend surface as the bot."""

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.booking import Booking
from src.core.models.enums import BookingStatus
from src.core.request_context import reset_family_context, set_family_context
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage
from src.skills.base import SkillResult
from src.voice.session_store import VoiceCallMetadata

logger = logging.getLogger(__name__)

ToolExecutor = Callable[[dict[str, str | bool | None]], Awaitable[dict[str, object]]]


class VoiceToolAdapter:
    """Dispatch voice tool calls to the existing skill/backend layer."""

    def __init__(self, context: SessionContext | None, metadata: VoiceCallMetadata) -> None:
        self.context = context
        self.metadata = metadata

    async def handle_tool_call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        """Execute a tool call inside the existing bot runtime surface."""
        if self.context is None:
            return {
                "ok": False,
                "message": (
                    "Voice is connected, but this phone line is not linked "
                    "to a bot owner account yet."
                ),
            }

        handlers: dict[str, Callable[[dict[str, object]], Awaitable[dict[str, object]]]] = {
            "receptionist": self._run_receptionist,
            "create_booking": self._run_create_booking,
            "find_available_slots": self._run_find_available_slots,
            "find_contact": self._run_find_contact,
            "take_message": self._run_take_message,
            "create_task": self._run_create_task,
            "set_reminder": self._run_set_reminder,
            "create_event": self._run_create_event,
            "reschedule_event": self._run_reschedule_event,
            "cancel_booking": self._run_cancel_booking,
            "reschedule_booking": self._run_reschedule_booking,
            "confirm_booking": self._run_confirm_booking,
            "send_to_client": self._run_send_to_client,
        }

        handler = handlers.get(name)
        if handler is None:
            return {"ok": False, "message": f"Unsupported voice tool: {name}"}
        return await handler(arguments)

    async def _run_skill(
        self,
        intent: str,
        message_text: str,
        intent_data: dict[str, object],
    ) -> dict[str, object]:
        from src.core.router import get_registry

        if self.context is None:
            return {"ok": False, "message": "Voice context is unavailable."}

        registry = get_registry()
        skill = registry.get(intent)
        if skill is None:
            return {"ok": False, "message": f"Skill not registered for intent: {intent}"}

        message = IncomingMessage(
            id=str(uuid.uuid4()),
            user_id=self.context.channel_user_id or self.context.user_id,
            chat_id=self.metadata.call_id,
            type=MessageType.text,
            text=message_text,
            channel="voice",
            channel_user_id=self.context.channel_user_id,
            language=self.context.language,
        )

        token = set_family_context(self.context.family_id, self.context.user_id)
        try:
            result = await skill.execute(message, self.context, intent_data)
        finally:
            reset_family_context(token)

        return await self._format_skill_result(result)

    async def _format_skill_result(self, result: SkillResult) -> dict[str, object]:
        payload: dict[str, object] = {"ok": True, "message": result.response_text}

        if self._is_telegram_confirmation(result.buttons):
            sent = await self._send_telegram_follow_up(result)
            payload["approval_requested"] = sent
            if sent:
                payload["message"] = (
                    f"{result.response_text}\n\n"
                    "I sent the confirmation request to Telegram for final approval."
                )
        return payload

    async def _send_telegram_follow_up(self, result: SkillResult) -> bool:
        owner_telegram_id = self.metadata.owner_telegram_id
        if not owner_telegram_id:
            return False

        from api import main as api_main

        if api_main.gateway is None:
            return False

        buttons = []
        for button in result.buttons or []:
            callback = button.get("callback") or button.get("callback_data")
            if not callback:
                continue
            buttons.append({"text": button.get("text", "Confirm"), "callback": callback})

        if not buttons:
            return False

        await api_main.gateway.send(
            OutgoingMessage(
                text=result.response_text,
                chat_id=owner_telegram_id,
                buttons=buttons,
            )
        )
        return True

    @staticmethod
    def _is_telegram_confirmation(buttons: list[dict] | None) -> bool:
        if not buttons:
            return False
        callbacks = [button.get("callback") or button.get("callback_data") for button in buttons]
        return all(
            isinstance(callback, str)
            and (
                callback.startswith("confirm_action:")
                or callback.startswith("cancel_action:")
            )
            for callback in callbacks
        )

    def _build_iso_datetime(self, date_text: str | None, time_text: str | None) -> str | None:
        if not date_text or not time_text:
            return None
        try:
            tz = ZoneInfo(self.context.timezone if self.context else "UTC")
            dt = datetime.fromisoformat(f"{date_text}T{time_text}:00")
            return dt.replace(tzinfo=tz).isoformat()
        except ValueError:
            return None

    async def _run_receptionist(self, arguments: dict[str, object]) -> dict[str, object]:
        question = str(arguments.get("question") or "Help the caller.")
        intent_data = {}
        topic = arguments.get("receptionist_topic")
        if isinstance(topic, str) and topic:
            intent_data["receptionist_topic"] = topic
        return await self._run_skill("receptionist", question, intent_data)

    async def _run_create_booking(self, arguments: dict[str, object]) -> dict[str, object]:
        date_text = str(arguments.get("date") or "")
        time_text = str(arguments.get("time") or "")
        service = str(arguments.get("service") or "appointment")
        client_name = str(arguments.get("client_name") or "")
        phone = str(arguments.get("phone") or self.metadata.from_phone or "")
        address = str(arguments.get("address") or "")
        message_text = f"Book {service} for {client_name} on {date_text} at {time_text}".strip()
        return await self._run_skill(
            "create_booking",
            message_text,
            {
                "booking_title": service,
                "booking_service_type": service,
                "contact_name": client_name,
                "phone": phone,
                "booking_location": address or None,
                "event_datetime": self._build_iso_datetime(date_text, time_text),
            },
        )

    async def _run_find_available_slots(self, arguments: dict[str, object]) -> dict[str, object]:
        date_text = str(arguments.get("date") or "")
        return await self._run_skill(
            "find_free_slots",
            f"Find free slots for {date_text}".strip(),
            {"date": date_text},
        )

    async def _run_find_contact(self, arguments: dict[str, object]) -> dict[str, object]:
        query = str(arguments.get("search_query") or "")
        return await self._run_skill(
            "find_contact",
            query,
            {"search_query": query},
        )

    async def _run_take_message(self, arguments: dict[str, object]) -> dict[str, object]:
        caller_name = str(arguments.get("caller_name") or self.metadata.from_phone or "caller")
        callback_number = str(arguments.get("callback_number") or self.metadata.from_phone or "")
        message_body = str(arguments.get("message") or "")
        description = (
            f"Call back {caller_name}"
            f"{f' at {callback_number}' if callback_number else ''}: {message_body}"
        )
        return await self._run_skill(
            "create_task",
            description,
            {
                "task_title": f"Call back {caller_name}",
                "description": description,
            },
        )

    async def _run_create_task(self, arguments: dict[str, object]) -> dict[str, object]:
        title = str(arguments.get("task_title") or "")
        description = str(arguments.get("description") or title)
        return await self._run_skill(
            "create_task",
            description,
            {"task_title": title, "description": description},
        )

    async def _run_set_reminder(self, arguments: dict[str, object]) -> dict[str, object]:
        title = str(arguments.get("task_title") or "")
        deadline = arguments.get("task_deadline")
        intent_data: dict[str, object] = {"task_title": title}
        if isinstance(deadline, str) and deadline:
            intent_data["task_deadline"] = deadline
        return await self._run_skill("set_reminder", title, intent_data)

    async def _run_create_event(self, arguments: dict[str, object]) -> dict[str, object]:
        title = str(arguments.get("event_title") or arguments.get("title") or "appointment")
        date_text = str(arguments.get("date") or "")
        time_text = str(arguments.get("time") or "")
        location = str(arguments.get("location") or "")
        return await self._run_skill(
            "create_event",
            f"Create event {title}",
            {
                "event_title": title,
                "event_datetime": self._build_iso_datetime(date_text, time_text),
                "location": location or None,
            },
        )

    async def _run_reschedule_event(self, arguments: dict[str, object]) -> dict[str, object]:
        event_name = str(arguments.get("event_name") or "")
        date_text = str(arguments.get("new_date") or "")
        time_text = str(arguments.get("new_time") or "")
        return await self._run_skill(
            "reschedule_event",
            f"Reschedule {event_name}",
            {
                "event_name": event_name,
                "event_datetime": self._build_iso_datetime(date_text, time_text),
            },
        )

    async def _run_cancel_booking(self, arguments: dict[str, object]) -> dict[str, object]:
        search = str(arguments.get("booking_title") or arguments.get("contact_name") or "")
        return await self._run_skill(
            "cancel_booking",
            f"Cancel booking {search}".strip(),
            {
                "booking_title": arguments.get("booking_title"),
                "contact_name": arguments.get("contact_name"),
                "description": search,
            },
        )

    async def _run_send_to_client(self, arguments: dict[str, object]) -> dict[str, object]:
        contact_name = str(arguments.get("contact_name") or "")
        description = str(arguments.get("description") or "")
        return await self._run_skill(
            "send_to_client",
            description,
            {
                "contact_name": contact_name,
                "description": description,
            },
        )

    async def _run_confirm_booking(self, arguments: dict[str, object]) -> dict[str, object]:
        if self.context is None:
            return {"ok": False, "message": "Voice context is unavailable."}

        booking_id = str(arguments.get("booking_id") or "")
        confirmed = bool(arguments.get("confirmed"))
        if not booking_id:
            return {"ok": False, "message": "Booking id is required to confirm a booking."}

        try:
            booking_uuid = uuid.UUID(booking_id)
        except ValueError:
            return {"ok": False, "message": "Booking id is invalid."}

        token = set_family_context(self.context.family_id, self.context.user_id)
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(Booking).where(
                        Booking.id == booking_uuid,
                        Booking.family_id == uuid.UUID(self.context.family_id),
                    )
                )
                booking = result.scalar_one_or_none()
                if booking is None:
                    return {"ok": False, "message": "Booking not found."}

                if confirmed:
                    await session.execute(
                        update(Booking)
                        .where(Booking.id == booking.id)
                        .values(
                            status=BookingStatus.confirmed,
                            confirmation_sent=True,
                        )
                    )
                    await session.commit()
                    return {
                        "ok": True,
                        "message": f"Confirmed booking: {booking.title}",
                    }
        finally:
            reset_family_context(token)

        return await self._run_skill(
            "create_task",
            f"Follow up on declined booking {booking_id}",
            {
                "task_title": "Follow up on declined booking",
                "description": f"Client declined booking {booking_id} on a voice call.",
            },
        )

    async def _run_reschedule_booking(self, arguments: dict[str, object]) -> dict[str, object]:
        if self.context is None:
            return {"ok": False, "message": "Voice context is unavailable."}

        booking_id = str(arguments.get("booking_id") or "")
        date_text = str(arguments.get("new_date") or "")
        time_text = str(arguments.get("new_time") or "")
        new_start_iso = self._build_iso_datetime(date_text, time_text)

        if booking_id and new_start_iso:
            try:
                booking_uuid = uuid.UUID(booking_id)
                new_start = datetime.fromisoformat(new_start_iso)
            except ValueError:
                return {"ok": False, "message": "Booking id or new time is invalid."}

            token = set_family_context(self.context.family_id, self.context.user_id)
            try:
                async with async_session() as session:
                    result = await session.execute(
                        select(Booking).where(
                            Booking.id == booking_uuid,
                            Booking.family_id == uuid.UUID(self.context.family_id),
                        )
                    )
                    booking = result.scalar_one_or_none()
                    if booking is None:
                        return {"ok": False, "message": "Booking not found."}

                    duration = booking.end_at - booking.start_at
                    await session.execute(
                        update(Booking)
                        .where(Booking.id == booking.id)
                        .values(
                            start_at=new_start,
                            end_at=new_start + duration,
                            status=BookingStatus.scheduled,
                            reminder_sent=False,
                            confirmation_sent=False,
                        )
                    )
                    await session.commit()
                    return {
                        "ok": True,
                        "message": (
                            f"Rescheduled booking: {booking.title}\n"
                            f"New time: {new_start.strftime('%b %d, %I:%M %p')}"
                        ),
                    }
            finally:
                reset_family_context(token)

        search = str(arguments.get("contact_name") or arguments.get("booking_title") or "")
        return await self._run_skill(
            "reschedule_booking",
            f"Reschedule booking {search}".strip(),
            {
                "booking_title": arguments.get("booking_title"),
                "contact_name": arguments.get("contact_name"),
                "event_datetime": new_start_iso,
            },
        )
