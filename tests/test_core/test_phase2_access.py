"""Phase 2 access layer regression tests."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.core.access import apply_visibility_filter, can_view_visibility
from src.core.context import SessionContext
from src.core.models.category import Category
from src.core.models.task import Task
from src.core.models.transaction import Transaction


def _compile_sql(stmt) -> str:
    """Compile a SQLAlchemy statement with literal binds for assertion."""
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.fixture
def owner_ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
        permissions=[],
    )


@pytest.fixture
def member_ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="member",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
        permissions=["view_finance", "create_finance"],
    )


@pytest.fixture
def worker_ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="worker",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
        permissions=["view_work_tasks"],
        membership_type="worker",
    )


# --- filter_query auto-detection ---


def test_filter_query_transaction_uses_visibility(owner_ctx):
    stmt = select(Transaction)
    result = owner_ctx.filter_query(stmt, Transaction)
    sql = str(result)
    assert "visibility" in sql


def test_filter_query_category_uses_scope_not_visibility(owner_ctx):
    stmt = select(Category)
    result = owner_ctx.filter_query(stmt, Category)
    sql = str(result)
    assert "scope" in sql
    assert "visibility" not in sql


def test_filter_query_task_uses_visibility(owner_ctx):
    stmt = select(Task)
    result = owner_ctx.filter_query(stmt, Task)
    sql = str(result)
    assert "visibility" in sql


# --- apply_visibility_filter SQL output ---


def test_owner_visibility_allows_all_types():
    uid = str(uuid.uuid4())
    stmt = select(Transaction)
    result = apply_visibility_filter(stmt, Transaction, "owner", uid)
    sql = _compile_sql(result)
    assert "private_user" in sql
    assert "family_shared" in sql
    assert "work_shared" in sql


def test_member_visibility_includes_family_shared():
    uid = str(uuid.uuid4())
    stmt = select(Transaction)
    result = apply_visibility_filter(stmt, Transaction, "member", uid)
    sql = _compile_sql(result)
    assert "family_shared" in sql
    assert "private_user" in sql


def test_worker_visibility_includes_work_shared():
    uid = str(uuid.uuid4())
    stmt = select(Transaction)
    result = apply_visibility_filter(stmt, Transaction, "worker", uid)
    sql = _compile_sql(result)
    assert "work_shared" in sql
    assert "private_user" in sql


# --- NULL visibility backward compat ---


def test_null_visibility_fallback_transaction():
    uid = str(uuid.uuid4())
    stmt = select(Transaction)
    result = apply_visibility_filter(stmt, Transaction, "member", uid)
    sql = str(result)
    # Should contain IS NULL for legacy rows
    assert "NULL" in sql.upper()


def test_null_visibility_fallback_task():
    uid = str(uuid.uuid4())
    stmt = select(Task)
    result = apply_visibility_filter(stmt, Task, "member", uid)
    sql = str(result)
    assert "NULL" in sql.upper()


# --- can_view_visibility ---


def test_owner_can_view_all_own():
    assert can_view_visibility("owner", "private_user", "self") is True
    assert can_view_visibility("owner", "family_shared", "self") is True
    assert can_view_visibility("owner", "work_shared", "self") is True


def test_nobody_sees_other_private():
    assert can_view_visibility("member", "private_user", "other") is False
    assert can_view_visibility("owner", "private_user", "other") is False
    assert can_view_visibility("worker", "private_user", "other") is False


def test_member_can_view_family_shared():
    assert can_view_visibility("member", "family_shared", "other") is True


def test_worker_can_view_work_shared():
    assert can_view_visibility("worker", "work_shared", "other") is True


def test_worker_cannot_view_family_shared():
    assert can_view_visibility("worker", "family_shared", "other") is False


def test_accountant_can_view_work_shared():
    assert can_view_visibility("accountant", "work_shared", "other") is True


# --- Permission checks ---


def test_owner_has_all_permissions(owner_ctx):
    assert owner_ctx.has_permission("view_finance") is True
    assert owner_ctx.has_permission("anything_at_all") is True


def test_member_has_granted_permissions(member_ctx):
    assert member_ctx.has_permission("view_finance") is True
    assert member_ctx.has_permission("create_finance") is True
    assert member_ctx.has_permission("delete_finance") is False


def test_worker_has_only_work_permissions(worker_ctx):
    assert worker_ctx.has_permission("view_work_tasks") is True
    assert worker_ctx.has_permission("view_finance") is False
