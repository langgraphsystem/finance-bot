# Production Access Control Design

**Date:** 2026-03-06
**Status:** Phase 0-4 done (2026-03-09)
**Scope:** Family / worker access, privacy boundaries, RBAC, RLS

---

## Problem

The project currently isolates data mostly by `family_id`.

That creates two systemic problems:

1. After `join_family()` a new user lands in the same tenant and can reach data that should stay private.
2. The codebase already contains the idea of `owner/member + scope`, but it is enforced inconsistently. Some paths use `user_id`, others only `family_id`.

Result: family access, worker access, and the user's private contour are mixed together.

---

## Goal

Create a production-grade access model where:

- every user has a private contour;
- an owner can add either `family` or `worker`;
- default access comes from a role preset;
- the owner may adjust a small number of permissions;
- private chats, memory, notes, and integrations do not become shared automatically;
- enforcement works both in Python and at the DB/RLS layer.

---

## Non-Goals

- Do not rename the whole project from `family` to `workspace` right now.
- Do not build full enterprise IAM with SSO, groups, ABAC, and external policy engines.
- Do not rewrite every entity and every API in one release.

---

## Core Principle

`family_id` stays the tenant boundary, but it stops being the access boundary.

The new access boundary becomes:

- `tenant` -> `family_id`
- `actor` -> `user_id`
- `membership` -> membership type, role, permissions
- `resource visibility` -> who may see a specific record

In other words:

- a single tenant may contain multiple users;
- but not all tenant data should be shared.

---

## Production Recommendation

Recommended model:

**RBAC in the core + simple access templates in the UX**

What that means:

- inside the system, store real roles and permissions;
- in the owner UI, show simple templates instead of an ACL matrix:
  - `Family -> Partner`
  - `Family -> Family member`
  - `Worker -> Worker access`
  - `Worker -> Assistant`
  - `Worker -> Accountant`
  - `Read only`

This gives:

- simple UX for small owners;
- enough flexibility for accountants and staff;
- safe defaults;
- a model that can scale without being redesigned.

---

## UX Flow

### 1. Add User

The owner clicks `Add user`.

Fields:

- name
- invite method
- membership type:
  - `Family`
  - `Worker`

### 2. Choose Role

If `Family`:

- `Partner`
- `Family member`
- `Read only`

If `Worker`:

- `Worker access`
- `Assistant`
- `Accountant`
- `Read only`
- `Custom` (advanced mode only)

### 3. Access Screen

The screen is prefilled from the role preset.

The owner sees 5-7 main toggles:

- view finances
- add transactions
- edit transactions
- view reports
- work tasks
- work documents
- clients and contacts

And a fixed summary block:

`Always hidden by default`

- personal bot chats
- personal memory
- personal notes / life events
- personal email / calendar
- personal drafts / browser sessions

### 4. Confirm

Show summary:

- type: `Worker`
- role: `Accountant`
- can see: finances, budgets, reports
- cannot see: private chats, memory, owner email

Then create the membership with preset permissions.

---

## Core Concepts

### 1. Membership Type

New membership attribute:

- `family`
- `worker`

This is not a permission. It defines the context.

### 2. Role

The role defines safe default permissions.

Recommended roles:

- `owner`
- `partner`
- `family_member`
- `worker`
- `assistant`
- `accountant`
- `viewer`
- `custom`

### 3. Permissions

Minimum production permission set:

- `view_finance`
- `create_finance`
- `edit_finance`
- `delete_finance`
- `view_reports`
- `export_reports`
- `view_budgets`
- `manage_budgets`
- `view_work_tasks`
- `manage_work_tasks`
- `view_work_documents`
- `manage_work_documents`
- `view_contacts`
- `manage_contacts`
- `invite_members`
- `manage_members`

Sensitive permissions that should not be granted by default:

- `view_private_chat`
- `view_private_memory`
- `view_private_life`
- `view_private_tasks`
- `view_private_documents`
- `view_owner_email`
- `view_owner_calendar`

