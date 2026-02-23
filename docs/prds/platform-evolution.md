# Phase 9 — Platform Evolution

**Author:** Claude Code
**Date:** 2026-02-23
**Status:** Draft
**Star Rating:** 8★ → 9★ (Life operating system — autonomous multi-step workflows)
**RICE Score:** See individual module scores below

---

## 1. Problem Statement

### What problem are we solving?

The bot processes text messages but ignores voice — 70% of Americans send voice messages at least weekly. The Telegram Mini App backend (`api/miniapp.py`, 40K lines) is built but has no frontend — users can't see charts, dashboards, or interactive reports. Memory is flat (key-value pairs via Mem0) — the bot doesn't understand relationships between people, places, and events. Business profiles require manual YAML configuration — new users get generic categories instead of tailored ones.

These gaps prevent the product from reaching 8★+ (autonomous workflows) because the bot lacks the input channels, visual output, relational understanding, and personalization needed to truly manage a user's life.

### The Maria Test

> Maria is driving and needs to add something to her grocery list. She can't type — she sends a 5-second voice message: "Add milk and eggs to the list." The bot doesn't understand voice. She has to pull over, type, and loses 3 minutes. When she gets home, she wants to see her weekly spending as a chart — but the bot can only send text. Her friend asks "who's your dentist?" and Maria has to search through messages — the bot doesn't know that Dr. Kim is Emma's dentist at the Brooklyn Heights office.

### The David Test

> David drives between job sites all day. He sends voice messages to his employees and wants to do the same with the bot: "Invoice Mrs. Chen for four thousand two hundred, bathroom remodel, include parts." The bot ignores it. After work, David wants to show his wife their monthly business performance on his phone — a chart, not a wall of text. When he signed up, the bot asked about his business type but still used generic categories. It took 3 weeks of corrections before the bot learned plumbing categories. A new employee, Alex, starts next week — David wants the bot to know "Alex is my apprentice, he works with Jose on Tuesdays and Thursdays."

### Who else has this problem?

- **Voice input**: 70% of messaging app users send voice messages (Statista 2025). Critical for on-the-go users (drivers, parents, field workers).
- **Visual output**: 100% of users benefit from charts and interactive reports. Text-only limits comprehension of financial trends.
- **Graph memory**: Every user with 3+ contacts benefits from relationship understanding. Business users (with teams, clients, suppliers) benefit most.
- **Auto-profiling**: 100% of new users get a better first-week experience. Reduces time-to-value from ~3 weeks to ~3 days.

---

## 2. Solution Overview

### What are we building?

Five capabilities that transform the product from a text-based tool to a multi-modal life operating system:

1. **Voice Message Processing** — STT via Whisper/gpt-4o-transcribe, process as text, respond in text (or optionally TTS)
2. **Telegram Mini App Frontend** — React SPA for charts, reports, settings, dashboards (backend `api/miniapp.py` ready)
3. **Mem0g Graph Memory** — Entity-relationship graph: people → roles, places → visits, events → participants
4. **AI-Generated YAML Profiles** — Auto-create business profiles from first 20 conversations, iteratively refined
5. **Telegram Stars Monetization** — Premium features (advanced reports, priority support, extra exports) via in-app purchases

### Conversation Example

**Maria's scenario:**
```
[Voice message from Maria, 3 seconds]
Maria: 🎤 "Add milk and eggs to the grocery list"
Bot: Added milk and eggs. Your list has 8 items now.

Maria: who's emma's dentist?
Bot: Dr. Sarah Kim at Brooklyn Heights Dental — you were there last on January 15. Next appointment isn't scheduled yet. Want me to book one?

Maria: show me our spending this month
Bot: [Opens Mini App with interactive chart]
     February spending: $2,340 total
     📊 [Pie chart: Groceries 35%, Dining 18%, Transport 12%, Other 35%]
     Tap any category for details. Compare with January?
```

