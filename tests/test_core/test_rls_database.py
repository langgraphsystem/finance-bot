"""DB-level RLS integration tests.

These tests verify that PostgreSQL RLS policies actually block:
1. Cross-family data access (family A cannot see family B's rows)
2. Intra-family private access (user A cannot see user B's private_user rows)

Requires a real PostgreSQL database with migrations applied.
Skipped when DATABASE_URL points to SQLite or when no PG is available.
"""

import os
import uuid

import pytest
from sqlalchemy import text

# Skip entire module unless RLS_TESTS=1 is explicitly set.
# These tests need a real PostgreSQL database with migrations applied and RLS policies active.
# CI uses SQLite, so these are skipped by default.
_run_rls = os.environ.get("RLS_TESTS", "") == "1"

pytestmark = [
    pytest.mark.skipif(not _run_rls, reason="Set RLS_TESTS=1 with real PostgreSQL to run"),
    pytest.mark.asyncio,
]


@pytest.fixture
async def pg_session():
    """Get a raw async session connected to the test PostgreSQL database."""
    from src.core.db import async_session

    async with async_session() as session:
        yield session


@pytest.fixture
def family_a_id():
    return str(uuid.uuid4())


@pytest.fixture
def family_b_id():
    return str(uuid.uuid4())


@pytest.fixture
def user_a_id():
    return str(uuid.uuid4())


@pytest.fixture
def user_b_id():
    return str(uuid.uuid4())


async def _set_rls_context(session, family_id, user_id=None):
    """Set RLS session variables."""
    await session.execute(
        text("SELECT set_config('app.current_family_id', :fid, true)"),
        {"fid": family_id},
    )
    if user_id:
        await session.execute(
            text("SELECT set_config('app.current_user_id', :uid, true)"),
            {"uid": user_id},
        )


async def _reset_rls_context(session):
    """Reset RLS session variables."""
    await session.execute(text("SELECT set_config('app.current_family_id', '', true)"))
    await session.execute(text("SELECT set_config('app.current_user_id', '', true)"))


# ---------------------------------------------------------------------------
# 1. Cross-family isolation
# ---------------------------------------------------------------------------


async def test_rls_cross_family_transaction_isolation(
    pg_session, family_a_id, family_b_id, user_a_id
):
    """Transactions in family A are invisible when RLS context is set to family B."""
    # Insert a test transaction in family A (bypass RLS using superuser/no-RLS session)
    await _reset_rls_context(pg_session)

    # Check if transactions table exists and has RLS
    result = await pg_session.execute(
        text("SELECT COUNT(*) FROM pg_policies WHERE tablename = 'transactions'")
    )
    policy_count = result.scalar()
    if policy_count == 0:
        pytest.skip("No RLS policies found on transactions table")

    # Create minimal family + user for FK constraints
    await pg_session.execute(
        text(
            "INSERT INTO families (id, name, invite_code, currency) "
            "VALUES (:id, 'Test A', 'TESTA1', 'USD') ON CONFLICT DO NOTHING"
        ),
        {"id": family_a_id},
    )
    await pg_session.execute(
        text(
            "INSERT INTO families (id, name, invite_code, currency) "
            "VALUES (:id, 'Test B', 'TESTB1', 'USD') ON CONFLICT DO NOTHING"
        ),
        {"id": family_b_id},
    )
    await pg_session.execute(
        text(
            "INSERT INTO users (id, family_id, telegram_id, name, role, language, onboarded) "
            "VALUES (:uid, :fid, :tid, 'User A', 'owner', 'en', true) ON CONFLICT DO NOTHING"
        ),
        {"uid": user_a_id, "fid": family_a_id, "tid": 999900001},
    )

    # Create a test category for FK
    cat_id = str(uuid.uuid4())
    await pg_session.execute(
        text(
            "INSERT INTO categories (id, family_id, name, scope, icon, is_default) "
            "VALUES (:cid, :fid, 'Test Cat', 'family', '📦', true) ON CONFLICT DO NOTHING"
        ),
        {"cid": cat_id, "fid": family_a_id},
    )

    # Insert a transaction in family A
    tx_id = str(uuid.uuid4())
    await pg_session.execute(
        text(
            "INSERT INTO transactions "
            "(id, family_id, user_id, category_id, type, amount, "
            "description, date, scope, visibility) "
            "VALUES (:tid, :fid, :uid, :cid, 'expense', 100, "
            "'RLS test', CURRENT_DATE, 'family', 'family_shared')"
        ),
        {"tid": tx_id, "fid": family_a_id, "uid": user_a_id, "cid": cat_id},
    )
    await pg_session.commit()

    # Set RLS context to family B
    await _set_rls_context(pg_session, family_b_id)

    # Query transactions — should NOT see family A's transaction
    result = await pg_session.execute(text("SELECT id FROM transactions"))
    rows = result.all()
    visible_ids = [str(r[0]) for r in rows]
    assert tx_id not in visible_ids, "Family B should NOT see Family A's transaction"

    # Set RLS context to family A — should see own transaction
    await _set_rls_context(pg_session, family_a_id)
    result = await pg_session.execute(text("SELECT id FROM transactions"))
    rows = result.all()
    visible_ids = [str(r[0]) for r in rows]
    assert tx_id in visible_ids, "Family A should see own transaction"

    # Cleanup
    await _reset_rls_context(pg_session)
    await pg_session.execute(text("DELETE FROM transactions WHERE id = :tid"), {"tid": tx_id})
    await pg_session.execute(text("DELETE FROM categories WHERE id = :cid"), {"cid": cat_id})
    await pg_session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_a_id})
    await pg_session.execute(
        text("DELETE FROM families WHERE id IN (:a, :b)"),
        {"a": family_a_id, "b": family_b_id},
    )
    await pg_session.commit()


