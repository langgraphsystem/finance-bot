# Phase 7 — Intelligence & Export

**Author:** Claude Code
**Date:** 2026-02-23
**Status:** Draft
**Star Rating:** 6★ → 7★ (Cross-domain intelligence, proactive insights, data portability)
**RICE Score:** See individual module scores below

---

## 1. Problem Statement

### What problem are we solving?

The bot has 67 skills across 11 agents, but each skill operates in relative isolation. Intent detection relies on static rules without learning from user patterns. 51 of 67 skill prompts are hardcoded strings — making prompt iteration slow and error-prone. Users generate valuable data (expenses, life events, tasks) but have no way to export it in professional formats. The weekly cadence has no touchpoint between morning/evening briefs.

These gaps keep the product at 6★ (proactive but domain-siloed) instead of 7★ (cross-domain intelligence with data portability).

### The Maria Test

> Maria tracks groceries, school events, and expenses daily. She wants to share a spending summary with her husband but the bot only shows text in chat — she can't attach it to an email or print it. At tax time she needs a proper spreadsheet, not chat screenshots. She also notices the bot asks the same clarifying questions repeatedly — it never learned that "school" means Emma's PS 321.

### The David Test

> David texts the bot 20+ times daily for expenses, scheduling, and client follow-ups. His accountant asks for a monthly expense report in Excel — David has to manually re-type everything. The bot still misclassifies "supply run" as personal despite David correcting it 15 times. He'd pay more if the bot gave a smart weekly summary connecting his revenue trends to upcoming jobs.

### Who else has this problem?

Every active user (100% Reach) benefits from smarter intent detection. 70%+ of business users need exportable reports. Weekly digests serve 90%+ of daily-active users who want a consolidated view without asking.

---

## 2. Solution Overview

### What are we building?

Four capabilities that elevate the product from reactive tool to intelligent assistant with data portability:

1. **Hybrid Semantic Search** — BM25 + pgvector Reciprocal Rank Fusion for context retrieval
2. **Dynamic Few-shot Examples** — pgvector bank of successful intent classifications that auto-tunes per user
3. **YAML Prompt Migration** — Externalize remaining 51 hardcoded prompts to versioned YAML files
4. **Weekly Digest** — Automated cross-domain summary (finance + tasks + life + calendar) via Telegram/email
5. **Excel Export** — Download spending reports, task lists, and contact lists as `.xlsx`
6. **Google Sheets Sync** — Live spreadsheet sync for families and accountants

### Conversation Example

**Maria's scenario:**
```
[Sunday 9:00 AM — proactive weekly digest]
Bot: Your week in review:
• Spent $487 (groceries $180, dining $95, transport $62) — 12% under budget
• Completed 8/11 tasks — 3 carried over to this week
• Emma has a dentist appointment Tuesday, Noah's soccer Wednesday
• You tracked 5 meals and 3 workouts — nice consistency

Anything you want to adjust for this week?

Maria: send this to alex as a spreadsheet
Bot: Sent Alex a spending summary for Feb 17-23 as an Excel file. Includes transaction breakdown by category.
```

**David's scenario:**
```
David: export this month's expenses for my accountant
Bot: Here's February expenses as Excel — 47 transactions, $12,340 total. Categorized by job, supplies, and overhead. I included the receipt photos as links.

[Sends .xlsx file with formatted sheets: Summary, By Category, By Job, Timeline]

David: also set up a live sheet my accountant can check anytime
Bot: Done — created a Google Sheet syncing your expenses hourly. Shared with accounting@davidplumbing.com (read-only). They'll always see the latest data.
```

### What are we NOT building?

- PDF report generation (separate PRD, requires WeasyPrint template design)
- Real-time collaborative editing of shared sheets (read-only sync only)
- Custom report builder UI (conversation-only — user describes what they want)
- Automated tax filing (we export data, accountant files taxes)
- Bank account sync via Plaid (separate Phase, different risk profile)

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | receive a weekly digest on Sunday morning | I see my week's patterns without asking |
| 2 | Business user | export my expenses as an Excel file | I can share with my accountant |
| 3 | User | have the bot learn from my corrections | it stops misclassifying the same merchants |
| 4 | Developer | edit skill prompts in YAML without code changes | I can iterate prompts faster and A/B test |

