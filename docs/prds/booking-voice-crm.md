# PRD: Booking & Voice CRM Agent

**Author:** Claude Code
**Date:** 2026-02-19
**Status:** Draft → Review
**Star Rating:** 6★ → 7★ (MVP → stretch)
**RICE Score:** (55% × 2.5 × 65%) / 6 = 14.9 (Phase 2)

---

## 1. Problem Statement

### The Pain

Service professionals (plumbers, barbers, dentists, tutors, cleaners) and busy parents manage bookings through a chaotic mix of phone calls, WhatsApp messages, paper notebooks, and memory. Clients call at inconvenient times, messages get lost, follow-ups don't happen, no-shows cost money.

### How Frequent / How Severe

- David gets 5-10 booking calls/day. Misses 2-3 while on a job. Each missed call = $150-500 lost job.
- Maria juggles 3-5 appointments/week for her kids across multiple providers. Double-books at least once a month.

### Maria Test

Maria is driving when Dr. Chen's office calls to confirm Emma's dentist appointment. She can't answer. Later she forgets to call back. The appointment lapses. She discovers this 2 days before when she checks her fridge sticky note.

**With the bot:** The bot answers the incoming call via AI voice: "Hi, this is Maria's assistant. She's unavailable right now. How can I help?" The office says "Confirming Emma's dentist Thursday at 10am." The bot confirms, adds it to Maria's calendar, and texts Maria: "Dr. Chen confirmed Emma's dentist Thursday 10am. Added to your calendar."

### David Test

David is under a sink when a new client calls. Voicemail picks up, but the client hangs up and calls the next plumber. David loses a $400 job. When he finishes, he has 3 missed calls and no idea who they were.

**With the bot:** The bot answers: "Hi, thanks for calling David's Plumbing. David's on a job right now — I can help you schedule an appointment. What do you need done?" The caller says "My kitchen faucet is leaking." The bot books them for tomorrow at 2pm, sends David a summary, and texts the client a confirmation.

---

## 2. Solution Overview

An AI booking agent that:

1. **Answers phone calls** via Twilio Voice + OpenAI Realtime API (speech-to-speech). Talks to callers naturally, books appointments, takes messages.
2. **Makes outbound calls** to confirm appointments, follow up on no-shows, and remind clients.
3. **Accepts bookings** via any channel (Telegram, WhatsApp, SMS, voice) and maintains one unified schedule.
4. **Remembers every client** — preferences, history, communication style, preferred times.
5. **Messages clients** on the owner's behalf via WhatsApp/SMS with owner approval.
6. **Sends reminders** (24h + 1h before) to both owner and client automatically.

### Conversation Examples

**Inbound call (new client):**
```
Caller: "Hi, I need a plumber for a leaky faucet."
Bot:    "Hi! Thanks for calling David's Plumbing. I can help schedule
         that. When works best for you?"
Caller: "Tomorrow afternoon if possible."
Bot:    "David has 2pm and 4pm available tomorrow. Which do you prefer?"
Caller: "2pm works."
Bot:    "Great — you're booked for tomorrow at 2pm. Can I get your name
         and address?"
Caller: "John Smith, 145 Oak Street, Queens."
Bot:    "Got it, John. David will be at 145 Oak St tomorrow at 2pm for
         a faucet repair. You'll get a text confirmation shortly.
         Anything else?"
```

**David via Telegram:**
```
David: "Позвони миссис Джонсон и подтверди на завтра"
Bot:   "I'll call Mrs. Johnson at (917) 555-0142 to confirm her
        10am appointment tomorrow. Confirm?"
        [Call Now] [Cancel]
David: [Call Now]
Bot:   "Calling Mrs. Johnson... ✓ She confirmed. See you at 10am."
```

### Not Building

1. Online booking page / widget for clients (no web UI — Principle 1)
2. Payment processing at booking time (regulatory complexity)
3. Video calls / screen sharing
4. Calendar integration with Calendly/Acuity (we ARE the calendar)
5. Multi-location / multi-staff scheduling engine (Phase 2 consideration)

---

## 3. User Stories

### P0 — Must Have (Launch)

| # | Story | Conversation Example |
|---|-------|---------------------|
| 1 | Owner creates booking via text | "Book John tomorrow 2pm faucet repair" → confirmation |
| 2 | Owner lists today's/week's bookings | "What's on my schedule today?" → formatted list |
| 3 | Owner cancels/reschedules booking | "Move John to Thursday" → updates + notifies client |
| 4 | Bot answers inbound calls via AI voice | Caller → Twilio → OpenAI Realtime → books/takes message |
| 5 | Bot sends SMS/WhatsApp to clients | "Text John I'm running late" → approval → sends |
| 6 | Owner adds/finds contacts | "Add client: John Smith, 917-555-1234" |
| 7 | Booking reminders (24h, 1h) | Cron → reminds owner + texts client |
| 8 | Bot remembers client preferences | "John prefers mornings" stored in Mem0 |

