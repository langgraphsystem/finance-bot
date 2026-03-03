# Technical Design: Scheduled Intelligence Actions (SIA)

Date: 2026-03-03
Updated: 2026-03-03
Owner: Core Platform

## 1. Goals

1. Add a first-class scheduled action pipeline (not only `tasks.reminder_at`).
2. Reuse existing architecture: DomainRouter, skills, Taskiq, notification dispatch, callback handling.
3. Keep backward compatibility with current reminders and morning brief.
4. Full i18n support for all user-facing messages (EN/RU/ES).

## 2. As-Is Architecture Snapshot

### 2.1 What exists and is reusable

1. Reminder skill and due-reminder cron:
   1. `src/skills/set_reminder/handler.py`
   2. `src/core/tasks/reminder_tasks.py`
2. Brief data collection + synthesis:
   1. `src/skills/morning_brief/handler.py`
   2. `src/orchestrators/brief/nodes.py` — 5 collectors (calendar, tasks, finance, email, outstanding), each with `@with_retry(1)` + `@with_timeout(15)`, accept `BriefState` (no full SessionContext needed)
3. Worker/scheduler runtime:
   1. `src/core/tasks/broker.py`
   2. `scripts/entrypoint.sh`
4. Unified Telegram dispatch helpers:
   1. `src/core/notifications_pkg/dispatch.py` — `send_telegram_message(telegram_id, text)`, text-only
   2. `src/gateway/telegram.py` — `InlineKeyboardBuilder` for buttons, `_split_message()` for 4096-char limit
5. Callback pipeline and pending actions:
   1. `src/core/router.py` — `_handle_callback()` with 39 existing prefixes
   2. `src/core/pending_actions.py` — Redis TTL=120s (too short for SIA; not reused)
6. Multi-model SDK + tool support:
   1. `src/core/llm/clients.py`
7. Locale resolution:
   1. `src/core/locale_resolution.py` — `resolve_notification_locale()` with multi-layer fallback
8. Feature flags:
   1. `src/core/config.py` — `ff_*: bool` pattern via Pydantic BaseSettings
9. Formatting:
   1. `src/core/formatting.py` — `md_to_telegram_html()` converter
   2. `src/core/notifications_pkg/templates.py` — notification string tables (pattern to follow)
10. Proactivity dispatch pattern:
    1. `src/core/tasks/proactivity_tasks.py` — fetch all users → iterate → send per-user

### 2.2 Constraints

1. Existing reminder flow is task-centric and message text is mostly static.
2. `ModelRouter` is not the active runtime policy entrypoint.
3. Existing cron tasks are module-specific (reminder/life/proactivity), so SIA must avoid duplicating collector logic again.
4. `send_telegram_message()` does not support buttons — SIA dispatcher must use gateway directly for inline keyboards.
5. Telegram callback_data max ~64 bytes — complex data must go to Redis.

## 3. Target Architecture

## 3.1 New Modules

1. `src/core/models/scheduled_action.py`
2. `src/core/models/scheduled_action_run.py`
3. `src/core/scheduled_actions/engine.py`
4. `src/core/scheduled_actions/collectors.py` — thin wrappers importing from `orchestrators/brief/nodes.py`
5. `src/core/scheduled_actions/formatter.py` — compact (Jinja2) + decision_ready (LLM) modes
6. `src/core/scheduled_actions/i18n.py` — string tables for EN/RU/ES
7. `src/core/scheduled_actions/message_builder.py` — HTML message construction + button assembly
8. `src/core/tasks/scheduled_action_tasks.py`
9. `src/skills/schedule_action/handler.py`
10. `src/skills/list_scheduled_actions/handler.py`
11. `src/skills/manage_scheduled_action/handler.py`

## 3.2 Database Design

### `scheduled_actions`

