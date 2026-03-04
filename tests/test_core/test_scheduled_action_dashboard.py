"""Tests for SIA dashboard query templates."""

from src.core.scheduled_actions.dashboard import DASHBOARD_QUERIES


def test_dashboard_queries_has_all_five_metrics():
    expected = {"activation_rate", "reliability", "source_freshness", "engagement", "cost"}
    assert set(DASHBOARD_QUERIES.keys()) == expected


def test_dashboard_queries_are_valid_sql_strings():
    for name, sql in DASHBOARD_QUERIES.items():
        assert isinstance(sql, str), f"{name} is not a string"
        assert len(sql) > 50, f"{name} query is too short"
        upper = sql.upper()
        assert "SELECT" in upper, f"{name} missing SELECT"
        assert "scheduled_action" in sql.lower(), f"{name} missing scheduled_action reference"


def test_reliability_query_references_status_filters():
    sql = DASHBOARD_QUERIES["reliability"]
    assert "success" in sql
    assert "partial" in sql
    assert "failed" in sql
    assert "7 days" in sql


def test_cost_query_references_tokens():
    sql = DASHBOARD_QUERIES["cost"]
    assert "tokens_used" in sql
    assert "model_used" in sql
