# Scheduled Intelligence Actions (SIA)

**Author:** Codex
**Date:** 2026-03-03
**Updated:** 2026-03-03
**Status:** Draft
**Star Rating:** 6.5 stars -> 7.5 stars (from static reminders to scheduled, decision-ready, cross-domain actions)
**RICE Score:** 41.3 (Reach 75% x Impact 2.5 x Confidence 88% / Effort 5.5 wks)

---

## 1. Problem Statement

### What problem are we solving?

The project already supports task reminders and separately supports rich data synthesis (morning brief).
But users cannot reliably schedule one request such as:

1. "At 8:00 AM, collect my calendar, tasks, money, and important emails."
2. "Send one short actionable summary."
3. "Let me snooze/reschedule from buttons."

Current reminders mostly send static stored text at trigger time. For users, this feels like a timer, not an AI assistant.

### Why this matters now

1. Market baseline in 2026 already includes scheduled AI actions and recurring automation.
2. We already have most building blocks in code (Taskiq cron, notification dispatch, brief collectors, callbacks, locale/timezone resolver).
3. Converging reminders + scheduled data actions provides immediate product lift without rewriting core architecture.

### Current architecture constraints (as-is)

1. Reminder creation and reminder dispatch are task-centric (`tasks.reminder_at`), not action-centric.
2. Rich data collection exists in `morning_brief` flow but is not reusable by reminder runtime.
3. Callback infrastructure exists, but reminder-specific post-actions (snooze/reschedule/run-now) are not implemented.
4. Runtime model policy is distributed (agents/skills/clients), while `ModelRouter` is mostly not in active runtime path.

---

## 2. Solution Overview

### What are we building?

A new capability class: **Scheduled Intelligence Actions**.

Each action has:

1. A schedule (`once`, `daily`, `weekly`, `monthly`, then `weekdays`/`cron` in next phase).
2. A data source set (`schedule`, `tasks`, `money_summary`, `email_highlights`, `outstanding`).
3. An output mode (`compact` or `decision_ready`).
4. Runtime execution that collects fresh data, synthesizes, sends, and logs run status.
5. Full internationalization — messages rendered in user's preferred language.

### Example conversations

**Maria (household, English):**
```
Maria: Every weekday at 7:30 send me today's plan with calendar, tasks, and money.
Bot: Done — weekday brief at 7:30 AM your time.
     Sources: calendar, tasks, money.

[07:30]
Bot: ☀️ Good morning, Maria!

📅 Today
• 10:00 Parent-teacher conference
• 2:00 PM Dentist (Jake)

✅ Tasks (3 open, 1 urgent)
• 🔥 Pay electricity bill — due today
• Order birthday cake
• Return Amazon package

💰 Money
• This month: $2,340 spent
• Budget left: $660 (22 days)

What should I handle first?
[⏰ Snooze 10m] [▶️ Run now] [⏸ Pause]
```

**David (service business, Russian):**
```
David: Каждый день в 8 проверяй неоплаченные счета и сегодняшние заказы.
Bot: Готово — ежедневно в 8:00.
     Источники: заказы, неоплаченные счета.

[08:00]
Bot: 🔧 Доброе утро, David!

📋 Сегодня (3 заказа)
• 09:00 Иванов — замена труб, $450
• 13:00 Петрова — установка смесителя, $180
• 16:00 Сидоров — диагностика, $80

💰 Неоплаченные счета (2)
• 🔴 Козлов — $1,200, просрочка 5 дн.
• 🟡 Морозова — $350, срок завтра

Итого к получению: $1,550. Отправить напоминание Козлову?
[📨 Напомнить] [⏸ Пауза] [⏰ +10 мин]
```

**Maria (Spanish):**
```
Maria: Cada lunes a las 9 envíame un resumen de la semana.
Bot: Listo — resumen semanal cada lunes a las 9:00.
     Fuentes: calendario, tareas, finanzas.
```

### What are we NOT building?

1. Autonomous purchasing or payment execution.
2. New communication channels in this phase (Telegram only).
3. Full geofencing/location triggers in this phase.
4. Unconfirmed destructive actions without approval.

---

## 3. User Stories

### P0 - Must Have

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | schedule a recurring AI action in natural language | I get useful updates without asking every day |
| 2 | User | choose what data to include (calendar/tasks/money/email) | the summary matches my workflow |
| 3 | User | receive actionable output with buttons | I can react quickly (snooze/pause/run now/delete) |
| 4 | User | list/pause/resume/delete my scheduled actions | I stay in control |
| 5 | User | receive messages in my preferred language | the bot feels natural regardless of my language |

