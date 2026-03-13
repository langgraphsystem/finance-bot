"""Tests for Memory Vault skill - show / forget / save."""

import importlib
import sys
import types
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch


class _DummyConnectionPool:
    pass



def _load_memory_vault_handler():
    if "psycopg_pool" not in sys.modules:
        psycopg_pool = types.ModuleType("psycopg_pool")
        psycopg_pool.ConnectionPool = _DummyConnectionPool
        sys.modules["psycopg_pool"] = psycopg_pool

    if "mem0" not in sys.modules:
        mem0 = types.ModuleType("mem0")

        class _DummyMemory:
            @classmethod
            def from_config(cls, config):
                return cls()

        mem0.Memory = _DummyMemory
        sys.modules["mem0"] = mem0
        sys.modules["mem0.vector_stores"] = types.ModuleType("mem0.vector_stores")
        pgvector = types.ModuleType("mem0.vector_stores.pgvector")
        pgvector.ConnectionPool = _DummyConnectionPool
        sys.modules["mem0.vector_stores.pgvector"] = pgvector

    return importlib.import_module("src.skills.memory_vault.handler")


MemoryVaultSkill = _load_memory_vault_handler().MemoryVaultSkill


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
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ),
        patch("src.core.identity.get_core_identity", new_callable=AsyncMock, return_value={}),
        patch("src.core.identity.get_user_rules", new_callable=AsyncMock, return_value=[]),
    ):
        result = await skill.execute(_MockMessage(), ctx, {"_intent": "memory_show"})
    assert "no stored memories" in result.response_text.lower()


async def test_memory_show_with_identity_and_rules_even_without_memories():
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
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ),
        patch(
            "src.core.identity.get_core_identity",
            new_callable=AsyncMock,
            return_value={"name": "Манас", "bot_name": "Хюррем"},
        ),
        patch(
            "src.core.identity.get_user_rules",
            new_callable=AsyncMock,
            return_value=["отвечай кратко"],
        ),
    ):
        result = await skill.execute(_MockMessage(), ctx, {"_intent": "memory_show"})

    assert "Identity:" in result.response_text
    assert "Манас" in result.response_text
    assert "Хюррем" in result.response_text
    assert "отвечай кратко" in result.response_text


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
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ),
        patch("src.core.identity.get_core_identity", new_callable=AsyncMock, return_value={}),
        patch("src.core.identity.get_user_rules", new_callable=AsyncMock, return_value=[]),
    ):
        result = await skill.execute(_MockMessage(), ctx, {"_intent": "memory_show"})
    assert "coffee" in result.response_text
    assert "Brooklyn" in result.response_text
    assert result.buttons is not None
    assert any("clear" in button["text"].lower() for button in result.buttons)


async def test_memory_save():
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock) as mock_add,
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ),
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
    assert call_kwargs["metadata"]["category"] == "life_note"


async def test_memory_save_empty():
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ),
    ):
        result = await skill.execute(_MockMessage(text=""), ctx, {"_intent": "memory_save"})
    assert "what should i remember" in result.response_text.lower()


async def test_memory_forget_with_matches():
    matches = [{"id": "m1", "memory": "User dislikes rain"}]
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
            return_value=matches,
        ),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock) as mock_del,
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
        patch("src.core.identity.get_user_rules", new_callable=AsyncMock, return_value=[]),
    ):
        result = await skill.execute(
            _MockMessage(text="forget about rain"),
            ctx,
            {"_intent": "memory_forget", "memory_query": "rain"},
        )
    assert "deleted 1" in result.response_text.lower()
    mock_del.assert_called_once()


