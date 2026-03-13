"""Core identity layer — permanent user facts that are never dropped in overflow.

Loaded as step 0 in assemble_context(), placed at the BEGINNING of the
system prompt inside the cacheable prefix. Typical size: ~1-3K tokens.

Schema:
    name, occupation, family_members, preferred_currency, business_type,
    communication_preferences, active_business_profile, important_facts,
    bot_name, bot_role, city, country, age
"""

import json
import logging
import re
import uuid as _uuid

from sqlalchemy import select, update

from src.core.db import async_session
from src.core.memory.event_log import (
    MEMORY_TOMBSTONE_ACTION,
    MEMORY_UPSERT_ACTION,
    identity_memory_slot,
    record_memory_event,
    rule_memory_slot,
)
from src.core.models.user_profile import UserProfile

logger = logging.getLogger(__name__)


async def _ensure_user_profile(session, user_id: str) -> None:
    """Create a minimal user_profiles row if one doesn't exist yet.

    Without this, UPDATE ... WHERE user_id=X silently affects 0 rows
    and the bot says 'saved' but nothing persists.
    """
    from src.core.models.user import User

    existing = await session.scalar(
        select(UserProfile.id).where(UserProfile.user_id == _uuid.UUID(user_id)).limit(1)
    )
    if existing is not None:
        return

    user = await session.scalar(
        select(User).where(User.id == _uuid.UUID(user_id))
    )
    if not user:
        logger.warning("_ensure_user_profile: no user row for %s", user_id)
        return

    profile = UserProfile(
        user_id=user.id,
        family_id=user.family_id,
        display_name=user.name,
        preferred_language=getattr(user, "language", "en") or "en",
    )
    session.add(profile)
    await session.flush()
    logger.info("Created missing user_profile for %s", user_id)

# Default empty identity
_EMPTY_IDENTITY: dict = {}

# Redis cache TTL for identity (10 minutes)
_IDENTITY_CACHE_TTL = 600
_IDENTITY_CACHE_PREFIX = "core_identity"

# Categories that trigger immediate identity update
IDENTITY_CATEGORIES = {"user_identity", "bot_identity", "user_rule", "user_preference"}

# Mapping from fact category fields to core_identity keys
_CATEGORY_FIELD_MAP = {
    "user_identity": [
        "name", "age", "occupation", "city", "country", "family_members",
    ],
    "bot_identity": ["bot_name", "bot_role"],
    "user_preference": [
        "preferred_currency", "communication_preferences", "response_language",
    ],
}
_FIELD_CATEGORY_MAP = {
    field: category
    for category, fields in _CATEGORY_FIELD_MAP.items()
    for field in fields
}


def _get_redis():
    """Lazy import Redis to avoid circular imports."""
    from src.core.db import redis
    return redis


async def get_core_identity(user_id: str) -> dict:
    """Load core identity from Redis cache or user_profiles.core_identity JSONB."""
    # Try Redis cache first
    try:
        redis = _get_redis()
        cached = await redis.get(f"{_IDENTITY_CACHE_PREFIX}:{user_id}")
        if cached:
            return json.loads(cached)
    except Exception:
        pass  # Redis miss or error — fall through to DB

    try:
        async with async_session() as session:
            result = await session.execute(
                select(UserProfile.core_identity)
                .where(UserProfile.user_id == _uuid.UUID(user_id))
                .limit(1)
            )
            row = result.scalar_one_or_none()
            identity = row if row else _EMPTY_IDENTITY

        # Populate cache
        try:
            redis = _get_redis()
            await redis.set(
                f"{_IDENTITY_CACHE_PREFIX}:{user_id}",
                json.dumps(identity, ensure_ascii=False),
                ex=_IDENTITY_CACHE_TTL,
            )
        except Exception:
            pass

        return identity
    except Exception as e:
        logger.warning("Failed to load core identity for %s: %s", user_id, e)
        return _EMPTY_IDENTITY


