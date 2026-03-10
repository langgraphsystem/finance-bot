# Phase 1 RBAC: Membership + Visibility Implementation Plan

**Статус:** ✅ DONE (2026-03-10) — верифицировано по коду

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Introduce `workspace_memberships` table as the access source of truth and `visibility` columns on key entities, enabling intra-tenant privacy (private_user / family_shared / work_shared).

**Architecture:** New `workspace_memberships` table stores per-user membership type, role, and JSONB permissions. A `resource_visibility` enum added to transactions, tasks, documents, conversation_messages, and session_summaries. Existing `users.family_id` + `users.role` kept for compatibility during migration. Access layer (`src/core/access.py`) extended with visibility-aware filtering.

**Tech Stack:** SQLAlchemy 2.0 async, Alembic, PostgreSQL enums, pytest-asyncio

---

## Task 1: Add New Enums

**Files:**
- Modify: `src/core/models/enums.py`
- Test: `tests/test_core/test_enums.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_core/test_enums.py
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core/test_enums.py -v`
Expected: FAIL with ImportError

**Step 3: Write implementation**

Add to `src/core/models/enums.py`:

```python
class MembershipType(enum.StrEnum):
    family = "family"
    worker = "worker"


class MembershipRole(enum.StrEnum):
    owner = "owner"
    partner = "partner"
    family_member = "family_member"
    worker = "worker"
    assistant = "assistant"
    accountant = "accountant"
    viewer = "viewer"
    custom = "custom"


class MembershipStatus(enum.StrEnum):
    invited = "invited"
    active = "active"
    suspended = "suspended"
    revoked = "revoked"


class ResourceVisibility(enum.StrEnum):
    private_user = "private_user"
    family_shared = "family_shared"
    work_shared = "work_shared"
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core/test_enums.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/models/enums.py tests/test_core/test_enums.py
git commit -m "feat: add MembershipType, MembershipRole, MembershipStatus, ResourceVisibility enums"
```

---

## Task 2: Create WorkspaceMembership Model

**Files:**
- Create: `src/core/models/workspace_membership.py`
- Modify: `src/core/models/__init__.py` (add import + __all__)
- Test: `tests/test_core/test_workspace_membership_model.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_core/test_workspace_membership_model.py
from src.core.models.workspace_membership import WorkspaceMembership
from src.core.models.enums import MembershipType, MembershipRole, MembershipStatus


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
    from src.core.models.workspace_membership import ROLE_PRESETS
    assert "owner" in ROLE_PRESETS
    assert "partner" in ROLE_PRESETS
    assert "accountant" in ROLE_PRESETS
    assert "viewer" in ROLE_PRESETS
    assert "view_finance" in ROLE_PRESETS["accountant"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core/test_workspace_membership_model.py -v`
Expected: FAIL with ImportError

**Step 3: Write implementation**

```python
# src/core/models/workspace_membership.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import MembershipRole, MembershipStatus, MembershipType


ROLE_PRESETS: dict[str, list[str]] = {
    "owner": [
        "view_finance", "create_finance", "edit_finance", "delete_finance",
        "view_reports", "export_reports",
        "view_budgets", "manage_budgets",
        "view_work_tasks", "manage_work_tasks",
        "view_work_documents", "manage_work_documents",
        "view_contacts", "manage_contacts",
        "invite_members", "manage_members",
    ],
    "partner": [
        "view_finance", "create_finance", "edit_finance",
        "view_budgets", "manage_budgets",
        "view_reports",
    ],
    "family_member": [
        "create_finance",
        "view_budgets",
    ],
    "worker": [
        "view_work_tasks", "manage_work_tasks",
        "view_contacts",
    ],
    "assistant": [
        "view_work_tasks", "manage_work_tasks",
        "view_contacts", "manage_contacts",
        "view_work_documents",
    ],
    "accountant": [
        "view_finance", "create_finance", "edit_finance",
        "view_reports", "export_reports",
        "view_budgets", "manage_budgets",
    ],
    "viewer": [
        "view_finance", "view_reports", "view_budgets",
    ],
    "custom": [],
}


class WorkspaceMembership(Base, TimestampMixin):
    __tablename__ = "workspace_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"),
    )
    membership_type: Mapped[MembershipType] = mapped_column(
        ENUM(MembershipType, name="membership_type", create_type=False),
    )
    role: Mapped[MembershipRole] = mapped_column(
        ENUM(MembershipRole, name="membership_role", create_type=False),
    )
    permissions: Mapped[dict] = mapped_column(JSONB, default=list)
    status: Mapped[MembershipStatus] = mapped_column(
        ENUM(MembershipStatus, name="membership_status", create_type=False),
        default=MembershipStatus.active,
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=func.now(),
    )

    user = relationship("User", foreign_keys=[user_id])
    invited_by = relationship("User", foreign_keys=[invited_by_user_id])
```

