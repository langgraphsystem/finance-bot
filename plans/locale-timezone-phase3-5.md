# Locale/Timezone Close-out: Phases 3-5 Implementation Plan

Date: 2026-02-26
Branch: `claude/review-pricing-plans-Wxzf4`

## Context

Phases 0-2 are complete:
- Feature flags defined (`ff_locale_v2_read`, `ff_locale_v2_write`, `ff_reminder_dispatch_v2`)
- DB migration applied (013: notification_language, timezone_source, timezone_confidence, locale_updated_at)
- Central resolver `src/core/locale_resolution.py` implemented
- Read path integrated in all 3 task modules (reminder_tasks, life_tasks, proactivity_tasks)

## Problem Summary

1. **Language mismatch**: `users.language` defaults to `ru`, `user_profiles.preferred_language` defaults to `en` — different flows read different fields
2. **Timezone auto-override**: `_maybe_set_timezone_from_language` in `api/main.py` maps `language_code=ru` → `Europe/Moscow` even for US-based Russian speakers
3. **No write path for `notification_language`**: field exists but unreachable via any API/skill
4. **`notifications.py` hardcoded Russian**: budget/anomaly alerts use Russian strings, not localized
5. **Fragmented dispatch**: 3 task modules + notifications.py each have own locale handling and templates

---

## Phase 3: Write Path Normalization

### 3.1 Fix `_maybe_set_timezone_from_language` (api/main.py:64-102)

**Current**: auto-sets timezone from Telegram language_code, no `timezone_source` tracking.

**Changes**:
- Gate behind `ff_locale_v2_write` flag
- When flag ON: set `timezone_source='channel_hint'`, `timezone_confidence=30`
- Never overwrite if `timezone_source` is `user_set` or `geo_ip` (only overwrite `default`)
- When flag OFF: keep current behavior (backward compat)

**File**: `api/main.py`

### 3.2 Fix geo/detect endpoint (api/miniapp.py:1405-1480)

**Current**: sets timezone but doesn't set `timezone_source` or `timezone_confidence`.

**Changes**:
- Set `timezone_source='geo_ip'`, `timezone_confidence=70`
- Set `locale_updated_at=now()`
- Only overwrite timezone if new source has higher confidence than existing

**File**: `api/miniapp.py`

### 3.3 Fix settings endpoint (api/miniapp.py:1364-1367)

**Current**: when user changes language via settings, updates `users.language` + `preferred_language` but not `notification_language`.

**Changes**:
- Gate behind `ff_locale_v2_write`
- When flag ON: also set `notification_language` to same value (explicit user choice)
- Set `locale_updated_at=now()`

**File**: `api/miniapp.py`

### 3.4 Tests for Phase 3

**File**: `tests/test_core/test_write_path_locale.py` (new)

Tests:
- `test_timezone_from_language_respects_flag_off` — legacy behavior unchanged
- `test_timezone_from_language_sets_source_when_flag_on` — timezone_source=channel_hint
- `test_timezone_from_language_skips_user_set` — doesn't overwrite user_set timezone
- `test_geo_detect_sets_timezone_source` — geo_ip source + confidence=70
- `test_settings_update_sets_notification_language` — syncs notification_language

---

## Phase 4: Dispatch Unification

### 4.1 Create `src/core/notifications/templates.py`

Consolidate all i18n templates into one place:
- Move `_TEXTS` from `life_tasks.py`
- Move `_reminder_label` from `reminder_tasks.py`
- Add localized financial notification templates (currently hardcoded Russian in `notifications.py`)
- Export: `get_text(lang, key)`, `get_reminder_label(lang)`, `get_financial_header(lang)`

### 4.2 Create `src/core/notifications/dispatch.py`

Shared dispatch helper:
- `send_localized_message(telegram_id, text)` — wraps aiogram Bot send
- `mark_daily_once(kind, user_id, day)` — unified Redis dedup (move from life_tasks)
- `is_send_window(timezone, target_hour, target_minute, window_minutes)` — move from life_tasks
- `now_in_timezone(timezone)` — move from life_tasks

