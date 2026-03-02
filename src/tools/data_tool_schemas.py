"""OpenAI-compatible tool schemas for AI Data Tools.

These schemas define the parameters the LLM can pass. Note that
family_id and user_id are NEVER exposed — they are injected by
the ToolExecutor from SessionContext.

Progressive tool loading: ``get_schemas_for_domain()`` returns only
the tables relevant to a domain, reducing token usage by ~70%.
"""

_TABLE_NAMES = [
    "transactions",
    "categories",
    "budgets",
    "recurring_payments",
    "tasks",
    "life_events",
    "bookings",
    "contacts",
    "monitors",
    "shopping_lists",
    "shopping_list_items",
    "documents",
    "invoices",
]

_WRITABLE_TABLES = [t for t in _TABLE_NAMES if t != "categories"]

# ---------------------------------------------------------------------------
# Per-domain table groups for progressive tool loading
# ---------------------------------------------------------------------------

DOMAIN_TABLES: dict[str, list[str]] = {
    "finance": ["transactions", "categories", "budgets", "recurring_payments", "invoices"],
    "tasks": ["tasks"],
    "life": ["life_events", "monitors"],
    "booking": ["bookings", "contacts"],
    "shopping": ["shopping_lists", "shopping_list_items"],
    "document": ["documents"],
}

# Adjacent domains that frequently cross-reference each other
_ADJACENT_DOMAINS: dict[str, list[str]] = {
    "finance": ["tasks"],
    "tasks": ["finance", "life", "shopping"],
    "life": ["finance", "tasks"],
    "booking": ["contacts"],
    "shopping": [],
    "document": [],
}

# Map agent names to their primary domain
_AGENT_DOMAIN_MAP: dict[str, str] = {
    "chat": "finance",
    "analytics": "finance",
    "finance_specialist": "finance",
    "tasks": "tasks",
    "life": "life",
    "booking": "booking",
}

DATA_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_data",
            "description": (
                "Query records from a database table. Use this to look up "
                "transactions, tasks, bookings, life events, contacts, budgets, etc. "
                "Returns a list of matching records."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": _TABLE_NAMES,
                        "description": "The database table to query.",
                    },
                    "filters": {
                        "type": "object",
                        "description": (
                            "Column filters. Simple: {\"status\": \"pending\"}. "
                            "Operators: {\"date\": {\"gte\": \"2026-01-01\"}}. "
                            "Supported: eq, ne, gt, gte, lt, lte, in, like."
                        ),
                        "additionalProperties": True,
                    },
                    "order_by": {
                        "type": "string",
                        "description": "Column to sort by (e.g. 'date', 'created_at').",
                    },
                    "order_dir": {
                        "type": "string",
                        "enum": ["asc", "desc"],
                        "description": "Sort direction. Default: desc.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max records to return (1-100, default 20).",
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific columns to return. Omit for all columns.",
                    },
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_record",
            "description": (
                "Create a new record in a database table. "
                "Do NOT set id, family_id, or user_id — those are auto-set. "
                "For transactions: set type (income/expense), amount, merchant, date, category_id. "
                "For tasks: set title, due_date, priority (low/medium/high/urgent). "
                "For life_events: set type (note/food/drink/mood), data (JSON), note."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": _WRITABLE_TABLES,
                        "description": "The table to insert into.",
                    },
                    "data": {
                        "type": "object",
                        "description": "Record fields and values to set.",
                        "additionalProperties": True,
                    },
                },
                "required": ["table", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_record",
            "description": (
                "Update an existing record by its UUID. "
                "Cannot change id, family_id, or user_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": _WRITABLE_TABLES,
                        "description": "The table containing the record.",
                    },
                    "record_id": {
                        "type": "string",
                        "description": "UUID of the record to update.",
                    },
                    "data": {
                        "type": "object",
                        "description": "Fields to update with new values.",
                        "additionalProperties": True,
                    },
                },
                "required": ["table", "record_id", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_record",
            "description": (
                "Delete a record by UUID. For important data (transactions, budgets, "
                "bookings, contacts) returns a pending confirmation — tell the user "
                "to confirm. For other data, deletes immediately."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": _WRITABLE_TABLES,
                        "description": "The table containing the record.",
                    },
                    "record_id": {
                        "type": "string",
                        "description": "UUID of the record to delete.",
                    },
                },
                "required": ["table", "record_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_data",
            "description": (
                "Run aggregate statistics on a table: count, sum, avg, min, max. "
                "Optionally group by a column. "
                "Example: sum of amount in transactions grouped by type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": _TABLE_NAMES,
                        "description": "The table to aggregate.",
                    },
                    "metric": {
                        "type": "string",
                        "enum": ["count", "sum", "avg", "min", "max"],
                        "description": "Aggregation function to apply.",
                    },
                    "column": {
                        "type": "string",
                        "description": "Column to aggregate (required for sum/avg/min/max).",
                    },
                    "group_by": {
                        "type": "string",
                        "description": "Column to group results by (e.g. 'type', 'category_id').",
                    },
                    "filters": {
                        "type": "object",
                        "description": "Same filter syntax as query_data.",
                        "additionalProperties": True,
                    },
                },
                "required": ["table", "metric"],
            },
        },
    },
]