### P1 - Should Have

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | use weekdays and custom cron schedules | I can match real routines |
| 2 | User | set end conditions (until date / N runs) | schedules don't run forever |
| 3 | User | edit existing schedule via natural language | I don't recreate from scratch |

### P2 - Nice to Have (Differentiators)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | get a decision-ready summary (priorities + next step) | I can act immediately |
| 2 | User | get finance-aware reminders | reminders reflect real budget risk |
| 3 | User | run outcome-based reminders ("until done") | I close loops instead of reading alerts |

### Won't Have (this cycle)

| # | Feature | Reason |
|---|---------|--------|
| 1 | Auto-pay / auto-buy | trust/liability risk |
| 2 | Location triggers | requires separate geofencing system |
| 3 | Cross-channel delivery orchestration | out of scope for first release |

---

## 4. Success Metrics

| Category | Metric | Target | Measurement |
|----------|--------|--------|-------------|
| Activation | Users creating >=1 scheduled action in 30 days | >=35% active users | `scheduled_actions` create events |
| Reliability | Successful run delivery rate | >=98.5% | run logs + send success |
| Freshness | Sections with data <=15 min old at send time | >=95% | run metadata timestamps |
| Engagement | Messages with any action (reply/button) in 2h | >=30% | callback/reply correlation |
| Retention | Week-4 retention uplift for SIA users | +8% vs control | cohort analysis |
| Cost | Incremental cost per SIA active user | <=$1.5/month | usage logs by model |

### Failure signals

1. >5% duplicate sends for same schedule slot.
2. >20% users pausing all actions within first week.
3. >10% runs failing due to source unavailability for 3+ consecutive days.

---

## 5. Technical Scope

### New product intents/skills

1. `schedule_action` (create/update from NL).
2. `list_scheduled_actions`.
3. `manage_scheduled_action` (pause/resume/delete/reschedule).

### Runtime architecture

1. New scheduled-action model and run log model.
2. New cron dispatcher (`* * * * *`) with idempotent run handling.
3. Reuse brief data collectors directly (import from `orchestrators/brief/nodes.py`).
4. Formatter with two modes:
   1. Fast template mode (no LLM) — Jinja2 with i18n string tables.
   2. LLM synthesis mode with fallback chain.
5. Telegram callback actions for post-send controls.
6. Full i18n: string tables for EN/RU/ES, LLM synthesis respects `language` field.

### Model policy (allowed model set only)

1. Extraction/structure: `gpt-5.2`.
2. Synthesis primary: `claude-sonnet-4-6`.
3. Synthesis fallback: `gpt-5.2`.
4. Cheap fallback summary: `gemini-3-flash-preview`.
5. Deep reasoning (optional future): `gemini-3.1-pro-preview`.
6. Keep existing intent-detection stack: `gemini-3-flash-preview` + `claude-haiku-4-5` fallback.

---

## 6. Message Design

### Design principles

1. **Lead with context** — time-appropriate greeting + user name.
2. **Scannable** — section headers with emoji, bullet points, max 12 bullets total.
3. **Actionable** — end with a question or suggestion, always include buttons.
4. **Degraded gracefully** — skip empty sections, mark failed sources with footer.
5. **Beautiful** — consistent emoji usage, bold for key numbers, visual hierarchy.

### Compact mode template

```
{greeting_emoji} <b>{greeting}, {name}!</b>

{foreach source with data:}
{section_emoji} <b>{section_title}</b>
• {item_1}
• {item_2}
• {item_3}
{/foreach}

{closing_question}
[{button_1}] [{button_2}] [{button_3}]
```

### Decision-ready mode template

```
{greeting_emoji} <b>{greeting}, {name}!</b>

🎯 <b>{priority_header}</b>
{top_priority_insight}

{foreach source with data:}
{section_emoji} <b>{section_title}</b>
• {item_1}
• {item_2}
{/foreach}

💡 <b>{recommendation_header}</b>
{next_step_suggestion}

[{action_button}] [{snooze_button}] [{pause_button}]

<i>{trust_footer}</i>
```

### Section emoji contract

| Source | Emoji | Header EN | Header RU | Header ES |
|--------|-------|-----------|-----------|-----------|
| calendar | 📅 | Today | Сегодня | Hoy |
| tasks | ✅ | Tasks | Задачи | Tareas |
| money_summary | 💰 | Money | Финансы | Finanzas |
| email_highlights | 📧 | Email | Почта | Correo |
| outstanding | 🔴 | Outstanding | Неоплаченные | Pendientes |