# ---------------------------------------------------------------------------
# 2. Intra-family private_user isolation
# ---------------------------------------------------------------------------


async def test_rls_private_user_visibility_isolation(
    pg_session, family_a_id, user_a_id, user_b_id
):
    """private_user transactions should only be visible to the owning user within same family."""
    await _reset_rls_context(pg_session)

    result = await pg_session.execute(
        text("SELECT COUNT(*) FROM pg_policies WHERE tablename = 'transactions'")
    )
    if result.scalar() == 0:
        pytest.skip("No RLS policies found on transactions table")

    # Setup family + users
    await pg_session.execute(
        text(
            "INSERT INTO families (id, name, invite_code, currency) "
            "VALUES (:id, 'Fam Vis', 'VISTST', 'USD') ON CONFLICT DO NOTHING"
        ),
        {"id": family_a_id},
    )
    await pg_session.execute(
        text(
            "INSERT INTO users (id, family_id, telegram_id, name, role, language, onboarded) "
            "VALUES (:uid, :fid, :tid, 'User A', 'owner', 'en', true) ON CONFLICT DO NOTHING"
        ),
        {"uid": user_a_id, "fid": family_a_id, "tid": 999900002},
    )
    await pg_session.execute(
        text(
            "INSERT INTO users (id, family_id, telegram_id, name, role, language, onboarded) "
            "VALUES (:uid, :fid, :tid, 'User B', 'member', 'en', true) ON CONFLICT DO NOTHING"
        ),
        {"uid": user_b_id, "fid": family_a_id, "tid": 999900003},
    )

    cat_id = str(uuid.uuid4())
    await pg_session.execute(
        text(
            "INSERT INTO categories (id, family_id, name, scope, icon, is_default) "
            "VALUES (:cid, :fid, 'Test Cat', 'personal', '📦', true) ON CONFLICT DO NOTHING"
        ),
        {"cid": cat_id, "fid": family_a_id},
    )

    # Insert private transaction for user A
    tx_private = str(uuid.uuid4())
    await pg_session.execute(
        text(
            "INSERT INTO transactions "
            "(id, family_id, user_id, category_id, type, amount, "
            "description, date, scope, visibility) "
            "VALUES (:tid, :fid, :uid, :cid, 'expense', 50, "
            "'Private A', CURRENT_DATE, 'personal', 'private_user')"
        ),
        {"tid": tx_private, "fid": family_a_id, "uid": user_a_id, "cid": cat_id},
    )

    # Insert shared transaction
    tx_shared = str(uuid.uuid4())
    await pg_session.execute(
        text(
            "INSERT INTO transactions "
            "(id, family_id, user_id, category_id, type, amount, "
            "description, date, scope, visibility) "
            "VALUES (:tid, :fid, :uid, :cid, 'expense', 75, "
            "'Shared', CURRENT_DATE, 'family', 'family_shared')"
        ),
        {"tid": tx_shared, "fid": family_a_id, "uid": user_a_id, "cid": cat_id},
    )
    await pg_session.commit()

    # Query as user B (same family) — should see shared but NOT private
    await _set_rls_context(pg_session, family_a_id, user_b_id)
    result = await pg_session.execute(text("SELECT id FROM transactions"))
    visible_ids = [str(r[0]) for r in result.all()]
    assert tx_shared in visible_ids, "User B should see family_shared transaction"
    assert tx_private not in visible_ids, "User B should NOT see user A's private_user transaction"

    # Query as user A — should see both
    await _set_rls_context(pg_session, family_a_id, user_a_id)
    result = await pg_session.execute(text("SELECT id FROM transactions"))
    visible_ids = [str(r[0]) for r in result.all()]
    assert tx_private in visible_ids, "User A should see own private transaction"
    assert tx_shared in visible_ids, "User A should see shared transaction"

    # Cleanup
    await _reset_rls_context(pg_session)
    await pg_session.execute(
        text("DELETE FROM transactions WHERE id IN (:a, :b)"),
        {"a": tx_private, "b": tx_shared},
    )
    await pg_session.execute(text("DELETE FROM categories WHERE id = :cid"), {"cid": cat_id})
    await pg_session.execute(
        text("DELETE FROM users WHERE id IN (:a, :b)"),
        {"a": user_a_id, "b": user_b_id},
    )
    await pg_session.execute(
        text("DELETE FROM families WHERE id = :fid"), {"fid": family_a_id}
    )
    await pg_session.commit()