1. `id UUID PK DEFAULT gen_random_uuid()`
2. `family_id UUID NOT NULL FK families`
3. `user_id UUID NOT NULL FK users`
4. `title VARCHAR(255) NOT NULL`
5. `instruction TEXT NOT NULL`
6. `action_kind VARCHAR(32) NOT NULL`
7. `schedule_kind VARCHAR(16) NOT NULL`
8. `schedule_config JSONB NOT NULL`
9. `sources JSONB NOT NULL`
10. `output_mode VARCHAR(32) NOT NULL DEFAULT 'compact'`
11. `timezone VARCHAR(50) NOT NULL`
12. `language VARCHAR(10) NOT NULL DEFAULT 'en'`
13. `status VARCHAR(16) NOT NULL DEFAULT 'active'`
14. `next_run_at TIMESTAMPTZ`
15. `last_run_at TIMESTAMPTZ`
16. `last_success_at TIMESTAMPTZ`
17. `run_count INTEGER NOT NULL DEFAULT 0`
18. `failure_count INTEGER NOT NULL DEFAULT 0`
19. `max_failures INTEGER NOT NULL DEFAULT 3`
20. `end_at TIMESTAMPTZ`
21. `max_runs INTEGER`
22. `created_at TIMESTAMPTZ DEFAULT now()`
23. `updated_at TIMESTAMPTZ DEFAULT now()`

Indexes:

1. `ix_sched_actions_dispatch ON (status, next_run_at) WHERE status = 'active'` — partial index for dispatcher
2. `ix_sched_actions_user ON (family_id, user_id, status)`

### `scheduled_action_runs`

1. `id UUID PK DEFAULT gen_random_uuid()`
2. `scheduled_action_id UUID NOT NULL FK scheduled_actions ON DELETE CASCADE`
3. `planned_run_at TIMESTAMPTZ NOT NULL`
4. `started_at TIMESTAMPTZ`
5. `finished_at TIMESTAMPTZ`
6. `status VARCHAR(16) NOT NULL`
7. `error_code VARCHAR(64)`
8. `error_text TEXT`
9. `sources_status JSONB` — per-source success/fail/duration
10. `payload_snapshot JSONB`
11. `message_preview TEXT`
12. `model_used VARCHAR(64)`
13. `tokens_used INTEGER`
14. `duration_ms INTEGER`
15. `created_at TIMESTAMPTZ DEFAULT now()`

Unique constraint:

1. `uq_sched_run_idempotent ON (scheduled_action_id, planned_run_at)` for idempotency.

### Enum values

```python
class ScheduleKind(StrEnum):
    once = "once"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    weekdays = "weekdays"    # P1
    cron = "cron"            # P1

class ActionStatus(StrEnum):
    active = "active"
    paused = "paused"
    completed = "completed"  # end condition reached
    deleted = "deleted"

class RunStatus(StrEnum):
    pending = "pending"
    running = "running"
    success = "success"
    partial = "partial"      # some sources failed
    failed = "failed"
    skipped = "skipped"      # quiet hours, comm_mode=silent

class OutputMode(StrEnum):
    compact = "compact"
    decision_ready = "decision_ready"
```

### ScheduleConfig validation (Pydantic)

```python
class ScheduleConfig(BaseModel):
    time: str                           # "08:00" local wall-clock
    days: list[int] | None = None       # 0=Mon..6=Sun for weekly
    day_of_month: int | None = None     # 1-31 for monthly, clamped
    cron_expr: str | None = None        # P1: validated cron expression
    original_time: str | None = None    # preserved for DST-safe advancement
    end_at: datetime | None = None      # P1: stop after this date
    max_runs: int | None = None         # P1: stop after N runs
    snooze_minutes: int = 10            # default snooze duration
```

## 3.3 Runtime Pipeline

1. Dispatcher cron (`every minute`) fetches due actions:
   1. `status='active'`
   2. `next_run_at <= now()`
   3. `FOR UPDATE SKIP LOCKED` — multi-worker safe
   4. `LIMIT 50` — batch cap per run
2. Pre-send checks per action:
   1. `is_send_window()` — respect quiet hours
   2. `comm_mode != 'silent'` — respect communication mode
   3. End conditions: `run_count < max_runs`, `now < end_at`
   4. If skipped → create run with status `skipped`, advance `next_run_at`
