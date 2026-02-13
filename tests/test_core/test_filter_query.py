"""Tests for SessionContext.filter_query()."""

from unittest.mock import MagicMock


def test_owner_filter_query_callable(sample_context):
    """Owner context should have a callable filter_query method."""
    assert hasattr(sample_context, "filter_query")
    assert callable(sample_context.filter_query)


def test_member_filter_query_callable(member_context):
    """Member context should have a callable filter_query method."""
    assert hasattr(member_context, "filter_query")
    assert callable(member_context.filter_query)


def test_owner_filter_query_adds_family_filter(sample_context):
    """Owner filter_query should add family_id WHERE clause."""
    mock_stmt = MagicMock()
    mock_stmt.where.return_value = mock_stmt

    mock_model = MagicMock()
    mock_model.family_id = MagicMock()
    mock_model.scope = MagicMock()

    sample_context.filter_query(mock_stmt, mock_model)
    # Owner: only one .where() call (family_id), no scope restriction
    mock_stmt.where.assert_called_once()


def test_member_filter_query_adds_scope_filter(member_context):
    """Member filter_query should add both family_id and scope WHERE clauses."""
    mock_stmt = MagicMock()
    mock_stmt.where.return_value = mock_stmt

    mock_model = MagicMock()
    mock_model.family_id = MagicMock()
    mock_model.scope = MagicMock()

    member_context.filter_query(mock_stmt, mock_model)
    # Member: two .where() calls (family_id + scope restriction)
    assert mock_stmt.where.call_count == 2


def test_filter_query_returns_statement(sample_context):
    """filter_query should return the modified statement."""
    mock_stmt = MagicMock()
    mock_stmt.where.return_value = mock_stmt

    mock_model = MagicMock()

    result = sample_context.filter_query(mock_stmt, mock_model)
    assert result is mock_stmt
