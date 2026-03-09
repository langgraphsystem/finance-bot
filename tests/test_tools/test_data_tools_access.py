import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.core.models.budget import Budget
from src.core.models.transaction import Transaction
from src.tools.data_tools import _apply_access_filter, _apply_filters


def _compile_sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_apply_filters_uses_scope_filter_for_scope_only_models():
    stmt = select(Budget)
    result = _apply_filters(
        stmt,
        Budget,
        {},
        family_id=str(uuid.uuid4()),
        role="family_member",
        user_id=str(uuid.uuid4()),
    )

    sql = _compile_sql(result)
    assert "budgets.scope" in sql
    assert "'family'" in sql
    assert "visibility" not in sql


def test_apply_access_filter_uses_visibility_for_visibility_models():
    stmt = select(Transaction)
    result = _apply_access_filter(
        stmt,
        Transaction,
        role="worker",
        user_id=str(uuid.uuid4()),
    )

    sql = _compile_sql(result)
    assert "transactions.visibility" in sql
    assert "work_shared" in sql
    assert "private_user" in sql
