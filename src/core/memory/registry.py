"""Canonical registry over user-visible memory stores."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Any

from sqlalchemy import delete, select

import src.core.identity as identity_store
import src.core.memory.mem0_client as mem0_client
from src.core.db import async_session
from src.core.memory.governance import normalize_memory_metadata
from src.core.models.session_summary import SessionSummary

logger = logging.getLogger(__name__)

REGISTRY_STORES = frozenset({"mem0", "identity", "rule", "summary"})
_STORE_PRECEDENCE = {"identity": 0, "rule": 1, "mem0": 2, "summary": 3}

_IDENTITY_CATEGORY_BY_FIELD = {
    "name": "user_identity",
    "age": "user_identity",
    "occupation": "user_identity",
    "city": "user_identity",
    "country": "user_identity",
    "family_members": "user_identity",
    "bot_name": "bot_identity",
    "bot_role": "bot_identity",
    "preferred_currency": "user_preference",
    "communication_preferences": "user_preference",
    "response_language": "user_preference",
}


def _preview(text: str, limit: int = 160) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _timestamp_sort_value(entry: dict[str, Any]) -> str:
    return str(entry.get("updated_at") or entry.get("created_at") or "")


def _registry_sort_key(entry: dict[str, Any]) -> tuple[int, str, str]:
    return (
        _STORE_PRECEDENCE.get(str(entry.get("store") or ""), 99),
        _timestamp_sort_value(entry),
        str(entry.get("id") or ""),
    )


def _rule_registry_id(rule: str) -> str:
    digest = hashlib.sha1(rule.encode("utf-8")).hexdigest()[:12]
    return f"rule:{digest}"


def _serialize_identity_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item is not None)
    if isinstance(value, dict):
        parts = [f"{key}: {val}" for key, val in value.items()]
        return ", ".join(parts)
    return str(value)


def _identity_entry(field: str, value: Any) -> dict[str, Any]:
    text = _serialize_identity_value(value).strip()
    category = _IDENTITY_CATEGORY_BY_FIELD.get(field, "profile")
    metadata = normalize_memory_metadata(
        {
            "source": "core_identity",
            "type": "structured",
            "category": category,
            "write_policy": "explicit",
            "confidence": 1.0,
            "retention_class": "long_term",
        }
    )
    return {
        "id": f"identity:{field}",
        "store": "identity",
        "source_id": field,
        "field": field,
        "text": text,
        "display_text": f"{field}: {text}",
        "preview": _preview(f"{field}: {text}"),
        "metadata": metadata,
        "created_at": None,
        "updated_at": None,
        "deletable": True,
    }


def _rule_entry(rule: str) -> dict[str, Any]:
    metadata = normalize_memory_metadata(
        {
            "source": "active_rules",
            "type": "structured",
            "category": "user_rule",
            "write_policy": "explicit",
            "confidence": 1.0,
            "retention_class": "long_term",
        }
    )
    return {
        "id": _rule_registry_id(rule),
        "store": "rule",
        "source_id": rule,
        "text": rule,
        "display_text": rule,
        "preview": _preview(rule),
        "metadata": metadata,
        "created_at": None,
        "updated_at": None,
        "deletable": True,
    }


def _mem0_entry(memory: dict[str, Any]) -> dict[str, Any]:
    metadata = normalize_memory_metadata(memory.get("metadata") or {})
    text = str(memory.get("memory") or memory.get("text") or "").strip()
    return {
        "id": f"mem0:{memory.get('id')}",
        "store": "mem0",
        "source_id": str(memory.get("id") or ""),
        "text": text,
        "display_text": text,
        "preview": _preview(text),
        "metadata": metadata,
        "created_at": memory.get("created_at") or metadata.get("created_at"),
        "updated_at": memory.get("updated_at") or metadata.get("updated_at"),
        "deletable": True,
        "score": memory.get("score"),
    }


def _summary_entry(summary: SessionSummary) -> dict[str, Any]:
    metadata = normalize_memory_metadata(
        {
            "source": "session_summary",
            "type": "summary",
            "category": "session_summary",
            "write_policy": "system",
            "confidence": 0.9,
            "retention_class": "session_archive",
            "source_ref": str(summary.session_id),
        }
    )
    text = str(summary.summary or "").strip()
    return {
        "id": f"summary:{summary.id}",
        "store": "summary",
        "source_id": str(summary.id),
        "session_id": str(summary.session_id),
        "text": text,
        "display_text": text,
        "preview": _preview(text),
        "metadata": metadata,
        "created_at": summary.created_at.isoformat() if summary.created_at else None,
        "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
        "deletable": True,
    }


async def _load_summary_entries(
    user_id: str,
    *,
    session=None,
) -> list[dict[str, Any]]:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return []

    owns_session = session is None
    if owns_session:
        async with async_session() as local_session:
            result = await local_session.execute(
                select(SessionSummary)
                .where(SessionSummary.user_id == uid)
                .order_by(SessionSummary.updated_at.desc(), SessionSummary.id.desc())
            )
            return [_summary_entry(summary) for summary in result.scalars()]

    result = await session.execute(
        select(SessionSummary)
        .where(SessionSummary.user_id == uid)
        .order_by(SessionSummary.updated_at.desc(), SessionSummary.id.desc())
    )
    return [_summary_entry(summary) for summary in result.scalars()]


async def list_memory_registry(
    user_id: str,
    *,
    include_stores: set[str] | None = None,
    session=None,
) -> list[dict[str, Any]]:
    """Aggregate user-visible memory records across supported stores."""
    stores = set(include_stores or REGISTRY_STORES) & set(REGISTRY_STORES)
    entries: list[dict[str, Any]] = []

    if "identity" in stores:
        try:
            identity = await identity_store.get_core_identity(user_id)
            for field, value in identity.items():
                if value in (None, "", [], {}):
                    continue
                entries.append(_identity_entry(field, value))
        except Exception:
            logger.warning("Memory registry failed to load identity for %s", user_id, exc_info=True)

    if "rule" in stores:
        try:
            rules = await identity_store.get_user_rules(user_id)
            entries.extend(_rule_entry(rule) for rule in rules if rule)
        except Exception:
            logger.warning("Memory registry failed to load rules for %s", user_id, exc_info=True)

    if "mem0" in stores:
        try:
            memories = await mem0_client.get_all_memories(user_id)
            entries.extend(_mem0_entry(memory) for memory in memories if memory.get("id"))
        except Exception:
            logger.warning(
                "Memory registry failed to load Mem0 memories for %s",
                user_id,
                exc_info=True,
            )

    if "summary" in stores:
        try:
            entries.extend(await _load_summary_entries(user_id, session=session))
        except Exception:
            logger.warning(
                "Memory registry failed to load summaries for %s",
                user_id,
                exc_info=True,
            )

    return sorted(entries, key=_registry_sort_key)


def _structured_match_score(query: str, text: str) -> float:
    normalized_query = _normalize_text(query)
    normalized_text = _normalize_text(text)
    if not normalized_query or not normalized_text:
        return 0.0
    if normalized_query == normalized_text:
        return 1.0
    if normalized_query in normalized_text:
        return 0.95

    query_tokens = set(re.findall(r"[\wёЁ]+", normalized_query))
    text_tokens = set(re.findall(r"[\wёЁ]+", normalized_text))
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = len(query_tokens & text_tokens) / len(query_tokens)
    if overlap <= 0:
        return 0.0
    return 0.5 + overlap * 0.4


async def search_memory_registry(
    user_id: str,
    query: str,
    *,
    limit: int = 10,
    include_stores: set[str] | None = None,
    session=None,
) -> list[dict[str, Any]]:
    """Search supported memory stores with semantic Mem0 + text match fallback."""
    normalized_query = query.strip()
    if not normalized_query:
        return []

    stores = set(include_stores or REGISTRY_STORES) & set(REGISTRY_STORES)
    matches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if "mem0" in stores:
        try:
            semantic_matches = await mem0_client.search_memories_all_namespaces(
                normalized_query,
                user_id,
                limit=limit,
            )
            for memory in semantic_matches:
                entry = _mem0_entry(memory)
                entry["match_score"] = float(memory.get("score") or 0.0)
                if entry["id"] in seen_ids:
                    continue
                seen_ids.add(entry["id"])
                matches.append(entry)
        except Exception:
            logger.warning("Memory registry Mem0 search failed for %s", user_id, exc_info=True)

    structured_stores = stores - {"mem0"}
    if structured_stores:
        structured_entries = await list_memory_registry(
            user_id,
            include_stores=structured_stores,
            session=session,
        )
        for entry in structured_entries:
            score = _structured_match_score(
                normalized_query,
                f"{entry.get('display_text', '')} {entry.get('text', '')}",
            )
            if score <= 0:
                continue
            candidate = dict(entry)
            candidate["match_score"] = score
            if candidate["id"] in seen_ids:
                continue
            seen_ids.add(candidate["id"])
            matches.append(candidate)

    matches.sort(
        key=lambda entry: (
            float(entry.get("match_score") or 0.0),
            _timestamp_sort_value(entry),
            -_STORE_PRECEDENCE.get(str(entry.get("store") or ""), 99),
        ),
        reverse=True,
    )
    return matches[:limit]


async def delete_registry_entry(
    user_id: str,
    entry: dict[str, Any],
    *,
    session=None,
) -> bool:
    """Delete a single registry entry from its backing store."""
    store = str(entry.get("store") or "")
    source_id = str(entry.get("source_id") or "")

    if store == "mem0" and source_id:
        await mem0_client.delete_memory(source_id, user_id)
        return True

    if store == "identity" and source_id:
        removed = await identity_store.clear_identity_fields(user_id, [source_id])
        return bool(removed)

    if store == "rule":
        return await identity_store.remove_user_rule(user_id, str(entry.get("text") or source_id))

    if store == "summary" and source_id:
        try:
            summary_id = int(source_id)
        except ValueError:
            return False

        owns_session = session is None
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            return False

        if owns_session:
            async with async_session() as local_session:
                await local_session.execute(
                    delete(SessionSummary).where(
                        SessionSummary.id == summary_id,
                        SessionSummary.user_id == uid,
                    )
                )
                await local_session.commit()
                return True

        await session.execute(
            delete(SessionSummary).where(
                SessionSummary.id == summary_id,
                SessionSummary.user_id == uid,
            )
        )
        return True

    return False


async def clear_memory_registry(
    user_id: str,
    *,
    include_stores: set[str] | None = None,
    session=None,
) -> dict[str, int]:
    """Bulk-clear supported stores and return deleted entry counts by store."""
    stores = set(include_stores or REGISTRY_STORES) & set(REGISTRY_STORES)
    counts = {"mem0": 0, "identity": 0, "rule": 0, "summary": 0}

    if "mem0" in stores:
        try:
            memories = await mem0_client.get_all_memories(user_id)
            counts["mem0"] = len(memories)
            await mem0_client.delete_all_memories(user_id)
        except Exception:
            logger.warning("Memory registry failed to clear Mem0 for %s", user_id, exc_info=True)

    if "rule" in stores:
        try:
            counts["rule"] = await identity_store.clear_user_rules(user_id)
        except Exception:
            logger.warning("Memory registry failed to clear rules for %s", user_id, exc_info=True)

    if "identity" in stores:
        try:
            identity = await identity_store.get_core_identity(user_id)
            fields = [field for field, value in identity.items() if value not in (None, "", [], {})]
            counts["identity"] = len(await identity_store.clear_identity_fields(user_id, fields))
        except Exception:
            logger.warning(
                "Memory registry failed to clear identity for %s",
                user_id,
                exc_info=True,
            )

    if "summary" in stores:
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            uid = None

        if uid is not None:
            owns_session = session is None
            if owns_session:
                async with async_session() as local_session:
                    result = await local_session.execute(
                        select(SessionSummary.id).where(SessionSummary.user_id == uid)
                    )
                    summary_ids = list(result.scalars())
                    counts["summary"] = len(summary_ids)
                    if summary_ids:
                        await local_session.execute(
                            delete(SessionSummary).where(SessionSummary.user_id == uid)
                        )
                        await local_session.commit()
            else:
                result = await session.execute(
                    select(SessionSummary.id).where(SessionSummary.user_id == uid)
                )
                summary_ids = list(result.scalars())
                counts["summary"] = len(summary_ids)
                if summary_ids:
                    await session.execute(
                        delete(SessionSummary).where(SessionSummary.user_id == uid)
                    )

    if "identity" in stores or "rule" in stores:
        await identity_store.invalidate_identity_cache(user_id)

    return counts


async def export_memory_registry(
    user_id: str,
    *,
    session=None,
) -> list[dict[str, Any]]:
    """Export unified user memory records for access/debug flows."""
    return await list_memory_registry(user_id, session=session)