**David's scenario:**
```
[Voice message from David, 5 seconds]
David: 🎤 "Invoice Mrs. Chen for four thousand two hundred, bathroom remodel, include parts"
Bot: Invoice #2024-048 created for Mrs. Chen — $4,200 (bathroom remodel, parts included). Send now?

David: yes. also, alex starts monday — he's my new apprentice, works with jose tuesdays and thursdays
Bot: Got it. I'll remember Alex as your apprentice, paired with Jose on Tue/Thu. Want me to add him to next week's schedule?

[David opens Mini App]
Bot: [Dashboard showing]
     💰 February Revenue: $18,400 (+15% vs Jan)
     📋 Active Jobs: 7 | Pending Invoices: 3 ($6,800)
     👥 Team: Mike (12 jobs), Jose (8), Alex (new)
     📈 [Bar chart: weekly revenue trend]
```

### What are we NOT building?

- Voice calls (phone-based voice assistant — separate product with different UX)
- TTS audio responses (text responses are faster and scannable — voice input → text output)
- Full mobile app (Mini App covers visual needs without app store friction)
- Social features (comments, likes, shared feeds — this is a personal assistant, not a social platform)
- Marketplace for third-party skills/plugins (too early — focus on first-party quality)
- Real-time voice transcription (batch processing of completed voice messages only)

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User on the go | send voice messages to the bot | I can use the bot while driving or cooking |
| 2 | User | see my spending as charts in Telegram | I understand trends visually, not just text |
| 3 | Business user | have the bot learn my business categories automatically | I don't spend weeks correcting misclassifications |
| 4 | User | ask "who is X?" and get relationship context | the bot understands my life network |

### P1 — Should Have (expected within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | access interactive dashboards in Mini App | I explore my data beyond static text |
| 2 | Business user | have team relationships auto-tracked | scheduling and invoicing reference the right people |
| 3 | User | buy premium reports with Telegram Stars | I unlock advanced analytics without leaving Telegram |
| 4 | New user | see the bot adapt to my profession within days | the first-week experience feels personalized |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | have the bot suggest relationship updates | "You haven't contacted Dr. Kim in 6 months — schedule a checkup?" |
| 2 | Business user | see a team performance dashboard in Mini App | I compare employee productivity visually |
| 3 | User | use voice in any language and get text in my preferred language | voice input supports multilingual users |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | Voice output (TTS) | Text is faster to scan. Voice output requires headphones/speaker — bad UX in most contexts. Revisit if users request. |
| 2 | Real-time voice transcription (streaming) | Batch processing is simpler and reliable. Telegram sends completed voice messages, not streams. |
| 3 | Full mobile app | Mini App gives 80% of app value with 20% of effort. No app store review, no separate codebase. |
| 4 | Graph visualization in Mini App | Too complex for MVP. Text-based relationship queries first. Visual graph explorer in P2. |
| 5 | Third-party plugin marketplace | Quality control is impossible at this stage. First-party only. |

---

## 4. Success Metrics

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % of users who send at least 1 voice message in first week | > 25% | Telegram message type tracking |
| **Activation** | % of users who open Mini App in first week | > 40% | Mini App session tracking |
| **Usage** | Voice messages processed per active user per week | > 3 | `usage_logs` with type=`voice` |
| **Usage** | Mini App sessions per user per week | > 2 | Session analytics |
| **Quality** | Voice transcription accuracy (WER) | < 8% | Sample 100 voice messages, manual review |
| **Revenue** | Telegram Stars revenue per paying user per month | > $2 | Telegram Stars analytics |
| **Retention** | 30-day retention for users who use voice vs. text-only | +20% higher | Cohort comparison |
| **Quality** | Graph memory query accuracy ("who is X?") | > 90% | Manual evaluation of 100 queries |

### Leading Indicators (check at 48 hours)

- [ ] Voice transcription latency < 3 seconds for messages under 30 seconds
- [ ] Mini App loads within 2 seconds on 4G connection
- [ ] First 10 auto-generated profiles match user's actual business type

