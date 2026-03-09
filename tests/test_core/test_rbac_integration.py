"""RBAC integration tests — verify access control across layers."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.core.access import apply_visibility_filter
from src.core.context import SessionContext
from src.core.models.category import Category
from src.core.models.task import Task
from src.core.models.transaction import Transaction
from src.gateway.types import IncomingMessage, MessageType


# --- Fixtures ---


def _make_context(role="owner", permissions=None, membership_type=None):
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role=role,
        language="en",
        currency="USD",
        business_type=None,
        categories=[{"id": str(uuid.uuid4()), "name": "Food", "scope": "family"}],
        merchant_mappings=[],
        permissions=permissions or [],
        membership_type=membership_type,
    )


def _compile_sql(stmt) -> str:
    """Compile a SQLAlchemy statement with literal binds for assertion."""
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _msg(text="test"):
    return IncomingMessage(id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=text)


# --- 1. Permission gate integration ---


async def test_expense_skill_blocks_unauthorized_member():
    """A member without create_finance permission cannot add expenses."""
    from src.skills.add_expense.handler import skill

    ctx = _make_context(role="member", permissions=["view_finance"])
    result = await skill.execute(_msg("50 coffee"), ctx, {"amount": 50, "category": "Food"})
    assert "прав" in result.response_text.lower()


async def test_expense_skill_allows_authorized_member():
    """A member with create_finance permission can add expenses."""
    from src.skills.add_expense.handler import skill

    ctx = _make_context(role="member", permissions=["view_finance", "create_finance"])

    with patch("src.skills.add_expense.handler.async_session") as mock_sm:
        mock_session = AsyncMock()
        mock_sm.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sm.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch("src.skills.add_expense.handler.log_action", new_callable=AsyncMock):
            result = await skill.execute(_msg("50 coffee"), ctx, {
                "amount": 50,
                "category": "Food",
                "confidence": 0.9,
                "merchant": "Starbucks",
            })

    # Should not be a permission error
    assert "прав" not in result.response_text.lower()


async def test_income_skill_blocks_unauthorized():
    """A member without create_finance cannot add income."""
    from src.skills.add_income.handler import skill

    ctx = _make_context(role="worker", permissions=["view_work_tasks"])
    result = await skill.execute(_msg("1000 salary"), ctx, {"amount": 1000})
    assert "прав" in result.response_text.lower()


async def test_budget_skill_blocks_unauthorized():
    """A member without manage_budgets cannot set budget."""
    from src.skills.set_budget.handler import skill

    ctx = _make_context(role="member", permissions=["view_finance"])
    result = await skill.execute(_msg("budget 500"), ctx, {"amount": 500})
    assert "прав" in result.response_text.lower()


# --- 2. Visibility filter integration ---


def test_owner_filter_query_includes_all_visibility_types():
    """Owner's filter_query on Transaction should include all visibility conditions."""
    ctx = _make_context(role="owner")
    stmt = ctx.filter_query(select(Transaction), Transaction)
    sql = _compile_sql(stmt)
    assert "visibility" in sql
    assert "family_id" in sql


def test_member_filter_query_restricts_visibility():
    """Member's filter_query should restrict to family_shared + own private."""
    ctx = _make_context(role="member")
    stmt = ctx.filter_query(select(Transaction), Transaction)
    sql = _compile_sql(stmt)
    assert "family_shared" in sql
    assert "family_id" in sql


def test_worker_sees_only_work_shared_transactions():
    """Worker visibility filter should include work_shared but not family_shared."""
    uid = str(uuid.uuid4())
    stmt = select(Transaction).where(Transaction.family_id == uuid.uuid4())
    result = apply_visibility_filter(stmt, Transaction, "worker", uid)
    sql = _compile_sql(result)
    assert "work_shared" in sql
    assert "family_shared" not in sql


def test_accountant_visibility_matches_role():
    """Accountant should see work_shared resources."""
    uid = str(uuid.uuid4())
    stmt = select(Transaction).where(Transaction.family_id == uuid.uuid4())
    result = apply_visibility_filter(stmt, Transaction, "accountant", uid)
    sql = _compile_sql(result)
    assert "work_shared" in sql


# --- 3. Privilege escalation prevention ---


def test_has_permission_owner_bypass():
    """Owner should have all permissions regardless of permissions list."""
    ctx = _make_context(role="owner", permissions=[])
    assert ctx.has_permission("delete_finance") is True
    assert ctx.has_permission("manage_members") is True
    assert ctx.has_permission("nonexistent") is True


def test_has_permission_member_restricted():
    """Member should only have explicitly granted permissions."""
    ctx = _make_context(role="member", permissions=["view_finance"])
    assert ctx.has_permission("view_finance") is True
    assert ctx.has_permission("delete_finance") is False
    assert ctx.has_permission("manage_members") is False


async def test_invite_member_skill_requires_permission():
    """Invite skill should block users without invite_members permission."""
    from src.skills.invite_member.handler import skill

    ctx = _make_context(role="member", permissions=["view_finance"])
    result = await skill.execute(_msg("invite"), ctx, {})
    assert "permission" in result.response_text.lower() or "denied" in result.response_text.lower()


# --- 4. Context auto-detection ---


def test_filter_query_uses_visibility_for_task():
    """Tasks have visibility column — filter_query should use visibility filter."""
    ctx = _make_context(role="owner")
    stmt = ctx.filter_query(select(Task), Task)
    sql = _compile_sql(stmt)
    assert "visibility" in sql


def test_filter_query_uses_scope_for_category():
    """Categories don't have visibility — should use scope filter."""
    ctx = _make_context(role="member")
    stmt = ctx.filter_query(select(Category), Category)
    sql = _compile_sql(stmt)
    assert "scope" in sql


# --- 5. Visibility filter edge cases ---


def test_visibility_filter_with_empty_user_id():
    """apply_visibility_filter should not crash with empty user_id.

    With empty user_id the private_user condition is skipped (no valid UUID),
    but role-based visibility and scope fallback conditions still apply.
    """
    stmt = select(Transaction)
    result = apply_visibility_filter(stmt, Transaction, "member", "")
    sql = _compile_sql(result)
    # member sees family_shared; private_user condition is skipped (no valid UUID)
    assert "family_shared" in sql
    assert "private_user" not in sql


def test_visibility_filter_with_invalid_user_id():
    """apply_visibility_filter should not crash with invalid user_id."""
    stmt = select(Transaction)
    result = apply_visibility_filter(stmt, Transaction, "owner", "not-a-uuid")
    sql = str(result)
    assert sql  # Should produce some SQL without crashing
