"""Tool executor — dispatches LLM tool calls to data_tools functions.

Injects family_id and user_id from SessionContext into every call.
The LLM never controls these parameters.
"""

import json
import logging
from typing import Any

from src.core.context import SessionContext
from src.core.observability import observe
from src.tools.data_tools import (
    _get_allowed_columns,
    aggregate_data,
    create_record,
    delete_record,
    query_data,
    update_record,
)

logger = logging.getLogger(__name__)

TOOL_FUNCTIONS = {
    "query_data": query_data,
    "create_record": create_record,
    "update_record": update_record,
    "delete_record": delete_record,
    "aggregate_data": aggregate_data,
}

_TABLE_ALIASES = {
    "transaction": "transactions",
    "transactions": "transactions",
    "category": "categories",
    "categories": "categories",
    "budget": "budgets",
    "budgets": "budgets",
    "recurring_payment": "recurring_payments",
    "recurring payments": "recurring_payments",
    "recurring_payments": "recurring_payments",
    "task": "tasks",
    "tasks": "tasks",
    "life_event": "life_events",
    "life event": "life_events",
    "life_events": "life_events",
    "booking": "bookings",
    "bookings": "bookings",
    "contact": "contacts",
    "contacts": "contacts",
    "monitor": "monitors",
    "monitors": "monitors",
    "shopping_list": "shopping_lists",
    "shopping list": "shopping_lists",
    "shopping_lists": "shopping_lists",
    "shopping_list_item": "shopping_list_items",
    "shopping list item": "shopping_list_items",
    "shopping_list_items": "shopping_list_items",
    "document": "documents",
    "documents": "documents",
}

_TABLE_COLUMN_ALIASES = {
    "budgets": {
        "active": "is_active",
        "budget_amount": "amount",
        "limit": "amount",
        "monthly_limit": "amount",
        "weekly_limit": "amount",
        "frequency": "period",
        "interval": "period",
    },
    "recurring_payments": {"active": "is_active"},
}

_TRANSACTION_TYPES = {"income", "expense"}
_LIFE_EVENT_TYPES = {"note", "food", "drink", "mood", "task", "reflection"}


def _normalize_table_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    key = value.strip().lower()
    return _TABLE_ALIASES.get(key)


def _normalize_column_name(table: str, value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    alias_map = _TABLE_COLUMN_ALIASES.get(table, {})
    normalized = alias_map.get(value, value)
    if normalized in _get_allowed_columns(table):
        return normalized
    return None


def _merge_flat_fields_into_data(
    normalized: dict[str, Any],
    *,
    table: str | None,
    reserved_keys: set[str],
) -> dict[str, Any]:
    if not table:
        return normalized

    data = normalized.get("data")
    if not isinstance(data, dict):
        data = {}
        normalized["data"] = data

    for key in list(normalized.keys()):
        if key in reserved_keys:
            continue
        normalized_key = _normalize_column_name(table, key)
        if not normalized_key:
            continue
        data.setdefault(normalized_key, normalized.pop(key))

    return normalized


def _normalize_create_record_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(arguments)

    table = _normalize_table_name(normalized.get("table"))
    if table:
        normalized["table"] = table

    legacy_record = normalized.pop("record", None)
    if "data" not in normalized and isinstance(legacy_record, dict):
        normalized["data"] = legacy_record

    data = normalized.get("data")
    if not isinstance(data, dict):
        data = {}
        normalized["data"] = data

    legacy_type = normalized.pop("type", None)
    if isinstance(legacy_type, str):
        normalized_table = _normalize_table_name(legacy_type)
        if normalized_table and "table" not in normalized:
            normalized["table"] = normalized_table
        elif legacy_type in _TRANSACTION_TYPES:
            normalized.setdefault("table", "transactions")
            data.setdefault("type", legacy_type)
        elif legacy_type in _LIFE_EVENT_TYPES:
            normalized.setdefault("table", "life_events")
            data.setdefault("type", legacy_type)

    return _merge_flat_fields_into_data(
        normalized,
        table=normalized.get("table"),
        reserved_keys={"table", "data", "record", "type"},
    )


def _normalize_update_record_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(arguments)

    table = _normalize_table_name(normalized.get("table"))
    if table:
        normalized["table"] = table

    legacy_record = normalized.pop("record", None)
    if "data" not in normalized and isinstance(legacy_record, dict):
        normalized["data"] = legacy_record

    if "record_id" not in normalized and isinstance(normalized.get("id"), str):
        normalized["record_id"] = normalized.pop("id")
    else:
        normalized.pop("id", None)

    return _merge_flat_fields_into_data(
        normalized,
        table=normalized.get("table"),
        reserved_keys={"table", "record_id", "data", "record"},
    )


def _normalize_query_data_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(arguments)

    table = _normalize_table_name(normalized.get("table"))
    if not table:
        return normalized
    normalized["table"] = table

    filters = normalized.get("filters")
    if isinstance(filters, dict):
        cleaned_filters = {}
        for key, value in filters.items():
            if key in {"family_id", "user_id", "id"}:
                cleaned_filters[key] = value
                continue
            normalized_key = _normalize_column_name(table, key)
            if normalized_key:
                cleaned_filters[normalized_key] = value
        normalized["filters"] = cleaned_filters

    columns = normalized.get("columns")
    if isinstance(columns, list):
        cleaned_columns = []
        for column in columns:
            normalized_column = _normalize_column_name(table, column)
            if normalized_column and normalized_column not in cleaned_columns:
                cleaned_columns.append(normalized_column)
        if cleaned_columns:
            normalized["columns"] = cleaned_columns
        else:
            normalized.pop("columns", None)

    order_by = normalized.get("order_by")
    normalized_order_by = _normalize_column_name(table, order_by)
    if normalized_order_by:
        normalized["order_by"] = normalized_order_by
    else:
        normalized.pop("order_by", None)

    return normalized


def _normalize_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "create_record":
        return _normalize_create_record_arguments(arguments)
    if tool_name == "update_record":
        return _normalize_update_record_arguments(arguments)
    if tool_name == "query_data":
        return _normalize_query_data_arguments(arguments)
    return dict(arguments)


@observe(name="tool_execute")
async def execute_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    context: SessionContext,
) -> dict[str, Any]:
    """Execute a single tool call with security context injection."""
    func = TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return {"error": f"Unknown tool: {tool_name}"}

    arguments = _normalize_tool_arguments(tool_name, arguments)

    # Inject security context — LLM cannot override
    arguments["family_id"] = context.family_id
    arguments["user_id"] = context.user_id
    arguments["role"] = context.role

    try:
        return await func(**arguments)
    except (ValueError, TypeError) as e:
        logger.warning("Tool %s validation error: %s", tool_name, e)
        return {"error": str(e)}
    except Exception:
        logger.exception("Tool %s execution error", tool_name)
        return {"error": f"Internal error executing {tool_name}"}


async def execute_tool_calls_openai(
    tool_calls: list,
    context: SessionContext,
) -> list[dict[str, Any]]:
    """Execute OpenAI-format tool calls, return results for the next LLM turn."""
    results = []
    for tc in tool_calls:
        tool_name = tc.function.name
        try:
            arguments = json.loads(tc.function.arguments)
        except (json.JSONDecodeError, AttributeError):
            arguments = {}

        result = await execute_tool_call(tool_name, arguments, context)
        results.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, default=str),
        })
    return results