### P1 — Expected Within 2 Weeks

| # | Story |
|---|-------|
| 9 | Bot makes outbound confirmation calls via AI voice |
| 10 | Google Calendar 2-way sync (booking → event, event → booking) |
| 11 | Follow-up broadcast ("remind last week's clients to rebook") |
| 12 | No-show detection + auto-follow-up |
| 13 | Available slots suggestion ("tomorrow has 3 open slots") |

### P2 — Nice to Have

| # | Story |
|---|-------|
| 14 | Call recording + transcription stored in client history |
| 15 | Multi-language voice (Spanish callers handled in Spanish) |
| 16 | Smart scheduling (suggest optimal times based on location/travel) |

### Won't Have

- Client self-service portal
- Payment collection
- Staff management / shift scheduling
- Video consultations

---

## 4. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Activation** | 40% of new users create a booking within 48h | DB query |
| **Usage** | 8+ bookings/week for service businesses | DB query |
| **Missed calls captured** | 90% of inbound calls answered by AI | Twilio call logs |
| **Client notification rate** | 95% of bookings get reminder sent | Background task logs |
| **Retention** | 70% weekly retention for booking users | Cohort analysis |

### Leading Indicators (48h)

- User creates first contact AND first booking within 48h
- User sends first message to a client via bot

### Failure Signals

- <3 bookings/week after onboarding → feature not sticky
- >20% of AI calls result in caller hang-up within 10s → voice quality issue
- >10% of outbound messages get no approval within 5 min → flow too complex

---

## 5. Technical Specification

### Architecture

| Component | Technology |
|-----------|-----------|
| **Voice (inbound)** | Twilio Voice + Media Streams WebSocket → OpenAI Realtime API (gpt-4o-realtime) |
| **Voice (outbound)** | Twilio REST API → TwiML `<Connect><Stream>` → OpenAI Realtime |
| **Client messaging** | WhatsAppGateway / SMSGateway (existing) |
| **Booking DB** | PostgreSQL `bookings` table + `client_interactions` table |
| **Client memory** | Mem0 with new fact types: `client_preference`, `service_history` |
| **Reminders** | Taskiq cron every minute (like existing `dispatch_due_reminders`) |
| **Agent model** | Claude Haiku 4.5 (text skills), GPT-4o Realtime (voice) |

### Voice Call Flow (Inbound)

```
Phone call → Twilio number
  → POST /webhook/voice/inbound (TwiML: <Connect><Stream url="/ws/voice">)
  → WebSocket /ws/voice/inbound
    → Twilio streams μ-law 8kHz audio
    → Server converts to 16kHz PCM16
    → OpenAI Realtime WebSocket (session with system prompt + tools)
    → OpenAI streams back audio + tool calls
    → Tool: create_booking(contact, service, datetime, location)
    → Tool: find_available_slots(date)
    → Tool: send_summary_to_owner(text)
    → Server converts response to μ-law 8kHz
    → Twilio plays audio to caller
  → On call end: save transcript to client_interactions
```

### Voice Call Flow (Outbound)

```
Owner: "Call John to confirm tomorrow"
  → Approval buttons
  → Owner confirms
  → Twilio REST: client.calls.create(to=john_phone, from_=twilio_number,
      twiml=<Connect><Stream url="/ws/voice/outbound/{call_id}">)
  → WebSocket /ws/voice/outbound/{call_id}
    → OpenAI Realtime with confirmation script as system prompt
    → Tools: confirm_booking(booking_id), reschedule_booking(booking_id, new_time)
  → On call end: update booking status, notify owner
```

### Data Model

```sql
-- New table: bookings
CREATE TABLE bookings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    user_id UUID NOT NULL REFERENCES users(id),
    contact_id UUID REFERENCES contacts(id),
    title VARCHAR(255) NOT NULL,
    service_type VARCHAR(100),
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    location VARCHAR(500),
    notes TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    reminder_sent BOOLEAN DEFAULT FALSE,
    confirmation_sent BOOLEAN DEFAULT FALSE,
    source_channel VARCHAR(50) DEFAULT 'telegram',
    external_calendar_event_id VARCHAR(255),
    meta JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- New table: client_interactions (call/message log)
CREATE TABLE client_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    contact_id UUID NOT NULL REFERENCES contacts(id),
    channel VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    content TEXT,
    booking_id UUID REFERENCES bookings(id),
    call_duration_seconds INTEGER,
    call_recording_url VARCHAR(500),
    meta JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS policies (same pattern as other tables)
ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_interactions ENABLE ROW LEVEL SECURITY;
```

### New Config Settings