async def test_memory_forget_no_matches():
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
        patch("src.core.identity.get_user_rules", new_callable=AsyncMock, return_value=[]),
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
        patch(
            "src.core.memory.mem0_client.get_all_memories",
            new_callable=AsyncMock,
            return_value=[{"id": "m1", "memory": "remember this"}],
        ),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.delete_all_memories",
            new_callable=AsyncMock,
        ) as mock_del_all,
        patch("src.core.identity.get_user_rules", new_callable=AsyncMock, return_value=[]),
        patch(
            "src.core.identity.get_core_identity",
            new_callable=AsyncMock,
            return_value={"name": "Alice", "bot_name": "Memo"},
        ),
        patch("src.core.identity.clear_user_rules", new_callable=AsyncMock, return_value=1),
        patch(
            "src.core.identity.clear_identity_fields",
            new_callable=AsyncMock,
            return_value=["name", "bot_name"],
        ) as mock_clear_identity,
    ):
        result = await skill.execute(
            _MockMessage(text="forget everything"),
            ctx,
            {"_intent": "memory_forget", "memory_query": "forget everything"},
        )
    assert "all memories cleared" in result.response_text.lower()
    mock_del_all.assert_called_once()
    mock_clear_identity.assert_called_once()


async def test_memory_update_preserves_existing_category():
    ctx = _MockContext()
    matches = [
        {
            "id": "mem0:m1",
            "source_id": "m1",
            "store": "mem0",
            "text": "My name is Alice",
            "metadata": {"category": "user_identity", "source": "memory_vault"},
        }
    ]

    with (
        patch(
            "src.core.memory.registry.write_canonical_memory",
            new_callable=AsyncMock,
            return_value={"store": "identity"},
        ) as mock_write,
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.registry.search_memory_registry",
            new_callable=AsyncMock,
            return_value=matches,
        ),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(
            _MockMessage(text="My name is Alicia"),
            ctx,
            {"_intent": "memory_update", "memory_query": "My name is Alicia"},
        )

    assert "updated" in result.response_text.lower()
    mock_write.assert_awaited_once_with(
        "u1",
        "My name is Alicia",
        source="memory_update",
        category="user_identity",
        existing_memory=matches[0],
    )


async def test_memory_save_user_identity_routes_to_canonical_store():
    ctx = _MockContext()
    with (
        patch(
            "src.core.memory.registry.write_canonical_memory",
            new_callable=AsyncMock,
            return_value={"store": "identity"},
        ) as mock_write,
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock) as mock_add,
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(
            _MockMessage(text="My name is Alice"),
            ctx,
            {"_intent": "memory_save", "memory_query": "My name is Alice"},
        )

    assert "saved" in result.response_text.lower()
    mock_write.assert_awaited_once_with(
        "u1",
        "My name is Alice",
        source="memory_vault",
        category="user_identity",
    )
    mock_add.assert_not_awaited()


async def test_memory_forget_ignores_misrouted_calendar_delete_request():
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ) as mock_search,
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock) as mock_del,
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(
            _MockMessage(text="удали мероприятие из календаря Поход в Чикаго"),
            ctx,
            {
                "_intent": "memory_forget",
                "memory_query": "удали мероприятие из календаря Поход в Чикаго",
            },
        )

    assert "calendar event deletion request" in result.response_text.lower()
    mock_search.assert_not_awaited()
    mock_del.assert_not_awaited()


async def test_memory_forget_all_rules_clears_rules_not_all_memories():
    ctx = _MockContext()
    with (
        patch(
            "src.core.identity.clear_user_rules",
            new_callable=AsyncMock,
            return_value=2,
        ) as mock_clear_rules,
        patch("src.core.identity.clear_identity_fields", new_callable=AsyncMock),
        patch("src.core.identity.get_user_rules", new_callable=AsyncMock, return_value=[]),
        patch("src.core.identity.remove_user_rule", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.get_all_memories",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": "m1",
                    "memory": "без эмодзи",
                    "metadata": {"category": "user_rule"},
                }
            ],
        ),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock) as mock_del,
        patch(
            "src.core.memory.mem0_client.delete_all_memories",
            new_callable=AsyncMock,
        ) as mock_del_all,
    ):
        result = await skill.execute(
            _MockMessage(text="удали все правила"),
            ctx,
            {"_intent": "memory_forget", "memory_query": "удали все правила"},
        )

    assert "all rules cleared" in result.response_text.lower()
    mock_clear_rules.assert_awaited_once_with("u1")
    mock_del.assert_awaited_once_with("m1", "u1")
    mock_del_all.assert_not_awaited()


