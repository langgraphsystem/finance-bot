"""Universal AI Data Tools — give LLM agents safe database access.

All functions enforce family_id isolation. The LLM never sees or controls
the family_id parameter — it is injected by the ToolExecutor from SessionContext.
"""

import enum
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc as sa_desc
from sqlalchemy import func, select

from src.core.access import apply_scope_filter
from src.core.audit import log_action
from src.core.db import async_session
from src.core.models import (
    Booking,
    Budget,
    Category,
    Contact,
    LifeEvent,
    Monitor,
    RecurringPayment,
    ShoppingList,
    ShoppingListItem,
    Task,
    Transaction,
)
from src.core.models.document import Document
from src.core.observability import observe
from src.core.pending_actions import store_pending_action

logger = logging.getLogger(__name__)

# ── Table whitelist (table_name -> ORM model class) ──────────────────────────

ALLOWED_TABLES: dict[str, type] = {
    "transactions": Transaction,
    "categories": Category,
    "budgets": Budget,
    "recurring_payments": RecurringPayment,
    "tasks": Task,
    "life_events": LifeEvent,
    "bookings": Booking,
    "contacts": Contact,
    "monitors": Monitor,
    "shopping_lists": ShoppingList,
    "shopping_list_items": ShoppingListItem,
    "documents": Document,
}

# Tables the LLM cannot create/update/delete
READ_ONLY_TABLES = {"categories"}

# Tables that require user confirmation before delete
CONFIRM_DELETE_TABLES = {
    "transactions",
    "budgets",
    "recurring_payments",
    "bookings",
    "contacts",
    "documents",
}

# ── Helpers ──────────────────────────────────────────────────────────────────

_COLUMN_CACHE: dict[str, set[str]] = {}


def _get_allowed_columns(table_name: str) -> set[str]:
    if table_name not in _COLUMN_CACHE:
        model = ALLOWED_TABLES[table_name]
        _COLUMN_CACHE[table_name] = {c.name for c in model.__table__.columns}
    return _COLUMN_CACHE[table_name]


def _validate_table(table_name: str) -> type:
    if table_name not in ALLOWED_TABLES:
        raise ValueError(
            f"Table '{table_name}' not allowed. Allowed: {', '.join(sorted(ALLOWED_TABLES))}"
        )
    return ALLOWED_TABLES[table_name]


def _validate_columns(table_name: str, columns: list[str]) -> None:
    allowed = _get_allowed_columns(table_name)
    invalid = set(columns) - allowed - {"family_id", "user_id", "id"}
    if invalid:
        raise ValueError(f"Invalid columns for '{table_name}': {invalid}")


def _serialize_value(val: Any) -> Any:
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, datetime | date):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, enum.Enum):
        return val.value
    if isinstance(val, dict | list):
        return val
    return val


def _row_to_dict(row: Any, table_name: str) -> dict[str, Any]:
    columns = _get_allowed_columns(table_name)
    return {col: _serialize_value(getattr(row, col, None)) for col in columns if hasattr(row, col)}


def _coerce_enum(model: type, col_name: str, value: Any) -> Any:
    """Convert string values to enum if the column is an enum type."""
    col = model.__table__.columns.get(col_name)
    if col is not None and hasattr(col.type, "enum_class"):
        enum_class = col.type.enum_class
        if enum_class and isinstance(value, str):
            try:
                return enum_class(value)
            except ValueError:
                pass
    return value


def _coerce_uuids(model: type, data: dict[str, Any]) -> None:
    """Convert string UUIDs to uuid.UUID for UUID-typed columns in-place."""
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    for col_name, value in list(data.items()):
        if not isinstance(value, str):
            continue
        col = model.__table__.columns.get(col_name)
        if col is None:
            continue
        if isinstance(col.type, PG_UUID):
            try:
                data[col_name] = uuid.UUID(value)
            except ValueError:
                pass


def _apply_filters(
    stmt: Any,
    model: type,
    filters: dict[str, Any],
    family_id: str,
    role: str | None = None,
    user_id: str | None = None,
) -> Any:
    """Apply family_id + visibility + user filters to a select statement."""
    stmt = stmt.where(model.family_id == uuid.UUID(family_id))
    stmt = _apply_access_filter(stmt, model, role=role, user_id=user_id)

    for col_name, value in filters.items():
        if col_name in ("family_id", "user_id"):
            continue
        col = getattr(model, col_name, None)
        if col is None:
            continue

        if isinstance(value, dict):
            for op, val in value.items():
                val = _coerce_enum(model, col_name, val)
                if op == "eq":
                    stmt = stmt.where(col == val)
                elif op == "ne":
                    stmt = stmt.where(col != val)
                elif op == "gt":
                    stmt = stmt.where(col > val)
                elif op == "gte":
                    stmt = stmt.where(col >= val)
                elif op == "lt":
                    stmt = stmt.where(col < val)
                elif op == "lte":
                    stmt = stmt.where(col <= val)
                elif op == "in":
                    stmt = stmt.where(col.in_(val))
                elif op == "like":
                    stmt = stmt.where(col.ilike(f"%{val}%"))
        else:
            value = _coerce_enum(model, col_name, value)
            stmt = stmt.where(col == value)
    return stmt