```python
# Twilio Voice (extends existing SMS config)
twilio_voice_phone_number: str = ""    # dedicated voice number

# OpenAI Realtime
openai_realtime_model: str = "gpt-4o-realtime-preview"
openai_realtime_voice: str = "alloy"   # alloy, echo, shimmer, etc.
```

### Edge Cases

1. **Caller hangs up mid-booking** → save partial data, notify owner "Missed booking attempt from (917) 555-0142 — they said 'leaky faucet'"
2. **Double booking** → check conflicts before confirming, offer next available slot
3. **Unknown caller (no contact match)** → create new contact from call data
4. **Owner has no available slots** → "David's fully booked tomorrow. Would Thursday work?"
5. **Cold start (no contacts, no bookings)** → first-use tutorial via text
6. **Voice quality issues** → fallback to "I'm having trouble hearing you. Can I text you instead?" + sends SMS

### Cost Estimate

| Component | Cost per call | Monthly (50 calls) |
|-----------|--------------|-------------------|
| Twilio Voice (inbound) | $0.0085/min × 3 min avg | $1.28 |
| Twilio Voice (outbound) | $0.014/min × 2 min avg | $1.40 |
| OpenAI Realtime audio | ~$0.06/min (input) + $0.24/min (output) | $15.00 |
| Text skills (Haiku) | ~$0.001/request × 200 | $0.20 |
| SMS/WhatsApp | $0.0079/msg × 100 | $0.79 |
| **Total** | | **~$18.67/mo** |

Note: At $49/month subscription, voice-heavy users cost ~$19/mo, leaving $30 margin. Acceptable for differentiation.

---

## 6. Proactivity Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| Booking in 24h | Remind owner + text/call client | Per booking | Telegram + SMS |
| Booking in 1h | Final reminder to owner | Per booking | Telegram |
| Booking end time passed | "John's appointment ended. How did it go?" | Per booking | Telegram |
| No-show (15 min past start) | "John hasn't shown up. Mark as no-show?" | Per booking | Telegram |
| Client hasn't rebooked in 30 days | "5 clients haven't been back in a month. Send follow-up?" | Weekly | Telegram |
| Missed inbound call | "Missed call from (917) 555-0142. Call back?" | Per event | Telegram |

Max proactive messages: 5/day (shared with other proactivity triggers).

---

## 7. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OpenAI Realtime latency >500ms | Medium | High | Buffer audio, use `alloy` voice (fastest). Fallback to TTS+STT pipeline |
| Caller misunderstood by AI | Medium | High | Always repeat booking details. Send SMS confirmation. Owner reviews |
| Twilio costs spike (viral usage) | Low | Medium | Per-user call minute limits. Alert at $30/user/mo |
| TCPA compliance (outbound calls) | Medium | High | Always require owner approval. No auto-calling without consent |
| Caller expects human, gets AI | Medium | Medium | Upfront disclosure: "Hi, this is David's AI assistant" |
| Voice quality over poor cell connection | Medium | Medium | Detect silence/noise, offer SMS fallback |

---

## 8. Timeline

| Phase | Duration | Deliverables |
|-------|----------|-------------|
| **P0 Build** | 2 weeks | Booking model, CRM skills, text-based booking, client messaging, reminders |
| **P0 Voice** | 2 weeks | Twilio Voice webhooks, OpenAI Realtime integration, inbound/outbound calls |
| **P1 Build** | 2 weeks | Calendar sync, follow-up broadcast, no-show detection, slot suggestions |
| **Polish** | 1 week | Edge cases, voice quality tuning, Langfuse dashboards |

---

## 9. Self-Score

| Criterion | Weight | Score | Weighted |
|-----------|--------|-------|----------|
| Problem Clarity | 2.0x | 5 | 10.0 |
| User Stories | 1.5x | 4 | 6.0 |
| Success Metrics | 1.5x | 4 | 6.0 |
| Scope Definition | 1.0x | 4 | 4.0 |
| Technical Feasibility | 1.0x | 4 | 4.0 |
| Risk Assessment | 1.0x | 4 | 4.0 |
| **Total** | **8.0x** | | **34.0/40** |

**Normalized: (34/40) × 30 = 25.5/30** ✅ Ready to build

**Star Rating: 6★ → 7★**
- 6★ because: proactive booking + AI voice answers calls + remembers clients
- Not 8★ because: no autonomous rebooking, no AI-generated optimal schedules
- Not 5★ because: voice calling is a step above text-only booking

Sources:
- [Twilio + OpenAI Realtime API (Python)](https://www.twilio.com/en-us/blog/voice-ai-assistant-openai-realtime-api-python)
- [Outbound Calls with OpenAI Realtime](https://www.twilio.com/en-us/blog/outbound-calls-python-openai-realtime-api-voice)
- [OpenAI Realtime API](https://openai.com/index/introducing-the-realtime-api/)
