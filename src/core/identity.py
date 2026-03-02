"""Core identity layer — permanent user facts that are never dropped in overflow.

Loaded as step 0 in assemble_context(), placed at the BEGINNING of the
system prompt inside the cacheable prefix. Typical size: ~1-3K tokens.

Schema:
    name, occupation, family_members, preferred_currency, business_type,
    communication_preferences, active_business_profile, important_facts
"""

import logging
import uuid as _uuid

from sqlalchemy import select, update

from src.core.db import async_session
from src.core.models.user_profile import UserProfile

logger = logging.getLogger(__name__)

# Default empty identity
_EMPTY_IDENTITY: dict = {}


async def get_core_identity(user_id: str) -> dict:
    """Load core identity from user_profiles.core_identity JSONB."""
    try:
        async with async_session() as session:
            result = await session.execute(
                select(UserProfile.core_identity)
                .where(UserProfile.user_id == _uuid.UUID(user_id))
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return row if row else _EMPTY_IDENTITY
    except Exception as e:
        logger.warning("Failed to load core identity for %s: %s", user_id, e)
        return _EMPTY_IDENTITY


async def update_core_identity(user_id: str, updates: dict) -> dict:
    """Merge updates into core_identity (partial update, not replace)."""
    try:
        current = await get_core_identity(user_id)
        merged = {**current, **updates}
        # Remove None values (explicit deletion)
        merged = {k: v for k, v in merged.items() if v is not None}

        async with async_session() as session:
            await session.execute(
                update(UserProfile)
                .where(UserProfile.user_id == _uuid.UUID(user_id))
                .values(core_identity=merged)
            )
            await session.commit()
        return merged
    except Exception as e:
        logger.warning("Failed to update core identity for %s: %s", user_id, e)
        return await get_core_identity(user_id)


def format_identity_block(identity: dict) -> str:
    """Format core identity as a compact context block for the system prompt."""
    if not identity:
        return ""

    parts: list[str] = []
    if identity.get("name"):
        parts.append(f"Name: {identity['name']}")
    if identity.get("occupation"):
        parts.append(f"Occupation: {identity['occupation']}")
    if identity.get("family_members"):
        members = identity["family_members"]
        if isinstance(members, list):
            parts.append(f"Family: {', '.join(members)}")
        else:
            parts.append(f"Family: {members}")
    if identity.get("preferred_currency"):
        parts.append(f"Currency: {identity['preferred_currency']}")
    if identity.get("business_type"):
        parts.append(f"Business: {identity['business_type']}")
    if identity.get("communication_preferences"):
        parts.append(f"Communication: {identity['communication_preferences']}")
    if identity.get("important_facts"):
        facts = identity["important_facts"]
        if isinstance(facts, list):
            for fact in facts:
                parts.append(f"- {fact}")
        else:
            parts.append(f"- {facts}")

    if not parts:
        return ""
    return "\n<core_identity>\n" + "\n".join(parts) + "\n</core_identity>"
