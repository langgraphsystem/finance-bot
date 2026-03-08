from src.core.access import can_view_visibility, get_default_visibility
from src.core.models.enums import ResourceVisibility, Scope


def test_owner_can_view_own_private():
    assert can_view_visibility("owner", ResourceVisibility.private_user, "self") is True


def test_owner_can_view_family_shared():
    assert can_view_visibility("owner", ResourceVisibility.family_shared, "self") is True


def test_owner_can_view_work_shared():
    assert can_view_visibility("owner", ResourceVisibility.work_shared, "self") is True


def test_owner_cannot_view_other_private():
    assert can_view_visibility("owner", ResourceVisibility.private_user, "other") is False


def test_member_can_view_family_shared():
    assert can_view_visibility("member", ResourceVisibility.family_shared, "self") is True


def test_member_cannot_view_work_shared():
    assert can_view_visibility("member", ResourceVisibility.work_shared, "self") is False


def test_member_can_view_own_private():
    assert can_view_visibility("member", ResourceVisibility.private_user, "self") is True


def test_member_cannot_view_other_private():
    assert can_view_visibility("member", ResourceVisibility.private_user, "other") is False


def test_accountant_can_view_work_shared():
    assert can_view_visibility("accountant", ResourceVisibility.work_shared, "self") is True


def test_accountant_cannot_view_family_shared():
    assert can_view_visibility("accountant", ResourceVisibility.family_shared, "self") is False


def test_default_visibility_from_scope():
    assert get_default_visibility(Scope.personal) == ResourceVisibility.private_user
    assert get_default_visibility(Scope.family) == ResourceVisibility.family_shared
    assert get_default_visibility(Scope.business) == ResourceVisibility.work_shared
