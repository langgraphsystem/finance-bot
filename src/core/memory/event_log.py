"""Persisted audit trail for governed structured memory slots."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import log_action
from src.core.db import async_session
from src.core.models.audit import AuditLog
from src.core.models.user import User
from src.core.models.user_profile import UserProfile

logger = logging.getLogger(__name__)

MEMORY_AUDIT_ENTITY_TYPE = "memory_slot"
MEMORY_UPSERT_ACTION = "memory_upsert"
MEMORY_TOMBSTONE_ACTION = "memory_tombstone"
_MEMORY_SLOT_NAMESPACE = uuid.UUID("5af8ea47-4be7-4f6c-bc4a-78e4ef5b80a4")


def normalize_memory_slot_text(text: str) -> str:
    return " ".join((text or "").strip().casefold().split())


def identity_memory_slot(field: str) -> str:
    return f"identity:{str(field or '').strip()}"


def rule_memory_slot(rule_text: str) -> str:
    return f"rule:{normalize_memory_slot_text(rule_text)}"


def memory_entity_id(user_id: str, store: str, slot: str) -> uuid.UUID:
    key = f"{user_id}:{store}:{slot}"
    return uuid.uuid5(_MEMORY_SLOT_NAMESPACE, key)


async def _resolve_family_id(session: AsyncSession, user_id: str) -> uuid.UUID | None:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None

    family_id = await session.scalar(
        select(UserProfile.family_id).where(UserProfile.user_id == uid).limit(1)
    )
    if family_id is not None:
        return family_id

    return await session.scalar(select(User.family_id).where(User.id == uid).limit(1))


async def _latest_memory_state(
    session: AsyncSession,
    *,
    entity_id: uuid.UUID,
) -> dict[str, Any] | None:
    state = await session.scalar(
        select(AuditLog.new_data)
        .where(
            AuditLog.entity_type == MEMORY_AUDIT_ENTITY_TYPE,
            AuditLog.entity_id == entity_id,
        )
        .order_by(desc(AuditLog.id))
        .limit(1)
    )
    return state if isinstance(state, dict) else None


def _coerce_version(state: dict[str, Any] | None) -> int:
    if not state:
        return 0
    raw_version = state.get("version", 0)
    try:
        return int(raw_version)
    except (TypeError, ValueError):
        return 0


def _merged_metadata(
    previous: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(previous or {})
    if metadata:
        merged.update(metadata)
    return merged


def _build_state(
    *,
    store: str,
    slot: str,
    version: int,
    value: Any,
    tombstoned: bool,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "store": store,
        "slot": slot,
        "version": version,
        "value": value,
        "tombstoned": tombstoned,
        "metadata": dict(metadata or {}),
    }


async def record_memory_event(
    session: AsyncSession,
    *,
    user_id: str,
    store: str,
    slot: str,
    action: str,
    old_value: Any = None,
    new_value: Any = None,
    metadata: dict[str, Any] | None = None,
    family_id: str | uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """Persist a versioned memory slot change into AuditLog."""
    entity_id = memory_entity_id(user_id, store, slot)
    previous_state = await _latest_memory_state(session, entity_id=entity_id)
    previous_version = _coerce_version(previous_state)
    next_version = previous_version + 1
    previous_metadata = None
    if previous_state:
        previous_metadata = previous_state.get("metadata")
    merged_metadata = _merged_metadata(previous_metadata, metadata)
    tombstoned = action == MEMORY_TOMBSTONE_ACTION

    if previous_state is None and old_value is None:
        old_payload = None
    else:
        old_payload = _build_state(
            store=store,
            slot=slot,
            version=previous_version,
            value=old_value,
            tombstoned=bool((previous_state or {}).get("tombstoned")),
            metadata=merged_metadata,
        )

    new_payload = _build_state(
        store=store,
        slot=slot,
        version=next_version,
        value=new_value,
        tombstoned=tombstoned,
        metadata=merged_metadata,
    )

    resolved_family_id = family_id
    if resolved_family_id is None:
        resolved_family_id = await _resolve_family_id(session, user_id)
    if resolved_family_id is None:
        logger.warning(
            "Skipping memory event log for %s %s: family_id missing",
            store,
            slot,
        )
        return None

    await log_action(
        session=session,
        family_id=str(resolved_family_id),
        user_id=user_id,
        action=action,
        entity_type=MEMORY_AUDIT_ENTITY_TYPE,
        entity_id=str(entity_id),
        old_data=old_payload,
        new_data=new_payload,
    )
    return new_payload


def _history_entry(audit_row: AuditLog) -> dict[str, Any]:
    current = audit_row.new_data or {}
    previous = audit_row.old_data or {}
    return {
        "audit_id": audit_row.id,
        "action": audit_row.action,
        "store": current.get("store") or previous.get("store"),
        "slot": current.get("slot") or previous.get("slot"),
        "version": current.get("version"),
        "value": current.get("value"),
        "previous_value": previous.get("value"),
        "tombstoned": bool(current.get("tombstoned")),
        "metadata": current.get("metadata") or previous.get("metadata") or {},
        "created_at": audit_row.created_at.isoformat() if audit_row.created_at else None,
    }


async def list_memory_history(
    user_id: str,
    *,
    store: str | None = None,
    slot: str | None = None,
    limit: int = 20,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    """Return persisted history for versioned structured memory slots."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return []

    owns_session = session is None
    if owns_session:
        async with async_session() as local_session:
            return await list_memory_history(
                user_id,
                store=store,
                slot=slot,
                limit=limit,
                session=local_session,
            )

    stmt = (
        select(AuditLog)
        .where(
            AuditLog.user_id == uid,
            AuditLog.entity_type == MEMORY_AUDIT_ENTITY_TYPE,
        )
        .order_by(desc(AuditLog.created_at), desc(AuditLog.id))
    )
    if slot and store:
        stmt = stmt.where(AuditLog.entity_id == memory_entity_id(user_id, store, slot))

    result = await session.execute(stmt.limit(max(limit, 1)))
    rows = list(result.scalars())
    history = [_history_entry(row) for row in rows]
    if store:
        history = [entry for entry in history if entry.get("store") == store]
    if slot:
        history = [entry for entry in history if entry.get("slot") == slot]
    return history[:limit]
