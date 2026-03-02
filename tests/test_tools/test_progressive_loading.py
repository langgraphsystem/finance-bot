"""Tests for progressive tool loading — per-domain schema scoping."""

from src.tools.data_tool_schemas import (
    _AGENT_DOMAIN_MAP,
    DATA_TOOL_SCHEMAS,
    DOMAIN_TABLES,
    get_schemas_for_domain,
)


class TestDomainTableMapping:
    def test_all_agents_have_domains(self):
        """Every agent in the map has a corresponding domain."""
        for agent, domain in _AGENT_DOMAIN_MAP.items():
            assert domain in DOMAIN_TABLES, f"Agent {agent} → domain {domain} not in DOMAIN_TABLES"

    def test_finance_domain_tables(self):
        tables = DOMAIN_TABLES["finance"]
        assert "transactions" in tables
        assert "categories" in tables
        assert "budgets" in tables
        assert "invoices" in tables

    def test_tasks_domain_tables(self):
        assert DOMAIN_TABLES["tasks"] == ["tasks"]

    def test_life_domain_tables(self):
        tables = DOMAIN_TABLES["life"]
        assert "life_events" in tables
        assert "monitors" in tables


class TestGetSchemasForDomain:
    def test_unknown_agent_returns_full_schemas(self):
        schemas = get_schemas_for_domain(agent_name="unknown_agent")
        assert schemas == DATA_TOOL_SCHEMAS

    def test_none_agent_returns_full_schemas(self):
        schemas = get_schemas_for_domain(agent_name=None)
        assert schemas == DATA_TOOL_SCHEMAS

    def test_finance_agent_has_finance_tables(self):
        schemas = get_schemas_for_domain(agent_name="chat")
        query_schema = schemas[0]
        table_enum = query_schema["function"]["parameters"]["properties"]["table"]["enum"]
        assert "transactions" in table_enum
        assert "budgets" in table_enum

    def test_finance_agent_excludes_unrelated_tables(self):
        schemas = get_schemas_for_domain(agent_name="chat")
        query_schema = schemas[0]
        table_enum = query_schema["function"]["parameters"]["properties"]["table"]["enum"]
        assert "bookings" not in table_enum
        assert "contacts" not in table_enum
        assert "documents" not in table_enum
        assert "shopping_lists" not in table_enum

    def test_finance_includes_adjacent_tasks(self):
        schemas = get_schemas_for_domain(agent_name="chat", include_adjacent=True)
        query_schema = schemas[0]
        table_enum = query_schema["function"]["parameters"]["properties"]["table"]["enum"]
        assert "tasks" in table_enum  # adjacent domain

    def test_finance_without_adjacent(self):
        schemas = get_schemas_for_domain(agent_name="chat", include_adjacent=False)
        query_schema = schemas[0]
        table_enum = query_schema["function"]["parameters"]["properties"]["table"]["enum"]
        assert "tasks" not in table_enum

    def test_tasks_agent_scoped(self):
        schemas = get_schemas_for_domain(agent_name="tasks")
        query_schema = schemas[0]
        table_enum = query_schema["function"]["parameters"]["properties"]["table"]["enum"]
        # tasks + adjacent finance + life + shopping
        assert "tasks" in table_enum
        assert "transactions" in table_enum  # from adjacent finance
        assert "life_events" in table_enum  # from adjacent life
        assert "shopping_lists" in table_enum  # from adjacent shopping

    def test_booking_agent_scoped(self):
        schemas = get_schemas_for_domain(agent_name="booking")
        query_schema = schemas[0]
        table_enum = query_schema["function"]["parameters"]["properties"]["table"]["enum"]
        assert "bookings" in table_enum
        assert "contacts" in table_enum
        assert "transactions" not in table_enum

    def test_scoped_schemas_have_all_5_tools(self):
        schemas = get_schemas_for_domain(agent_name="life")
        assert len(schemas) == 5
        tool_names = {s["function"]["name"] for s in schemas}
        assert tool_names == {
            "query_data", "create_record", "update_record",
            "delete_record", "aggregate_data",
        }

    def test_scoped_writable_excludes_categories(self):
        schemas = get_schemas_for_domain(agent_name="chat")
        create_schema = schemas[1]  # create_record
        writable_enum = create_schema["function"]["parameters"]["properties"]["table"]["enum"]
        assert "categories" not in writable_enum

    def test_scoped_schemas_smaller_than_full(self):
        """Progressive loading should reduce token count."""
        import json

        full = json.dumps(DATA_TOOL_SCHEMAS)
        scoped = json.dumps(get_schemas_for_domain(agent_name="life"))
        assert len(scoped) < len(full)