### Button contract

| Action | Text EN | Text RU | Text ES | Callback |
|--------|---------|---------|---------|----------|
| Snooze 10m | ⏰ +10 min | ⏰ +10 мин | ⏰ +10 min | `sched:snooze:{redis_key}` |
| Run now | ▶️ Run now | ▶️ Запустить | ▶️ Ejecutar | `sched:run:{action_id}` |
| Pause | ⏸ Pause | ⏸ Пауза | ⏸ Pausar | `sched:pause:{action_id}` |
| Resume | ▶️ Resume | ▶️ Возобновить | ▶️ Reanudar | `sched:resume:{action_id}` |
| Delete | 🗑 Delete | 🗑 Удалить | 🗑 Eliminar | `sched:del:{action_id}` |

### Visual indicators

| Indicator | Symbol | Usage |
|-----------|--------|-------|
| Urgent | 🔥 | Overdue tasks, late payments |
| Warning | 🟡 | Approaching deadline, budget 80%+ |
| Critical | 🔴 | Overdue payments, exceeded budget |
| Positive | 📈 | Growth, under budget |
| Negative | 📉 | Overspending trend |
| Priority bar | █░░░░ | Visual budget/progress fill |

### Confirmation message (on schedule creation)

```
EN: ✅ Scheduled — {schedule_description}.
    Sources: {source_list}.
    Next run: {next_run_at_local}.

RU: ✅ Запланировано — {schedule_description}.
    Источники: {source_list}.
    Следующий запуск: {next_run_at_local}.

ES: ✅ Programado — {schedule_description}.
    Fuentes: {source_list}.
    Próxima ejecución: {next_run_at_local}.
```

### List view (list_scheduled_actions)

```
📋 <b>{header}</b>

1. {status_icon} <b>{title}</b>
   {schedule_description} · {next_run_label}: {next_run_time}

2. {status_icon} <b>{title}</b>
   {schedule_description} · {next_run_label}: {next_run_time}

{empty_state_message_if_none}

Status icons: ▶️ active, ⏸ paused, ✅ completed
```

### Trust footer (P2)

```
<i>📡 {sources_ok}/{sources_total} sources · Data as of {freshness_time}</i>
```

---

## 7. Internationalization (i18n)

### Supported languages (P0)

1. English (en) — primary.
2. Russian (ru) — primary.
3. Spanish (es) — secondary.

### Language resolution

1. Use `context.language` from SessionContext (already resolved per request).
2. Background tasks: use `scheduled_actions.language` field (stored at creation time).
3. Fallback chain: user preferred → user language → `en`.

### Implementation approach

1. **Static strings** (confirmations, buttons, headers): Python dict `_STRINGS[lang][key]`.
2. **LLM synthesis**: pass `language` in system prompt — `"Respond in: {language}"`.
3. **Template mode**: Jinja2 templates with i18n string injection.
4. **Date/time formatting**: locale-aware via `babel` or manual format strings.

### String table structure