def _apply_access_filter(
    stmt: Any,
    model: type,
    role: str | None = None,
    user_id: str | None = None,
) -> Any:
    """Apply visibility-aware access control for the current actor."""
    if hasattr(model, "visibility") and role and user_id:
        from src.core.access import apply_visibility_filter

        return apply_visibility_filter(stmt, model, role, user_id)

    if hasattr(model, "scope") and role:
        return apply_scope_filter(stmt, model, role)

    return stmt


# ── Tool Functions ───────────────────────────────────────────────────────────


@observe(name="data_tool_query")
async def query_data(
    family_id: str,
    user_id: str,
    table: str,
    filters: dict[str, Any] | None = None,
    order_by: str | None = None,
    order_dir: str = "desc",
    limit: int = 20,
    columns: list[str] | None = None,
    role: str = "owner",
) -> dict[str, Any]:
    """Query records from a table with filters."""
    model = _validate_table(table)
    if filters:
        _validate_columns(table, [k for k in filters if k not in ("family_id", "user_id")])
    if columns:
        _validate_columns(table, columns)
    limit = min(limit, 100)

    async with async_session() as session:
        stmt = select(model)
        stmt = _apply_filters(stmt, model, filters or {}, family_id, role=role, user_id=user_id)

        if order_by:
            _validate_columns(table, [order_by])
            col = getattr(model, order_by)
            stmt = stmt.order_by(sa_desc(col) if order_dir == "desc" else col.asc())

        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()

        records = [_row_to_dict(r, table) for r in rows]

    if columns:
        records = [{k: v for k, v in r.items() if k in columns} for r in records]

    return {"records": records, "count": len(records), "table": table}


@observe(name="data_tool_create")
async def create_record(
    family_id: str,
    user_id: str,
    table: str,
    data: dict[str, Any],
    role: str = "owner",
) -> dict[str, Any]:
    """Create a new record in a table."""
    model = _validate_table(table)
    if table in READ_ONLY_TABLES:
        raise ValueError(f"Table '{table}' is read-only")
    _validate_columns(table, list(data.keys()))

    # Inject security fields — LLM cannot control these
    data["family_id"] = uuid.UUID(family_id)
    if "user_id" in _get_allowed_columns(table):
        data["user_id"] = uuid.UUID(user_id)
    record_id = uuid.uuid4()
    data["id"] = record_id

    # Inject default visibility for tables that support it
    if table in ("transactions", "tasks", "documents") and "visibility" not in data:
        if "scope" in data:
            from src.core.access import get_default_visibility
            from src.core.models.enums import Scope as ScopeEnum

            try:
                data["visibility"] = get_default_visibility(ScopeEnum(data["scope"])).value
            except ValueError:
                pass
        elif table == "tasks":
            data["visibility"] = "private_user"
        elif table == "documents":
            data["visibility"] = "private_user"

    # Coerce enum values and UUID foreign keys
    for k, v in list(data.items()):
        data[k] = _coerce_enum(model, k, v)
    _coerce_uuids(model, data)

    async with async_session() as session:
        record = model(**data)
        session.add(record)
        await session.flush()

        await log_action(
            session=session,
            family_id=family_id,
            user_id=user_id,
            action="create",
            entity_type=table,
            entity_id=str(record_id),
            new_data={k: _serialize_value(v) for k, v in data.items()},
        )

        await session.commit()
        return {"record": _row_to_dict(record, table), "table": table}


@observe(name="data_tool_update")
async def update_record(
    family_id: str,
    user_id: str,
    table: str,
    record_id: str,
    data: dict[str, Any],
    role: str = "owner",
) -> dict[str, Any]:
    """Update an existing record by ID."""
    model = _validate_table(table)
    if table in READ_ONLY_TABLES:
        raise ValueError(f"Table '{table}' is read-only")
    _validate_columns(table, list(data.keys()))

    # Never allow updating security fields
    for forbidden in ("family_id", "user_id", "id"):
        data.pop(forbidden, None)

    # Coerce enum values and UUID foreign keys
    for k, v in list(data.items()):
        data[k] = _coerce_enum(model, k, v)
    _coerce_uuids(model, data)

    async with async_session() as session:
        stmt = select(model).where(
            model.id == uuid.UUID(record_id),
            model.family_id == uuid.UUID(family_id),
        )
        stmt = _apply_access_filter(stmt, model, role=role, user_id=user_id)
        record = await session.scalar(stmt)
        if not record:
            return {"error": "Record not found", "table": table}

        old_data = _row_to_dict(record, table)

        for key, value in data.items():
            setattr(record, key, value)

        await log_action(
            session=session,
            family_id=family_id,
            user_id=user_id,
            action="update",
            entity_type=table,
            entity_id=record_id,
            old_data=old_data,
            new_data={k: _serialize_value(v) for k, v in data.items()},
        )

        await session.commit()
        return {"record": _row_to_dict(record, table), "table": table}


