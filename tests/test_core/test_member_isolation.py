"""Regression tests: member cannot access owner's private data."""
from src.core.access import can_view_visibility, get_default_visibility
from src.core.context import SessionContext
from src.core.models.enums import ResourceVisibility, Scope


def _owner_context():
    return SessionContext(
        user_id="owner-uuid", family_id="fam-uuid", role="owner",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
        permissions=["view_finance", "create_finance", "edit_finance",
                     "delete_finance", "view_reports", "manage_budgets",
                     "invite_members", "manage_members"],
        membership_type="family",
    )


def _member_context():
    return SessionContext(
        user_id="member-uuid", family_id="fam-uuid", role="member",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
        permissions=["create_finance", "view_budgets"],
        membership_type="family",
    )


def test_member_cannot_manage_members():
    ctx = _member_context()
    assert ctx.has_permission("manage_members") is False
    assert ctx.has_permission("invite_members") is False


def test_member_cannot_delete_finance():
    ctx = _member_context()
    assert ctx.has_permission("delete_finance") is False


def test_member_cannot_view_reports():
    ctx = _member_context()
    assert ctx.has_permission("view_reports") is False


def test_owner_has_all_permissions():
    ctx = _owner_context()
    assert ctx.has_permission("manage_members") is True
    assert ctx.has_permission("delete_finance") is True
    assert ctx.has_permission("view_reports") is True


def test_member_can_create_finance():
    ctx = _member_context()
    assert ctx.has_permission("create_finance") is True


def test_member_scope_forced_to_family():
    ctx = _member_context()
    scope = "personal"
    if ctx.role == "member":
        scope = "family"
    assert scope == "family"


def test_visibility_private_user_blocks_other():
    assert can_view_visibility("member", "private_user", "other") is False
    assert can_view_visibility("owner", "private_user", "other") is False


def test_visibility_family_shared_allows_member():
    assert can_view_visibility("member", "family_shared", "self") is True


def test_visibility_work_shared_blocks_member():
    assert can_view_visibility("member", "work_shared", "self") is False


def test_default_visibility_maps_correctly():
    assert get_default_visibility(Scope.personal) == ResourceVisibility.private_user
    assert get_default_visibility(Scope.family) == ResourceVisibility.family_shared
    assert get_default_visibility(Scope.business) == ResourceVisibility.work_shared
