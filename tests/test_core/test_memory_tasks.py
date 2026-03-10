from unittest.mock import AsyncMock, patch

from src.core.tasks.memory_tasks import async_mem0_update


async def test_async_mem0_update_does_not_clear_buffer_without_durable_write():
    with (
        patch(
            "src.core.memory.mem0_client.add_memory",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "src.core.memory.mem0_dlq.enqueue_failed_memory",
            new_callable=AsyncMock,
            side_effect=RuntimeError("redis down"),
        ),
        patch(
            "src.core.memory.session_buffer.clear_session_buffer",
            new_callable=AsyncMock,
        ) as mock_clear,
    ):
        await async_mem0_update.original_func("user-1", "salary 6000", {"category": "income"})

    mock_clear.assert_not_called()


async def test_async_mem0_update_clears_buffer_when_queued():
    with (
        patch(
            "src.core.memory.mem0_client.add_memory",
            new_callable=AsyncMock,
            return_value={"queued": True},
        ),
        patch(
            "src.core.memory.session_buffer.clear_session_buffer",
            new_callable=AsyncMock,
        ) as mock_clear,
    ):
        await async_mem0_update.original_func("user-1", "salary 6000", {"category": "income"})

    mock_clear.assert_awaited_once_with("user-1")