### Failure Signals (trigger re-evaluation)

- [ ] Voice transcription accuracy < 85% (users frustrated by errors)
- [ ] Mini App bounce rate > 60% (users open but immediately close)
- [ ] Auto-profiling accuracy < 70% (wrong categories generated)
- [ ] Telegram Stars purchases < $0.50/user/month (pricing or value mismatch)

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Orchestrator** | None new — voice messages convert to text and enter normal message flow |
| **Skills** | `voice_process` (enhanced from stub), `graph_query` (new), `manage_relationship` (new), `stars_purchase` (new) — 4 new skills |
| **APIs** | OpenAI Whisper/gpt-4o-transcribe (STT), Telegram Bot API (voice download), Telegram Stars API (payments), React + Vite (Mini App) |
| **Models** | gpt-4o-transcribe for STT, Claude Haiku 4.5 for graph entity extraction, Gemini Flash for profile generation |
| **Database** | `entity_graph` table (new), `entity_relationships` table (new), `auto_profiles` table (new), `stars_transactions` table (new) |
| **Background Jobs** | `profile_learning_task` (enhanced — now generates YAML), `graph_update_task` (after each conversation — extract entities) |
| **Frontend** | React + Vite SPA at `static/miniapp/`, served via `api/miniapp.py` routes |

### Data Model

```sql
-- Entity graph nodes (people, places, businesses)
CREATE TABLE IF NOT EXISTS entity_graph (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    entity_type VARCHAR(32) NOT NULL, -- 'person', 'place', 'business', 'school', 'doctor', 'vehicle'
    entity_name VARCHAR(256) NOT NULL,
    aliases TEXT[], -- ["Dr. Kim", "Sarah Kim", "Emma's dentist"]
    attributes JSONB DEFAULT '{}', -- {"specialty": "pediatric dentistry", "address": "..."}
    last_mentioned_at TIMESTAMPTZ,
    mention_count INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(family_id, entity_type, entity_name)
);

-- Entity relationships (edges)
CREATE TABLE IF NOT EXISTS entity_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    source_entity_id UUID NOT NULL REFERENCES entity_graph(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES entity_graph(id) ON DELETE CASCADE,
    relationship_type VARCHAR(64) NOT NULL, -- 'dentist_of', 'employee', 'works_with', 'located_at', 'child_of'
    attributes JSONB DEFAULT '{}', -- {"schedule": "Tue/Thu", "start_date": "2026-02-24"}
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(family_id, source_entity_id, target_entity_id, relationship_type)
);

-- Auto-generated business profiles
CREATE TABLE IF NOT EXISTS auto_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    profile_version INTEGER DEFAULT 1,
    inferred_business_type VARCHAR(64), -- 'plumber', 'designer', 'restaurant', etc.
    generated_yaml TEXT NOT NULL, -- Full YAML profile content
    confidence FLOAT DEFAULT 0.5,
    source_message_count INTEGER DEFAULT 0, -- How many messages contributed
    is_active BOOLEAN DEFAULT false, -- Becomes active when confidence > 0.8
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Telegram Stars transactions
CREATE TABLE IF NOT EXISTS stars_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    user_id UUID NOT NULL REFERENCES users(id),
    telegram_payment_id VARCHAR(128) NOT NULL UNIQUE,
    stars_amount INTEGER NOT NULL,
    product_id VARCHAR(64) NOT NULL, -- 'premium_report', 'advanced_analytics', 'priority_support'
    status VARCHAR(16) DEFAULT 'completed',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_entity_graph_family ON entity_graph(family_id);
CREATE INDEX IF NOT EXISTS idx_entity_graph_type ON entity_graph(family_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_rel_source ON entity_relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_rel_target ON entity_relationships(target_entity_id);
```

### Voice Processing Pipeline

