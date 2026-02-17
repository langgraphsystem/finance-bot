# 11-Star Experience — AI Life Assistant

Based on Brian Chesky's framework from Masters of Scale: imagine the experience on a 1-to-11 scale, where 1★ is broken and 11★ is physically impossible magic. Then work backward from absurdly good to find the sweet spot.

**Journey evaluated:** First Contact → First Completed Task

**MVP target:** 6★ | **Stretch:** 7★

---

## ★ 1 — Broken

The user texts the bot and nothing happens. Or it responds with an error. Or it asks them to create an account on a website first.

| Maria | David |
|-------|-------|
| Texts "Hi" — gets a 404 error or no response for 30 seconds | Texts "Hi" — gets asked to fill out a registration form on a website |

**Lesson:** This is what happens when you prioritize backend architecture over the first 10 seconds.

---

## ★★ 2 — Frustrating

The bot responds, but it's generic, slow, or requires too many steps. It feels like talking to an IVR phone tree.

| Maria | David |
|-------|-------|
| Texts "Remind me to pick up Emma at 3:15" — bot asks "What is your name? What timezone are you in? Would you like to set up a profile?" | Texts "Schedule Mike for the 10am job on Elm St tomorrow" — bot says "I can help with scheduling! First, let's set up your team. How many employees do you have?" |

**Lesson:** Asking setup questions before delivering value is a death sentence for retention.

---

## ★★★ 3 — Functional but Cold

The bot works but feels robotic. It completes the task but the experience is transactional and impersonal.

| Maria | David |
|-------|-------|
| "Remind me to pick up Emma at 3:15" → "Reminder set for 3:15 PM." No context awareness, no follow-up. | "Schedule Mike for 10am Elm St" → "Event created: 10am, Elm St." Doesn't know who Mike is or that this is a plumbing job. |

**Lesson:** Correct output isn't enough. The user should feel understood, not processed.

---

## ★★★★ 4 — Adequate

The bot handles the task correctly and the response feels natural. But it's purely reactive — you have to ask for everything.

| Maria | David |
|-------|-------|
| "Remind me to pick up Emma at 3:15" → "Got it! I'll remind you at 3:15 to pick up Emma." Clear, friendly, done. But no awareness of Emma's school or usual pickup routine. | "Schedule Mike for 10am Elm St tomorrow" → "Done — Mike's on the Elm St job at 10am tomorrow. Want me to notify him?" Helpful, but only because David spelled everything out. |

**Lesson:** This is where most chatbots stop. Useful, but not indispensable.

---

## ★★★★★ 5 — Good

The bot remembers context from past conversations and starts connecting dots. It feels like talking to someone who has been paying attention.

| Maria | David |
|-------|-------|
| "Remind me to pick up Emma at 3:15" → "Reminder set! By the way, Noah's soccer practice ends at 4 — want me to remind you about that too?" Remembers Noah exists and his schedule. | "Schedule Mike for Elm St" → "The 10am slot, like his usual morning jobs? I'll put it on tomorrow's schedule and let Mike know." Remembers Mike's patterns. |

**Lesson:** Memory transforms a tool into an assistant. This is the minimum bar for "I'd tell a friend about this."

---

## ★★★★★★ 6 — Great (MVP Target)

The bot is proactive. It doesn't just respond — it anticipates. Morning briefs, deadline warnings, pattern-based suggestions. The user starts relying on it daily.

| Maria | David |
|-------|-------|
| **Morning brief at 7:30am:** "Good morning! Today: Emma's dentist at 2pm (I'll remind you at 1:30), Noah's soccer at 4pm, and you're low on milk — want me to add it to your grocery list?" Maria didn't ask for any of this. | **Morning brief at 6:30am:** "Morning, David. Today's schedule: Mike on the Elm St job at 10am, Jose doing the bathroom remodel on Oak Ave at 8am. Reminder: Mrs. Chen's invoice from last week is still unpaid — want me to send a follow-up?" David opens his phone and his day is organized. |
| "Add eggs to the grocery list" → instantly done, one message confirmation | "Push Mike's job to 11am" → "Done. Mike's been notified. His next job at 2pm still works with the new time." |

**Lesson:** Proactivity is the difference between a tool and an assistant. This is where users say "I can't go back."

---

## ★★★★★★★ 7 — Excellent (Stretch Target)

The bot understands the user's life holistically. It cross-references across domains — calendar, tasks, contacts, finances — to make non-obvious connections. It saves time the user didn't know they were losing.