### 4. Resource Visibility

Each resource that may be shared or private should carry visibility:

- `private_user`
- `family_shared`
- `work_shared`

The owner should not automatically see `private_user` data of other users.

That is an important product rule: the owner administers the workspace, but does not automatically get omniscient access to every private user contour.

---

## Data Classification

Below is the recommended production classification of existing entities.

### Private User

Private by default and never shared automatically:

- `conversation_messages`
- `session_summaries`
- user memory / Mem0 user namespace
- `life_events`
- personal `tasks`
- `user_profiles`
- personal settings / communication mode / learned patterns
- email tokens and inbox cache
- calendar tokens and cached events
- browser sessions
- personal drafts / pending flows

### Family Shared

Visible only to the family contour:

- family transactions
- family budgets
- shopping lists
- family recurring payments
- family categories

### Work Shared

Visible only to the work contour:

- business transactions
- business budgets
- reports
- clients / contacts
- work documents
- work tasks
- projects
- invoices / bookings / CRM data

---

## Entity-by-Entity Recommendation

### Transactions

Current state:

- already has `scope = business | family | personal`

Recommendation:

- keep `scope` as business meaning;
- add `visibility`;
- map defaults:
  - `scope=personal` -> `visibility=private_user`
  - `scope=family` -> `visibility=family_shared`
  - `scope=business` -> `visibility=work_shared`

### Tasks

Current state:

- has `family_id`, `user_id`, but no visibility;
- some bot paths already treat tasks as personal;
- miniapp currently reads them too broadly.

Recommendation:

- add `visibility`;
- default new tasks to `private_user`;
- use `family_shared` or `work_shared` for shared tasks;
- add `created_by_user_id` and optionally `assigned_user_id`.

### Life Events

Current state:

- has `family_id`, `user_id`;
- semantically personal;
- miniapp currently exposes them by `family_id`.

Recommendation:

- treat `life_events` as strictly `private_user`;
- do not make them shared by default;
- if a shared journal is needed later, use a separate entity.

### Documents

Current state:

- has `family_id`, `user_id`;
- a document may be personal or work-shared.

Recommendation:

- add `visibility`;
- defaults:
  - user-uploaded document -> `private_user`
  - templates, invoices, shared business docs -> `work_shared`

### Conversation Messages / Summaries

Current state:

- tenant-scoped by `family_id`, but semantically personal dialog data.

Recommendation:

- treat them as `private_user`;
- RLS and query paths must use `user_id`, not only `family_id`.

### Mem0 / Memory

Current state:

- primary memory is already `user_id`-scoped;
- that is correct.

Recommendation:

- keep user-scoped memory as the default;
- if shared memory is needed, add separate namespaces:
  - `family:{family_id}:shared`
  - `work:{family_id}:shared`

Do not mix private and shared memory in one namespace.

---

## Recommended Role Presets

### Family: Partner

- `view_finance`
- `create_finance`
- `edit_finance`
- `view_budgets`
- `manage_budgets`
- `view_reports` optional

Denied:

- `view_private_chat`
- `view_private_memory`
- `view_private_life`
- `view_owner_email`
- `view_owner_calendar`

### Family: Family Member

- limited or optional `view_finance`
- `create_finance`
- optional `view_budgets`
- shared family tasks only

Denied:

- private data of other users

### Worker: Worker

- `view_work_tasks`
- `manage_work_tasks`
- `view_contacts`

Denied:

- all private data
- finance/reporting by default

### Worker: Assistant

- `view_work_tasks`
- `manage_work_tasks`
- `view_contacts`
- `manage_contacts`
- `view_work_documents`

Denied:

- private data
- reporting/finance unless explicitly enabled

### Worker: Accountant

- `view_finance`
- `create_finance`
- `edit_finance`
- `view_reports`
- `export_reports`
- `view_budgets`
- `manage_budgets`