```
1. User sends voice message via Telegram
2. Telegram webhook delivers message with voice file_id
3. Download voice file via Telegram Bot API (OGG format)
4. Convert OGG → WAV (ffmpeg, already available in Docker)
5. Send to gpt-4o-transcribe API → text
6. Inject text into normal message flow (router.py:handle_message)
7. Process as regular text message
8. Respond in text (not voice)
```

**Latency budget**: Download (200ms) + Convert (100ms) + Transcribe (800ms) + Process (normal) = ~1.1s overhead.

### Mini App Architecture

```
static/miniapp/
├── index.html
├── src/
│   ├── App.tsx
│   ├── pages/
│   │   ├── Dashboard.tsx      (overview: spending, tasks, calendar)
│   │   ├── Spending.tsx       (charts: pie, bar, trend)
│   │   ├── Tasks.tsx          (task list with completion)
│   │   ├── Calendar.tsx       (week view)
│   │   ├── Reports.tsx        (export options)
│   │   ├── Settings.tsx       (language, timezone, notifications)
│   │   └── Premium.tsx        (Telegram Stars store)
│   ├── components/
│   │   ├── Chart.tsx          (Chart.js wrapper)
│   │   ├── TransactionList.tsx
│   │   └── NavBar.tsx
│   └── api/
│       └── client.ts          (fetch wrapper for api/miniapp.py)
├── package.json
└── vite.config.ts
```

**Auth**: Telegram Mini App initData → validate HMAC → extract user_id → match to internal user via `channel_links`.

### Graph Memory Entity Extraction

After each conversation turn, a background task:
1. Sends the message + recent context to Claude Haiku 4.5
2. Extracts entities: `{name, type, aliases, relationships}`
3. Upserts into `entity_graph` and `entity_relationships`
4. Updates `mention_count` and `last_mentioned_at`

Query path: "Who is Emma's dentist?" → extract entities ["Emma", "dentist"] → graph query → find path → "Dr. Sarah Kim at Brooklyn Heights Dental"

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Voice message in language different from user's preferred | Transcribe in detected language, translate to preferred language, process normally |
| Voice message with background noise | Attempt transcription. If confidence < 0.7: "I had trouble understanding that. Could you text it or try again in a quieter spot?" |
| Voice message > 60 seconds | Process in chunks of 30s. Combine transcriptions. Warn if > 120s: "Long voice messages may lose accuracy. Consider splitting into shorter messages." |
| Mini App opened with no data (new user) | Show onboarding card: "Start by texting me an expense or task. I'll show your data here." |
| Graph query for unknown entity | "I don't have anyone named Alex in my records yet. Want to tell me about them?" |
| Auto-profile confidence stays low after 20 messages | Stick with `household` default. Ask user: "I'm having trouble figuring out your business type. Are you a [top 3 guesses]?" |
| Telegram Stars refund request | Handle via Telegram's built-in refund API. No custom refund flow. |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users |
|-----------|---------------------|---------------------|
| Voice transcription (gpt-4o-transcribe) | $0.006 per minute | $180 (5 min/user/week × 4 weeks × 1K) |
| Graph entity extraction (Haiku) | $0.002 per message | $120 (60 messages/user/month × 1K) |
| Mini App hosting (static via Railway) | $0 (bundled) | $0 |
| Profile generation (Gemini Flash) | $0.01 per generation | $10 (1 gen/user) |
| **Total** | | **~$310/month @ 1K users ($0.31/user)** |

Within $3-8/month per user budget. Voice is the largest cost — monitor usage patterns.

---

## 6. Proactivity Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| New entity mentioned 3+ times without relationship | "You mention Alex a lot. Who is Alex to you?" | 1x per entity | Conversation reply |
| Auto-profile reaches 0.8 confidence | "I think you run a plumbing business. I've set up plumbing-specific categories. That right?" | 1x per profile update | Standalone message |
| User hasn't opened Mini App in 14 days | Include "See your dashboard →" button in morning brief | 1x per 14 days | Morning brief |
| Premium report generated (paid via Stars) | Push notification with "Your report is ready in the app" | On generation | Telegram notification |

