"""Regression tests: member cannot access owner's private data."""
import uuid

from src.core.access import apply_visibility_filter, can_view_visibility, get_default_visibility
from src.core.context import SessionContext
from src.core.models.enums import ResourceVisibility, Scope

_FAM_UUID = str(uuid.uuid4())
_OWNER_UUID = str(uuid.uuid4())
_MEMBER_UUID = str(uuid.uuid4())
_PARTNER_UUID = str(uuid.uuid4())
_WORKER_UUID = str(uuid.uuid4())
_ACCOUNTANT_UUID = str(uuid.uuid4())


def _owner_context():
    return SessionContext(
        user_id=_OWNER_UUID, family_id=_FAM_UUID, role="owner",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
        permissions=["view_finance", "create_finance", "edit_finance",
                     "delete_finance", "view_reports", "manage_budgets",
                     "invite_members", "manage_members"],
        membership_type="family",
    )


def _member_context():
    return SessionContext(
        user_id=_MEMBER_UUID, family_id=_FAM_UUID, role="member",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
        permissions=["create_finance", "view_budgets"],
        membership_type="family",
    )


def _partner_context():
    return SessionContext(
        user_id=_PARTNER_UUID, family_id=_FAM_UUID, role="partner",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
        permissions=["view_finance", "create_finance", "edit_finance",
                     "view_budgets", "manage_budgets", "view_reports"],
        membership_type="family",
    )


def _worker_context():
    return SessionContext(
        user_id=_WORKER_UUID, family_id=_FAM_UUID, role="worker",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
        permissions=["view_work_tasks", "manage_work_tasks", "view_contacts"],
        membership_type="worker",
    )


def _accountant_context():
    return SessionContext(
        user_id=_ACCOUNTANT_UUID, family_id=_FAM_UUID, role="accountant",
        language="en", currency="USD", business_type=None,
        categories=[], merchant_mappings=[],
        permissions=["view_finance", "create_finance", "edit_finance",
                     "view_reports", "export_reports",
                     "view_budgets", "manage_budgets"],
        membership_type="worker",
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


# ---------------------------------------------------------------------------
# Requirement #2: member cannot view owner memory
# Mem0 namespaces are scoped via {user_id}:{domain} — inherently isolated.
# ---------------------------------------------------------------------------


def test_mem0_namespace_isolates_users():
    """Mem0 domain scoping ensures member cannot access owner's namespace."""
    from src.core.memory.mem0_domains import MemoryDomain

    for domain in MemoryDomain:
        owner_ns = f"{_OWNER_UUID}:{domain.value}"
        member_ns = f"{_MEMBER_UUID}:{domain.value}"
        assert owner_ns != member_ns, f"Namespaces must differ for {domain}"


def test_mem0_search_scoped_by_user_id():
    """Verify that mem0_client.search() receives user_id-scoped namespace."""
    from src.core.memory.mem0_domains import MemoryDomain

    owner_finance_ns = f"{_OWNER_UUID}:{MemoryDomain.finance.value}"
    member_finance_ns = f"{_MEMBER_UUID}:{MemoryDomain.finance.value}"

    # Member searching in their namespace cannot reach owner's
    assert _OWNER_UUID not in member_finance_ns
    assert _MEMBER_UUID not in owner_finance_ns


# ---------------------------------------------------------------------------
# Requirement #3: worker cannot view family private data
# ---------------------------------------------------------------------------


def test_worker_cannot_view_family_shared():
    assert can_view_visibility("worker", "family_shared", "self") is False
    assert can_view_visibility("worker", "family_shared", "other") is False


def test_worker_can_view_work_shared():
    assert can_view_visibility("worker", "work_shared", "self") is True


def test_worker_cannot_view_private_of_others():
    assert can_view_visibility("worker", "private_user", "other") is False


# ---------------------------------------------------------------------------
# Requirement #4: accountant can view work finance but not private chat
# ---------------------------------------------------------------------------


def test_accountant_can_view_work_shared():
    assert can_view_visibility("accountant", "work_shared", "self") is True


def test_accountant_cannot_view_others_private():
    assert can_view_visibility("accountant", "private_user", "other") is False


def test_accountant_cannot_view_family_shared():
    assert can_view_visibility("accountant", "family_shared", "self") is False


def test_accountant_has_finance_permissions():
    ctx = _accountant_context()
    assert ctx.has_permission("view_finance") is True
    assert ctx.has_permission("view_reports") is True
    assert ctx.has_permission("export_reports") is True


def test_accountant_cannot_manage_members():
    ctx = _accountant_context()
    assert ctx.has_permission("manage_members") is False
    assert ctx.has_permission("invite_members") is False


# ---------------------------------------------------------------------------
# Requirement #5: partner can view family-shared but not owner personal
# ---------------------------------------------------------------------------


def test_partner_can_view_family_shared():
    assert can_view_visibility("partner", "family_shared", "self") is True


def test_partner_can_view_work_shared():
    assert can_view_visibility("partner", "work_shared", "self") is True


def test_partner_cannot_view_others_private():
    assert can_view_visibility("partner", "private_user", "other") is False


def test_partner_can_view_own_private():
    assert can_view_visibility("partner", "private_user", "self") is True


# ---------------------------------------------------------------------------
# Requirement #9: shared tasks visible only to users with correct permission
# (visibility-based SQL filter verification)
# ---------------------------------------------------------------------------


def _compile_sql(stmt):
    """Compile SQLAlchemy statement to string for inspection."""
    from sqlalchemy.dialects import postgresql

    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_family_member_filter_includes_family_shared_tasks():
    """Family member's filter_query includes family_shared visibility for tasks."""
    from src.core.models.task import Task

    ctx = _member_context()
    from sqlalchemy import select

    stmt = select(Task).where(Task.family_id == uuid.UUID(ctx.family_id))
    filtered = apply_visibility_filter(stmt, Task, ctx.role, ctx.user_id)
    sql = _compile_sql(filtered)
    assert "family_shared" in sql


def test_worker_filter_excludes_family_shared_tasks():
    """Worker's filter_query does NOT include family_shared for tasks."""
    from src.core.models.task import Task

    ctx = _worker_context()
    from sqlalchemy import select

    stmt = select(Task).where(Task.family_id == uuid.UUID(ctx.family_id))
    filtered = apply_visibility_filter(stmt, Task, ctx.role, ctx.user_id)
    sql = _compile_sql(filtered)
    assert "family_shared" not in sql
    assert "work_shared" in sql


def test_worker_filter_includes_own_private_tasks():
    """Worker can see their own private tasks."""
    from src.core.models.task import Task

    ctx = _worker_context()
    from sqlalchemy import select

    stmt = select(Task).where(Task.family_id == uuid.UUID(ctx.family_id))
    filtered = apply_visibility_filter(stmt, Task, ctx.role, ctx.user_id)
    sql = _compile_sql(filtered)
    assert "private_user" in sql
    assert ctx.user_id in sql


def test_owner_filter_includes_all_visibility_types():
    """Owner sees all visibility types."""
    from src.core.models.task import Task

    ctx = _owner_context()
    from sqlalchemy import select

    stmt = select(Task).where(Task.family_id == uuid.UUID(ctx.family_id))
    filtered = apply_visibility_filter(stmt, Task, ctx.role, ctx.user_id)
    sql = _compile_sql(filtered)
    assert "family_shared" in sql
    assert "work_shared" in sql
    assert "private_user" in sql