3. Engine creates run row (idempotent by unique constraint `(action_id, planned_run_at)`).
4. Collectors run in parallel with timeouts:
   1. Import and call collectors from `src/orchestrators/brief/nodes.py`
   2. Each collector: `@with_timeout(15)` + `@with_retry(1)`
   3. Only run collectors matching `sources` JSONB list
   4. Track per-source status in `sources_status` field
5. Formatter chooses rendering mode:
   1. `compact` → Jinja2 template with i18n strings, **zero LLM calls**
   2. `decision_ready` → LLM synthesis with fallback chain (gated by `ff_sia_synthesis`)
6. Message builder assembles HTML + inline keyboard buttons.
7. Send via `TelegramGateway` (not `send_telegram_message` — need buttons).
8. Update run status and action state:
   1. success → reset `failure_count`, set `last_success_at`, increment `run_count`, compute `next_run_at`
   2. partial → same as success but log degraded sources
   3. failure → increment `failure_count`, retry with backoff, pause when `failure_count >= max_failures`

## 3.4 Schedule Resolution

Supported P0:

1. `once`: fixed datetime.
2. `daily`: same local wall-clock time.
3. `weekly`: same weekday/time.
4. `monthly`: same day/time, clamp short month.

Supported P1:

1. `weekdays`: Mon-Fri by local timezone.
2. `cron`: validated cron expression.
3. End conditions: `end_at`, `max_runs`.

Implementation notes:

1. Store raw schedule params in `schedule_config` (validated by `ScheduleConfig` Pydantic model).
2. Compute `next_run_at` in UTC, preserve local wall-clock semantics.
3. Reuse DST-safe strategy from recurring reminders (`original_time` field in `ScheduleConfig`).
4. `_compute_next_run(action, after: datetime) -> datetime | None`:
   1. Resolve user timezone from `action.timezone`.
   2. Convert `after` to local time.
   3. Advance by schedule kind (add 1 day / 7 days / 1 month).
   4. Apply `original_time` to preserve wall-clock.
   5. Convert back to UTC.
   6. Return `None` if end condition reached (signals completion).

### DST edge cases

1. **Spring forward** (02:00 → 03:00): if scheduled at 02:30, fire at 03:00 (next valid time).
2. **Fall back** (02:00 → 01:00): if scheduled at 01:30, fire only once (first occurrence).
3. **Test coverage**: parametrized tests for US/Eastern, Europe/Moscow, America/Santiago.

## 3.5 Callbacks and Interaction Contracts

Add callback prefix `sched:` to `_handle_callback()` in router:

1. `sched:snooze:{redis_key}` — snooze minutes stored in Redis (`sched_snooze:{action_id}`, TTL 3600s, value = minutes)
2. `sched:pause:{action_id}`
3. `sched:resume:{action_id}`
4. `sched:run:{action_id}`
5. `sched:del:{action_id}`

All callbacks validate ownership: `action.user_id == callback_user_id AND action.family_id == callback_family_id`.

Response button layout (Telegram, 2 columns via `builder.adjust(2)`):

Row 1: `[⏰ +10 min] [▶️ Run now]`
Row 2: `[⏸ Pause]` or `[▶️ Resume]`

Delete button is not shown in scheduled message output — only via `manage_scheduled_action` skill.

### Snooze flow

1. User taps `⏰ +10 min`.
2. Callback: `sched:snooze:{redis_key}`.
3. Handler reads minutes from Redis, shifts `next_run_at` by minutes.
4. Responds with i18n string: `"Snoozed — will run in {minutes} min."`.
5. Original message buttons are removed (edit_reply_markup).

## 3.6 Model and Prompt Policy

Allowed model IDs only:

1. `gpt-5.2`
2. `claude-sonnet-4-6`
3. `claude-haiku-4-5`
4. `gemini-3-flash-preview`
5. `gemini-3.1-pro-preview` (optional future, deep reasoning for complex multi-source synthesis)

Model assignment:

