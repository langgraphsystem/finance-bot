# Phase 8 — Financial Pro

**Author:** Claude Code
**Date:** 2026-02-23
**Status:** Draft
**Star Rating:** 7★ → 8★ (Autonomous financial management — delegation without supervision)
**RICE Score:** See individual module scores below

---

## 1. Problem Statement

### What problem are we solving?

The bot tracks expenses and generates reports, but US self-employed users need tax-aware categorization, deduction tracking, and compliance exports. 41 million Americans are self-employed — they spend 10+ hours/month on bookkeeping that an AI assistant should handle. The current system treats all expenses equally: a $50 lunch is the same as a $50 work tool. The IRS doesn't agree.

Business users also lack role-based access — David can't give his accountant read-only access to review expenses without sharing his entire bot conversation. And invoicing — the core revenue cycle for service businesses — has only a stub implementation.

### The Maria Test

> Maria does freelance graphic design on weekends. She earned $8,400 last quarter but has no idea what she can deduct. She paid $1,200 for Adobe Creative Cloud, $400 for a home office chair, and $60/month for her phone plan (50% business use). At tax time she texts her accountant screenshots from the bot. Her accountant charges $200/hour and spends 3 hours sorting through chat messages. Maria's home office deduction is $0 because she didn't know it existed.

### The David Test

> David's plumber business does $180K/year in revenue. He has 5 employees driving 3 trucks across NYC boroughs. Each quarter his accountant needs fuel receipts organized by state for IFTA filing. David currently keeps paper receipts in a shoebox — last quarter he missed $2,100 in deductions because receipts were lost. His employees text him expenses throughout the day but there's no structured way to approve or categorize them. He also sends invoices manually via email — 2-3 per day, 15 minutes each.

### Who else has this problem?

- **41M self-employed Americans** need Schedule C tracking
- **3.5M commercial vehicle operators** need IFTA reporting
- **Every traveling professional** has per diem tracking needs
- **100% of business bot users** benefit from accountant access
- **80%+ of service businesses** send invoices manually

---

## 2. Solution Overview

### What are we building?

Five capabilities that turn the bot from an expense tracker into a financial management system:

1. **Schedule C + AI Auto-Deductions** — Classify expenses as deductible, track by Schedule C category, surface missed deductions
2. **IFTA Export** — Track fuel purchases by state, calculate gallons, generate IFTA-compliant CSV
3. **Per Diem Tracking** — IRS standard rates by city, auto-apply to travel days synced with calendar
4. **Accountant Read-Only Access** — New `accountant` role with restricted data view, shareable via invite link
5. **Invoice Tracking** — Create, send, track, and follow up on invoices tied to bookings/jobs

### Conversation Example

**Maria's scenario:**
```
Maria: I bought a new iPad for $899 — it's for my design work
Bot: Logged $899 for the iPad. Since it's for your freelance design, I marked it as a Schedule C deduction under "Equipment." Your total deductions this quarter: $3,240.

Maria: what can I deduct that I'm missing?
Bot: Based on your spending patterns, you might be missing:
• Home office deduction — you work from home 3+ days/week. Simplified method: $5/sq ft, up to $1,500
• Phone plan — 50% business use based on your work hours = $30/month ($360/year)
• Internet — same split = $40/month ($480/year)
Want me to start tracking these automatically?

Maria: yes please. also give my accountant access — lisa@taxhelp.com
Bot: Done. Lisa now has read-only access to your expenses, deductions, and reports. She can view everything at [link] but can't edit or see your personal notes.
```

**David's scenario:**
```
David: Jose filled up the truck — $87 at Shell, 24 gallons, we're in New Jersey
Bot: Logged: $87 fuel, 24 gal, Shell, NJ. IFTA tracker updated — NJ now shows 312 gallons this quarter.

David: send Mrs. Chen an invoice for the bathroom job — $4,200 including parts
Bot: Invoice #2024-047 created for Mrs. Chen — $4,200 (bathroom renovation, parts included). Sending to chen.margaret@gmail.com now. I'll follow up in 7 days if unpaid.

[7 days later]
Bot: Mrs. Chen's invoice #2024-047 ($4,200) is 7 days overdue. Want me to send a polite reminder?

David: yes
Bot: Reminder sent. I'll check again in 5 days.

David: I need the IFTA report for Q1
Bot: Here's your Q1 IFTA summary:
• NY: 1,240 gal purchased, 3,100 miles driven
• NJ: 312 gal purchased, 780 miles driven
• CT: 89 gal purchased, 220 miles driven
Downloading CSV for filing. Your net fuel tax credit: $124.

[Sends IFTA-formatted CSV file]
```