```python
_STRINGS = {
    "en": {
        "greeting_morning": "Good morning",
        "greeting_afternoon": "Good afternoon",
        "greeting_evening": "Good evening",
        "section_calendar": "Today",
        "section_tasks": "Tasks",
        "section_money": "Money",
        "section_email": "Email",
        "section_outstanding": "Outstanding",
        "btn_snooze": "⏰ +10 min",
        "btn_run_now": "▶️ Run now",
        "btn_pause": "⏸ Pause",
        "btn_resume": "▶️ Resume",
        "btn_delete": "🗑 Delete",
        "scheduled_confirm": "Scheduled — {desc}.\nSources: {sources}.\nNext run: {next_run}.",
        "list_header": "Your scheduled actions",
        "list_empty": "No scheduled actions yet. Say something like:\n<i>\"Every morning at 8 send me calendar and tasks\"</i>",
        "action_paused": "Paused — {title}.",
        "action_resumed": "Resumed — {title}. Next run: {next_run}.",
        "action_deleted": "Deleted — {title}.",
        "action_snoozed": "Snoozed — will run in {minutes} min.",
    },
    "ru": {
        "greeting_morning": "Доброе утро",
        "greeting_afternoon": "Добрый день",
        "greeting_evening": "Добрый вечер",
        "section_calendar": "Сегодня",
        "section_tasks": "Задачи",
        "section_money": "Финансы",
        "section_email": "Почта",
        "section_outstanding": "Неоплаченные",
        "btn_snooze": "⏰ +10 мин",
        "btn_run_now": "▶️ Запустить",
        "btn_pause": "⏸ Пауза",
        "btn_resume": "▶️ Возобновить",
        "btn_delete": "🗑 Удалить",
        "scheduled_confirm": "Запланировано — {desc}.\nИсточники: {sources}.\nСледующий запуск: {next_run}.",
        "list_header": "Ваши запланированные действия",
        "list_empty": "Нет запланированных действий. Попробуйте:\n<i>\"Каждое утро в 8 отправляй календарь и задачи\"</i>",
        "action_paused": "Приостановлено — {title}.",
        "action_resumed": "Возобновлено — {title}. Следующий запуск: {next_run}.",
        "action_deleted": "Удалено — {title}.",
        "action_snoozed": "Отложено — запущу через {minutes} мин.",
    },
    "es": {
        "greeting_morning": "Buenos días",
        "greeting_afternoon": "Buenas tardes",
        "greeting_evening": "Buenas noches",
        "section_calendar": "Hoy",
        "section_tasks": "Tareas",
        "section_money": "Finanzas",
        "section_email": "Correo",
        "section_outstanding": "Pendientes",
        "btn_snooze": "⏰ +10 min",
        "btn_run_now": "▶️ Ejecutar",
        "btn_pause": "⏸ Pausar",
        "btn_resume": "▶️ Reanudar",
        "btn_delete": "🗑 Eliminar",
        "scheduled_confirm": "Programado — {desc}.\nFuentes: {sources}.\nPróxima ejecución: {next_run}.",
        "list_header": "Tus acciones programadas",
        "list_empty": "No hay acciones programadas. Prueba:\n<i>\"Cada mañana a las 8 envíame calendario y tareas\"</i>",
        "action_paused": "Pausado — {title}.",
        "action_resumed": "Reanudado — {title}. Próxima ejecución: {next_run}.",
        "action_deleted": "Eliminado — {title}.",
        "action_snoozed": "Pospuesto — se ejecutará en {minutes} min.",
    },
}
```

---

## 8. Proactivity/Dispatch Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| `next_run_at <= now` | Execute scheduled action pipeline | every minute scan | Telegram |
| Callback `snooze` | Shift `next_run_at` by N minutes | on demand | Telegram |
| Callback `pause/resume` | Update status | on demand | Telegram |
| Callback `run_now` | Immediate one-off run | on demand | Telegram |
| Callback `delete` | Mark action deleted | on demand | Telegram |

### Guardrails

1. Per-user cap for proactive sends/day (default: 20).
2. Honor communication mode (`silent` → skip, `receipt` → compact, `coaching` → decision_ready).
3. Honor quiet hours via `is_send_window()`.
4. Degraded-mode message when some sources fail — show partial data + trust footer.
5. Retry with exponential backoff before marking run failed.

---

## 9. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Duplicate sends under multi-worker race | Medium | High | `FOR UPDATE SKIP LOCKED`, idempotency key `(action_id, planned_run_at)` |
| LLM cost spikes | Medium | Medium | fast template mode first, synthesis fallback chain, max token caps, separate `ff_sia_synthesis` flag |
| Source outages (calendar/email) | High | Medium | partial-data rendering + source status footer |
| User notification fatigue | Medium | High | caps, quiet hours, easy pause/snooze, comm_mode integration |
| Schedule parsing ambiguity | Medium | Medium | clarify loop + explicit confirmation text |
| DST transitions break schedule | Medium | Medium | wall-clock preservation via `original_time` field, DST-safe `next_run_at` computation |
| i18n inconsistency | Low | Medium | string tables for static text, `language` in LLM prompt for synthesis |

---

## 10. Timeline

| Phase | Scope | Duration |
|-------|-------|----------|
| Phase 1 | schema + dispatcher + create/list/manage skills + i18n strings | 2.0 weeks |
| Phase 2 | collectors + formatter + callbacks + message design | 1.5 weeks |
| Phase 3 | parity features (`weekdays`, `cron`, end conditions, NL edit) | 1.0 week |
| Phase 4 | differentiators + hardening + rollout | 1.0 week |
| **Total** | | **5.5 weeks** |

---

## 11. Release Criteria

1. `ruff check` and full test suite pass.
2. No duplicate send in load test scenario.
3. P0 user stories validated by QA checklist.
4. Feature flags allow progressive rollout (5%, 25%, 100%).
5. Messages render correctly in EN, RU, ES.
6. Button callbacks work for all actions (snooze/pause/resume/run/delete).
7. DST transition test passes for major timezones.
