"""Shared governance helpers for memory metadata and audit-safe mutations."""

from __future__ import annotations

from typing import Any

from src.core.memory.mem0_domains import get_domain_for_category

DEFAULT_MEMORY_CATEGORY = "life_note"
DEFAULT_MEMORY_TYPE = "implicit"
DEFAULT_MEMORY_SOURCE = "memory_system"
DEFAULT_RETENTION_CLASS = "long_term"
DEFAULT_SENSITIVITY = "personal"
DEFAULT_CONFIDENCE = 0.7


def normalize_memory_metadata(
    metadata: dict[str, Any] | None,
    *,
    source: str | None = None,
    memory_type: str | None = None,
    default_category: str | None = None,
    confidence: float | None = None,
    sensitivity: str | None = None,
    retention_class: str | None = None,
) -> dict[str, Any]:
    """Normalize memory metadata into a stable, governance-friendly shape."""
    meta = dict(metadata or {})

    category = str(
        meta.get("category")
        or default_category
        or DEFAULT_MEMORY_CATEGORY
    ).strip()
    meta["category"] = category

    resolved_source = str(meta.get("source") or source or DEFAULT_MEMORY_SOURCE).strip()
    if resolved_source:
        meta["source"] = resolved_source

    resolved_type = str(meta.get("type") or memory_type or DEFAULT_MEMORY_TYPE).strip()
    if resolved_type:
        meta["type"] = resolved_type

    if "confidence" not in meta:
        meta["confidence"] = float(
            DEFAULT_CONFIDENCE if confidence is None else max(0.0, min(1.0, confidence))
        )

    if "sensitivity" not in meta:
        meta["sensitivity"] = sensitivity or DEFAULT_SENSITIVITY

    if "retention_class" not in meta:
        meta["retention_class"] = retention_class or DEFAULT_RETENTION_CLASS

    if "write_policy" not in meta:
        meta["write_policy"] = "explicit" if meta.get("type") == "explicit" else "implicit"

    if "domain" not in meta and category:
        meta["domain"] = get_domain_for_category(category).value

    return meta


def extract_memory_metadata(
    memory: dict[str, Any] | None,
    *,
    default_category: str | None = None,
) -> dict[str, Any]:
    """Extract normalized metadata from a memory record."""
    record = memory or {}
    metadata = dict(record.get("metadata") or {})

    if not metadata.get("category") and record.get("category"):
        metadata["category"] = record.get("category")
    if not metadata.get("source") and record.get("source"):
        metadata["source"] = record.get("source")
    if not metadata.get("type") and record.get("type"):
        metadata["type"] = record.get("type")

    return normalize_memory_metadata(
        metadata,
        default_category=default_category,
    )


def explicit_memory_metadata(
    *,
    source: str,
    category: str | None = None,
    existing_memory: dict[str, Any] | None = None,
    confidence: float = 1.0,
) -> dict[str, Any]:
    """Build metadata for an explicit user-initiated memory write."""
    existing_meta = extract_memory_metadata(existing_memory, default_category=category)
    existing_meta.pop("type", None)
    existing_meta.pop("source", None)
    existing_meta.pop("write_policy", None)
    return normalize_memory_metadata(
        existing_meta,
        source=source,
        memory_type="explicit",
        default_category=category or existing_meta.get("category"),
        confidence=confidence,
    )
