from src.core.models.workspace_membership import ROLE_PRESETS, WorkspaceMembership


def test_model_tablename():
    assert WorkspaceMembership.__tablename__ == "workspace_memberships"


def test_model_has_required_columns():
    columns = {c.name for c in WorkspaceMembership.__table__.columns}
    required = {
        "id", "family_id", "user_id", "membership_type", "role",
        "permissions", "status", "invited_by_user_id", "joined_at",
        "created_at", "updated_at",
    }
    assert required.issubset(columns), f"Missing: {required - columns}"


def test_default_permissions():
    assert "owner" in ROLE_PRESETS
    assert "partner" in ROLE_PRESETS
    assert "accountant" in ROLE_PRESETS
    assert "viewer" in ROLE_PRESETS
    assert "view_finance" in ROLE_PRESETS["accountant"]
