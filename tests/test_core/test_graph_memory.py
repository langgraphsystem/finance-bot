"""Tests for Graph Memory (Phase 3.4)."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.core.memory.graph_memory import (
    CONTACT_ROLE_RELATION_MAP,
    ENTITY_TYPES,
    GRAPH_INTENTS,
    MAX_RELATIONSHIPS,
    RELATION_TYPES,
    add_relationship,
    format_graph_block,
    get_entity_network,
    get_relationships,
    relation_for_contact_role,
    strengthen_relationship,
)

_SENTINEL = object()


def _mock_db_session(scalars_result=None, scalar_one=_SENTINEL):
    """Helper: build async context manager mock for DB session."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_result = MagicMock()

    if scalars_result is not None:
        mock_result.scalars.return_value.all.return_value = scalars_result
    if scalar_one is not _SENTINEL:
        mock_result.scalar_one_or_none.return_value = scalar_one

    mock_session.execute.return_value = mock_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_ctx.__aexit__.return_value = False
    return mock_ctx, mock_session


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_relation_types(self):
        assert "works_at" in RELATION_TYPES
        assert "family_member" in RELATION_TYPES
        assert "client_of" in RELATION_TYPES
        assert "frequent_merchant" in RELATION_TYPES

    def test_entity_types(self):
        assert "person" in ENTITY_TYPES
        assert "company" in ENTITY_TYPES
        assert "merchant" in ENTITY_TYPES
        assert "contact" in ENTITY_TYPES

    def test_graph_intents(self):
        assert "send_email" in GRAPH_INTENTS
        assert "create_booking" in GRAPH_INTENTS
        assert "find_contact" in GRAPH_INTENTS
        assert "list_contacts" in GRAPH_INTENTS
        assert "morning_brief" in GRAPH_INTENTS

    def test_max_relationships(self):
        assert MAX_RELATIONSHIPS == 20

    def test_contact_role_relation_map(self):
        assert CONTACT_ROLE_RELATION_MAP["family"] == "family_member"
        assert relation_for_contact_role("partner") == "colleague"
        assert relation_for_contact_role("client") == "related_to"
        assert relation_for_contact_role(None) == "related_to"


