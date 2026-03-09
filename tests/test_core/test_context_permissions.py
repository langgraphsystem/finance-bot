import uuid

from src.core.context import SessionContext


def test_context_has_permissions_field():
    ctx = SessionContext(
        user_id="u1", family_id="f1", role="owner",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
        permissions=["view_finance", "create_finance"],
        membership_type="family",
    )
    assert ctx.permissions == ["view_finance", "create_finance"]
    assert ctx.membership_type == "family"


def test_has_permission():
    ctx = SessionContext(
        user_id="u1", family_id="f1", role="member",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
        permissions=["view_finance", "create_finance"],
    )
    assert ctx.has_permission("view_finance") is True
    assert ctx.has_permission("delete_finance") is False


def test_owner_has_all_permissions():
    ctx = SessionContext(
        user_id="u1", family_id="f1", role="owner",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
    )
    assert ctx.has_permission("anything") is True


def test_default_permissions_empty():
    ctx = SessionContext(
        user_id="u1", family_id="f1", role="member",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
    )
    assert ctx.permissions == []
    assert ctx.membership_type is None


def test_filter_query_uses_visibility_for_transaction():
    """filter_query should use visibility filter for models with visibility column."""
    from sqlalchemy import select

    from src.core.models.transaction import Transaction

    ctx = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="member",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )
    stmt = select(Transaction)
    result = ctx.filter_query(stmt, Transaction)
    sql_str = str(result)
    assert "visibility" in sql_str


def test_filter_query_uses_scope_for_category():
    """filter_query should use scope filter for models without visibility column."""
    from sqlalchemy import select

    from src.core.models.category import Category

    ctx = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="member",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )
    stmt = select(Category)
    result = ctx.filter_query(stmt, Category)
    sql_str = str(result)
    assert "scope" in sql_str
    assert "visibility" not in sql_str