### P1 — Should Have (expected within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | get smarter context retrieval from my history | the bot remembers relevant past conversations |
| 2 | Family member | have a shared Google Sheet with our expenses | my spouse sees spending in real time |
| 3 | User | customize my weekly digest (what to include, what day) | I get the summary I actually want |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | see how intent detection accuracy improves over time | I trust the bot is learning |
| 2 | Business user | auto-send weekly reports to my accountant on a schedule | I never have to remember to export |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | CSV export | Excel covers this — `.xlsx` can be opened as CSV by any tool |
| 2 | Custom chart generation in exports | Adds complexity. Accountants want raw data, not our charts |
| 3 | Multi-user edit on shared sheets | Google Sheets handles collaboration natively — we just sync data |
| 4 | Bank reconciliation | Requires Plaid integration — separate phase with different risk profile |

---

## 4. Success Metrics

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % users who open weekly digest within 2h | > 50% | Track message read receipt / reply rate |
| **Usage** | Excel exports per week across all users | > 100 | `usage_logs` table, intent=`export_excel` |
| **Usage** | Google Sheets sync active accounts | > 20% of business users | `oauth_tokens` with sheets scope |
| **Retention** | Users who receive digest AND interact same day | > 40% | Cohort analysis: digest sent → message within 24h |
| **Quality** | Intent detection accuracy (post few-shot) | > 92% (from ~85%) | Langfuse evaluation traces |
| **Business** | Churn reduction for users with exports enabled | -15% vs control | Subscription analytics |

### Leading Indicators (check at 48 hours)

- [ ] 60%+ of weekly digests generate a reply (engagement)
- [ ] Zero errors in first 50 Excel exports (reliability)
- [ ] Few-shot bank has 100+ examples seeded from production data

### Failure Signals (trigger re-evaluation)

- [ ] Weekly digest reply rate < 20% (users ignoring it — too noisy or irrelevant)
- [ ] Excel export errors > 5% (formatting issues, missing data)
- [ ] Intent accuracy doesn't improve after 2 weeks of few-shot learning

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Orchestrator** | None new — weekly digest reuses BriefOrchestrator pattern with extended collectors |
| **Skills** | `weekly_digest` (new), `export_excel` (new), `sheets_sync` (new) |
| **APIs** | Google Sheets API v4 (via aiogoogle OAuth), openpyxl for Excel generation |
| **Models** | Claude Sonnet 4.6 for digest synthesis, Claude Haiku 4.5 for export formatting |
| **Database** | `few_shot_examples` table (new), `export_jobs` table (new), `sheet_sync_configs` table (new) |
| **Background Jobs** | `weekly_digest_task` (cron: Sunday 9am user timezone), `sheets_sync_task` (cron: hourly) |

### Data Model