async def update_core_identity(user_id: str, updates: dict) -> dict:
    """Merge updates into core_identity (partial update, not replace).

    Creates the user_profiles row if it doesn't exist yet (upsert).
    Invalidates Redis cache after successful write.
    """
    try:
        current = await get_core_identity(user_id)
        merged = {**current, **updates}
        # Remove None values (explicit deletion)
        merged = {k: v for k, v in merged.items() if v is not None}
        changed_fields = sorted(set(current) | set(merged))

        async with async_session() as session:
            await _ensure_user_profile(session, user_id)
            await session.execute(
                update(UserProfile)
                .where(UserProfile.user_id == _uuid.UUID(user_id))
                .values(core_identity=merged)
            )
            for field in changed_fields:
                old_value = current.get(field)
                new_value = merged.get(field)
                if old_value == new_value:
                    continue
                await _safe_record_memory_event(
                    session,
                    user_id=user_id,
                    store="identity",
                    slot=identity_memory_slot(field),
                    action=(
                        MEMORY_TOMBSTONE_ACTION
                        if new_value is None
                        else MEMORY_UPSERT_ACTION
                    ),
                    old_value=old_value,
                    new_value=new_value,
                    metadata={
                        "category": _FIELD_CATEGORY_MAP.get(field, "profile"),
                        "field": field,
                        "source": "core_identity",
                        "write_path": "structured_profile",
                    },
                )
            await session.commit()

        # Invalidate cache
        await invalidate_identity_cache(user_id)

        return merged
    except Exception as e:
        logger.warning("Failed to update core identity for %s: %s", user_id, e)
        # Invalidate cache even on failure so stale data doesn't persist
        await invalidate_identity_cache(user_id)
        return await get_core_identity(user_id)


async def invalidate_identity_cache(user_id: str) -> None:
    """Remove identity from Redis cache (call after any update)."""
    try:
        redis = _get_redis()
        await redis.delete(f"{_IDENTITY_CACHE_PREFIX}:{user_id}")
    except Exception:
        pass


async def _safe_record_memory_event(
    session,
    *,
    user_id: str,
    store: str,
    slot: str,
    action: str,
    old_value=None,
    new_value=None,
    metadata: dict | None = None,
) -> None:
    """Best-effort audit trail: never block the primary structured write path."""
    try:
        await record_memory_event(
            session,
            user_id=user_id,
            store=store,
            slot=slot,
            action=action,
            old_value=old_value,
            new_value=new_value,
            metadata=metadata,
        )
    except Exception:
        logger.warning(
            "Failed to persist memory event for %s %s on user %s",
            store,
            slot,
            user_id,
            exc_info=True,
        )


async def immediate_identity_update(
    user_id: str, category: str, content: str
) -> None:
    """Update core_identity IMMEDIATELY for critical categories.

    Called from background task after fact extraction. For user_identity,
    bot_identity, and user_rule categories — writes to DB + invalidates cache
    right away instead of waiting for nightly cron.
    """
    if category not in IDENTITY_CATEGORIES:
        return

    updates: dict = {}

    if category == "user_identity":
        updates = _parse_identity_fact(content)
    elif category == "bot_identity":
        updates = _parse_bot_identity_fact(content)
    elif category == "user_rule":
        # Rules go to active_rules, not core_identity (Phase 4 handles this)
        await _add_user_rule(user_id, content)
        return
    elif category == "user_preference":
        updates = _parse_preference_fact(content)

    if updates:
        await update_core_identity(user_id, updates)
        logger.info("Immediate identity update for %s: %s → %s", user_id, category, updates)


def _parse_identity_fact(content: str) -> dict:
    """Extract identity fields from a fact string."""
    lower = content.lower()
    updates: dict = {}

    # Name patterns
    for pattern in ["имя:", "зовут", "name:", "my name is", "меня зовут"]:
        if pattern in lower:
            # Extract the value after the pattern
            idx = lower.index(pattern) + len(pattern)
            value = content[idx:].strip().strip(".,!").split("\n")[0].strip()
            if value:
                updates["name"] = value
                break

    # City patterns
    for pattern in ["город:", "живу в", "city:", "i live in", "из города"]:
        if pattern in lower:
            idx = lower.index(pattern) + len(pattern)
            value = content[idx:].strip().strip(".,!").split("\n")[0].strip()
            if value:
                updates["city"] = value
                break

    # Occupation patterns
    for pattern in ["профессия:", "работаю", "occupation:", "i work as"]:
        if pattern in lower:
            idx = lower.index(pattern) + len(pattern)
            value = content[idx:].strip().strip(".,!").split("\n")[0].strip()
            if value:
                updates["occupation"] = value
                break

    # If no structured match, store as important_fact
    if not updates and content.strip():
        updates["_raw_identity"] = content.strip()

    return updates


