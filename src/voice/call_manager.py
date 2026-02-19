"""Call manager — orchestrates voice calls and persists call records."""

import logging
import uuid
from typing import Any

from src.core.db import async_session
from src.core.models.client_interaction import ClientInteraction
from src.core.models.enums import InteractionChannel, InteractionDirection
from src.voice.twilio_handler import initiate_outbound_call

logger = logging.getLogger(__name__)


async def start_outbound_call(
    contact_id: str,
    contact_phone: str,
    contact_name: str,
    owner_name: str,
    call_purpose: str,
    family_id: str,
    booking_id: str | None = None,
) -> dict[str, Any]:
    """Initiate an outbound call and create interaction record."""
    call_result = await initiate_outbound_call(
        to_phone=contact_phone,
        owner_name=owner_name,
        contact_name=contact_name,
        call_purpose=call_purpose,
        family_id=family_id,
    )

    if "error" not in call_result:
        interaction = ClientInteraction(
            id=uuid.uuid4(),
            family_id=uuid.UUID(family_id),
            contact_id=uuid.UUID(contact_id),
            channel=InteractionChannel.phone,
            direction=InteractionDirection.outbound,
            content=f"Outbound call: {call_purpose}",
            booking_id=uuid.UUID(booking_id) if booking_id else None,
            meta={
                "call_sid": call_result.get("call_sid"),
                "call_id": call_result.get("call_id"),
            },
        )
        async with async_session() as session:
            session.add(interaction)
            await session.commit()

    return call_result


async def record_inbound_call(
    family_id: str,
    contact_id: str | None,
    transcript: str,
    duration_seconds: int,
    caller_phone: str,
    booking_id: str | None = None,
    recording_url: str | None = None,
) -> None:
    """Save an inbound call record after call ends."""
    interaction = ClientInteraction(
        id=uuid.uuid4(),
        family_id=uuid.UUID(family_id),
        contact_id=uuid.UUID(contact_id) if contact_id else uuid.uuid4(),
        channel=InteractionChannel.phone,
        direction=InteractionDirection.inbound,
        content=transcript,
        booking_id=uuid.UUID(booking_id) if booking_id else None,
        call_duration_seconds=duration_seconds,
        call_recording_url=recording_url,
        meta={"caller_phone": caller_phone},
    )
    async with async_session() as session:
        session.add(interaction)
        await session.commit()
