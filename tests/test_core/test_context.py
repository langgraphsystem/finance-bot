"""Tests for SessionContext."""

from types import SimpleNamespace


def test_owner_can_access_all_scopes(sample_context):
    assert sample_context.can_access_scope("business")
    assert sample_context.can_access_scope("family")
    assert sample_context.can_access_scope("personal")


def test_member_can_only_access_family(member_context):
    assert member_context.can_access_scope("family")
    assert not member_context.can_access_scope("business")
    assert not member_context.can_access_scope("personal")


def test_owner_visible_scopes(sample_context):
    scopes = sample_context.get_visible_scopes()
    assert "business" in scopes
    assert "family" in scopes
    assert "personal" in scopes


def test_member_visible_scopes(member_context):
    scopes = member_context.get_visible_scopes()
    assert scopes == ["family"]


def test_owner_can_access_transaction(sample_context):
    tx = SimpleNamespace(family_id=sample_context.family_id, scope="business")
    assert sample_context.can_access_transaction(tx)


def test_member_cannot_access_business_transaction(member_context):
    tx = SimpleNamespace(family_id=member_context.family_id, scope="business")
    assert not member_context.can_access_transaction(tx)


def test_member_can_access_family_transaction(member_context):
    tx = SimpleNamespace(family_id=member_context.family_id, scope="family")
    assert member_context.can_access_transaction(tx)


def test_cannot_access_other_family(sample_context):
    tx = SimpleNamespace(family_id="other-family-id", scope="family")
    assert not sample_context.can_access_transaction(tx)