def _parse_bot_identity_fact(content: str) -> dict:
    """Extract bot identity fields from a fact string."""
    lower = content.lower()
    updates: dict = {}

    for pattern in [
        "зови себя", "тебя зовут", "твоё имя", "call yourself",
        "your name is", "имя бота:",
    ]:
        if pattern in lower:
            idx = lower.index(pattern) + len(pattern)
            value = content[idx:].strip().strip(".,!").split("\n")[0].strip()
            if value:
                updates["bot_name"] = value
                break

    return updates


def _parse_preference_fact(content: str) -> dict:
    """Extract preference fields from a fact string."""
    lower = content.lower()
    updates: dict = {}

    for lang_marker, lang in [
        ("на русском", "ru"), ("на английском", "en"), ("in english", "en"),
        ("in russian", "ru"), ("по-русски", "ru"), ("по-английски", "en"),
        ("en español", "es"), ("на испанском", "es"),
        ("auf deutsch", "de"), ("на немецком", "de"),
        ("en français", "fr"), ("на французском", "fr"),
        ("на казахском", "kk"), ("на кыргызском", "ky"),
        ("на турецком", "tr"), ("на китайском", "zh"),
    ]:
        if lang_marker in lower:
            updates["response_language"] = lang
            break

    return updates


_RULE_KEYWORDS = (
    "на русском",
    "на английском",
    "по-русски",
    "по-английски",
    "без эмодзи",
    "без emoji",
    "не используй эмодзи",
    "не используй emoji",
    "always respond",
    "reply in",
    "answer in",
    "keep it brief",
    "keep responses",
    "call yourself",
    "your name is",
    "зови себя",
    "тебя зовут",
    "пиши на",
    "пиши без",
)

_RULE_WORD_KEYWORDS = (
    "отвечай",
    "говори",
    "коротко",
    "кратко",
    "подробно",
    "эмодзи",
    "emoji",
    "язык",
    "language",
    "формат",
    "format",
    "стиль",
    "style",
    "тон",
    "tone",
)

_RULE_REJECT_PREFIXES = (
    "как ", "what ", "who ", "where ", "when ", "why ",
    "что ", "кто ", "где ", "когда ", "почему ",
    "о чём ", "о чем ", "что обсуждали", "what did we discuss",
    "conversation history", "show conversation",
    "забудь", "удали", "forget", "delete", "remove",
)

_RULE_ACTION_PREFIXES = (
    "напиши ",
    "write ",
    "draft ",
    "переведи ",
    "translate ",
    "прочитай ",
    "check ",
    "проверь ",
    "найди ",
    "find ",
    "покажи ",
    "show ",
    "запиши клиента",
    "book ",
    "schedule ",
    "создай ",
    "create ",
    "добавь ",
    "add ",
)

_RULE_REJECT_EXACT = frozenset({
    "да", "нет", "ок", "ok", "okay", "yes", "no", "хорошо", "ладно",
    "понял", "поняла", "понятно", "ясно", "конечно", "sure", "yeah",
    "да, всегда", "всегда", "always", "never", "никогда",
    "спасибо", "thanks", "спс", "thx",
})