# ---------------------------------------------------------------------------
# 3. Life events strict private isolation
# ---------------------------------------------------------------------------


async def test_rls_life_events_strictly_private(
    pg_session, family_a_id, user_a_id, user_b_id
):
    """Life events should only be visible to the owning user, even within same family."""
    await _reset_rls_context(pg_session)

    result = await pg_session.execute(
        text("SELECT COUNT(*) FROM pg_policies WHERE tablename = 'life_events'")
    )
    if result.scalar() == 0:
        pytest.skip("No RLS policies found on life_events table")

    # Setup
    await pg_session.execute(
        text(
            "INSERT INTO families (id, name, invite_code, currency) "
            "VALUES (:id, 'Fam Life', 'LIFETS', 'USD') ON CONFLICT DO NOTHING"
        ),
        {"id": family_a_id},
    )
    await pg_session.execute(
        text(
            "INSERT INTO users (id, family_id, telegram_id, name, role, language, onboarded) "
            "VALUES (:uid, :fid, :tid, 'Owner', 'owner', 'en', true) ON CONFLICT DO NOTHING"
        ),
        {"uid": user_a_id, "fid": family_a_id, "tid": 999900004},
    )
    await pg_session.execute(
        text(
            "INSERT INTO users (id, family_id, telegram_id, name, role, language, onboarded) "
            "VALUES (:uid, :fid, :tid, 'Member', 'member', 'en', true) ON CONFLICT DO NOTHING"
        ),
        {"uid": user_b_id, "fid": family_a_id, "tid": 999900005},
    )

    # Insert life event for user A
    event_id = str(uuid.uuid4())
    await pg_session.execute(
        text(
            "INSERT INTO life_events (id, family_id, user_id, event_type, title, event_date) "
            "VALUES (:eid, :fid, :uid, 'mood', 'Feeling good', CURRENT_DATE)"
        ),
        {"eid": event_id, "fid": family_a_id, "uid": user_a_id},
    )
    await pg_session.commit()

    # Query as user B — should NOT see user A's life event
    await _set_rls_context(pg_session, family_a_id, user_b_id)
    result = await pg_session.execute(text("SELECT id FROM life_events"))
    visible_ids = [str(r[0]) for r in result.all()]
    assert event_id not in visible_ids, "User B should NOT see User A's life event"

    # Query as user A — should see own life event
    await _set_rls_context(pg_session, family_a_id, user_a_id)
    result = await pg_session.execute(text("SELECT id FROM life_events"))
    visible_ids = [str(r[0]) for r in result.all()]
    assert event_id in visible_ids, "User A should see own life event"

    # Cleanup
    await _reset_rls_context(pg_session)
    await pg_session.execute(
        text("DELETE FROM life_events WHERE id = :eid"), {"eid": event_id}
    )
    await pg_session.execute(
        text("DELETE FROM users WHERE id IN (:a, :b)"),
        {"a": user_a_id, "b": user_b_id},
    )
    await pg_session.execute(
        text("DELETE FROM families WHERE id = :fid"), {"fid": family_a_id}
    )
    await pg_session.commit()


