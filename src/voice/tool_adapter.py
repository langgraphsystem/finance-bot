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
from src.core.pending_actions import store_pending_action
from src.core.request_context import reset_family_context, set_family_context
from src.gateway.sms_gw import SMSGateway
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage
from src.skills.base import SkillResult
from src.voice.policy import evaluate_voice_policy
from src.voice.session_store import VoiceCallMetadata
from src.voice.verification import voice_verification_store

logger = logging.getLogger(__name__)


class VoiceToolAdapter:
    """Dispatch voice tool calls to the existing skill/backend layer."""

    def __init__(
        self,
        context: SessionContext | None,
        metadata: VoiceCallMetadata,
        *,
        enforce_policy: bool = True,
    ) -> None:
        self.context = context
        self.metadata = metadata
        self.enforce_policy = enforce_policy

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

        if self.enforce_policy:
            decision = evaluate_voice_policy(self.context, self.metadata, name, arguments)
            if decision.requires_approval:
                return await self._request_owner_approval(
                    tool_name=name,
                    arguments=arguments,
                    summary=decision.summary,
                    fallback_message=decision.message,
                )
            if not decision.allow:
                return {"ok": False, "message": decision.message}

        return await self._execute_tool(name, arguments)

    async def _execute_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        """Run a tool after policy checks have passed."""
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
            "request_verification": self._run_request_verification,
            "verify_caller": self._run_verify_caller,
            "handoff_to_owner": self._run_handoff_to_owner,
            "schedule_callback": self._run_schedule_callback,
        }

        handler = handlers.get(name)
        if handler is None:
            return {"ok": False, "message": f"Unsupported voice tool: {name}"}
        return await handler(arguments)

    async def _request_owner_approval(
        self,
        tool_name: str,
        arguments: dict[str, object],
        summary: str,
        fallback_message: str,
    ) -> dict[str, object]:
        """Request approval in Telegram before executing a high-risk voice action."""
        if self.context is None:
            return {"ok": False, "message": fallback_message}

        pending_id = await store_pending_action(
            intent="voice_tool_execution",
            user_id=self.context.user_id,
            family_id=self.context.family_id,
            action_data={
                "tool_name": tool_name,
                "arguments": arguments,
                "metadata": self.metadata.__dict__,
            },
        )

        sent = await self._send_telegram_message(
            text=summary,
            buttons=[
                {"text": "Confirm", "callback": f"confirm_action:{pending_id}"},
                {"text": "Cancel", "callback": f"cancel_action:{pending_id}"},
            ],
        )

        if not sent:
            return {
                "ok": False,
                "message": (
                    "This request needs owner approval, but Telegram delivery is not available "
                    "right now."
                ),
            }

        return {
            "ok": True,
            "approval_requested": True,
            "message": (
                f"{fallback_message}\n\n"
                "I sent the approval request to Telegram."
            ),
        }

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
        buttons = []
        for button in result.buttons or []:
            callback = button.get("callback") or button.get("callback_data")
            if not callback:
                continue
            buttons.append({"text": button.get("text", "Confirm"), "callback": callback})

        if not buttons:
            return False

        return await self._send_telegram_message(
            text=result.response_text,
            buttons=buttons,
        )

    async def _send_telegram_message(
        self,
        text: str,
        buttons: list[dict[str, str]],
    ) -> bool:
        """Send a follow-up or approval request to the owner in Telegram."""
        owner_telegram_id = self.metadata.owner_telegram_id
        if not owner_telegram_id:
            return False

        from api import main as api_main

        if api_main.gateway is None:
            return False

        await api_main.gateway.send(
            OutgoingMessage(
                text=text,
                chat_id=owner_telegram_id,
                buttons=buttons,
            )
        )
        return True

    async def _send_sms_message(self, phone_number: str, text: str) -> bool:
        """Send an SMS using the shared Twilio SMS gateway."""
        if not phone_number:
            return False

        gateway = SMSGateway()
        if not gateway.is_configured:
            return False

        try:
            await gateway.send(
                OutgoingMessage(
                    text=text,
                    chat_id=phone_number,
                    channel="sms",
                )
            )
        finally:
            await gateway.close()
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

    async def _run_request_verification(self, arguments: dict[str, object]) -> dict[str, object]:
        phone_number = str(arguments.get("phone") or self.metadata.from_phone or "")
        if not phone_number:
            return {"ok": False, "message": "I do not have a phone number to send the code to."}

        challenge = await voice_verification_store.create(self.metadata.call_id, phone_number)
        sent = await self._send_sms_message(
            phone_number,
            (
                f"{self.metadata.business_name}: your verification code is {challenge.code}. "
                "It expires in 5 minutes."
            ),
        )
        if not sent:
            return {
                "ok": False,
                "message": (
                    "SMS verification is not available right now. "
                    "I can request owner approval."
                ),
            }

        if self.context is not None and self.context.voice_auth_state in {"none", "anonymous"}:
            self.context.voice_auth_state = "verification_pending"

        return {
            "ok": True,
            "message": (
                "I sent a verification code by text. Please read the code back to continue."
            ),
        }

    async def _run_verify_caller(self, arguments: dict[str, object]) -> dict[str, object]:
        code = str(arguments.get("code") or "").strip()
        if not code:
            return {"ok": False, "message": "Please provide the verification code."}

        verified = await voice_verification_store.verify(self.metadata.call_id, code)
        if not verified:
            return {
                "ok": False,
                "message": "That code did not match. I can resend it or request owner approval.",
            }

        if self.context is not None:
            self.context.voice_auth_state = "verified_by_sms"
            if not self.context.voice_phone_number:
                self.context.voice_phone_number = self.metadata.from_phone

        return {
            "ok": True,
            "message": "Thanks. The caller is now verified for this call.",
        }

    async def _run_handoff_to_owner(self, arguments: dict[str, object]) -> dict[str, object]:
        reason = str(arguments.get("reason") or "caller requested a manual follow-up")
        caller_name = str(
            arguments.get("caller_name")
            or (self.context.voice_contact_name if self.context else "")
            or self.metadata.contact_name
            or self.metadata.from_phone
            or "unknown caller"
        )
        callback_number = self.metadata.from_phone or self.metadata.to_phone or ""
        summary = (
            "Voice handoff requested\n\n"
            f"Caller: {caller_name}\n"
            f"Phone: {callback_number or 'unknown'}\n"
            f"Reason: {reason}"
        )
        sent = await self._send_telegram_message(text=summary, buttons=[])
        if sent:
            return {
                "ok": True,
                "message": "I notified the owner and asked for a manual follow-up.",
            }

        return await self._run_schedule_callback(
            {
                "caller_name": caller_name,
                "callback_number": callback_number,
                "reason": reason,
            }
        )

    async def _run_schedule_callback(self, arguments: dict[str, object]) -> dict[str, object]:
        caller_name = str(arguments.get("caller_name") or self.metadata.contact_name or "caller")
        callback_number = str(arguments.get("callback_number") or self.metadata.from_phone or "")
        reason = str(arguments.get("reason") or "Requested a callback from the owner.")
        description = (
            f"Call back {caller_name}"
            f"{f' at {callback_number}' if callback_number else ''}. Reason: {reason}"
        )
        task_result = await self._run_skill(
            "create_task",
            description,
            {
                "task_title": f"Call back {caller_name}",
                "description": description,
            },
        )
        sms_sent = await self._send_sms_message(
            callback_number,
            (
                f"{self.metadata.business_name}: we received your request and "
                "will call you back as soon as possible."
            ),
        )
        if sms_sent:
            task_result["message"] = (
                f"{task_result.get('message')}\n\n"
                "I also sent the caller a callback confirmation by text."
            )
        return task_result

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


async def execute_pending_voice_tool(
    action_data: dict[str, object],
    context: SessionContext,
) -> str:
    """Execute a previously approved voice tool action from Telegram."""
    metadata_payload = action_data.get("metadata")
    tool_name = str(action_data.get("tool_name") or "")
    arguments = action_data.get("arguments")

    if not isinstance(metadata_payload, dict) or not isinstance(arguments, dict) or not tool_name:
        return "Voice approval payload is invalid."

    metadata = VoiceCallMetadata(**metadata_payload)
    adapter = VoiceToolAdapter(context=context, metadata=metadata, enforce_policy=False)
    result = await adapter.handle_tool_call(tool_name, arguments)
    return str(result.get("message") or "Voice action completed.")
