# AI Life Assistant

## PM Skills

When working on product decisions, PRDs, feature design, or prioritization, read and follow the PM skills in this directory:

- **Start here:** `PM_SKILL.md` — Core product principles, framework references, and product context
- **Writing PRDs:** Use `PRD_TEMPLATE.md` for every feature. Score with the rubric before development.
- **Prioritization:** Check `PRIORITIZATION.md` for module rankings, RICE/ICE scores, and phase assignments.
- **Experience quality:** Reference `11_STAR_EXPERIENCE.md` for the 1-11 star scale. MVP = 6 stars.
- **Writing:** Follow `LANGUAGE_VOICE.md` for bot messages, PRDs, and all internal docs.

### Key Rules

1. Every PRD must include Maria (Brooklyn mom) and David (Queens plumber) scenarios.
2. Every feature must state its star rating and justify it.
3. Every PRD must be self-scored against the review rubric before submission.
4. Never build Phase 2 features until Phase 1 reaches 6-star quality.
5. Follow the 5 product principles in PM_SKILL.md — they override feature requests.

## Architecture

| Component | Technology |
|-----------|-----------|
| Routing | DomainRouter → AgentRouter (simple) or LangGraph (complex) |
| LangGraph domains | Email, Research, Writing, Browser automation |
| skill.execute() domains | Finance, Life-tracking, Calendar, Tasks, Contacts, Monitor |
| Database | Supabase (PostgreSQL + pgvector + RLS) |
| Primary model | Claude Haiku 4.5 (70% of calls) |
| Complex tasks | Claude Sonnet 4.5 (25%), Claude Opus 4.6 (rare) |
| OCR / Intent | Gemini 3 Flash |
| Google APIs | aiogoogle (async, per-user OAuth) |
| Channels | Telegram, WhatsApp (Business API), Slack (slack-bolt), SMS (Twilio) |
| Browser automation | Browser-Use + Steel.dev |
| Cost target | $3-8/month API cost per user |

## Conventions

- **Language:** Python 3.12+, typed, async
- **Framework:** FastAPI
- **Formatting:** ruff (line-length 100)
- **Testing:** pytest-asyncio, all external I/O mocked
- **User-facing text:** English (primary) → Spanish (second) → user's preferred language. See LANGUAGE_VOICE.md
- **Tone:** Smart capable friend (see LANGUAGE_VOICE.md)
- **Naming:** snake_case for Python, kebab-case for URLs
- **PRDs:** Stored in `docs/prds/`, named by module
- **Commits:** Conventional commits format