### 4.3 Create `src/core/notifications/__init__.py`

Re-export from templates + dispatch for backward compat.

### 4.4 Refactor existing modules

- `reminder_tasks.py` — import labels from templates, send from dispatch
- `life_tasks.py` — import texts from templates, use shared dispatch helpers
- `proactivity_tasks.py` — import send from dispatch (already uses life_tasks._send_telegram_message)
- `notification_tasks.py` — use localized templates instead of hardcoded Russian

### 4.5 Localize `src/core/notifications.py` (financial alerts)

**Current hardcoded Russian strings**:
- `"⚠️ Необычно: {category}"` → localized
- `"🔴 Бюджет «{cat}» превышен"` → localized
- `"🟡 {pct}% бюджета «{cat}» использовано"` → localized
- `"📊 Финансовые уведомления:"` → localized
- `"Общий"` / `"Категория"` → localized

Add language parameter to `check_anomalies()`, `check_budgets()`, `format_notification()`.

### 4.6 Tests for Phase 4

**File**: `tests/test_core/test_notification_templates.py` (new)

Tests:
- `test_all_languages_have_all_keys` — completeness check
- `test_reminder_label_fallback` — unknown lang → English
- `test_financial_alerts_localized` — en/es/ru all produce correct text
- `test_send_window_edge_cases` — boundary conditions
- `test_mark_daily_once_dedup` — Redis dedup works correctly

---

## Phase 5: Hardening and Cleanup

### 5.1 Enable feature flags by default

- Set `ff_locale_v2_read: bool = True` (was False)
- Set `ff_locale_v2_write: bool = True` (was False)
- Set `ff_reminder_dispatch_v2: bool = True` (was False)

**File**: `src/core/config.py`

### 5.2 Change `User.language` default from `ru` to `en`

**File**: `src/core/models/user.py`

Change: `language: Mapped[str] = mapped_column(String(5), default="en")`

This only affects NEW users. Existing users keep their current value.

### 5.3 Update plan document progress tracker

**File**: `docs/plans/2026-02-25-architecture-audit-vnext-language-timezone-reminders.md`

Mark Phases 3-5 as DONE with commit references.

### 5.4 Tests for Phase 5

- `test_default_language_is_english` — verify User model default
- `test_flags_enabled_by_default` — verify Settings defaults

---

## File Change Summary

| File | Phase | Change Type |
|------|-------|-------------|
| `api/main.py` | 3 | Modify _maybe_set_timezone_from_language |
| `api/miniapp.py` | 3 | Modify geo/detect + settings endpoints |
| `src/core/notifications/templates.py` | 4 | NEW — consolidated i18n |
| `src/core/notifications/dispatch.py` | 4 | NEW — shared send/dedup/window |
| `src/core/notifications/__init__.py` | 4 | NEW — re-exports |
| `src/core/notifications.py` | 4 | Modify — add language param, use templates |
| `src/core/tasks/reminder_tasks.py` | 4 | Refactor — use shared templates/dispatch |
| `src/core/tasks/life_tasks.py` | 4 | Refactor — extract templates/helpers |
| `src/core/tasks/proactivity_tasks.py` | 4 | Refactor — use shared dispatch |
| `src/core/tasks/notification_tasks.py` | 4 | Modify — pass language to notifications |
| `src/core/config.py` | 5 | Modify — flip flag defaults |
| `src/core/models/user.py` | 5 | Modify — default ru→en |
| `tests/test_core/test_write_path_locale.py` | 3 | NEW |
| `tests/test_core/test_notification_templates.py` | 4 | NEW |
| `docs/plans/...` | 5 | Update tracker |

## Execution Order

1. Phase 3 first (write path fixes) — immediate bug reduction
2. Phase 4 (dispatch unification) — structural improvement
3. Phase 5 (hardening) — flip flags and change defaults
4. Run full test suite after each phase
5. Commit per phase for clean rollback