Denied:

- `view_private_chat`
- `view_private_memory`
- `view_private_life`
- `view_owner_email`
- `view_owner_calendar`

### Viewer

- read-only access to allowed shared resources

---

## Schema Changes

### New Table: `workspace_memberships`

Recommended fields:

- `id`
- `family_id`
- `user_id`
- `membership_type`
- `role`
- `permissions` JSONB
- `status` (`invited`, `active`, `suspended`, `revoked`)
- `invited_by_user_id`
- `joined_at`
- `updated_at`

Notes:

- do not remove current `users.family_id` in phase 1;
- use the membership table as the new access source of truth;
- keep `users.family_id` as a compatibility field during migration.

### New Enum: `resource_visibility`

Values:

- `private_user`
- `family_shared`
- `work_shared`

### Columns to Add

Minimum set:

- `tasks.visibility`
- `documents.visibility`
- `transactions.visibility`
- `conversation_messages.visibility`
- `session_summaries.visibility`

Optional:

- `created_by_user_id`
- `shared_by_user_id`

For `life_events`, it is acceptable not to add visibility if the product rule is to keep them strictly `private_user`.

---

## Enforcement Model

### Layer 1. Access Service in Python

Introduce a single access layer:

- `can_view_resource(context, resource)`
- `can_edit_resource(context, resource)`
- `apply_access_filter(context, stmt, model, resource_kind)`

Do not keep manual access filtering scattered around the codebase.

### Layer 2. SessionContext

`SessionContext` already contains role and helper methods.

Extend it with:

- membership type
- permissions
- active workspace mode (`family` / `work`)

### Layer 3. RLS

RLS must stop being family-only.

Target model:

- tenant isolation: `family_id`
- intra-tenant isolation: `visibility + actor user_id + membership permissions`

Recommended rollout:

1. App-level enforcement first.
2. RLS hardening for critical tables second.

---

## Current High-Risk Areas

Immediate high-risk gaps:

1. `api/miniapp.py`
   - `/me` exposes `invite_code`
   - `tasks` list/update/delete are family-wide
   - `life-events` list is family-wide

2. Analytics and finance skills
   - many read paths are `family_id`-only and ignore role/visibility

3. Context assembly
   - tenant-wide categories/mappings are loaded without role-aware filtering

4. RLS
   - isolates only across tenants, not inside a tenant

---

## Rollout Plan

### Phase 0: Emergency Hotfixes — DONE (2026-03-08)

- ✅ hide `invite_code` from `/api/me` for non-owner (already done)
- ✅ switch miniapp `life-events` to `user_id` (already done)
- ✅ switch miniapp `tasks` to `user_id` (already done)
- ✅ Budget DELETE — add `apply_scope_filter()`
- ✅ add_expense / add_income — force member to `scope=family`

### Phase 1: Introduce Membership + Visibility — DONE (2026-03-08)

- ✅ `workspace_memberships` table + migration 030
- ✅ `MembershipType`, `MembershipRole`, `MembershipStatus`, `ResourceVisibility` enums
- ✅ `ROLE_PRESETS` (8 roles with default permissions)
- ✅ `visibility` column on transactions, tasks, documents, conversation_messages, session_summaries
- ✅ Backfill: existing users → workspace_memberships, transactions visibility from scope
- ✅ Access layer: `apply_visibility_filter()`, `can_view_visibility()`, `get_default_visibility()`
- ✅ `SessionContext` extended with `permissions`, `membership_type`, `has_permission()`
- ✅ Load membership in context builders (`build_session_context`, `build_context_from_channel`)
- ✅ Auto-create membership on user creation (all 4 create/join functions)
- ✅ Set visibility on record creation (expense, income, task, data_tools)
- ✅ 10 member isolation regression tests

### Phase 2: App-Level Access Layer — DONE (2026-03-09)