@observe(name="data_tool_delete")
async def delete_record(
    family_id: str,
    user_id: str,
    table: str,
    record_id: str,
    role: str = "owner",
) -> dict[str, Any]:
    """Delete a record by ID. Destructive tables require confirmation."""
    model = _validate_table(table)
    if table in READ_ONLY_TABLES:
        raise ValueError(f"Table '{table}' is read-only")

    async with async_session() as session:
        stmt = select(model).where(
            model.id == uuid.UUID(record_id),
            model.family_id == uuid.UUID(family_id),
        )
        stmt = _apply_access_filter(stmt, model, role=role, user_id=user_id)
        record = await session.scalar(stmt)
        if not record:
            return {"error": "Record not found", "table": table}

        record_data = _row_to_dict(record, table)

        if table in CONFIRM_DELETE_TABLES:
            pending_id = await store_pending_action(
                intent="data_tool_delete",
                user_id=user_id,
                family_id=family_id,
                action_data={"table": table, "record_id": record_id},
            )
            return {
                "pending_id": pending_id,
                "message": "Confirmation required before deletion",
                "record": record_data,
            }

        # Non-critical tables: delete immediately
        await log_action(
            session=session,
            family_id=family_id,
            user_id=user_id,
            action="delete",
            entity_type=table,
            entity_id=record_id,
            old_data=record_data,
        )
        await session.delete(record)
        await session.commit()

    return {"deleted": True, "table": table, "record_id": record_id}


@observe(name="data_tool_delete_confirmed")
async def delete_record_confirmed(
    family_id: str,
    user_id: str,
    table: str,
    record_id: str,
    role: str = "owner",
) -> str:
    """Execute a confirmed deletion (called from pending action handler)."""
    model = _validate_table(table)

    async with async_session() as session:
        stmt = select(model).where(
            model.id == uuid.UUID(record_id),
            model.family_id == uuid.UUID(family_id),
        )
        stmt = _apply_access_filter(stmt, model, role=role, user_id=user_id)
        record = await session.scalar(stmt)
        if not record:
            return "Record not found or already deleted."

        old_data = _row_to_dict(record, table)
        await log_action(
            session=session,
            family_id=family_id,
            user_id=user_id,
            action="delete",
            entity_type=table,
            entity_id=record_id,
            old_data=old_data,
        )
        await session.delete(record)
        await session.commit()

    return "Deleted successfully."


@observe(name="data_tool_aggregate")
async def aggregate_data(
    family_id: str,
    user_id: str,
    table: str,
    metric: str,
    column: str | None = None,
    group_by: str | None = None,
    filters: dict[str, Any] | None = None,
    role: str = "owner",
) -> dict[str, Any]:
    """Run aggregate stats (count, sum, avg, min, max) on a table."""
    model = _validate_table(table)
    if metric not in ("count", "sum", "avg", "min", "max"):
        raise ValueError(f"Invalid metric: {metric}. Use: count, sum, avg, min, max")
    if column and metric != "count":
        _validate_columns(table, [column])
    if group_by:
        _validate_columns(table, [group_by])
    if filters:
        _validate_columns(table, [k for k in filters if k not in ("family_id", "user_id")])

    agg_funcs = {
        "count": func.count,
        "sum": func.sum,
        "avg": func.avg,
        "min": func.min,
        "max": func.max,
    }
    agg_func = agg_funcs[metric]

    async with async_session() as session:
        if metric == "count":
            agg_col = agg_func(model.id)
        else:
            agg_col = agg_func(getattr(model, column))

        if group_by:
            group_col = getattr(model, group_by)
            stmt = select(group_col, agg_col.label("value")).group_by(group_col)
        else:
            stmt = select(agg_col.label("value"))

        stmt = _apply_filters(stmt, model, filters or {}, family_id, role=role, user_id=user_id)
        result = await session.execute(stmt)

        if group_by:
            rows = result.all()
            groups = [
                {"key": _serialize_value(r[0]), "value": _serialize_value(r[1])} for r in rows
            ]
            return {"groups": groups, "table": table, "metric": metric}
        else:
            scalar = result.scalar()
            return {
                "result": _serialize_value(scalar) if scalar is not None else 0,
                "table": table,
                "metric": metric,
            }