def get_schemas_for_domain(
    agent_name: str | None = None,
    include_adjacent: bool = True,
) -> list[dict]:
    """Return tool schemas scoped to a domain's tables.

    Reduces token usage by ~70% compared to sending all 12 tables.
    Falls back to full schemas if the agent has no domain mapping.

    Parameters
    ----------
    agent_name:
        Agent name (e.g. "chat", "tasks", "life").
    include_adjacent:
        If True, also include tables from adjacent domains
        (e.g. finance→tasks for cross-referencing).
    """
    if not agent_name or agent_name not in _AGENT_DOMAIN_MAP:
        return DATA_TOOL_SCHEMAS

    domain = _AGENT_DOMAIN_MAP[agent_name]
    tables = set(DOMAIN_TABLES.get(domain, []))

    if include_adjacent:
        for adj in _ADJACENT_DOMAINS.get(domain, []):
            tables.update(DOMAIN_TABLES.get(adj, []))

    if not tables:
        return DATA_TOOL_SCHEMAS

    scoped_tables = sorted(tables)
    scoped_writable = [t for t in scoped_tables if t != "categories"]

    return _build_schemas(scoped_tables, scoped_writable)


def _build_schemas(
    table_names: list[str], writable_tables: list[str]
) -> list[dict]:
    """Build tool schemas with scoped table enums."""
    return [
        {
            "type": "function",
            "function": {
                "name": "query_data",
                "description": (
                    "Query records from a database table. Use this to look up "
                    "transactions, tasks, bookings, life events, contacts, budgets, etc. "
                    "Returns a list of matching records."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table": {
                            "type": "string",
                            "enum": table_names,
                            "description": "The database table to query.",
                        },
                        "filters": {
                            "type": "object",
                            "description": (
                                "Column filters. Simple: {\"status\": \"pending\"}. "
                                "Operators: {\"date\": {\"gte\": \"2026-01-01\"}}. "
                                "Supported: eq, ne, gt, gte, lt, lte, in, like."
                            ),
                            "additionalProperties": True,
                        },
                        "order_by": {
                            "type": "string",
                            "description": "Column to sort by (e.g. 'date', 'created_at').",
                        },
                        "order_dir": {
                            "type": "string",
                            "enum": ["asc", "desc"],
                            "description": "Sort direction. Default: desc.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max records to return (1-100, default 20).",
                        },
                        "columns": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Specific columns to return. Omit for all columns."
                            ),
                        },
                    },
                    "required": ["table"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_record",
                "description": (
                    "Create a new record in a database table. "
                    "Do NOT set id, family_id, or user_id — those are auto-set. "
                    "For transactions: set type (income/expense), amount, merchant, "
                    "date, category_id. "
                    "For tasks: set title, due_date, priority (low/medium/high/urgent). "
                    "For life_events: set type (note/food/drink/mood), data (JSON), note."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table": {
                            "type": "string",
                            "enum": writable_tables,
                            "description": "The table to insert into.",
                        },
                        "data": {
                            "type": "object",
                            "description": "Record fields and values to set.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["table", "data"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_record",
                "description": (
                    "Update an existing record by its UUID. "
                    "Cannot change id, family_id, or user_id."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table": {
                            "type": "string",
                            "enum": writable_tables,
                            "description": "The table containing the record.",
                        },
                        "record_id": {
                            "type": "string",
                            "description": "UUID of the record to update.",
                        },
                        "data": {
                            "type": "object",
                            "description": "Fields to update with new values.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["table", "record_id", "data"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_record",
                "description": (
                    "Delete a record by UUID. For important data (transactions, "
                    "budgets, bookings, contacts) returns a pending confirmation "
                    "— tell the user to confirm. For other data, deletes immediately."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table": {
                            "type": "string",
                            "enum": writable_tables,
                            "description": "The table containing the record.",
                        },
                        "record_id": {
                            "type": "string",
                            "description": "UUID of the record to delete.",
                        },
                    },
                    "required": ["table", "record_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "aggregate_data",
                "description": (
                    "Run aggregate statistics on a table: count, sum, avg, min, max. "
                    "Optionally group by a column. "
                    "Example: sum of amount in transactions grouped by type."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table": {
                            "type": "string",
                            "enum": table_names,
                            "description": "The table to aggregate.",
                        },
                        "metric": {
                            "type": "string",
                            "enum": ["count", "sum", "avg", "min", "max"],
                            "description": "Aggregation function to apply.",
                        },
                        "column": {
                            "type": "string",
                            "description": (
                                "Column to aggregate (required for sum/avg/min/max)."
                            ),
                        },
                        "group_by": {
                            "type": "string",
                            "description": (
                                "Column to group results by (e.g. 'type', 'category_id')."
                            ),
                        },
                        "filters": {
                            "type": "object",
                            "description": "Same filter syntax as query_data.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["table", "metric"],
                },
            },
        },
    ]