1. Extraction from conversation context (schedule_action skill): `gpt-5.2` JSON mode.
2. Main synthesis (decision_ready mode): `claude-sonnet-4-6`.
3. Fallback synthesis: `gpt-5.2`.
4. Cheap emergency fallback: `gemini-3-flash-preview`.

### Synthesis prompt template

```
You generate a scheduled intelligence summary for the user.
You receive real data from {sources_list}.
Synthesize into one scannable message.

Rules:
- Start with a time-appropriate greeting using the user's name.
- Use section headers with emoji for each domain that has data.
- Bullet points, short lines — scannable, not dense paragraphs.
- Skip sections that have no data (don't say "no data available").
- End with one actionable question or suggestion.
- Max 12 bullet points total across all sections.
- Use HTML tags for Telegram (<b>, <i>). No Markdown.
- Bold key numbers and amounts.
- Use priority indicators: 🔥 urgent, 🟡 warning, 🔴 critical.
- Respond in: {language}.
```

## 3.7 Message Design and Formatting

### HTML structure rules

1. All output uses Telegram HTML: `<b>`, `<i>`, `<code>` only.
2. No Markdown — LLM output converted via `md_to_telegram_html()` as safety net.
3. Max message length: 4000 chars (leave 96 char buffer for Telegram's 4096 limit).
4. Longer messages split via `_split_message()` — buttons on last chunk only.
5. Section headers: `{emoji} <b>{title}</b>` on its own line.
6. Bullets: `• ` prefix (Unicode bullet, not `-`).
7. Numbers and amounts: always `<b>bold</b>`.
8. No smiley-face or decorative emoji — only informational icons.

### Compact mode (Jinja2, zero LLM)

Template file: `src/core/scheduled_actions/templates/compact.html.j2`

```jinja2
{{ greeting_emoji }} <b>{{ greeting }}, {{ name }}!</b>

{% for section in sections %}
{% if section.data %}
{{ section.emoji }} <b>{{ section.title }}</b>
{% for item in section.items[:5] %}
• {{ item }}
{% endfor %}

{% endif %}
{% endfor %}
{% if closing_question %}{{ closing_question }}{% endif %}
```

### Decision-ready mode (LLM synthesis)

System prompt generates free-form HTML following the rules above. Output validated:
1. Check for unclosed HTML tags.
2. Strip disallowed tags.
3. Truncate to 4000 chars if needed.

### List view template

```jinja2
📋 <b>{{ header }}</b>

{% for action in actions %}
{{ loop.index }}. {{ status_icon(action.status) }} <b>{{ action.title }}</b>
   {{ schedule_desc(action) }} · {{ next_run_label }}: {{ format_time(action.next_run_at, tz) }}

{% endfor %}
{% if not actions %}
{{ empty_message }}
{% endif %}
```

### Degraded mode

When some collectors fail, message includes available data plus footer:

```
{normal_message_with_available_sections}

<i>⚠️ {unavailable_sources} temporarily unavailable</i>
```

## 3.8 Internationalization (i18n)

### Architecture

1. **String table module**: `src/core/scheduled_actions/i18n.py` — `_STRINGS[lang][key]` dict.
2. **Accessor function**: `t(key: str, lang: str, **kwargs) -> str` — lookup + `.format(**kwargs)`.
3. **Fallback**: if key missing for `lang`, fall back to `en`.
4. **Languages**: `en`, `ru`, `es` (P0). Adding a language = adding a dict entry.

### What is i18n'd

| Element | Method | Source |
|---------|--------|--------|
| Confirmation messages | String table `t()` | `i18n.py` |
| Button labels | String table `t()` | `i18n.py` |
| Section headers | String table `t()` | `i18n.py` |
| Greeting (time-of-day) | String table `t()` | `i18n.py` |
| Compact template static text | Jinja2 with `t()` vars | `templates/compact.html.j2` |
| LLM synthesis body | `"Respond in: {language}"` in prompt | Prompt template |
| Schedule description | Formatter function with i18n | `formatter.py` |
| Error/degraded messages | String table `t()` | `i18n.py` |
| Date/time display | Locale-aware format | `formatter.py` |

### Date/time formatting by locale

```python
DATE_FORMATS = {
    "en": {"date": "%b %d", "time": "%I:%M %p", "datetime": "%b %d, %I:%M %p"},
    "ru": {"date": "%d.%m", "time": "%H:%M", "datetime": "%d.%m в %H:%M"},
    "es": {"date": "%d/%m", "time": "%H:%M", "datetime": "%d/%m a las %H:%M"},
}

WEEKDAY_NAMES = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "ru": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
}

SCHEDULE_DESCRIPTIONS = {
    "en": {
        "once": "once on {date}",
        "daily": "daily at {time}",
        "weekly": "every {day} at {time}",
        "monthly": "monthly on day {day_of_month} at {time}",
        "weekdays": "weekdays at {time}",
    },
    "ru": {
        "once": "однократно {date}",
        "daily": "ежедневно в {time}",
        "weekly": "каждый {day} в {time}",
        "monthly": "ежемесячно {day_of_month}-го в {time}",
        "weekdays": "по будням в {time}",
    },
    "es": {
        "once": "una vez el {date}",
        "daily": "diariamente a las {time}",
        "weekly": "cada {day} a las {time}",
        "monthly": "mensualmente el {day_of_month} a las {time}",
        "weekdays": "días laborables a las {time}",
    },
}
```

## 3.9 IntentData Fields

Add to `src/core/schemas/intent.py` in `IntentData` class:

```python
# --- Scheduled Actions (SIA) ---
schedule_frequency: str | None = None       # once, daily, weekly, monthly, weekdays, cron
schedule_time: str | None = None            # "08:00", "7:30 AM"
schedule_day_of_week: str | None = None     # "monday", "пн", "Mon-Fri"
schedule_sources: list[str] | None = None   # ["calendar", "tasks", "money"]
schedule_instruction: str | None = None     # free-text instruction for what to include
schedule_output_mode: str | None = None     # "compact", "decision_ready"
schedule_end_date: str | None = None        # "2026-04-01" or "in 2 weeks"
schedule_max_runs: int | None = None        # 5, 10
managed_action_title: str | None = None     # title or description to identify action
manage_operation: str | None = None         # pause, resume, delete, reschedule
```

## 3.10 Observability

Add structured logs and Langfuse traces:

Events:

1. `scheduled_action_triggered` — dispatcher picked up action
2. `scheduled_action_run_succeeded` — full success
3. `scheduled_action_run_partial` — some sources failed
4. `scheduled_action_run_failed` — all sources or send failed
5. `scheduled_action_run_skipped` — quiet hours or comm_mode
6. `scheduled_action_callback_used` — user tapped a button

Dimensions:

1. `user_id`, `family_id`
2. `action_kind`, `schedule_kind`
3. `language`, `timezone`
4. `output_mode`
5. `model_used`, `fallback_used`
6. `duration_ms`, `tokens_used`
7. `sources_status` — per-source success/fail

Metrics for PRD success tracking:

1. **Activation**: count distinct users with `scheduled_action_triggered` in 30 days.
2. **Reliability**: `run_succeeded / (run_succeeded + run_failed)`.
3. **Freshness**: `max(collector_finished_at) - run_started_at` per source.
4. **Engagement**: `callback_used / run_succeeded` within 2h window.
5. **Cost**: sum `tokens_used * model_price` per user per month.

## 3.11 Security and Isolation

1. Keep existing family isolation via RLS context (`set_family_context` in router path; worker uses scoped queries by family/user).
2. `scheduled_actions` table includes `family_id` FK — same RLS as all other tables.
3. Validate callback ownership (action belongs to current user/family) before any mutation.
4. Do not execute side-effect actions without explicit callback/approval.
5. Dispatcher queries always filter by `user_id` + `family_id` for data collectors.

### Security test checklist

1. User A cannot list/pause/delete User B's actions (even in same family if user-scoped).
2. Callback with forged `action_id` returns error, not data leak.
3. Dispatcher does not process actions for disabled/deleted users.

## 4. Integration Points

### 4.1 Files to modify (checklist)

1. `src/core/intent.py`
   1. Add 3 intents to `INTENT_DETECTION_PROMPT` with examples in EN/RU.
   2. Escape any literal curly braces with `{{}}`.
2. `src/core/schemas/intent.py`
   1. Add 9 IntentData fields (see §3.9).
3. `src/agents/config.py`
   1. Add new intents to tasks agent skills list.
4. `src/core/domains.py`
   1. Map 3 new intents to `Domain.tasks`.
5. `src/skills/__init__.py`
   1. Register 3 new skills.
6. `config/skill_catalog.yaml`
   1. Add `schedule_action`, `list_scheduled_actions`, `manage_scheduled_action` to tasks domain.
   2. Add trigger keywords: schedule, automate, recurring, scheduled, запланировать, регулярн, расписан, programar.
7. `src/core/memory/context.py`
   1. Add `QUERY_CONTEXT_MAP` entries for 3 new intents.
8. `scripts/entrypoint.sh`
   1. Add `src.core.tasks.scheduled_action_tasks` to TASK_MODULES.
9. `src/core/config.py`
   1. Add `ff_scheduled_actions: bool = False`.
   2. Add `ff_sia_synthesis: bool = False`.
10. `src/core/router.py`
    1. Add `sched:` callback prefix to `_handle_callback()`.

### 4.2 Migration naming

Next migration number: check `alembic heads` before creating.
Use raw SQL with `CREATE TABLE IF NOT EXISTS` and `DO $$ ... EXCEPTION` for enum types.

## 5. Rollout Plan

1. Flag off by default in production: `ff_scheduled_actions=False`, `ff_sia_synthesis=False`.
2. Internal enablement for test users.
3. Beta rollout:
   1. 5% users — compact mode only
   2. 25% users — compact + synthesis (enable `ff_sia_synthesis`)
   3. 100%
4. Rollback path:
   1. disable flags
   2. no impact on existing `set_reminder` and existing cron tasks.

## 6. Test Strategy

1. Unit tests:
   1. Schedule parser and `_compute_next_run()` calculations.
   2. DST transition tests (spring forward, fall back) for US/Eastern, Europe/Moscow, America/Santiago.
   3. Collector timeout/failure behavior.
   4. Formatter output for compact and decision-ready modes.
   5. i18n string table completeness (all keys present for all languages).
   6. ScheduleConfig Pydantic validation (valid/invalid inputs).
   7. Message builder HTML output.
2. Integration tests:
   1. Create action → due dispatch → send → next run progression.
   2. Callback actions (`snooze/pause/resume/run_now/delete`).
   3. Idempotency (duplicate trigger protection via unique constraint).
   4. Race condition: 2 workers, 1 action (mock `FOR UPDATE SKIP LOCKED`).
   5. All collectors failed → degraded mode message.
   6. Quiet hours → run skipped.
   7. `comm_mode=silent` → run skipped.
   8. End conditions: `max_runs` reached → action completed.
3. Regression tests:
   1. Existing `set_reminder` behavior unchanged.
   2. Existing `dispatch_due_reminders` unaffected.
   3. Brief orchestrator tests remain green (collectors not refactored).
4. i18n tests:
   1. All 3 languages render correctly for all message types.
   2. Date/time formatting matches locale expectations.
   3. Button labels are correct per language.

## 7. Resolved Decisions

1. **Domain**: `Domain.tasks` — no new domain needed. SIA is a natural extension of the tasks/reminders domain. Tasks agent already handles reminders.
2. **Channel**: Telegram-only for P0. Multi-channel deferred to P2+.
3. **Synthesis routing**: Direct engine + `generate_text()` — no LangGraph overhead for synthesis. LangGraph used only if SIA evolves into multi-step orchestration.
4. **Collector reuse**: Import directly from `orchestrators/brief/nodes.py` — no refactoring into shared module. Zero regression risk.
5. **Callback format**: 3 segments max (`sched:action:id`). Complex data (snooze minutes) stored in Redis.
