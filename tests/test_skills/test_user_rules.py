import importlib
import sys
import types
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch


class _DummyConnectionPool:
    pass


def _load_user_rules_handler():
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

    return importlib.import_module("src.skills.user_rules.handler")


_HANDLER = _load_user_rules_handler()
skill = _HANDLER.skill
SkillResult = importlib.import_module("src.skills.base").SkillResult


@dataclass
class _MockContext:
    user_id: str = "u1"
    family_id: str = "f1"
    language: str = "ru"
    timezone: str = "UTC"


@dataclass
class _MockMessage:
    id: str = "msg1"
    chat_id: str = "chat1"
    text: str = ""
    user_id: str = "u1"


async def test_user_rules_saves_bot_name():
    ctx = _MockContext()
    with (
        patch(
            "src.core.memory.registry.write_canonical_memory",
            new_callable=AsyncMock,
            return_value={"store": "identity"},
        ) as mock_write,
    ):
        result = await skill.execute(
            _MockMessage(text="Тебя зовут Хюррем"),
            ctx,
            {"rule_text": "Тебя зовут Хюррем"},
        )

    assert "Хюррем" in result.response_text
    mock_write.assert_awaited_once_with(
        "u1",
        "Тебя зовут Хюррем",
        source="user_rules",
        category="bot_identity",
    )


async def test_user_rules_delegates_forget_command_to_memory_vault():
    ctx = _MockContext()
    delegated = SkillResult(response_text="Removed saved rule.")

    with (
        patch(
            "src.core.memory.registry.write_canonical_memory",
            new_callable=AsyncMock,
        ) as mock_write,
        patch(
            "src.skills.memory_vault.handler.skill.execute",
            new_callable=AsyncMock,
            return_value=delegated,
        ) as mock_memory_forget,
    ):
        result = await skill.execute(
            _MockMessage(text="забудь Мындан кийин сенин атын Хюррем болот"),
            ctx,
            {"rule_text": "забудь Мындан кийин сенин атын Хюррем болот"},
        )

    assert result is delegated
    mock_memory_forget.assert_awaited_once()
    mock_write.assert_not_awaited()


async def test_user_rules_saves_user_name():
    ctx = _MockContext()
    with (
        patch(
            "src.core.memory.registry.write_canonical_memory",
            new_callable=AsyncMock,
            return_value={"store": "identity"},
        ) as mock_write,
    ):
        result = await skill.execute(
            _MockMessage(text="Меня зовут Манас"),
            ctx,
            {"rule_text": "Меня зовут Манас"},
        )

    assert "Манас" in result.response_text
    mock_write.assert_awaited_once_with(
        "u1",
        "Меня зовут Манас",
        source="user_rules",
        category="user_identity",
    )
