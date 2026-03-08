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