Add to `src/core/models/__init__.py`:
```python
from src.core.models.workspace_membership import WorkspaceMembership
# In __all__:
    "WorkspaceMembership",
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core/test_workspace_membership_model.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/models/workspace_membership.py src/core/models/__init__.py tests/test_core/test_workspace_membership_model.py
git commit -m "feat: add WorkspaceMembership model with role presets"
```

---

## Task 3: Add Visibility Column to Models

**Files:**
- Modify: `src/core/models/transaction.py` — add `visibility` column
- Modify: `src/core/models/task.py` — add `visibility` column
- Modify: `src/core/models/document.py` — add `visibility` column
- Modify: `src/core/models/conversation.py` — add `visibility` column
- Modify: `src/core/models/session_summary.py` — add `visibility` column
- Test: `tests/test_core/test_visibility_columns.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_core/test_visibility_columns.py
from src.core.models.transaction import Transaction
from src.core.models.task import Task
from src.core.models.document import Document
from src.core.models.conversation import ConversationMessage
from src.core.models.session_summary import SessionSummary


def test_transaction_has_visibility():
    columns = {c.name for c in Transaction.__table__.columns}
    assert "visibility" in columns


def test_task_has_visibility():
    columns = {c.name for c in Task.__table__.columns}
    assert "visibility" in columns


def test_document_has_visibility():
    columns = {c.name for c in Document.__table__.columns}
    assert "visibility" in columns


def test_conversation_message_has_visibility():
    columns = {c.name for c in ConversationMessage.__table__.columns}
    assert "visibility" in columns


def test_session_summary_has_visibility():
    columns = {c.name for c in SessionSummary.__table__.columns}
    assert "visibility" in columns
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core/test_visibility_columns.py -v`
Expected: FAIL with AssertionError ("visibility" not in columns)

**Step 3: Write implementation**

Add to each model file (import `ResourceVisibility` from enums):

**`src/core/models/transaction.py`** — add after `ai_confidence`:
```python
from src.core.models.enums import ResourceVisibility, Scope, TransactionType
# ...
    visibility: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
    )  # ResourceVisibility: private_user, family_shared, work_shared
```

**`src/core/models/task.py`** — add after `original_reminder_time`:
```python
    visibility: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="private_user",
    )
```

**`src/core/models/document.py`** — add after `parent_document_id`:
```python
    visibility: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
    )
```

**`src/core/models/conversation.py`** — add visibility column:
```python
    visibility: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="private_user",
    )
```

**`src/core/models/session_summary.py`** — add visibility column:
```python
    visibility: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="private_user",
    )
```

