from src.core.models.enums import MembershipType, MembershipRole, MembershipStatus, ResourceVisibility


def test_membership_type_values():
    assert MembershipType.family == "family"
    assert MembershipType.worker == "worker"


def test_membership_role_values():
    assert MembershipRole.owner == "owner"
    assert MembershipRole.partner == "partner"
    assert MembershipRole.family_member == "family_member"
    assert MembershipRole.worker == "worker"
    assert MembershipRole.assistant == "assistant"
    assert MembershipRole.accountant == "accountant"
    assert MembershipRole.viewer == "viewer"
    assert MembershipRole.custom == "custom"


def test_membership_status_values():
    assert MembershipStatus.invited == "invited"
    assert MembershipStatus.active == "active"
    assert MembershipStatus.suspended == "suspended"
    assert MembershipStatus.revoked == "revoked"


def test_resource_visibility_values():
    assert ResourceVisibility.private_user == "private_user"
    assert ResourceVisibility.family_shared == "family_shared"
    assert ResourceVisibility.work_shared == "work_shared"