async def test_memory_forget_specific_saved_rule():
    ctx = _MockContext()
    with (
        patch("src.core.identity.clear_user_rules", new_callable=AsyncMock, return_value=0),
        patch("src.core.identity.clear_identity_fields", new_callable=AsyncMock, return_value=[]),
        patch(
            "src.core.identity.get_user_rules",
            new_callable=AsyncMock,
            return_value=["Мындан кийин сенин атын Хюррем болот"],
        ),
        patch(
            "src.core.identity.remove_user_rule",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_remove_rule,
        patch(
            "src.core.memory.mem0_client.get_all_memories",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": "m1",
                    "memory": "Мындан кийин сенин атын Хюррем болот",
                    "metadata": {"category": "user_rule"},
                }
            ],
        ),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock) as mock_del,
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
    ):
        result = await skill.execute(
            _MockMessage(text="забудь Мындан кийин сенин атын Хюррем болот"),
            ctx,
            {
                "_intent": "memory_forget",
                "memory_query": "забудь Мындан кийин сенин атын Хюррем болот",
            },
        )

    assert "removed rule" in result.response_text.lower()
    mock_remove_rule.assert_awaited_once_with("u1", "Мындан кийин сенин атын Хюррем болот")
    mock_del.assert_awaited_once_with("m1", "u1")


async def test_memory_forget_bot_name_clears_identity():
    ctx = _MockContext()
    with (
        patch("src.core.identity.clear_user_rules", new_callable=AsyncMock, return_value=0),
        patch(
            "src.core.identity.clear_identity_fields",
            new_callable=AsyncMock,
            return_value=["bot_name"],
        ) as mock_clear_identity,
        patch("src.core.identity.get_user_rules", new_callable=AsyncMock, return_value=[]),
        patch("src.core.identity.remove_user_rule", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.get_all_memories",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": "m1",
                    "memory": "зови себя Хюррем",
                    "metadata": {"category": "bot_identity"},
                }
            ],
        ),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock) as mock_del,
        patch(
            "src.core.memory.mem0_client.delete_all_memories",
            new_callable=AsyncMock,
        ) as mock_del_all,
    ):
        result = await skill.execute(
            _MockMessage(text="забудь как тебя зовут"),
            ctx,
            {"_intent": "memory_forget", "memory_query": "забудь как тебя зовут"},
        )

    assert "forgot my saved name" in result.response_text.lower()
    mock_clear_identity.assert_awaited_once_with("u1", ["bot_name"])
    mock_del.assert_awaited_once_with("m1", "u1")
    mock_del_all.assert_not_awaited()


async def test_memory_forget_empty_query():
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
        ),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_all_memories", new_callable=AsyncMock),
        patch("src.core.identity.get_user_rules", new_callable=AsyncMock, return_value=[]),
    ):
        result = await skill.execute(_MockMessage(text=""), ctx, {"_intent": "memory_forget"})
    assert "what should i forget" in result.response_text.lower()


async def test_memory_forget_deletes_summary_registry_match():
    ctx = _MockContext()
    with (
        patch("src.core.memory.mem0_client.get_all_memories", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.add_memory", new_callable=AsyncMock),
        patch("src.core.memory.mem0_client.delete_memory", new_callable=AsyncMock),
        patch(
            "src.core.memory.registry.search_memory_registry",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": "summary:9",
                    "store": "summary",
                    "source_id": "9",
                    "text": "Discussed rain plans last week",
                }
            ],
        ),
        patch(
            "src.core.memory.registry.delete_registry_entry",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_delete_entry,
        patch("src.core.identity.get_user_rules", new_callable=AsyncMock, return_value=[]),
    ):
        result = await skill.execute(
            _MockMessage(text="forget rain plans"),
            ctx,
            {"_intent": "memory_forget", "memory_query": "rain plans"},
        )

    assert "deleted 1" in result.response_text.lower()
    mock_delete_entry.assert_awaited_once()



def test_skill_intents():
    assert "memory_show" in skill.intents
    assert "memory_forget" in skill.intents
    assert "memory_save" in skill.intents



def test_skill_name():
    assert skill.name == "memory_vault"