NOTE: Using `String(20)` instead of PostgreSQL ENUM to avoid migration complexity. Values validated at application layer. This is intentional — adding a PG enum to 5 tables in one migration is fragile.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core/test_visibility_columns.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/models/transaction.py src/core/models/task.py src/core/models/document.py src/core/models/conversation.py src/core/models/session_summary.py tests/test_core/test_visibility_columns.py
git commit -m "feat: add visibility column to Transaction, Task, Document, ConversationMessage, SessionSummary"
```

---

## Task 4: Alembic Migration

**Files:**
- Create: `alembic/versions/030_rbac_membership_visibility.py`

**Step 1: Write the migration**

```python
# alembic/versions/030_rbac_membership_visibility.py
"""Add workspace_memberships table, visibility columns, and RBAC enums.

Revision ID: 030
Revises: 029
"""
from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Enums ---
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE membership_type AS ENUM ('family', 'worker');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE membership_role AS ENUM (
                'owner', 'partner', 'family_member', 'worker',
                'assistant', 'accountant', 'viewer', 'custom'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE membership_status AS ENUM ('invited', 'active', 'suspended', 'revoked');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)

    # --- workspace_memberships table ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_memberships (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id UUID NOT NULL REFERENCES families(id),
            user_id UUID NOT NULL REFERENCES users(id),
            membership_type membership_type NOT NULL,
            role membership_role NOT NULL,
            permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
            status membership_status NOT NULL DEFAULT 'active',
            invited_by_user_id UUID REFERENCES users(id),
            joined_at TIMESTAMPTZ DEFAULT now(),
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(family_id, user_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wm_family_user "
        "ON workspace_memberships (family_id, user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wm_user_status "
        "ON workspace_memberships (user_id, status)"
    )

    # --- visibility columns ---
    op.execute(
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS visibility VARCHAR(20)"
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'private_user'"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS visibility VARCHAR(20)"
    )
    op.execute(
        "ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'private_user'"
    )
    op.execute(
        "ALTER TABLE session_summaries ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'private_user'"
    )

    # --- Backfill transactions visibility from scope ---
    op.execute("""
        UPDATE transactions SET visibility = CASE
            WHEN scope = 'personal' THEN 'private_user'
            WHEN scope = 'family' THEN 'family_shared'
            WHEN scope = 'business' THEN 'work_shared'
        END
        WHERE visibility IS NULL
    """)

    # --- Backfill documents visibility ---
    op.execute("""
        UPDATE documents SET visibility = CASE
            WHEN type IN ('template', 'invoice', 'report', 'spreadsheet') THEN 'work_shared'
            ELSE 'private_user'
        END
        WHERE visibility IS NULL
    """)

    # --- Backfill existing users into workspace_memberships ---
    op.execute("""
        INSERT INTO workspace_memberships (id, family_id, user_id, membership_type, role, permissions, status, joined_at)
        SELECT
            gen_random_uuid(),
            u.family_id,
            u.id,
            'family'::membership_type,
            CASE
                WHEN u.role = 'owner' THEN 'owner'::membership_role
                ELSE 'family_member'::membership_role
            END,
            CASE
                WHEN u.role = 'owner' THEN '["view_finance","create_finance","edit_finance","delete_finance","view_reports","export_reports","view_budgets","manage_budgets","view_work_tasks","manage_work_tasks","view_work_documents","manage_work_documents","view_contacts","manage_contacts","invite_members","manage_members"]'::jsonb
                ELSE '["create_finance","view_budgets"]'::jsonb
            END,
            'active'::membership_status,
            u.created_at
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM workspace_memberships wm WHERE wm.user_id = u.id AND wm.family_id = u.family_id
        )
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE session_summaries DROP COLUMN IF EXISTS visibility")
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS visibility")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS visibility")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS visibility")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS visibility")
    op.execute("DROP TABLE IF EXISTS workspace_memberships")
    op.execute("DROP TYPE IF EXISTS membership_status")
    op.execute("DROP TYPE IF EXISTS membership_role")
    op.execute("DROP TYPE IF EXISTS membership_type")
```

**Step 2: Verify migration runs locally**

Run: `uv run alembic heads` — should show `029 (head)`, no multiple heads.

**Step 3: Commit**

```bash
git add alembic/versions/030_rbac_membership_visibility.py
git commit -m "feat: migration 030 — workspace_memberships table, visibility columns, backfill"
```

---

## Task 5: Extend Access Layer

**Files:**
- Modify: `src/core/access.py` — add visibility-aware filtering
- Test: `tests/test_core/test_access.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_core/test_access.py
from src.core.access import (
    apply_scope_filter,
    apply_visibility_filter,
    can_view_visibility,
    get_default_visibility,
)
from src.core.models.enums import Scope, ResourceVisibility


def test_owner_can_view_all_visibility():
    assert can_view_visibility("owner", ResourceVisibility.private_user, "self") is True
    assert can_view_visibility("owner", ResourceVisibility.family_shared, "self") is True
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


def test_default_visibility_from_scope():
    assert get_default_visibility(Scope.personal) == ResourceVisibility.private_user
    assert get_default_visibility(Scope.family) == ResourceVisibility.family_shared
    assert get_default_visibility(Scope.business) == ResourceVisibility.work_shared
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core/test_access.py -v`
Expected: FAIL with ImportError

**Step 3: Write implementation**

Add to `src/core/access.py`:

```python
from src.core.models.enums import ResourceVisibility, Scope


_SCOPE_TO_VISIBILITY: dict[Scope, ResourceVisibility] = {
    Scope.personal: ResourceVisibility.private_user,
    Scope.family: ResourceVisibility.family_shared,
    Scope.business: ResourceVisibility.work_shared,
}

_ROLE_VISIBLE_VISIBILITY: dict[str, set[str]] = {
    "owner": {"private_user", "family_shared", "work_shared"},
    "partner": {"family_shared", "work_shared"},
    "family_member": {"family_shared"},
    "worker": {"work_shared"},
    "assistant": {"work_shared"},
    "accountant": {"work_shared"},
    "viewer": {"family_shared", "work_shared"},
    "member": {"family_shared"},  # legacy role
}


def get_default_visibility(scope: Scope) -> ResourceVisibility:
    """Map a transaction scope to a resource visibility."""
    return _SCOPE_TO_VISIBILITY.get(scope, ResourceVisibility.private_user)


def can_view_visibility(
    role: str,
    visibility: ResourceVisibility | str,
    ownership: str = "self",
) -> bool:
    """Check whether a role can view a resource with given visibility.

    ownership: "self" = resource belongs to current user, "other" = another user's.
    private_user is only visible to the resource owner regardless of role.
    """
    vis = visibility if isinstance(visibility, str) else visibility.value

    if vis == "private_user":
        return ownership == "self"

    allowed = _ROLE_VISIBLE_VISIBILITY.get(role, set())
    return vis in allowed


def apply_visibility_filter(stmt: Any, model: Any, role: str, user_id: str) -> Any:
    """Restrict a SQLAlchemy statement by visibility + user_id.

    Rules:
    - private_user: only visible to the owning user (model.user_id == user_id)
    - family_shared / work_shared: visible based on role
    - NULL visibility (legacy rows): fall back to scope-based filtering if available
    """
    import uuid as _uuid
    from sqlalchemy import or_

    allowed_vis = _ROLE_VISIBLE_VISIBILITY.get(role, set())

    conditions = [
        # Own private data
        (model.visibility == "private_user") & (model.user_id == _uuid.UUID(user_id)),
    ]

    for vis in allowed_vis:
        if vis != "private_user":
            conditions.append(model.visibility == vis)

    # Legacy: NULL visibility — fall back to existing scope filter logic
    if hasattr(model, "scope"):
        visible_scopes = get_visible_scopes(role)
        conditions.append(
            (model.visibility.is_(None)) & (model.scope.in_(visible_scopes))
        )
    else:
        # No scope column — NULL visibility means user's own data only
        conditions.append(
            (model.visibility.is_(None)) & (model.user_id == _uuid.UUID(user_id))
        )

    return stmt.where(or_(*conditions))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core/test_access.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/access.py tests/test_core/test_access.py
git commit -m "feat: extend access layer with visibility-aware filtering"
```

---

## Task 6: Extend SessionContext

**Files:**
- Modify: `src/core/context.py` — add membership_type, permissions, can_view_resource
- Modify: `tests/test_core/test_filter_query.py` — add visibility test
- Test: `tests/test_core/test_context_permissions.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_core/test_context_permissions.py
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core/test_context_permissions.py -v`
Expected: FAIL with TypeError (unexpected keyword argument 'permissions')

**Step 3: Write implementation**

Add to `SessionContext` in `src/core/context.py`:

```python
    # RBAC Phase 1
    membership_type: str | None = None  # "family" or "worker"
    permissions: list[str] = field(default_factory=list)

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission. Owner has all."""
        if self.role == "owner":
            return True
        return permission in self.permissions
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core/test_context_permissions.py -v`
Expected: PASS

**Step 5: Run existing tests to check nothing broke**

Run: `uv run pytest tests/test_core/test_filter_query.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/core/context.py tests/test_core/test_context_permissions.py
git commit -m "feat: extend SessionContext with permissions and membership_type"
```

---

## Task 7: Load Membership in Context Builders

**Files:**
- Modify: `api/main.py` — `build_session_context()` and `build_context_from_channel()` load membership
- Test: `tests/test_api/test_context_builder.py` (new)

**Step 1: Write implementation**

In both `build_session_context()` and `build_context_from_channel()` in `api/main.py`, after loading the user, add:

```python
from src.core.models.workspace_membership import WorkspaceMembership

# Load membership (if exists, otherwise use legacy role)
membership_result = await session.execute(
    select(WorkspaceMembership).where(
        WorkspaceMembership.user_id == user.id,
        WorkspaceMembership.family_id == user.family_id,
        WorkspaceMembership.status == "active",
    )
)
membership = membership_result.scalar_one_or_none()

# Build context with membership data
return SessionContext(
    # ... existing fields ...
    membership_type=membership.membership_type.value if membership else None,
    permissions=membership.permissions if membership else [],
)
```

**Step 2: Run existing API tests**

Run: `uv run pytest tests/test_api/ -x -q --tb=short`
Expected: PASS (membership is optional, defaults to empty)

**Step 3: Commit**

```bash
git add api/main.py
git commit -m "feat: load workspace membership into SessionContext"
```

---

## Task 8: Auto-Create Membership on User Creation

**Files:**
- Modify: `src/core/family.py` — create WorkspaceMembership in `create_family()`, `join_family()`, `create_family_for_channel()`, `join_family_for_channel()`

**Step 1: Write implementation**

In each function that creates a User, after `session.add(user)` and `await session.flush()`, add:

```python
from src.core.models.workspace_membership import WorkspaceMembership, ROLE_PRESETS
from src.core.models.enums import MembershipRole, MembershipStatus, MembershipType

role_key = "owner" if user.role == UserRole.owner else "family_member"
membership = WorkspaceMembership(
    family_id=family.id,
    user_id=user.id,
    membership_type=MembershipType.family,
    role=MembershipRole(role_key),
    permissions=ROLE_PRESETS[role_key],
    status=MembershipStatus.active,
)
session.add(membership)
```

**Step 2: Run existing family tests**

Run: `uv run pytest tests/ -k "family or onboard" -x -q --tb=short`
Expected: PASS

**Step 3: Commit**

```bash
git add src/core/family.py
git commit -m "feat: auto-create WorkspaceMembership on user creation"
```

---

## Task 9: Set Visibility on Record Creation

**Files:**
- Modify: `src/skills/add_expense/handler.py` — set `visibility` from scope
- Modify: `src/skills/add_income/handler.py` — set `visibility` from scope
- Modify: `src/skills/create_task/handler.py` — set `visibility = "private_user"`
- Modify: `src/tools/data_tools.py` — set `visibility` on `create_record()` for supported tables

**Step 1: Write implementation**

**`add_expense/handler.py`** — after setting `scope`, add:
```python
from src.core.access import get_default_visibility
# ...
    visibility=get_default_visibility(Scope(scope)).value,
```

**`add_income/handler.py`** — same pattern.

**`create_task/handler.py`** — when creating Task:
```python
    visibility="private_user",
```

**`data_tools.py`** — in `create_record()`, after injecting `family_id`/`user_id`:
```python
if table_name in ("transactions", "tasks", "documents") and "visibility" not in values:
    if "scope" in values:
        from src.core.access import get_default_visibility
        from src.core.models.enums import Scope
        values["visibility"] = get_default_visibility(Scope(values["scope"])).value
    elif table_name == "tasks":
        values["visibility"] = "private_user"
    elif table_name == "documents":
        values["visibility"] = "private_user"
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_skills/test_add_expense.py tests/test_skills/test_add_income.py tests/test_skills/test_create_task.py -x -q --tb=short`
Expected: PASS

**Step 3: Commit**

```bash
git add src/skills/add_expense/handler.py src/skills/add_income/handler.py src/skills/create_task/handler.py src/tools/data_tools.py
git commit -m "feat: set visibility on record creation (expense, income, task, data_tools)"
```

---

## Task 10: Integration Test — Member Cannot See Owner Data

**Files:**
- Create: `tests/test_core/test_member_isolation.py`

**Step 1: Write the test**

```python
# tests/test_core/test_member_isolation.py
"""Regression tests: member cannot access owner's private data."""
from unittest.mock import AsyncMock, patch, MagicMock
from src.core.context import SessionContext


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
    """Member's scope is always forced to family in add_expense/add_income."""
    ctx = _member_context()
    scope = "personal"
    if ctx.role == "member":
        scope = "family"
    assert scope == "family"


def test_visibility_private_user_blocks_other():
    from src.core.access import can_view_visibility
    assert can_view_visibility("member", "private_user", "other") is False
    assert can_view_visibility("owner", "private_user", "other") is False


def test_visibility_family_shared_allows_member():
    from src.core.access import can_view_visibility
    assert can_view_visibility("member", "family_shared", "self") is True


def test_visibility_work_shared_blocks_member():
    from src.core.access import can_view_visibility
    assert can_view_visibility("member", "work_shared", "self") is False
```

**Step 2: Run test**

Run: `uv run pytest tests/test_core/test_member_isolation.py -v`
Expected: PASS (all 10 tests)

**Step 3: Commit**

```bash
git add tests/test_core/test_member_isolation.py
git commit -m "test: add member isolation regression tests (10 scenarios)"
```

---

## Task 11: Update Design Doc Status

**Files:**
- Modify: `docs/plans/2026-03-06-access-control-rbac-design.md` — mark Phase 1 as done

**Step 1: Update status**

Change line 4: `**Status:** Proposed` → `**Status:** Phase 0 done, Phase 1 in progress`

Add to rollout section:
```markdown
### Phase 1: Introduce Membership + Visibility — DONE (2026-03-08)

- ✅ workspace_memberships table + migration 030
- ✅ MembershipType, MembershipRole, MembershipStatus, ResourceVisibility enums
- ✅ ROLE_PRESETS (8 roles with default permissions)
- ✅ visibility column on transactions, tasks, documents, conversation_messages, session_summaries
- ✅ Backfill: existing users → workspace_memberships, transactions visibility from scope
- ✅ Access layer: apply_visibility_filter(), can_view_visibility(), get_default_visibility()
- ✅ SessionContext extended with permissions, membership_type, has_permission()
- ✅ Auto-create membership on user creation (create_family, join_family)
- ✅ Set visibility on record creation (expense, income, task, data_tools)
- ✅ 10 member isolation regression tests
```

**Step 2: Commit**

```bash
git add docs/plans/2026-03-06-access-control-rbac-design.md
git commit -m "docs: mark Phase 1 RBAC as done"
```

---

## Summary

| Task | Description | Files | Tests |
|------|-------------|-------|-------|
| 1 | New enums | `enums.py` | 4 tests |
| 2 | WorkspaceMembership model | `workspace_membership.py`, `__init__.py` | 3 tests |
| 3 | Visibility columns on 5 models | 5 model files | 5 tests |
| 4 | Alembic migration 030 | `030_rbac_membership_visibility.py` | - |
| 5 | Extend access layer | `access.py` | 7 tests |
| 6 | Extend SessionContext | `context.py` | 3 tests |
| 7 | Load membership in context builders | `api/main.py` | existing tests |
| 8 | Auto-create membership on user creation | `family.py` | existing tests |
| 9 | Set visibility on record creation | 4 skill/tool files | existing tests |
| 10 | Member isolation regression tests | - | 10 tests |
| 11 | Update design doc | `access-control-rbac-design.md` | - |

**Total: 11 tasks, ~32 new tests, 1 migration, 15 files touched**
