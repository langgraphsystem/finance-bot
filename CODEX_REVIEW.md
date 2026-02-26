# miniapp.py patch verification

Reviewed file: `api/miniapp.py`

## Result

10/11 requested fixes are correctly applied.

## Checklist

1. `_escape_like()` used for ILIKE search: **PASS**  
   Implemented at `api/miniapp.py:46` and used in transaction search with `escape="\\"` at `api/miniapp.py:533-540`.

2. `_parse_enum()` wraps all enum constructors: **PASS**  
   Helper exists at `api/miniapp.py:50`. User-input enum parsing in this file is routed through `_parse_enum()` (transactions, budgets, recurring, life-events, tasks).

3. `_parse_uuid()` for body UUID fields: **PASS**  
   Helper exists at `api/miniapp.py:79`; used for body UUIDs in transaction create/update, budget create, recurring create (`api/miniapp.py:594`, `648`, `788`, `889`).

4. `uuid.UUID` type on all path params: **PASS**  
   Confirmed for `tx_id`, `budget_id`, `rec_id`, `task_id` (`api/miniapp.py:565`, `629`, `685`, `823`, `933`, `1170`, `1226`).

5. `_require_owner()` on invite-code/delete-budget/currency-change: **PASS**  
   Applied in `get_invite_code` (`api/miniapp.py:312`), `delete_budget` (`api/miniapp.py:826`), and currency change path in `update_settings` (`api/miniapp.py:1347-1348`).

6. `_is_public_ip()` in `geo/detect`: **PASS**  
   Helper at `api/miniapp.py:64`; enforced in `detect_geo_from_ip` at `api/miniapp.py:1413`.

7. `_month_offset()` for trend calculation: **PASS**  
   Helper at `api/miniapp.py:72`; used in monthly trend loop at `api/miniapp.py:447`.

8. `outerjoin` in `list_budgets`: **PASS**  
   Applied at `api/miniapp.py:719`.

9. `scope=cat.scope` in `create_transaction`: **PASS**  
   Applied at `api/miniapp.py:617`.

10. `.limit(10000)` on CSV export: **PASS**  
    Applied at `api/miniapp.py:1275`.

11. All returns inside `async with session` blocks: **FAIL (incomplete)**  
    There are still handlers returning after the session context exits, including:
    - `get_stats` (`api/miniapp.py:410`)
    - `get_monthly_trend` (`api/miniapp.py:476`)
    - `list_transactions` (`api/miniapp.py:555`)
    - `delete_transaction` (`api/miniapp.py:701`)
    - `list_budgets` (`api/miniapp.py:777`)
    - `delete_budget` (`api/miniapp.py:840`)
    - `mark_recurring_paid` (`api/miniapp.py:973`)
    - `delete_task` (`api/miniapp.py:1242`)
    - `export_csv` (`api/miniapp.py:1297`)

## Remaining issue summary

The patch set is mostly solid, but item 11 is not fully implemented. If strict compliance is required, these handlers should return from inside their corresponding `async with async_session()` blocks.
