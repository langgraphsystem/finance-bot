"""Graph Memory — entity relationship tracking (Phase 3.4).

PostgreSQL-based graph for tracking relationships between entities:
- person → company (works at)
- person → person (family, colleague)
- merchant → category (frequent purchase)
- contact → service (client preference)

Used by contact/booking/email/calendar intents to inject relationship
context into LLM prompts.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update

from src.core.observability import observe

logger = logging.getLogger(__name__)

# Max relationships to return in a single query
MAX_RELATIONSHIPS = 20

# Relationship types
RELATION_TYPES: frozenset[str] = frozenset({
    "works_at",
    "family_member",
    "colleague",
    "client_of",
    "prefers",
    "frequent_merchant",
    "lives_in",
    "related_to",
    "manages",
    "reports_to",
})

# Entity types
ENTITY_TYPES: frozenset[str] = frozenset({
    "person",
    "company",
    "merchant",
    "category",
    "location",
    "service",
    "contact",
})

CONTACT_ROLE_RELATION_MAP: dict[str, str] = {
    "family": "family_member",
    "partner": "colleague",
    "friend": "related_to",
    "client": "related_to",
    "vendor": "related_to",
    "doctor": "related_to",
    "other": "related_to",
}

# Intents that benefit from graph context
GRAPH_INTENTS: frozenset[str] = frozenset({
    "send_email",
    "draft_reply",
    "draft_message",
    "create_booking",
    "list_bookings",
    "add_contact",
    "list_contacts",
    "find_contact",
    "send_to_client",
    "receptionist",
    "create_event",
    "morning_brief",
})


def relation_for_contact_role(role: str | None) -> str:
    """Map a contact role to the graph relation used from the user node."""
    if not role:
        return "related_to"
    return CONTACT_ROLE_RELATION_MAP.get(str(role), "related_to")


@observe(name="add_relationship")
async def add_relationship(
    family_id: str,
    subject_type: str,
    subject_id: str,
    relation: str,
    object_type: str,
    object_id: str,
    metadata: dict[str, Any] | None = None,
    strength: float = 1.0,
) -> int | None:
    """Add or update a relationship in the graph.

    If the exact relationship already exists, strengthens it instead.
    Returns the relationship ID.
    """
    from src.core.db import async_session
    from src.core.models.memory_graph import MemoryGraph

    try:
        fid = uuid.UUID(family_id)
        async with async_session() as session:
            # Check for existing relationship
            result = await session.execute(
                select(MemoryGraph).where(
                    MemoryGraph.family_id == fid,
                    MemoryGraph.subject_type == subject_type,
                    MemoryGraph.subject_id == subject_id,
                    MemoryGraph.relation == relation,
                    MemoryGraph.object_type == object_type,
                    MemoryGraph.object_id == object_id,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Strengthen existing relationship
                existing.strength = min(10.0, existing.strength + 0.5)
                existing.updated_at = datetime.now(UTC)
                if metadata:
                    existing_meta = existing.graph_metadata or {}
                    existing_meta.update(metadata)
                    existing.graph_metadata = existing_meta
                await session.commit()
                return existing.id

            # Create new relationship
            edge = MemoryGraph(
                family_id=fid,
                subject_type=subject_type,
                subject_id=subject_id,
                relation=relation,
                object_type=object_type,
                object_id=object_id,
                strength=strength,
                graph_metadata=metadata or {},
            )
            session.add(edge)
            await session.commit()
            await session.refresh(edge)
            logger.debug(
                "Added relationship: %s:%s -[%s]-> %s:%s",
                subject_type, subject_id, relation, object_type, object_id,
            )
            return edge.id
    except Exception as e:
        logger.debug("Add relationship failed: %s", e)
        return None


@observe(name="get_relationships")
async def get_relationships(
    family_id: str,
    entity_type: str,
    entity_id: str,
    relation: str | None = None,
    direction: str = "both",
    limit: int = MAX_RELATIONSHIPS,
) -> list[dict[str, Any]]:
    """Get relationships for an entity.

    Args:
        direction: "outgoing" (entity is subject), "incoming" (entity is object),
                   "both" (either direction).
    """
    from src.core.db import async_session
    from src.core.models.memory_graph import MemoryGraph

    try:
        fid = uuid.UUID(family_id)
        async with async_session() as session:
            conditions = [MemoryGraph.family_id == fid]

            if direction == "outgoing":
                conditions.extend([
                    MemoryGraph.subject_type == entity_type,
                    MemoryGraph.subject_id == entity_id,
                ])
            elif direction == "incoming":
                conditions.extend([
                    MemoryGraph.object_type == entity_type,
                    MemoryGraph.object_id == entity_id,
                ])
            else:  # both
                conditions.append(
                    or_(
                        and_(
                            MemoryGraph.subject_type == entity_type,
                            MemoryGraph.subject_id == entity_id,
                        ),
                        and_(
                            MemoryGraph.object_type == entity_type,
                            MemoryGraph.object_id == entity_id,
                        ),
                    )
                )

            if relation:
                conditions.append(MemoryGraph.relation == relation)

            result = await session.execute(
                select(MemoryGraph)
                .where(*conditions)
                .order_by(MemoryGraph.strength.desc())
                .limit(limit)
            )
            edges = list(result.scalars().all())

        return [
            {
                "id": e.id,
                "subject_type": e.subject_type,
                "subject_id": e.subject_id,
                "relation": e.relation,
                "object_type": e.object_type,
                "object_id": e.object_id,
                "strength": e.strength,
                "metadata": e.graph_metadata or {},
            }
            for e in edges
        ]
    except Exception as e:
        logger.debug("Get relationships failed: %s", e)
        return []


async def strengthen_relationship(
    family_id: str,
    subject_type: str,
    subject_id: str,
    relation: str,
    object_type: str,
    object_id: str,
    amount: float = 0.5,
) -> bool:
    """Increase the strength of an existing relationship."""
    from src.core.db import async_session
    from src.core.models.memory_graph import MemoryGraph

    try:
        fid = uuid.UUID(family_id)
        async with async_session() as session:
            result = await session.execute(
                update(MemoryGraph)
                .where(
                    MemoryGraph.family_id == fid,
                    MemoryGraph.subject_type == subject_type,
                    MemoryGraph.subject_id == subject_id,
                    MemoryGraph.relation == relation,
                    MemoryGraph.object_type == object_type,
                    MemoryGraph.object_id == object_id,
                )
                .values(
                    strength=func.least(10.0, MemoryGraph.strength + amount),
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
            return result.rowcount > 0
    except Exception as e:
        logger.debug("Strengthen relationship failed: %s", e)
        return False


@observe(name="get_entity_network")
async def get_entity_network(
    family_id: str,
    entity_type: str,
    entity_id: str,
    depth: int = 1,
    limit: int = MAX_RELATIONSHIPS,
) -> list[dict[str, Any]]:
    """Get 1-hop (or N-hop) entity network.

    Returns all entities connected to the given entity within `depth` hops.
    Currently supports depth=1 (direct relationships only).
    """
    if depth < 1:
        return []

    # Depth 1: direct relationships
    relationships = await get_relationships(
        family_id, entity_type, entity_id, direction="both", limit=limit
    )

    if depth == 1 or not relationships:
        return relationships

    # Depth 2+: follow connections (limited to avoid explosion)
    all_edges = list(relationships)
    seen_ids = {(entity_type, entity_id)}

    for edge in relationships:
        # Get the "other" end of the relationship
        if edge["subject_type"] == entity_type and edge["subject_id"] == entity_id:
            other_type, other_id = edge["object_type"], edge["object_id"]
        else:
            other_type, other_id = edge["subject_type"], edge["subject_id"]

        if (other_type, other_id) in seen_ids:
            continue
        seen_ids.add((other_type, other_id))

        # 1-hop from the connected entity
        hop2 = await get_relationships(
            family_id, other_type, other_id,
            direction="both", limit=5,
        )
        all_edges.extend(hop2)
        if len(all_edges) >= limit:
            break

    return all_edges[:limit]


def format_graph_block(relationships: list[dict[str, Any]]) -> str:
    """Format relationships as a context block for LLM injection."""
    if not relationships:
        return ""
    lines: list[str] = []
    for r in relationships[:10]:
        strength_icon = "=" * min(3, int(r.get("strength", 1)))
        line = (
            f"- {r['subject_type']}:{r['subject_id']} "
            f"-[{r['relation']}({strength_icon})]-> "
            f"{r['object_type']}:{r['object_id']}"
        )
        meta = r.get("metadata", {})
        if meta:
            details = ", ".join(f"{k}={v}" for k, v in list(meta.items())[:3])
            if details:
                line += f" ({details})"
        lines.append(line)
    return "\n\n<entity_relationships>\n" + "\n".join(lines) + "\n</entity_relationships>"