### What are we NOT building?

- Automated tax filing (we prepare data, humans file)
- Payroll processing (W-2, 1099 generation — regulated domain)
- Bank account sync (separate phase — Plaid integration has different risk)
- Accountant two-way editing (read-only access only)
- Mileage tracking via GPS (requires mobile app — violates conversation-first principle)
- State-specific tax rules beyond federal Schedule C and IFTA

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | Self-employed user | have expenses auto-categorized by Schedule C line | I don't miss deductions at tax time |
| 2 | Self-employed user | see a deduction summary by category anytime | I know my tax position in real time |
| 3 | Business user | invite my accountant with read-only access | they review my data without seeing personal conversations |
| 4 | Service business | create and send invoices via chat | I don't spend 15 min per invoice in email |
| 5 | Service business | get notified when invoices are overdue | I follow up on unpaid work |

### P1 — Should Have (expected within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | Truck operator | track fuel by state and gallons | I file IFTA accurately |
| 2 | Traveling professional | auto-apply per diem rates to travel days | I claim the right daily allowance |
| 3 | Self-employed user | get proactive alerts about missed deductions | the bot catches what I forget |
| 4 | Business user | have invoices linked to bookings/jobs | I see the full job-to-payment lifecycle |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | Business user | auto-generate year-end Schedule C report | I hand my accountant a ready document |
| 2 | Fleet manager | see fuel efficiency per truck | I optimize routes and maintenance |
| 3 | Business user | set payment terms per client (net-15, net-30) | invoices auto-calculate due dates |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | Automated tax filing | Regulatory risk. We prepare, humans file. |
| 2 | Payroll/W-2/1099 | Separate regulated domain with heavy compliance. |
| 3 | GPS mileage tracking | Requires mobile app. Use manual entry or IRS simplified method. |
| 4 | State income tax calculations | Complexity explosion. Federal Schedule C only. |
| 5 | Credit card processing for invoices | Stripe Connect adds weeks of compliance work. Invoices show payment instructions (Zelle, Venmo, check). |

---

## 4. Success Metrics

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % of self-employed users who enable Schedule C tracking within 48h | > 40% | Profile flag + first deduction logged |
| **Usage** | Invoices sent per business user per month | > 4 | `invoices` table count |
| **Usage** | IFTA exports per quarter per fleet user | > 1 | `export_jobs` with type=`ifta` |
| **Retention** | Business users with accountant access still active after 30 days | > 80% | Subscription + activity check |
| **Revenue** | Average revenue per business user | +15% (upsell potential) | Stripe analytics |
| **Satisfaction** | "Would you recommend this to another business owner?" (1-10 NPS) | > 8 | In-chat survey at day 30 |

### Leading Indicators (check at 48 hours)

- [ ] 50%+ of existing business users enable at least one Financial Pro feature
- [ ] First invoice sent within 24h of feature launch
- [ ] Zero critical errors in IFTA calculations (verify against manual data)

### Failure Signals (trigger re-evaluation)

- [ ] Schedule C categorization accuracy < 80% (users correcting too often)
- [ ] Invoice feature used < 2x/month per user (not replacing their current workflow)
- [ ] Accountant invitation acceptance rate < 30% (friction too high)

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Orchestrator** | InvoiceOrchestrator (new LangGraph): `create → format → send → track` with follow-up loop |
| **Skills** | `schedule_c_track` (new), `deduction_summary` (new), `ifta_export` (new), `per_diem_track` (new), `create_invoice` (new), `list_invoices` (new), `invite_accountant` (new) — 7 new skills |
| **APIs** | IRS Per Diem rates (static YAML, updated annually), email for invoice sending (reuse EmailOrchestrator) |
| **Models** | Claude Sonnet 4.6 for deduction classification, Claude Haiku 4.5 for invoice formatting, Gemini Flash for receipt → Schedule C mapping |
| **Database** | `invoices` table (new), `invoice_items` table (new), `schedule_c_categories` table (new), `ifta_records` table (new), `accountant_access` table (new) |
| **Background Jobs** | `invoice_followup_task` (daily: check overdue invoices), `deduction_alert_task` (weekly: surface missed deductions), `ifta_quarterly_reminder` (quarterly: remind to export) |

### Data Model