```sql
-- Few-shot example bank for intent detection
CREATE TABLE IF NOT EXISTS few_shot_examples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    user_message TEXT NOT NULL,
    detected_intent VARCHAR(64) NOT NULL,
    corrected_intent VARCHAR(64),
    intent_data JSONB,
    embedding vector(768),
    usage_count INTEGER DEFAULT 0,
    accuracy_score FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Export job tracking
CREATE TABLE IF NOT EXISTS export_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    user_id UUID NOT NULL REFERENCES users(id),
    export_type VARCHAR(32) NOT NULL, -- 'excel', 'sheets_sync'
    parameters JSONB NOT NULL, -- date range, categories, format options
    status VARCHAR(16) DEFAULT 'pending', -- pending, processing, completed, failed
    file_url TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- Google Sheets sync configuration
CREATE TABLE IF NOT EXISTS sheet_sync_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    spreadsheet_id VARCHAR(128) NOT NULL,
    sheet_name VARCHAR(64) DEFAULT 'Expenses',
    sync_scope VARCHAR(32) DEFAULT 'expenses', -- expenses, tasks, contacts, all
    shared_emails TEXT[], -- emails with read access
    last_synced_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- pgvector index for semantic search
CREATE INDEX IF NOT EXISTS idx_few_shot_embedding ON few_shot_examples
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

### Hybrid Search Algorithm

```
1. User sends message
2. BM25 search over conversation history (PostgreSQL ts_vector) → top 20
3. pgvector cosine similarity over embeddings → top 20
4. Reciprocal Rank Fusion: score = Σ 1/(k + rank_i) for each retriever
5. Return top 5 by RRF score
6. Inject into context assembly at mem0 layer position
```

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| User has < 7 days of data for weekly digest | Send digest with available data + note: "This is your first partial week — next Sunday's will be more complete." |
| Excel export exceeds 10K rows | Split into multiple sheets by month. Warn user: "Large export — I split it by month for readability." |
| Google Sheets API rate limit hit | Queue sync and retry in 5 minutes. User notified only if sync is >1h delayed. |
| No Google OAuth token for Sheets | Prompt: "To sync with Google Sheets, I need access to your Google account. Here's the link to connect." |
| Few-shot bank has no examples for a new intent | Fall back to zero-shot (current behavior). Log for manual review. |
| User says "stop sending weekly digests" | Immediately disable. "Got it — no more weekly digests. Say 'resume weekly digest' anytime." |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users |
|-----------|---------------------|---------------------|
| Weekly digest LLM (Sonnet) | $0.015 per digest | $60 (4 digests × 1K) |
| Excel generation (openpyxl) | $0 (local CPU) | $0 |
| Sheets API calls | $0 (free tier covers 300 requests/min) | $0 |
| pgvector queries | ~$0.001 per query | $30 (30K queries) |
| Few-shot embedding generation | $0.002 per correction | $10 |
| **Total** | | **~$100/month @ 1K users ($0.10/user)** |

Within $3-8/month per user budget.

---

## 6. Proactivity Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| Sunday morning (user timezone) | Send weekly digest | 1x/week | Primary channel (Telegram/Slack/WhatsApp) |
| User corrects intent 3+ times for same pattern | Add to few-shot bank automatically | On correction | Background (no message) |
| Google Sheet hasn't synced in 24h | Alert user about sync failure | 1x per failure | Primary channel |
| Export requested but no data in range | Suggest alternative date range | On request | Reply in conversation |

### Rules

- Weekly digest: max 1x/week. User can change day/time or disable entirely.
- Few-shot learning: fully silent. No user notification. Visible only if user asks "what have you learned about me?"
- Export notifications: only on failure. Successful exports are silent confirmation in chat.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Few-shot examples degrade accuracy (bad corrections) | Medium | High | Minimum 3 consistent corrections before adding. Accuracy tracking per example. Auto-prune examples with <0.5 accuracy after 30 days. |
| Weekly digest feels generic/noisy | Medium | Medium | Personalize based on user's most-used domains. Skip empty sections. A/B test formats. |
| openpyxl memory usage on large exports | Low | Medium | Stream writes, limit to 50K rows per file. Background task with timeout. |
| Google Sheets API auth complexity | Medium | Low | Reuse existing OAuth flow from calendar/email. Same `require_google_or_prompt` helper. |
| YAML prompt migration breaks existing behavior | Medium | High | Side-by-side test: load YAML, compare output with hardcoded. Keep hardcoded as fallback for 2 weeks. CI validates all YAML at startup. |

### Dependencies

- [x] openpyxl package (add to pyproject.toml)
- [x] Google Sheets API scope addition to OAuth flow
- [x] pgvector extension (already active on Supabase)
- [ ] BM25 implementation (PostgreSQL ts_vector — built-in, needs index)

---

## 8. Timeline

| Phase | Scope | Milestone |
|-------|-------|-----------|
| 7a | YAML prompt migration for all 51 remaining skills | All prompts in YAML, CI validates |
| 7b | Hybrid semantic search (BM25 + pgvector RRF) | Context retrieval uses hybrid search |
| 7c | Dynamic few-shot examples for intent detection | Few-shot bank seeded, accuracy tracked |
| 7d | Weekly digest skill + Taskiq cron | Users receive Sunday digests |
| 7e | Excel export skill (openpyxl) | Users download .xlsx files |
| 7f | Google Sheets sync skill + cron | Live spreadsheet sync active |

---

# Review Rubric — Self-Score

| Criterion | Weight | Score (1-5) | Weighted |
|-----------|--------|-------------|----------|
| Problem Clarity | 2.0x | 5 | 10.0 |
| User Stories | 1.5x | 4 | 6.0 |
| Success Metrics | 1.5x | 5 | 7.5 |
| Scope Definition | 1.0x | 5 | 5.0 |
| Technical Feasibility | 1.0x | 4 | 4.0 |
| Risk Assessment | 1.0x | 4 | 4.0 |
| **Total** | **8.0x** | | **36.5/40** |

**Normalized: (36.5 / 40) × 30 = 27.4/30** — Ready to build.

## Auto-Check Checklist

- [x] Both Maria and David appear in the Problem Statement with specific, believable scenarios
- [x] Conversation examples use natural language (not formal commands)
- [x] "Not building" list has at least 3 items (4 items)
- [x] Every P0 user story maps to a conversation example
- [x] Success metrics include at least one failure signal (3 defined)
- [x] Cost estimate is within $3-8/month per user ($0.10/user)
- [x] Star rating is stated and justified (6★ → 7★)
- [x] RICE score referenced (see PRIORITIZATION.md update)
- [x] Proactivity section defines frequency limits
- [x] Edge cases include "no history" cold-start scenario
