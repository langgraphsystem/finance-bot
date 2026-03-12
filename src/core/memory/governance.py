"""Shared governance helpers for memory metadata and audit-safe mutations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.core.memory.mem0_domains import get_domain_for_category

DEFAULT_MEMORY_CATEGORY = "life_note"
DEFAULT_MEMORY_TYPE = "implicit"
DEFAULT_MEMORY_SOURCE = "memory_system"
DEFAULT_RETENTION_CLASS = "long_term"
DEFAULT_SENSITIVITY = "personal"
DEFAULT_CONFIDENCE = 0.7
MEMORY_SCHEMA_VERSION = 1

LEGACY_TYPE_CATEGORY_MAP = {
    "note": "life_note",
    "spending_pattern": "spending_pattern",
    "weekly_digest": "life_digest",
    "saved_video": "content",
    "saved_content": "content",
    "program": "program_artifact",
    "program_modify": "program_artifact",
}


def normalize_memory_content(content: str | None) -> str:
    """Normalize free-form memory content before persistence."""
    return str(content or "").strip()


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
    legacy_type = str(meta.get("type") or memory_type or "").strip()

    category = str(
        meta.get("category")
        or LEGACY_TYPE_CATEGORY_MAP.get(legacy_type)
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


def prepare_memory_write(
    content: str | None,
    metadata: dict[str, Any] | None = None,
    *,
    source: str | None = None,
    memory_type: str | None = None,
    category: str | None = None,
    confidence: float | None = None,
    sensitivity: str | None = None,
    retention_class: str | None = None,
    domain: str | None = None,
    source_ref: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Prepare content + metadata for a governed memory write."""
    normalized_content = normalize_memory_content(content)
    if not normalized_content:
        raise ValueError("memory content is empty")

    meta = dict(metadata or {})
    if domain and "domain" not in meta:
        meta["domain"] = domain
    if source_ref and "source_ref" not in meta:
        meta["source_ref"] = source_ref
    if "schema_version" not in meta:
        meta["schema_version"] = MEMORY_SCHEMA_VERSION
    if "written_at" not in meta:
        meta["written_at"] = datetime.now(UTC).isoformat()
    if "write_path" not in meta:
        meta["write_path"] = "governed_mem0"

    normalized_meta = normalize_memory_metadata(
        meta,
        source=source,
        memory_type=memory_type,
        default_category=category,
        confidence=confidence,
        sensitivity=sensitivity,
        retention_class=retention_class,
    )
    return normalized_content, normalized_meta


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