- ✅ `SessionContext.filter_query()` auto-detects visibility column
- ✅ miniapp: all Transaction queries use `apply_visibility_filter`
- ✅ skills: query_stats, financial_summary, morning_brief, evening_recap migrated
- ✅ data_tools: visibility filtering in query/update/delete + role injection
- ✅ orchestrators/brief: Task/Transaction visibility filtering
- ✅ reports.py: visibility-aware Transaction queries
- ✅ Permission checks: create_finance, edit_finance, delete_finance, manage_budgets, view_reports
- ✅ 17 Phase 2 regression tests

### Phase 3: RLS Hardening — DONE (2026-03-09)

- ✅ Migration 031: `app_current_user_id()` PL/pgSQL helper function
- ✅ Enhanced RLS policies for 5 visibility tables (private_user → user_id check)
- ✅ RLS policy for `workspace_memberships` table
- ✅ RLS policy for `life_events` (strictly private — user_id isolation)
- ✅ `_RLSToken` pattern in `request_context.py` for user_id context propagation
- ✅ `db.py`: `get_session()` and `rls_session()` set both `app.current_family_id` and `app.current_user_id`
- ✅ Migration 032: drop duplicate `ix_wm_family_user` index
- ✅ 12 RLS context unit tests, 15 RBAC integration tests

### Phase 4: UX Rollout — DONE (2026-03-09)

- ✅ Invite wizard: 3-step callback flow (type → role → show code + Redis role storage)
- ✅ List members skill with manage button for owners
- ✅ Manage member skill with per-member action buttons
- ✅ `member:` callback handlers in router.py (role change, suspend, remove)
- ✅ 5 miniapp API endpoints: GET /family/members, PUT role, PUT suspend, PUT activate, DELETE
- ✅ Permission checks on critical mutating skills (edit_finance, delete_finance, create_finance)
- ✅ Audit trail for permission/role changes (log_action on all member operations)
- ✅ Miniapp frontend: Team Members screen (owner-only, member detail modal, role changer)
- ✅ Access Screen: invite wizard shows permissions summary + "Always hidden" block before confirm
- ✅ Confirmation screen: Telegram invite flow (access summary → confirm → generate code)
- ✅ DB-level RLS integration tests (4 tests, PostgreSQL-only with RLS_TESTS=1 gate)

---

## Migration Strategy

### Backfill Defaults

Recommended initial defaults:

- `conversation_messages` -> `private_user`
- `session_summaries` -> `private_user`
- `life_events` -> `private_user`
- `tasks` -> `private_user`
- `documents`:
  - `template`, `invoice`, shared business docs -> `work_shared`
  - everything else -> `private_user`
- `transactions`:
  - `scope=family` -> `family_shared`
  - `scope=business` -> `work_shared`
  - `scope=personal` -> `private_user`

### Compatibility Period

During migration:

- old code continues to work through `family_id`;
- new write paths already set `visibility`;
- read paths are migrated to the access layer gradually.

---

## Testing Requirements

Add regression coverage for:

1. `member` cannot view owner private chat
2. `member` cannot view owner memory
3. `worker` cannot view family private data
4. `accountant` can view work finance but not private chat
5. `partner` can view family-shared transactions but not owner personal transactions
6. `/api/me` does not return invite code for non-owner
7. miniapp tasks do not expose another user's private tasks
8. miniapp life-events do not expose another user's private life events
9. shared tasks are visible only to users with the correct permission
10. RLS blocks intra-family private access

---

## Final Recommendation

For production, adopt these decisions:

1. Keep `family_id` as tenant identifier in phase 1.
2. Introduce `workspace_memberships` as the access source of truth.
3. Introduce `visibility` for shared/private resources.
4. Make the user's private contour private by default.
5. Grant access via role presets plus limited overrides.
6. Move enforcement into a single access layer and then into RLS.

That gives:

- safe family access;
- safe worker access;
- support for accountants, assistants, and service staff;
- predictable privacy;
- a realistic migration path without trying to rewrite the whole project in one release.