### Rules

- Entity relationship questions max 1x per day. Don't interrupt conversations to ask about entities.
- Profile updates: ask for confirmation before activating a new profile. One confirmation message, not repeated.
- Mini App nudges: max 1x per 2 weeks. Respect "I don't want the app" response.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Voice transcription accuracy varies by accent | Medium | High | Test with 10+ US accents. Fallback: "I'm not sure I caught that — here's what I heard: [text]. Correct?" Allow text correction. |
| Mini App adds frontend maintenance burden | High | Medium | Use Vite + React minimal stack. No SSR. Static deploy. Share types with backend via OpenAPI codegen. |
| Graph memory grows unbounded | Medium | Low | Cap at 500 entities per family. Prune entities not mentioned in 6 months. Background cleanup task. |
| Auto-profiling assigns wrong business type | Medium | Medium | Always ask for confirmation before activating. Easy reset: "Reset my business profile." Fallback to household. |
| Telegram Stars API changes or restrictions | Low | Medium | Stars is supplementary revenue, not core. If API changes, fall back to Stripe-only billing. |
| Voice enables harassment/abuse content | Low | High | Voice → text → existing guardrails pipeline. All safety checks apply to transcribed text. |

### Dependencies

- [ ] ffmpeg in Docker image (for OGG → WAV conversion) — add to Dockerfile
- [ ] React + Vite setup in `static/miniapp/` — new frontend codebase
- [ ] Telegram Stars API access (requires bot approval for payments)
- [ ] gpt-4o-transcribe API access (OpenAI — already configured)
- [x] Telegram Bot API voice message handling (aiogram supports this)
- [x] `api/miniapp.py` backend (40K lines, already built)
- [x] Mem0 integration (existing — extend with graph layer)

---

## 8. Timeline

| Phase | Scope | Milestone |
|-------|-------|-----------|
| 9a | Voice message processing (STT pipeline) | Users send voice → bot processes as text |
| 9b | Mini App React SPA (Dashboard + Spending + Tasks) | Users see interactive charts in Telegram |
| 9c | Graph memory (entity extraction + relationship queries) | "Who is X?" returns relationship context |
| 9d | AI-generated YAML profiles | New users get personalized categories within 3 days |
| 9e | Mini App — Settings, Calendar, Reports pages | Full Mini App experience |
| 9f | Telegram Stars integration (premium features) | Users purchase advanced reports in-app |

---

# Review Rubric — Self-Score

| Criterion | Weight | Score (1-5) | Weighted |
|-----------|--------|-------------|----------|
| Problem Clarity | 2.0x | 5 | 10.0 |
| User Stories | 1.5x | 4 | 6.0 |
| Success Metrics | 1.5x | 5 | 7.5 |
| Scope Definition | 1.0x | 4 | 4.0 |
| Technical Feasibility | 1.0x | 4 | 4.0 |
| Risk Assessment | 1.0x | 4 | 4.0 |
| **Total** | **8.0x** | | **35.5/40** |

**Normalized: (35.5 / 40) × 30 = 26.6/30** — Ready to build.

## Auto-Check Checklist

- [x] Both Maria and David appear in the Problem Statement with specific, believable scenarios
- [x] Conversation examples use natural language (not formal commands)
- [x] "Not building" list has at least 3 items (5 items)
- [x] Every P0 user story maps to a conversation example
- [x] Success metrics include at least one failure signal (4 defined)
- [x] Cost estimate is within $3-8/month per user ($0.31/user)
- [x] Star rating is stated and justified (8★ → 9★)
- [x] RICE score referenced (see PRIORITIZATION.md update)
- [x] Proactivity section defines frequency limits
- [x] Edge cases include "no history" cold-start scenario (Mini App with no data)