```sql
-- Schedule C deduction categories (IRS standard)
CREATE TABLE IF NOT EXISTS schedule_c_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    line_number VARCHAR(8) NOT NULL, -- '1', '8', '9', '10', '11', etc.
    category_name VARCHAR(128) NOT NULL, -- 'Advertising', 'Car and truck expenses', etc.
    description TEXT,
    is_active BOOLEAN DEFAULT true
);

-- Invoice tracking
CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    user_id UUID NOT NULL REFERENCES users(id),
    invoice_number VARCHAR(32) NOT NULL,
    client_id UUID REFERENCES contacts(id),
    client_name VARCHAR(256) NOT NULL,
    client_email VARCHAR(256),
    booking_id UUID REFERENCES bookings(id),
    subtotal DECIMAL(12,2) NOT NULL,
    tax_amount DECIMAL(12,2) DEFAULT 0,
    total_amount DECIMAL(12,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    status VARCHAR(16) DEFAULT 'draft', -- draft, sent, viewed, paid, overdue, cancelled
    payment_terms VARCHAR(16) DEFAULT 'net-30',
    due_date DATE,
    sent_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Invoice line items
CREATE TABLE IF NOT EXISTS invoice_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description VARCHAR(512) NOT NULL,
    quantity DECIMAL(10,2) DEFAULT 1,
    unit_price DECIMAL(12,2) NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    sort_order INTEGER DEFAULT 0
);

-- IFTA fuel records
CREATE TABLE IF NOT EXISTS ifta_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    transaction_id UUID REFERENCES transactions(id),
    state_code VARCHAR(2) NOT NULL,
    gallons DECIMAL(10,3) NOT NULL,
    price_per_gallon DECIMAL(6,3),
    total_cost DECIMAL(10,2) NOT NULL,
    station_name VARCHAR(256),
    vehicle_id VARCHAR(64), -- user-assigned vehicle name/number
    odometer_reading INTEGER,
    recorded_at TIMESTAMPTZ DEFAULT now()
);

-- Accountant access tokens
CREATE TABLE IF NOT EXISTS accountant_access (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    invited_by UUID NOT NULL REFERENCES users(id),
    accountant_email VARCHAR(256) NOT NULL,
    accountant_name VARCHAR(256),
    access_token VARCHAR(128) NOT NULL UNIQUE,
    permissions JSONB DEFAULT '{"view_expenses": true, "view_invoices": true, "view_reports": true, "view_personal": false}',
    is_active BOOLEAN DEFAULT true,
    last_accessed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ -- NULL = no expiry
);

-- Add schedule_c_line to transactions table
-- ALTER TABLE transactions ADD COLUMN schedule_c_line VARCHAR(8);
-- ALTER TABLE transactions ADD COLUMN is_deductible BOOLEAN DEFAULT false;
-- ALTER TABLE transactions ADD COLUMN per_diem_rate DECIMAL(8,2);
```

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| User marks personal expense as business deduction | Bot asks: "This looks like a personal expense. Want to mark it as business anyway? I'll flag it for accountant review." |
| IFTA record with no state specified | Bot asks: "Which state was this fuel stop in?" with top 3 suggestions based on recent locations. |
| Invoice sent to invalid email | Detect bounce within 5 min. Alert: "The email to chen@gamil.com bounced — did you mean chen@gmail.com?" |
| Accountant link accessed after expiry | Show "This link has expired. Ask [user name] to send a new invitation." |
| User has no expenses in requested quarter | "No expenses recorded for Q1 2026. Want me to check a different quarter?" |
| Per diem for a city not in IRS list | Use the nearest city's rate. Note: "Using nearby city rate — exact rate for [city] not in IRS tables." |
| Multiple vehicles for IFTA | Track by vehicle_id. "Which truck? You have: Van #1, Van #2, Truck #3." |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users |
|-----------|---------------------|---------------------|
| Schedule C classification (Sonnet) | $0.008 per expense | $160 (20 expenses × 1K users) |
| Invoice generation (Haiku) | $0.003 per invoice | $30 (10 invoices × 1K business users) |
| Deduction alert (weekly, Haiku) | $0.005 per user | $20 |
| IFTA CSV generation | $0 (local) | $0 |
| Email sending (existing infra) | $0.001 | $10 |
| **Total** | | **~$220/month @ 1K users ($0.22/user)** |

Within $3-8/month per user budget.

---