def _is_valid_rule(text: str) -> bool:
    """Check if text looks like a legitimate user rule."""
    stripped = text.strip()
    if len(stripped) < 5:
        return False
    lower = stripped.lower()
    if "?" in lower:
        return False
    if lower in _RULE_REJECT_EXACT:
        return False
    if any(lower.startswith(p) for p in _RULE_REJECT_PREFIXES):
        return False
    if any(lower.startswith(p) for p in _RULE_ACTION_PREFIXES):
        return False
    if any(kw in lower for kw in _RULE_KEYWORDS):
        return True
    if any(re.search(rf"\b{re.escape(kw)}\b", lower) for kw in _RULE_WORD_KEYWORDS):
        return True
    # Reject if no rule keyword found — likely garbage from LLM misclassification
    logger.debug("Rejected invalid rule (no keyword match): %s", stripped[:60])
    return False


def is_valid_user_rule(text: str) -> bool:
    """Public wrapper so routing and skills can share the same rule filter."""
    return _is_valid_rule(text)


async def _add_user_rule(user_id: str, rule_text: str) -> None:
    """Add a user rule to active_rules JSONB array.

    Creates the user_profiles row if it doesn't exist yet (upsert).
    Validates that the text looks like a real rule before saving.
    """
    if not _is_valid_rule(rule_text):
        logger.info("Skipped invalid rule for %s: %s", user_id, rule_text[:60])
        return

    try:
        async with async_session() as session:
            await _ensure_user_profile(session, user_id)
            result = await session.execute(
                select(UserProfile.active_rules)
                .where(UserProfile.user_id == _uuid.UUID(user_id))
                .limit(1)
            )
            current_rules = result.scalar_one_or_none() or []
            if not isinstance(current_rules, list):
                current_rules = []

            # Deduplicate (casefold for Unicode-safe comparison — GAP-M2)
            normalized = rule_text.strip().casefold()
            if not any(r.casefold() == normalized for r in current_rules):
                cleaned_rule = rule_text.strip()
                current_rules.append(cleaned_rule)
                await session.execute(
                    update(UserProfile)
                    .where(UserProfile.user_id == _uuid.UUID(user_id))
                    .values(active_rules=current_rules)
                )
                await _safe_record_memory_event(
                    session,
                    user_id=user_id,
                    store="rule",
                    slot=rule_memory_slot(cleaned_rule),
                    action=MEMORY_UPSERT_ACTION,
                    old_value=None,
                    new_value=cleaned_rule,
                    metadata={
                        "category": "user_rule",
                        "source": "active_rules",
                        "write_path": "structured_profile",
                    },
                )
                await session.commit()
                logger.info("Added user rule for %s: %s", user_id, rule_text[:50])

        await invalidate_identity_cache(user_id)
    except Exception as e:
        logger.warning("Failed to add user rule for %s: %s", user_id, e)


async def get_user_rules(user_id: str) -> list[str]:
    """Load active_rules from user_profiles."""
    try:
        async with async_session() as session:
            result = await session.execute(
                select(UserProfile.active_rules)
                .where(UserProfile.user_id == _uuid.UUID(user_id))
                .limit(1)
            )
            rules = result.scalar_one_or_none()
            if not isinstance(rules, list):
                return []
            valid_rules: list[str] = []
            seen: set[str] = set()
            changed = False
            for rule in rules:
                if not isinstance(rule, str):
                    changed = True
                    continue
                cleaned = rule.strip()
                if not is_valid_user_rule(cleaned):
                    changed = True
                    continue
                normalized = cleaned.casefold()
                if normalized in seen:
                    changed = True
                    continue
                seen.add(normalized)
                valid_rules.append(cleaned)

            if changed or len(valid_rules) != len(rules):
                await session.execute(
                    update(UserProfile)
                    .where(UserProfile.user_id == _uuid.UUID(user_id))
                    .values(active_rules=valid_rules)
                )
                await session.commit()
                await invalidate_identity_cache(user_id)
                logger.info(
                    "Cleaned invalid user rules for %s: %d -> %d",
                    user_id,
                    len(rules),
                    len(valid_rules),
                )

            return valid_rules
    except Exception as e:
        logger.warning("Failed to load user rules for %s: %s", user_id, e)
        return []


