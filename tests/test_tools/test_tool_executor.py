from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.tools.tool_executor import execute_tool_call


def _sample_context() -> SessionContext:
    return SessionContext(
        user_id="11111111-1111-1111-1111-111111111111",
        family_id="22222222-2222-2222-2222-222222222222",
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


async def test_execute_tool_call_normalizes_legacy_create_record_transaction():
    context = _sample_context()
    mock = AsyncMock(return_value={"ok": True})

    with patch.dict("src.tools.tool_executor.TOOL_FUNCTIONS", {"create_record": mock}, clear=False):
        await execute_tool_call(
            "create_record",
            {
                "type": "expense",
                "record": {"amount": 100, "merchant": "кофе"},
            },
            context,
        )

    mock.assert_awaited_once()
    kwargs = mock.await_args.kwargs
    assert kwargs["table"] == "transactions"
    assert kwargs["data"]["type"] == "expense"
    assert kwargs["data"]["amount"] == 100
    assert kwargs["family_id"] == context.family_id
    assert kwargs["user_id"] == context.user_id
    assert kwargs["role"] == context.role


async def test_execute_tool_call_normalizes_legacy_create_record_table_alias():
    context = _sample_context()
    mock = AsyncMock(return_value={"ok": True})

    with patch.dict("src.tools.tool_executor.TOOL_FUNCTIONS", {"create_record": mock}, clear=False):
        await execute_tool_call(
            "create_record",
            {
                "type": "budget",
                "record": {"amount": 1000, "period": "monthly"},
            },
            context,
        )

    kwargs = mock.await_args.kwargs
    assert kwargs["table"] == "budgets"
    assert kwargs["data"] == {"amount": 1000, "period": "monthly"}


async def test_execute_tool_call_collects_flat_create_record_fields_into_data():
    context = _sample_context()
    mock = AsyncMock(return_value={"ok": True})

    with patch.dict("src.tools.tool_executor.TOOL_FUNCTIONS", {"create_record": mock}, clear=False):
        await execute_tool_call(
            "create_record",
            {
                "table": "transactions",
                "amount": 100,
                "merchant": "кофе",
                "date": "2026-03-09",
                "category_id": "33333333-3333-3333-3333-333333333333",
            },
            context,
        )

    kwargs = mock.await_args.kwargs
    assert kwargs["table"] == "transactions"
    assert kwargs["data"]["amount"] == 100
    assert kwargs["data"]["merchant"] == "кофе"
    assert kwargs["data"]["date"] == "2026-03-09"
    assert kwargs["data"]["category_id"] == "33333333-3333-3333-3333-333333333333"


async def test_execute_tool_call_normalizes_query_data_legacy_columns():
    context = _sample_context()
    mock = AsyncMock(return_value={"records": [], "count": 0, "table": "budgets"})

    with patch.dict("src.tools.tool_executor.TOOL_FUNCTIONS", {"query_data": mock}, clear=False):
        await execute_tool_call(
            "query_data",
            {
                "table": "budget",
                "filters": {
                    "active": True,
                    "start_date": {"gte": "2026-03-01"},
                    "end_date": {"lte": "2026-03-31"},
                },
                "columns": ["id", "active", "start_date", "end_date"],
                "order_by": "active",
            },
            context,
        )

    kwargs = mock.await_args.kwargs
    assert kwargs["table"] == "budgets"
    assert kwargs["filters"] == {"is_active": True}
    assert kwargs["columns"] == ["id", "is_active"]
    assert kwargs["order_by"] == "is_active"


async def test_execute_tool_call_drops_invalid_category_columns():
    context = _sample_context()
    mock = AsyncMock(return_value={"records": [], "count": 0, "table": "categories"})

    with patch.dict("src.tools.tool_executor.TOOL_FUNCTIONS", {"query_data": mock}, clear=False):
        await execute_tool_call(
            "query_data",
            {
                "table": "categories",
                "columns": ["name", "created_at"],
                "order_by": "created_at",
            },
            context,
        )

    kwargs = mock.await_args.kwargs
    assert kwargs["columns"] == ["name"]
    assert "order_by" not in kwargs


async def test_execute_tool_call_collects_flat_update_record_fields_into_data():
    context = _sample_context()
    mock = AsyncMock(return_value={"ok": True})

    with patch.dict("src.tools.tool_executor.TOOL_FUNCTIONS", {"update_record": mock}, clear=False):
        await execute_tool_call(
            "update_record",
            {
                "table": "budget",
                "id": "44444444-4444-4444-4444-444444444444",
                "amount": 1200,
                "active": False,
            },
            context,
        )

    kwargs = mock.await_args.kwargs
    assert kwargs["table"] == "budgets"
    assert kwargs["record_id"] == "44444444-4444-4444-4444-444444444444"
    assert kwargs["data"] == {"amount": 1200, "is_active": False}
