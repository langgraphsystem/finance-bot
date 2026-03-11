# Phase 2: App-Level Access Layer Implementation Plan

> **Status (2026-03-10):** ✅ DONE — `apply_visibility_filter()` реализован в `src/core/access.py` (lines 93-135), SessionContext.filter_query() обновлён, permission checks добавлены.

**Goal:** Replace `apply_scope_filter()` with `apply_visibility_filter()` across all query paths for models that have a `visibility` column, and add permission checks at sensitive entry points.

**Architecture:** The `visibility` column already exists on 5 models (Transaction, Task, Document, ConversationMessage, SessionSummary) from Phase 1. `apply_visibility_filter()` exists in `src/core/access.py`. This phase wires it into all query paths, replacing the simpler scope-based filtering.

**Tech Stack:** SQLAlchemy 2.0 async, PostgreSQL, pytest

---

## Context

### Models WITH visibility column (migrate to `apply_visibility_filter`):
- `Transaction` — has both `scope` and `visibility`
- `Task` — has `visibility`, no `scope`
- `Document` — has `visibility`, no `scope`
- `ConversationMessage` — has `visibility`, no `scope`
- `SessionSummary` — has `visibility`, no `scope`

### Models WITHOUT visibility (keep `apply_scope_filter` or family_id-only):
- `Category` — shared per family, scope-filtered (correct as-is)
- `Budget`, `RecurringPayment`, `ShoppingList` — family-shared, no visibility needed
- `Contact`, `Booking`, `Invoice` — work-shared, no visibility needed
- `LifeEvent` — already filtered by `user_id` (Phase 0 fix)

### Key functions in `src/core/access.py`:
- `apply_scope_filter(stmt, model, role)` — scope-based, owner sees all
- `apply_visibility_filter(stmt, model, role, user_id)` — visibility-based, respects private_user

### What changes:
- `apply_scope_filter` stays for Category and other scope-only models
- For Transaction/Task/Document queries, replace `apply_scope_filter` with `apply_visibility_filter`
- `SessionContext.filter_query()` gains visibility support
- Miniapp endpoints gain visibility filtering
- Permission checks added at sensitive skill entry points

---

## Task 1: Upgrade `SessionContext.filter_query()` with visibility support

**Files:**
- Modify: `src/core/context.py:61-66`
- Test: `tests/test_core/test_context_permissions.py`

**What:** Update `filter_query()` to auto-detect if the model has a `visibility` column and use `apply_visibility_filter()` instead of `apply_scope_filter()`.

**Implementation:**

```python
def filter_query(self, stmt, model):
    """Add family_id and access filters to a SQLAlchemy select."""
    import uuid

    from src.core.access import apply_visibility_filter

    stmt = stmt.where(model.family_id == uuid.UUID(self.family_id))

    if hasattr(model, "visibility"):
        return apply_visibility_filter(stmt, model, self.role, self.user_id)
    return apply_scope_filter(stmt, model, self.role)
```

**Test:**

```python
def test_filter_query_uses_visibility_for_transaction(sample_context):
    from sqlalchemy import select
    from src.core.models.transaction import Transaction
    stmt = select(Transaction)
    result = sample_context.filter_query(stmt, Transaction)
    sql = str(result.compile(compile_kwargs={"literal_binds": True}))
    assert "visibility" in sql

def test_filter_query_uses_scope_for_category(sample_context):
    from sqlalchemy import select
    from src.core.models.category import Category
    stmt = select(Category)
    result = sample_context.filter_query(stmt, Category)
    sql = str(result.compile(compile_kwargs={"literal_binds": True}))
    assert "scope" in sql
```

**Run:** `pytest tests/test_core/test_context_permissions.py -v`

---

## Task 2: Add miniapp visibility helper

**Files:**
- Modify: `api/miniapp.py` (top-level imports + helper function)

**What:** Add a `_apply_access_filter()` helper that wraps `apply_visibility_filter` for miniapp (which has `user` not `SessionContext`). Import the function.

**Implementation:**

Add import at top:
```python
from src.core.access import apply_scope_filter, apply_visibility_filter, can_access_scope
```

Add helper:
```python
def _apply_tx_filter(stmt, user: User):
    """Apply visibility filter for Transaction queries in miniapp."""
    return apply_visibility_filter(stmt, Transaction, user.role.value, str(user.id))
```

---

## Task 3: Migrate miniapp Transaction queries to visibility filter

**Files:**
- Modify: `api/miniapp.py` — all Transaction query endpoints