async def remove_user_rule(user_id: str, rule_text: str) -> bool:
    """Remove a user rule by text match."""
    try:
        rules = await get_user_rules(user_id)
        normalized = rule_text.strip().casefold()
        removed_rules = [r for r in rules if r.casefold() == normalized]
        new_rules = [r for r in rules if r.casefold() != normalized]
        if len(new_rules) == len(rules):
            return False

        async with async_session() as session:
            await session.execute(
                update(UserProfile)
                .where(UserProfile.user_id == _uuid.UUID(user_id))
                .values(active_rules=new_rules)
            )
            for removed_rule in removed_rules:
                await _safe_record_memory_event(
                    session,
                    user_id=user_id,
                    store="rule",
                    slot=rule_memory_slot(removed_rule),
                    action=MEMORY_TOMBSTONE_ACTION,
                    old_value=removed_rule,
                    new_value=None,
                    metadata={
                        "category": "user_rule",
                        "source": "active_rules",
                        "write_path": "structured_profile",
                    },
                )
            await session.commit()

        await invalidate_identity_cache(user_id)
        return True
    except Exception as e:
        logger.warning("Failed to remove user rule for %s: %s", user_id, e)
        return False


async def clear_user_rules(user_id: str) -> int:
    """Remove all saved active_rules for a user."""
    try:
        rules = await get_user_rules(user_id)
        if not rules:
            return 0

        async with async_session() as session:
            await session.execute(
                update(UserProfile)
                .where(UserProfile.user_id == _uuid.UUID(user_id))
                .values(active_rules=[])
            )
            for rule in rules:
                await _safe_record_memory_event(
                    session,
                    user_id=user_id,
                    store="rule",
                    slot=rule_memory_slot(rule),
                    action=MEMORY_TOMBSTONE_ACTION,
                    old_value=rule,
                    new_value=None,
                    metadata={
                        "category": "user_rule",
                        "source": "active_rules",
                        "write_path": "structured_profile",
                    },
                )
            await session.commit()

        await invalidate_identity_cache(user_id)
        return len(rules)
    except Exception as e:
        logger.warning("Failed to clear user rules for %s: %s", user_id, e)
        return 0


async def clear_identity_fields(user_id: str, fields: list[str]) -> list[str]:
    """Delete selected keys from core_identity if they exist."""
    current = await get_core_identity(user_id)
    removable = [field for field in fields if current.get(field) is not None]
    if not removable:
        return []

    await update_core_identity(user_id, {field: None for field in removable})
    return removable


def format_identity_block(identity: dict) -> str:
    """Format core identity as a compact context block for the system prompt."""
    if not identity:
        return ""

    # Build explicit LLM instructions for saved names
    instructions: list[str] = []
    if identity.get("bot_name"):
        instructions.append(
            f"Your name is {identity['bot_name']}. "
            f"Always introduce yourself as {identity['bot_name']} when asked."
        )
    if identity.get("name"):
        instructions.append(
            f"The user's name is {identity['name']}. "
            "Address them by name naturally."
        )

    parts: list[str] = []
    if instructions:
        parts.append("IMPORTANT: " + " ".join(instructions))
    if identity.get("bot_name"):
        parts.append(f"Bot Name: {identity['bot_name']}")
    if identity.get("bot_role"):
        parts.append(f"Bot Role: {identity['bot_role']}")
    if identity.get("name"):
        parts.append(f"User Name: {identity['name']}")
    if identity.get("age"):
        parts.append(f"Age: {identity['age']}")
    if identity.get("occupation"):
        parts.append(f"Occupation: {identity['occupation']}")
    if identity.get("city"):
        parts.append(f"City: {identity['city']}")
    if identity.get("country"):
        parts.append(f"Country: {identity['country']}")
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
    if identity.get("response_language"):
        parts.append(f"Response Language: {identity['response_language']}")
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


def format_rules_block(rules: list[str]) -> str:
    """Format user rules as a NEVER DROP context block."""
    if not rules:
        return ""

    lines = ["ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА ПОЛЬЗОВАТЕЛЯ (нарушение запрещено):"]
    for rule in rules:
        lines.append(f"- {rule}")

    return "\n<user_rules>\n" + "\n".join(lines) + "\n</user_rules>"
