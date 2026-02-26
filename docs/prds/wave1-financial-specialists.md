# PRD: Wave 1 Financial Specialists

**Date:** 2026-02-26
**Author:** AI
**Star Rating:** 6★ (Great — proactive financial intelligence, daily reliance)
**Score:** 26/30

## Problem Statement

Users track expenses and income but get no proactive financial intelligence. Maria manually categorizes grocery receipts and has no idea where her money goes each week. David sends invoices from a spreadsheet, estimates taxes by feel, and can't predict whether next month will be tight.

### Maria's Pain (Brooklyn Mom)
Maria texts "bought groceries 87.50" and it records fine. But she never gets a summary of where her family's money goes. At tax time, she scrambles to find deductible expenses. She has no idea if she can afford the kids' summer camp.

### David's Pain (Queens Plumber)
David has 30+ transactions a week across jobs. He doesn't know which jobs are profitable. He creates invoices manually in Google Docs. Quarterly tax estimates are guesswork — last year he owed $2,400 more than expected.

## Solution Overview

Four new skills that turn raw transaction data into actionable financial intelligence:

1. **Financial Summary** — weekly/monthly breakdown by category with trends and insights
2. **Invoice Generator** — create professional PDF invoices from contacts + transaction history
3. **Tax Estimator** — quarterly estimate based on actual income/expenses, deduction tracking
4. **Cash Flow Forecast** — predict next 30/60/90 days based on recurring patterns + trends

## Conversation Examples

```
Maria: "where does my money go?"
Bot: Here's your February summary:
• Groceries: $847 (↑12% vs Jan) — Costco $340, Stop&Shop $290, other $217
• Kids: $425 — school lunch $160, soccer $125, clothes $140
• Transport: $310 — gas $180, MTA $90, Uber $40
• Total spent: $2,890 of $3,500 budget (83%)
You're on track. Groceries are up — want me to track by store?

David: "invoice Mike Chen for the bathroom job"
Bot: Got it — here's the invoice:
• Mike Chen — Bathroom remodel
• Labor: 8 hrs × $85 = $680
• Materials: $340 (from your receipts Feb 18-22)
• Total: $1,020
Send as PDF to Mike's email (mike@chen.com)?

David: "how much do I owe in taxes this quarter?"
Bot: Q1 2026 estimate:
• Gross income: $18,400
• Deductible expenses: $6,200 (materials $3,100, gas $980, tools $720, other $1,400)
• Net profit: $12,200
• Estimated tax (SE + income): ~$3,050
Pay by Apr 15. Want me to remind you a week before?

Maria: "can we afford summer camp?"
Bot: Based on your pattern:
• Average monthly surplus: $610
• By June you'll have ~$2,440 saved
• Camp cost: $1,800
Looks good — you'd have $640 buffer. Want me to set a savings goal?
```

## User Stories

### P0 (Must Have)
- As a user, I can ask for a financial summary and get a breakdown by category with trends
- As a user, I can generate an invoice for a contact using recorded transactions
- As a user, I can get a quarterly tax estimate based on my actual data
- As a user, I can ask about future affordability and get a forecast

### P1 (Should Have)
- Financial summary shows week-over-week and month-over-month comparisons
- Invoice includes line items from recent transactions with that contact
- Tax estimate tracks self-employment tax for freelancers/business owners
- Cash flow forecast accounts for recurring payments

### P2 (Nice to Have)
- Proactive weekly financial digest (Sunday evening)
- Invoice template customization
- Tax deduction category suggestions
- Forecast confidence intervals

### Won't Have (This Phase)
- Automated invoice sending on schedule
- Tax filing integration (TurboTax, etc.)
- Investment tracking or portfolio analysis
- Multi-currency consolidation
- Bank account reconciliation (no bank API)

## Success Metrics

| Metric | Target | Failure Signal |
|--------|--------|---------------|
| Activation | >40% users try within 7 days | <20% |
| Weekly use | >2 specialist queries/user/week | <0.5 |
| Invoice generation | >1 invoice/business user/week | 0 after 14 days |
| Tax estimate accuracy | Within 15% of actual | >30% deviation |
| Satisfaction | >4.0/5.0 | <3.5 |

## Technical Specification

### Architecture

All 4 skills use the existing `data_tools_enabled` path (LLM function calling with database tools). No new database tables needed — everything queries existing `transactions`, `contacts`, and `recurring_payments` tables.

New agent: `finance_specialist` (Claude Sonnet) with `data_tools_enabled=True`.

### Skills

| Skill | Intent | Agent | Model | Tier |
|-------|--------|-------|-------|------|
| financial_summary | `financial_summary` | finance_specialist | claude-sonnet-4-6 | 1 (single LLM + tools) |
| generate_invoice | `generate_invoice` | finance_specialist | claude-sonnet-4-6 | 1 (LLM + tools + PDF) |
| tax_estimate | `tax_estimate` | finance_specialist | claude-sonnet-4-6 | 1 (LLM + tools) |
| cash_flow_forecast | `cash_flow_forecast` | finance_specialist | claude-sonnet-4-6 | 1 (LLM + tools) |

### Data Flow

```
User message → intent detection → finance_specialist agent
  → LLM with data tools → query_data(transactions) + aggregate_data()
  → LLM synthesizes response with insights
  → SkillResult (text + optional PDF for invoices)
```

### Cost Estimate

- ~3K tokens per specialist query (Sonnet)
- ~5 tool calls average
- Estimated: $0.02-0.05 per query
- At 10 queries/user/week: ~$0.50/user/month (well within $3-8 budget)

### Edge Cases

1. **No transactions** — "You don't have any transactions yet. Start by recording an expense."
2. **No contact for invoice** — "I don't have Mike Chen's info. Want to add them first?"
3. **Insufficient data for forecast** — "I need at least 2 weeks of data to forecast. Check back soon."
4. **Non-business user asks for tax** — Show personal income summary, skip SE tax.

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Tax estimate inaccuracy | Disclaimer: "This is an estimate, not tax advice" |
| Invoice formatting issues | Use existing WeasyPrint PDF pipeline from query_report |
| Forecast unreliable with sparse data | Require minimum 14 days of history |
| Feature overlap with query_stats | Clear intent differentiation in prompt |

## Timeline

- Day 1: Skills + routing + tests (this PR)
- Week 2: Proactive weekly digest (P2)
- Week 3: LangGraph workflow upgrade (Tier 2)
