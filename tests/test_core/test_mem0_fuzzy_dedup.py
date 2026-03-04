"""Tests for Mem0 multi-domain search with fuzzy dedup."""

from unittest.mock import patch


async def test_multi_domain_deduplicates_similar_results():
    """Near-duplicate memories across domains are merged."""
    from src.core.memory.mem0_client import search_memories_multi_domain

    domain_1_results = [
        {"memory": "Paid rent $2000", "metadata": {"category": "rent"}},
        {"memory": "Coffee at Starbucks", "metadata": {"category": "food"}},
    ]
    domain_2_results = [
        {"memory": "paid rent $2000", "metadata": {"category": "housing"}},  # near-dup
        {"memory": "Gym membership renewed", "metadata": {"category": "health"}},
    ]

    async def mock_search(query, user_id, limit=10, filters=None, domain=None):
        if domain and domain.value == "finance":
            return domain_1_results
        return domain_2_results

    with patch(
        "src.core.memory.mem0_client.search_memories",
        new=mock_search,
    ):
        from src.core.memory.mem0_domains import MemoryDomain

        results = await search_memories_multi_domain(
            query="rent payment",
            user_id="user1",
            domains=[MemoryDomain.finance, MemoryDomain.life],
        )

    # Should have 3 unique results (near-dup "paid rent $2000" removed)
    texts = [r.get("memory", "") for r in results]
    assert len(texts) == 3
    assert "Paid rent $2000" in texts
    assert "Coffee at Starbucks" in texts
    assert "Gym membership renewed" in texts


async def test_multi_domain_keeps_empty_text_memories():
    """Memories without text are kept without dedup check."""
    from src.core.memory.mem0_client import search_memories_multi_domain

    domain_results = [
        {"metadata": {"category": "note"}},  # no text
        {"memory": "Valid memory", "metadata": {}},
    ]

    async def mock_search(query, user_id, limit=10, filters=None, domain=None):
        return domain_results

    with patch(
        "src.core.memory.mem0_client.search_memories",
        new=mock_search,
    ):
        from src.core.memory.mem0_domains import MemoryDomain

        results = await search_memories_multi_domain(
            query="test",
            user_id="user1",
            domains=[MemoryDomain.core],
        )

    assert len(results) == 2


async def test_multi_domain_handles_exceptions():
    """Exceptions from individual domains don't crash the merge."""
    from src.core.memory.mem0_client import search_memories_multi_domain

    call_count = 0

    async def mock_search(query, user_id, limit=10, filters=None, domain=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [{"memory": "Result 1", "metadata": {}}]
        raise RuntimeError("Domain failed")

    with patch(
        "src.core.memory.mem0_client.search_memories",
        new=mock_search,
    ):
        from src.core.memory.mem0_domains import MemoryDomain

        results = await search_memories_multi_domain(
            query="test",
            user_id="user1",
            domains=[MemoryDomain.core, MemoryDomain.finance],
        )

    assert len(results) == 1
    assert results[0]["memory"] == "Result 1"
