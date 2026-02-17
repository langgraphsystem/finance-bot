# PM Skills — AI Life Assistant

Product manager skills for AI coding agents. Load these files into Claude Code, Cursor, Factory, or any AI assistant to turn it into a senior PM for the AI Life Assistant product.

## Quick Start

### Claude Code

Add to your project's `CLAUDE.md`:

```markdown
## PM Skills
When working on product decisions, PRDs, or feature design, read and follow the PM skills in `skills/pm/`:
- `PM_SKILL.md` — Core skill (start here)
- `PRD_TEMPLATE.md` — Use for every feature PRD
- `PRIORITIZATION.md` — Module ranking and RICE scores
- `11_STAR_EXPERIENCE.md` — Experience quality framework
- `LANGUAGE_VOICE.md` — Writing and tone rules
```

### Cursor

Add `skills/pm/PM_SKILL.md` to your `.cursorrules` or reference it in prompts:

```
@skills/pm/PM_SKILL.md Write a PRD for the Tasks & Reminders module.
```

### Factory

Load `PM_SKILL.md` as a skill file for your product droid. Reference the supporting docs via relative paths.

### Direct Prompt

Copy `PM_SKILL.md` into your AI agent's system prompt or conversation context. It works as a standalone ~700-word document, with cross-references to the detailed files for deeper work.

---

## File Structure

```
skills/pm/
├── PM_SKILL.md              # Core skill file (~700 words) — the entry point
├── 11_STAR_EXPERIENCE.md     # 1-to-11 star quality scale with persona scenarios
├── PRD_TEMPLATE.md           # PRD template with review rubric and scoring
├── PRIORITIZATION.md         # RICE/ICE frameworks, module rankings, phase plan
├── LANGUAGE_VOICE.md         # Bot personality, writing rules, tone guide
└── README.md                 # This file
```

---

## How It Works

| File | Purpose | When to Use |
|------|---------|-------------|
| `PM_SKILL.md` | Defines principles, references all other files, sets the product context | Always — load first |
| `11_STAR_EXPERIENCE.md` | Calibrates ambition level for any feature using Brian Chesky's framework | When evaluating feature scope or writing the star rating section of a PRD |
| `PRD_TEMPLATE.md` | Standardized template with 8 sections + auto-scoring rubric | When speccing any new feature or module |
| `PRIORITIZATION.md` | RICE scores for 13 modules, ICE for within-module features, phase assignments | When deciding what to build next or debating scope trade-offs |
| `LANGUAGE_VOICE.md` | Voice attributes, message rules, banned words, tone calibration | When writing bot messages, reviewing copy, or writing docs |

---

## Usage Scenarios

### 1. "Write a PRD for Calendar Management"

```
Load PM_SKILL.md and PRD_TEMPLATE.md.

Write a complete PRD for the Calendar Management module using the template.
Include Maria and David scenarios, conversation examples, and score it
against the review rubric.
```

### 2. "Is this feature ambitious enough?"

```
Load PM_SKILL.md and 11_STAR_EXPERIENCE.md.

I'm designing [feature]. Rate it on the 11-star scale with scenarios
for both Maria and David. What would it take to go one star higher?
```

### 3. "What should we build next?"

```
Load PM_SKILL.md and PRIORITIZATION.md.

We've completed Phase 1. Review the RICE scores for Phase 2 modules
and recommend which to start first, given [constraints].
```

### 4. "Review this bot message"

```
Load LANGUAGE_VOICE.md.

Review this bot message against the voice guide and suggest improvements:
"Hello! I've successfully processed your request and created a new
reminder for you. The reminder has been scheduled for 3:15 PM today.
Is there anything else I can assist you with?"
```

### 5. "Evaluate this feature idea"

```
Load PM_SKILL.md and PRIORITIZATION.md.

A user requested [feature]. Score it with ICE, check it against the
Won't Build list, and recommend whether to add it to the roadmap.
```

### 6. "Help me think through a trade-off"

```
Load PM_SKILL.md and PRIORITIZATION.md.

We can either [Option A] or [Option B] for [module]. Use the trade-off
template to structure the decision. Reference the product principles.
```

---

## Recommended Project Structure

```
your-project/
├── CLAUDE.md                 # References skills/pm/ for product work
├── skills/
│   └── pm/
│       ├── PM_SKILL.md
│       ├── 11_STAR_EXPERIENCE.md
│       ├── PRD_TEMPLATE.md
│       ├── PRIORITIZATION.md
│       ├── LANGUAGE_VOICE.md
│       └── README.md
├── docs/
│   └── prds/                 # Completed PRDs go here
│       ├── tasks-reminders.md
│       ├── calendar.md
│       └── ...
└── src/                      # Implementation code
```

---

## When to Update These Skills

| Trigger | What to Update |
|---------|---------------|
| New user data changes assumptions | `PRIORITIZATION.md` — re-score Reach, Impact, Confidence |
| Product principles evolve | `PM_SKILL.md` — update principles, then cascade to all docs |
| New module launches | `PRIORITIZATION.md` — add to table, update phases |
| Competitor launches relevant feature | `PRIORITIZATION.md` — re-evaluate Impact and urgency |
| Bot voice feels off | `LANGUAGE_VOICE.md` — add new rules or examples |
| PRD quality is inconsistent | `PRD_TEMPLATE.md` — tighten rubric or add checklist items |
| User persona evolves | All files — Maria and David scenarios should reflect real user feedback |

---

## Product Context Summary

| Attribute | Value |
|-----------|-------|
| Product | AI Life Assistant |
| Price | $49/month |
| Market | US consumers and small business owners |
| Channels | iMessage, WhatsApp, SMS, Slack |
| Interface | Conversation only — no app, no dashboard |
| Tech | LangGraph, Supabase, multi-model routing (Haiku 70%, Sonnet 25%, Opus rare) |
| Cost target | $3-8/month API cost per user |
| Test personas | Maria (Brooklyn mom, 2 kids) and David (Queens plumber, 5 employees) |
| MVP target | 6-star experience (see 11_STAR_EXPERIENCE.md) |
| Current phase | Phase 1 — Tasks, Calendar, Research, Writing, Onboarding |