# ---------------------------------------------------------------------------
# add_relationship
# ---------------------------------------------------------------------------
class TestAddRelationship:
    async def test_creates_new_relationship(self):
        mock_ctx, mock_session = _mock_db_session(scalar_one=None)

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await add_relationship(
                fid, "person", "john", "works_at", "company", "acme",
            )

        # Verify the edge was added and committed
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        # Verify the added object is a MemoryGraph with correct fields
        from src.core.models.memory_graph import MemoryGraph

        added_obj = mock_session.add.call_args[0][0]
        assert isinstance(added_obj, MemoryGraph)
        assert added_obj.subject_type == "person"
        assert added_obj.subject_id == "john"
        assert added_obj.relation == "works_at"
        assert added_obj.object_type == "company"
        assert added_obj.object_id == "acme"

    async def test_strengthens_existing(self):
        existing = MagicMock()
        existing.id = 10
        existing.strength = 2.0
        existing.graph_metadata = {}

        mock_ctx, mock_session = _mock_db_session(scalar_one=existing)

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await add_relationship(
                fid, "person", "john", "works_at", "company", "acme",
            )

        assert result == 10
        assert existing.strength == 2.5
        mock_session.add.assert_not_called()
        mock_session.commit.assert_called_once()

    async def test_strength_caps_at_10(self):
        existing = MagicMock()
        existing.id = 10
        existing.strength = 9.8
        existing.graph_metadata = {}

        mock_ctx, _ = _mock_db_session(scalar_one=existing)

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await add_relationship(
                fid, "person", "john", "works_at", "company", "acme",
            )

        assert existing.strength == 10.0

    async def test_merges_metadata_on_existing(self):
        existing = MagicMock()
        existing.id = 10
        existing.strength = 1.0
        existing.graph_metadata = {"old_key": "val"}

        mock_ctx, _ = _mock_db_session(scalar_one=existing)

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await add_relationship(
                fid, "person", "john", "works_at", "company", "acme",
                metadata={"new_key": "new_val"},
            )

        assert existing.graph_metadata["old_key"] == "val"
        assert existing.graph_metadata["new_key"] == "new_val"

    async def test_db_failure_returns_none(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await add_relationship(
                fid, "person", "john", "works_at", "company", "acme",
            )

        assert result is None


# ---------------------------------------------------------------------------
# get_relationships
# ---------------------------------------------------------------------------
class TestGetRelationships:
    async def test_returns_edges(self):
        edge = MagicMock()
        edge.id = 1
        edge.subject_type = "person"
        edge.subject_id = "john"
        edge.relation = "works_at"
        edge.object_type = "company"
        edge.object_id = "acme"
        edge.strength = 3.0
        edge.graph_metadata = {"role": "engineer"}

        mock_ctx, _ = _mock_db_session(scalars_result=[edge])

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await get_relationships(fid, "person", "john")

        assert len(result) == 1
        assert result[0]["relation"] == "works_at"
        assert result[0]["metadata"]["role"] == "engineer"

    async def test_empty_on_no_edges(self):
        mock_ctx, _ = _mock_db_session(scalars_result=[])

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await get_relationships(fid, "person", "nobody")

        assert result == []

    async def test_db_failure_returns_empty(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await get_relationships(fid, "person", "john")

        assert result == []

    async def test_filters_private_edges_for_other_users(self):
        edge = MagicMock()
        edge.id = 1
        edge.subject_type = "person"
        edge.subject_id = "john"
        edge.relation = "works_at"
        edge.object_type = "company"
        edge.object_id = "acme"
        edge.strength = 3.0
        edge.graph_metadata = {"user_id": "owner-1", "visibility": "private_user"}

        mock_ctx, _ = _mock_db_session(scalars_result=[edge])

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await get_relationships(
                fid,
                "person",
                "john",
                requester_user_id="other-user",
                requester_role="owner",
            )

        assert result == []


# ---------------------------------------------------------------------------
# strengthen_relationship
# ---------------------------------------------------------------------------
class TestStrengthenRelationship:
    async def test_strengthens_existing(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await strengthen_relationship(
                fid, "person", "john", "works_at", "company", "acme",
            )

        assert result is True
        mock_session.commit.assert_called_once()

    async def test_returns_false_if_not_found(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await strengthen_relationship(
                fid, "person", "nobody", "works_at", "company", "acme",
            )

        assert result is False

    async def test_db_failure_returns_false(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        fid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await strengthen_relationship(
                fid, "person", "john", "works_at", "company", "acme",
            )

        assert result is False


# ---------------------------------------------------------------------------
# get_entity_network
# ---------------------------------------------------------------------------
class TestGetEntityNetwork:
    async def test_returns_1_hop(self):
        edge = {
            "id": 1,
            "subject_type": "person",
            "subject_id": "john",
            "relation": "works_at",
            "object_type": "company",
            "object_id": "acme",
            "strength": 3.0,
            "metadata": {},
        }

        with patch(
            "src.core.memory.graph_memory.get_relationships",
            new_callable=AsyncMock,
            return_value=[edge],
        ):
            result = await get_entity_network(
                "00000000-0000-0000-0000-000000000001",
                "person", "john", depth=1,
            )

        assert len(result) == 1
        assert result[0]["relation"] == "works_at"

    async def test_depth_0_returns_empty(self):
        result = await get_entity_network(
            "00000000-0000-0000-0000-000000000001",
            "person", "john", depth=0,
        )
        assert result == []

    async def test_2_hop_traversal(self):
        edge1 = {
            "id": 1,
            "subject_type": "person",
            "subject_id": "john",
            "relation": "works_at",
            "object_type": "company",
            "object_id": "acme",
            "strength": 3.0,
            "metadata": {},
        }
        edge2 = {
            "id": 2,
            "subject_type": "person",
            "subject_id": "alice",
            "relation": "works_at",
            "object_type": "company",
            "object_id": "acme",
            "strength": 2.0,
            "metadata": {},
        }

        call_count = 0

        async def mock_get_rel(family_id, entity_type, entity_id, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [edge1]  # Direct: john -> acme
            return [edge2]  # Hop 2: acme -> alice

        with patch(
            "src.core.memory.graph_memory.get_relationships",
            side_effect=mock_get_rel,
        ):
            result = await get_entity_network(
                "00000000-0000-0000-0000-000000000001",
                "person", "john", depth=2,
            )

        assert len(result) == 2
        assert result[0]["subject_id"] == "john"
        assert result[1]["subject_id"] == "alice"


# ---------------------------------------------------------------------------
# format_graph_block
# ---------------------------------------------------------------------------
class TestFormatGraphBlock:
    def test_empty_returns_empty(self):
        assert format_graph_block([]) == ""

    def test_formats_with_tags(self):
        edges = [
            {
                "subject_type": "person",
                "subject_id": "john",
                "relation": "works_at",
                "object_type": "company",
                "object_id": "acme",
                "strength": 3.0,
                "metadata": {"role": "engineer"},
            }
        ]
        result = format_graph_block(edges)
        assert "<entity_relationships>" in result
        assert "</entity_relationships>" in result
        assert "john" in result
        assert "works_at" in result
        assert "acme" in result
        assert "role=engineer" in result

    def test_caps_at_10(self):
        edges = [
            {
                "subject_type": "person",
                "subject_id": f"person_{i}",
                "relation": "knows",
                "object_type": "person",
                "object_id": f"other_{i}",
                "strength": 1.0,
                "metadata": {},
            }
            for i in range(20)
        ]
        result = format_graph_block(edges)
        assert result.count("person_") == 10

    def test_strength_icons(self):
        edge = {
            "subject_type": "a",
            "subject_id": "x",
            "relation": "r",
            "object_type": "b",
            "object_id": "y",
            "strength": 3.0,
            "metadata": {},
        }
        result = format_graph_block([edge])
        assert "===" in result  # strength 3 = 3 equals signs