| Maria | David |
|-------|-------|
| "What should I make for dinner?" → "Emma has a playdate at the Johnsons' tomorrow so you'll need a bigger meal tonight. You have chicken, rice, and broccoli from your last grocery order. Here's a 30-minute recipe that Noah liked last time." Cross-references calendar + groceries + meal history. | "How's this month looking?" → "Revenue is up 15% over last month. You've got 3 outstanding invoices totaling $4,200. Mike's been your top performer — 12 jobs completed. One thing: you haven't followed up on Mrs. Rodriguez's quote from last Tuesday. Want me to text her?" Cross-references finances + jobs + CRM. |

**Lesson:** Cross-domain intelligence is the moat. No single-purpose app can do this.

---

## ★★★★★★★★ 8 — Amazing

The bot becomes a true life operating system. It handles multi-step workflows autonomously — research, compare, book, confirm — and only checks in when it needs a decision.

| Maria | David |
|-------|-------|
| "I need to find a summer camp for Emma" → bot researches local camps, compares prices and reviews, finds 3 options matching Emma's interests and Maria's schedule, presents them with a recommendation. Maria picks one, bot registers Emma and adds all dates to the calendar. | "I need a new water heater supplier" → bot researches wholesale suppliers in Queens, compares pricing, checks reviews from other plumbers, presents 3 options with delivery timelines. David picks one, bot places the order and updates his inventory records. |

**Lesson:** Delegation without supervision. The user trusts the bot to do the legwork.

---

## ★★★★★★★★★ 9 — Extraordinary

The bot manages entire life domains end-to-end. Maria never thinks about grocery shopping — it just happens. David never manually invoices — it just happens.

| Maria | David |
|-------|-------|
| Groceries arrive at the door on Saturday morning. The bot tracked what was running low, planned meals around the family's preferences and weekly schedule, ordered from the cheapest available store, and scheduled delivery. Maria approved the cart with a single "looks good." | Invoices go out automatically after each job. The bot knows the job details, labor hours, and parts used because Mike logged them via text. It generates the invoice, sends it to the client, and follows up after 7 days. David just watches the money come in. |

**Lesson:** From assistant to autopilot. Users save hours per week without noticing.

---

## ★★★★★★★★★★ 10 — Unbelievable

The bot is prescient. It solves problems the user didn't know they had, finds opportunities they wouldn't have found, and makes decisions they would have made — just faster.

| Maria | David |
|-------|-------|
| "Maria, Emma's school is closed next Friday for teacher development day. I found a one-day art workshop at the Brooklyn Museum — Emma loved their last exhibit. Want me to sign her up? Noah can go to the Johnsons' — I already checked with Lisa." | "David, there's a burst pipe emergency posted on Nextdoor two blocks from Jose's current job. It's a 4-unit building — could be a $3K+ job. Jose can get there in 20 minutes after he finishes. Want me to reply and book it?" |

**Lesson:** This is where the product becomes a competitive advantage in the user's life.

---

## ★★★★★★★★★★★ 11 — Physically Impossible Magic

The user's entire life runs itself. Maria wakes up and her day is not just organized but optimized for happiness. David's business grows 30% without him working more hours. The bot negotiates, hires, shops, cooks, and somehow reads minds.

| Maria | David |
|-------|-------|
| The fridge restocks itself. The kids' schedules are perfectly balanced between education and fun. Dinner is ready when she gets home. Date nights are planned. She has more free time than she did before kids. | His business runs on autopilot. New customers appear through optimized marketing. Employees are scheduled for maximum efficiency. Supplies arrive before they run out. His accountant calls to say his taxes are already done. |

**Lesson:** This is the North Star, not the product. It tells us the direction, not the destination.

---

## How Agents Should Use Star Ratings

1. **Every PRD must state a target star rating** (e.g., "This feature brings calendar management from 4★ to 6★").
2. **Justify why it's not one star higher.** What would that take? Is it feasible within this phase?
3. **Justify why it's not one star lower.** What would we cut? Would users still find it valuable?
4. **Features below 5★ should not ship.** If we can't reach 5★, descope or rethink the approach.
5. **Features above 8★ go into the aspirational roadmap**, not the current sprint.
6. **Use star ratings in trade-off discussions:** "This adds complexity but takes us from 5★ to 6★ — worth it" or "This is cool but moves us from 6★ to 6.5★ while doubling scope — skip it."