# ---------------------------------------------------------------------------
# 4. Workspace memberships family isolation
# ---------------------------------------------------------------------------


async def test_rls_workspace_memberships_family_isolation(
    pg_session, family_a_id, family_b_id, user_a_id
):
    """Workspace memberships in family A are invisible from family B's RLS context."""
    await _reset_rls_context(pg_session)

    result = await pg_session.execute(
        text("SELECT COUNT(*) FROM pg_policies WHERE tablename = 'workspace_memberships'")
    )
    if result.scalar() == 0:
        pytest.skip("No RLS policies found on workspace_memberships table")

    # Setup
    await pg_session.execute(
        text(
            "INSERT INTO families (id, name, invite_code, currency) "
            "VALUES (:id, 'Fam WM A', 'WMTSTA', 'USD') ON CONFLICT DO NOTHING"
        ),
        {"id": family_a_id},
    )
    await pg_session.execute(
        text(
            "INSERT INTO families (id, name, invite_code, currency) "
            "VALUES (:id, 'Fam WM B', 'WMTSTB', 'USD') ON CONFLICT DO NOTHING"
        ),
        {"id": family_b_id},
    )
    await pg_session.execute(
        text(
            "INSERT INTO users (id, family_id, telegram_id, name, role, language, onboarded) "
            "VALUES (:uid, :fid, :tid, 'WM User', 'owner', 'en', true) ON CONFLICT DO NOTHING"
        ),
        {"uid": user_a_id, "fid": family_a_id, "tid": 999900006},
    )

    # Insert workspace membership
    wm_id = str(uuid.uuid4())
    await pg_session.execute(
        text(
            "INSERT INTO workspace_memberships "
            "(id, family_id, user_id, membership_type, role, permissions, status) "
            "VALUES (:wid, :fid, :uid, 'family', 'owner', '[]'::jsonb, 'active')"
        ),
        {"wid": wm_id, "fid": family_a_id, "uid": user_a_id},
    )
    await pg_session.commit()

    # Query as family B — should NOT see family A's membership
    await _set_rls_context(pg_session, family_b_id)
    result = await pg_session.execute(text("SELECT id FROM workspace_memberships"))
    visible_ids = [str(r[0]) for r in result.all()]
    assert wm_id not in visible_ids, "Family B should NOT see Family A's membership"

    # Query as family A — should see own membership
    await _set_rls_context(pg_session, family_a_id)
    result = await pg_session.execute(text("SELECT id FROM workspace_memberships"))
    visible_ids = [str(r[0]) for r in result.all()]
    assert wm_id in visible_ids, "Family A should see own membership"

    # Cleanup
    await _reset_rls_context(pg_session)
    await pg_session.execute(
        text("DELETE FROM workspace_memberships WHERE id = :wid"), {"wid": wm_id}
    )
    await pg_session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_a_id})
    await pg_session.execute(
        text("DELETE FROM families WHERE id IN (:a, :b)"),
        {"a": family_a_id, "b": family_b_id},
    )
    await pg_session.commit()
