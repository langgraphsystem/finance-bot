"""Tests for Memory Vault skill — show / forget / save."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

from src.skills.memory_vault.handler import MemoryVaultSkill


@dataclass
class _MockContext:
    user_id: str = "u1"
    family_id: str = "f1"
    language: str = "en"
    timezone: str = "UTC"


@dataclass
class _MockMessage:
    id: str = "msg1"
    chat_id: str = "chat1"
    text: str = ""
    user_id: str = "u1"


skill = MemoryVaultSkill()


async def test_memory_show_empty():
    ctx = _MockContext()
    with (
        patch(
            "src.core.memory.mem0_client.get_all_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.search_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(
            _MockMessage(), ctx, {"_intent": "memory_show"}
        )
    assert "no stored memories" in result.response_text.lower()


async def test_memory_show_with_memories():
    memories = [
        {"memory": "User likes coffee", "id": "m1"},
        {"memory": "User lives in Brooklyn", "id": "m2"},
    ]
    ctx = _MockContext()
    with (
        patch(
            "src.core.memory.mem0_client.get_all_memories",
            new_callable=AsyncMock,
            return_value=memories,
        ),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.search_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(_MockMessage(), ctx, {"_intent": "memory_show"})
    assert "coffee" in result.response_text
    assert "Brooklyn" in result.response_text
    assert result.buttons is not None
    assert any("clear" in b["text"].lower() for b in result.buttons)


async def test_memory_save():
    ctx = _MockContext()
    with (
        patch(
            "src.core.memory.mem0_client.add_memory", new_callable=AsyncMock
        ) as mock_add,
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.search_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(
            _MockMessage(text="I love sushi"),
            ctx,
            {"_intent": "memory_save", "memory_query": "I love sushi"},
        )
    assert "saved" in result.response_text.lower() or "remembered" in result.response_text.lower()
    mock_add.assert_called_once()
    call_kwargs = mock_add.call_args.kwargs
    assert call_kwargs["content"] == "I love sushi"
    assert call_kwargs["metadata"]["type"] == "explicit"


async def test_memory_save_empty():
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.search_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(
            _MockMessage(text=""), ctx, {"_intent": "memory_save"}
        )
    assert "what should i remember" in result.response_text.lower()


async def test_memory_forget_with_matches():
    matches = [{"id": "m1", "memory": "User dislikes rain"}]
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories",
            new_callable=AsyncMock,
            return_value=matches,
        ),
        patch(
            "src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock
        ) as mock_del,
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(
            _MockMessage(text="forget about rain"),
            ctx,
            {"_intent": "memory_forget", "memory_query": "rain"},
        )
    assert "deleted 1 memory" in result.response_text.lower()
    mock_del.assert_called_once()


async def test_memory_forget_no_matches():
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(
            _MockMessage(text="forget about unicorns"),
            ctx,
            {"_intent": "memory_forget", "memory_query": "unicorns"},
        )
    assert "no memories found" in result.response_text.lower()


async def test_memory_forget_all():
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.search_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock
        ) as mock_del_all,
    ):
        result = await skill.execute(
            _MockMessage(text="forget everything"),
            ctx,
            {"_intent": "memory_forget", "memory_query": "forget everything"},
        )
    assert "all memories cleared" in result.response_text.lower()
    mock_del_all.assert_called_once()


async def test_memory_forget_empty_query():
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.search_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(
            _MockMessage(text=""), ctx, {"_intent": "memory_forget"}
        )
    assert "what should i forget" in result.response_text.lower()


def test_skill_intents():
    assert "memory_show" in skill.intents
    assert "memory_forget" in skill.intents
    assert "memory_save" in skill.intents


def test_skill_name():
    assert skill.name == "memory_vault"