## 6. Proactivity Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| Expense logged without Schedule C category | Auto-suggest category + "Want me to mark this as [category]?" | Every new expense | Reply in conversation |
| Pattern detected: recurring expense not marked as deduction | "You've paid $60/month for Spotify for 6 months. Is this a business expense? That's $360 in deductions." | 1x per pattern discovery | Standalone message |
| Invoice overdue by 7 days | "Mrs. Chen's invoice ($4,200) is 7 days overdue. Send a reminder?" | 1x at 7 days, 1x at 14 days, 1x at 30 days | Standalone message |
| End of quarter approaching (within 2 weeks) | "Q1 ends March 31. Your IFTA data is ready. Want me to export it?" | 1x per quarter | Morning brief addition |
| Travel days detected on calendar | "You're in Chicago Tuesday-Thursday. Per diem rate: $79/day for meals. Want me to auto-track?" | 1x per trip | Pre-trip day |

### Rules

- Deduction suggestions max 2x/week. User can say "stop suggesting deductions" to disable.
- Invoice follow-ups: strict 7/14/30-day cadence. No more than 3 follow-ups total per invoice. User can cancel follow-up anytime.
- IFTA reminders: 1x per quarter, 2 weeks before deadline. Dismissible.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Schedule C misclassification leads to tax issues | Medium | High | Disclaimer: "This is informational, not tax advice. Review with your accountant." High-confidence threshold (>0.85) for auto-categorization, else ask user. |
| IRS per diem rates change mid-year | Low | Medium | Static YAML file updated annually. Build update script. Check IRS.gov quarterly. |
| Invoice email deliverability (spam filters) | Medium | Medium | Use verified sender domain. Include unsubscribe link. Monitor bounce rates. Fallback: user sends manually with bot-generated PDF. |
| Accountant access link shared with unauthorized person | Low | High | Access token + email verification. 90-day expiry default. User can revoke anytime. Audit log of all accountant views. |
| IFTA calculation errors | Low | High | Unit tests with known correct data from IFTA.net. Round to 3 decimal places per spec. Manual verification checklist for first 100 exports. |

### Dependencies

- [ ] IRS Schedule C category list (static, well-documented)
- [ ] IRS per diem rates by city (published annually at gsa.gov)
- [ ] IFTA quarterly filing format (standard CSV, published by IFTA Inc.)
- [x] Email sending (reuse existing EmailOrchestrator)
- [x] Contact management (reuse existing CRM skills)
- [x] Booking system (reuse for invoice linking)

---

## 8. Timeline

| Phase | Scope | Milestone |
|-------|-------|-----------|
| 8a | Schedule C categories + auto-deduction classification | Expenses tagged with Schedule C lines |
| 8b | Deduction summary skill + proactive alerts | Users see real-time deduction totals |
| 8c | Invoice creation + sending + tracking | Invoices sent from chat, status tracked |
| 8d | InvoiceOrchestrator (LangGraph) + follow-up loop | Auto-follow-up on overdue invoices |
| 8e | IFTA fuel tracking + quarterly export | Fleet users export IFTA CSV |
| 8f | Per diem tracking + calendar integration | Travel days auto-tracked with IRS rates |
| 8g | Accountant read-only access + invite flow | Accountants view data via secure link |

---

# Review Rubric — Self-Score

| Criterion | Weight | Score (1-5) | Weighted |
|-----------|--------|-------------|----------|
| Problem Clarity | 2.0x | 5 | 10.0 |
| User Stories | 1.5x | 5 | 7.5 |
| Success Metrics | 1.5x | 4 | 6.0 |
| Scope Definition | 1.0x | 5 | 5.0 |
| Technical Feasibility | 1.0x | 4 | 4.0 |
| Risk Assessment | 1.0x | 5 | 5.0 |
| **Total** | **8.0x** | | **37.5/40** |

**Normalized: (37.5 / 40) × 30 = 28.1/30** — Ready to build.

## Auto-Check Checklist

- [x] Both Maria and David appear in the Problem Statement with specific, believable scenarios
- [x] Conversation examples use natural language (not formal commands)
- [x] "Not building" list has at least 3 items (5 items)
- [x] Every P0 user story maps to a conversation example
- [x] Success metrics include at least one failure signal (3 defined)
- [x] Cost estimate is within $3-8/month per user ($0.22/user)
- [x] Star rating is stated and justified (7★ → 8★)
- [x] RICE score referenced (see PRIORITIZATION.md update)
- [x] Proactivity section defines frequency limits
- [x] Edge cases include "no history" cold-start scenario (no expenses in quarter)
