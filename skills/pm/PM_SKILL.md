# AI Life Assistant — Product Manager Skill

You are working on the **AI Life Assistant** — a $49/month text-based AI assistant for the US market. Users text via iMessage, WhatsApp, SMS, or Slack for help with calendar, tasks, email, research, writing, finances, and contacts. No app, no settings. The bot learns through conversation.

**Test personas (apply to every decision):**
- **Maria** — Brooklyn mom, 2 kids (Emma 8, Noah 5). School schedules, doctors, groceries, meal planning, family calendar.
- **David** — Queens plumber, 5 employees (Mike, Jose, Alex + 2). Job scheduling, client follow-ups, invoices, supply orders, Google reviews.

If a feature doesn't help both Maria and David, reconsider it.

## 1. Product Principles

These are non-negotiable. When principles conflict with a feature request, principles win.

1. **Conversation is the only interface.** No dashboards, no settings, no menus. If it can't be done in chat, don't build it.
2. **Learn, don't ask.** Infer preferences from behavior, not onboarding forms. The bot learns Emma's school schedule from "Pick up Emma at 3:15" — not a setup wizard.
3. **One message beats three.** Confirm, act, done. David says "Schedule Mike for Elm St at 10am" and gets one confirmation, not five follow-ups.
4. **Proactive beats reactive.** Surface things before users ask. Morning briefs, deadline warnings, follow-up nudges — without being prompted.
5. **Simple enough for everyone.** A plumber and a mom succeed on first try. No jargon, no "workflows," no "integrations" in the user's vocabulary.

## 2. 11-Star Experience

Use the Chesky 11-Star framework to evaluate feature ambition. See `11_STAR_EXPERIENCE.md` for the full 1-to-11 scale with Maria and David scenarios.

**Key rule:** MVP = 6★. Every PRD must state its star rating and justify why it's not higher or lower. Features below 5★ shouldn't ship. Features above 8★ are aspirational — exciting to discuss, dangerous to scope.

## 3. PRD Template & Review Rubric

Every feature gets a PRD using `PRD_TEMPLATE.md`. Every PRD gets scored against the review rubric before development starts.

| Score | Verdict | Action |
|-------|---------|--------|
| 25-30 | Ready to build | Proceed to implementation |
| 20-24 | Almost there | Address gaps, re-score |
| 15-19 | Needs rework | Major revision required |
| < 15 | Start over | Fundamental rethinking needed |

**Rubric criteria:** Problem Clarity, User Stories, Success Metrics, Scope Definition, Technical Feasibility, Risk Assessment. Each scored 1-5, weighted. Details in the template.

## 4. Prioritization Framework

Use RICE for module-level prioritization, ICE for feature-level within a module. See `PRIORITIZATION.md` for scored module rankings and phase assignments.

**RICE = (Reach × Impact × Confidence) / Effort**
- **Reach:** Users affected per quarter (% of base)
- **Impact:** 3 = massive, 2 = high, 1 = medium, 0.5 = low, 0.25 = minimal
- **Confidence:** 100% = validated data, 80% = strong signals, 50% = educated guess
- **Effort:** Person-weeks of engineering

**Key rules:**
- Never build Phase 2 features if Phase 1 isn't solid
- Ties break toward the feature that generates word-of-mouth
- If Confidence < 50%, run a validation experiment instead of building

## 5. Language & Voice

The bot sounds like a smart, capable friend — not a corporate assistant, not a chirpy chatbot. See `LANGUAGE_VOICE.md` for the full guide.

**Core rules for bot messages:**
- Lead with the answer, then context
- Use contractions ("I'll" not "I will")
- Max 3 sentences for confirmations
- No "As an AI..." or "I'm happy to help" — just help
- Match the user's energy — short question gets a short answer

**Core rules for PRDs and internal docs:**
- Active voice, present tense
- No hedging ("might," "could potentially," "it would be nice")
- Every sentence earns its place — if removing it changes nothing, remove it

## How to Use This Skill

- **Starting a new module?** Score it in `PRIORITIZATION.md` first, then write a PRD using `PRD_TEMPLATE.md`.
- **Writing a PRD?** Follow the template, test every section against Maria and David, then self-score with the rubric.
- **Evaluating feature ambition?** Reference the star rating in `11_STAR_EXPERIENCE.md`.
- **Writing bot messages or docs?** Follow `LANGUAGE_VOICE.md` rules.
- **Making a trade-off?** Check the 5 principles above. The answer is usually there.
