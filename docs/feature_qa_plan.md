# Feature QA Plan

## Goal
Validate each feature sequentially across five quality dimensions:
- Feature logic
- Information processing
- Response correctness
- Response formatting
- Response design

## Scope Snapshot
- Registered skills: 64
- Mini App API endpoints: 26
- Test files: 116

## Universal Per-Feature Checklist
For each feature, run the same checklist:
1. Logic
- Happy path works end-to-end
- Edge cases handled
- Error/rollback behavior is correct

2. Information processing
- Intent classification and routing are correct
- Parsed fields (amount/date/scope/entities) are correct
- Context and family/user boundaries are respected

3. Response correctness
- Output matches user request
- No hallucinated facts/actions
- Confirmation flows for destructive actions are present

4. Response formatting
- Telegram-safe HTML and parse mode behavior are correct
- Button labels/callbacks/URLs are correct
- Message length and chunking are readable

5. Response design
- Clear visual hierarchy in text response (title, key lines, summary)
- Good empty/loading/error states
- Consistent UX tone and structure

## Execution Order (Sequential)
1. Block A: Onboarding + Core Routing
- onboarding, general_chat, clarify flow, callback flow

2. Block B: Finance CRUD
- add_expense, add_income, correct_category, undo_last, delete_data

3. Block C: Finance Analytics + Documents
- query_stats, query_report, scan_receipt, scan_document, set_budget, add_recurring, mark_paid

4. Block D: Life Tracking
- quick_capture, track_food, track_drink, mood_checkin, day_plan, day_reflection, life_search, set_comm_mode, evening_recap

5. Block E: Tasks + Reminders + Shopping
- create_task, list_tasks, set_reminder, complete_task
- shopping_list_add, shopping_list_view, shopping_list_remove, shopping_list_clear

6. Block F: Research + Web + Monitoring
- quick_answer, web_search, compare_options, maps_search, youtube_search
- web_action, price_check, price_alert, news_monitor

7. Block G: Writing
- draft_message, translate_text, write_post, proofread, generate_card

8. Block H: Email + Calendar
- read_inbox, send_email, draft_reply, follow_up_email, summarize_thread
- list_events, create_event, find_free_slots, reschedule_event, morning_brief

9. Block I: Booking + CRM
- create_booking, list_bookings, cancel_booking, reschedule_booking
- add_contact, list_contacts, find_contact, send_to_client

10. Block J: Platform Layers
- API endpoints, gateways, voice, billing, proactivity, orchestrators

## Design/UX Verification Track
Run in parallel with functional checks:
1. Telegram message UX
- formatting, readability, CTA consistency, confirm/cancel patterns

2. Mini App UX
- mobile-first rendering, Telegram theme compatibility, visual consistency
- states: loading, empty, success, validation, and error

## Regression Strategy
1. Add/refresh tests per block
- happy path + 2-3 edge cases + destructive-action checks

2. Add response contract checks
- text structure, button schema, callback format

3. Maintain a coverage matrix
- feature -> logic / processing / correctness / formatting / design

## Definition of Done
A feature is marked PASS only if all five dimensions pass:
- Logic
- Information processing
- Response correctness
- Response formatting
- Response design