**What:** Replace every `apply_scope_filter(stmt, Transaction, user.role.value)` with `_apply_tx_filter(stmt, user)` in these endpoints:
- `get_stats` (2 calls)
- `get_monthly_trend` (2 calls)
- `list_transactions` (1 call)
- `get_transaction` (1 call)
- `create_transaction` (category scope check stays)
- `export_transactions` (1 call)
- `get_analytics` (multiple calls)
- `get_category_detail` (1 call)
- `get_recurring_payments` (no change — RecurringPayment has no visibility)
- `search_transactions` (1 call)

**Pattern:** Find `apply_scope_filter(stmt, Transaction, user.role.value)` → replace with `_apply_tx_filter(stmt, user)`.

---

## Task 4: Migrate miniapp Task queries to visibility filter

**Files:**
- Modify: `api/miniapp.py` — task endpoints

**What:** Task queries currently filter by `user_id` (Phase 0 fix). Add visibility filter on top.

**Pattern:** After `Task.user_id == user.id` filter, also add visibility filter:
```python
from src.core.access import apply_visibility_filter
stmt = apply_visibility_filter(stmt, Task, user.role.value, str(user.id))
```

Affects: `list_tasks`, `update_task`, `delete_task`.

---

## Task 5: Migrate skill handlers — query_stats, financial_summary

**Files:**
- Modify: `src/skills/query_stats/handler.py`
- Modify: `src/skills/financial_summary/handler.py`

**What:** These skills query Transaction with `apply_scope_filter`. Replace with `apply_visibility_filter` using `context.user_id`.

**Pattern:**
```python
# Before:
stmt = apply_scope_filter(stmt, Transaction, context.role)
# After:
stmt = apply_visibility_filter(stmt, Transaction, context.role, context.user_id)
```

---

## Task 6: Migrate skill handlers — list_tasks, complete_task, delete_data

**Files:**
- Modify: `src/skills/list_tasks/handler.py`
- Modify: `src/skills/complete_task/handler.py`
- Modify: `src/skills/delete_data/handler.py`

**What:** Task queries in these skills should use visibility filter.

---

## Task 7: Migrate data_tools universal query path

**Files:**
- Modify: `src/tools/data_tools.py:146` (`_apply_filters`)

**What:** The `_apply_filters()` function applies `family_id` filter universally. For models with `visibility` column, also apply visibility filter.

**Implementation:**
```python
# In _apply_filters, after family_id filter:
if hasattr(model, "visibility") and user_id:
    from src.core.access import apply_visibility_filter
    stmt = apply_visibility_filter(stmt, model, role or "owner", user_id)
```

---

## Task 8: Migrate reports.py and morning_brief/evening_recap

**Files:**
- Modify: `src/core/reports.py`
- Modify: `src/skills/morning_brief/handler.py`
- Modify: `src/skills/evening_recap/handler.py`

**What:** These files query Transaction and Task with `apply_scope_filter` or direct `family_id`. Add visibility filtering.

---

## Task 9: Migrate brief orchestrator nodes

**Files:**
- Modify: `src/orchestrators/brief/nodes.py`

**What:** Brief orchestrator queries Task, Transaction, Budget, RecurringPayment. Only Task and Transaction need visibility filter. Budget and RecurringPayment stay as-is.

---

## Task 10: Add permission checks at sensitive entry points

**Files:**
- Modify: `api/miniapp.py` — transaction create/update/delete
- Modify: `src/skills/add_expense/handler.py`
- Modify: `src/skills/add_income/handler.py`
- Modify: `src/skills/set_budget/handler.py`

**What:** Add `has_permission()` / `_ensure_permission()` checks:
- Creating expense/income → `create_finance`
- Viewing reports → `view_reports`
- Managing budgets → `manage_budgets`

**Implementation for miniapp:**
```python
def _ensure_permission(user: User, permission: str, membership=None):
    if user.role.value == "owner":
        return
    if membership and permission in (membership.permissions or []):
        return
    raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")
```

---

## Task 11: Add regression tests for Phase 2

**Files:**
- Create: `tests/test_core/test_phase2_access.py`

**What:** Test that visibility filtering works end-to-end:
1. Owner sees all visibility types via `filter_query`
2. Member sees only `family_shared` + own `private_user` via `filter_query`
3. Worker sees only `work_shared` + own `private_user`
4. `_apply_tx_filter` in miniapp produces correct SQL
5. Permission check blocks unauthorized create
6. NULL visibility falls back to scope filtering (backward compat)
