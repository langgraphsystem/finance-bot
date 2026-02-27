# generate_program Bug Fixes (2026-02-21)

Five critical bugs fixed in the code generation pipeline.

## 1. XSS via unescaped stdout/stderr

**Problem:** `_build_response()` embedded raw `exec_result.stdout` and `exec_result.error` into Telegram HTML `<code>` blocks. Malicious output like `</code><script>alert(1)</script>` would be sent unescaped.

**Location:** `src/skills/generate_program/handler.py`, `_build_response()` lines 348, 356

**Fix:** Added `html.escape()` on both error and stdout before embedding:
```python
err = html_mod.escape(_truncate(exec_result.error, 500))
out = html_mod.escape(_truncate(exec_result.stdout, 1000))
```

**Tests:** `test_xss_in_stdout_escaped`, `test_xss_in_error_escaped`

## 2. CSS files incorrectly wrapped in Flask

**Problem:** Condition `ext in (".html", ".css")` caused standalone CSS files to be wrapped in a Flask app via `_wrap_html_as_flask()`, which then failed in E2B.

**Location:** `src/skills/generate_program/handler.py`, line 272

**Fix:** Changed to `ext == ".html"` (strict equality). CSS files now pass through to E2B as-is.

**Test:** `test_css_file_not_wrapped_in_flask`

## 3. Gemini loses conversation history

**Problem:** `generate_text()` passed only `messages[-1]["content"]` to Gemini, discarding all prior messages. Multi-turn context was silently lost for JS/TS/HTML tasks routed to `gemini-3-flash-preview`.

**Location:** `src/core/llm/clients.py`, line 102

**Fix:** Single message passes as plain string; multi-turn passes structured `contents` list with role/parts:
```python
if len(messages) == 1:
    contents = messages[0]["content"]
else:
    contents = [{"role": ..., "parts": [{"text": ...}]} for m in messages]
```

**Test:** Implicit via routing tests (single-turn works correctly).

## 4. Web app sandbox resource leak

**Problem:** E2B sandboxes for web apps were never closed (`if not web_app: sandbox.close()`). They stayed alive indefinitely, consuming E2B quota.

**Location:** `src/core/sandbox/e2b_runner.py`, lines 231-235

**Fix:** Added `_close_sandbox_later()` that schedules `sandbox.close()` after 5 minutes via `asyncio.create_task()`:
```python
if web_app:
    asyncio.create_task(_close_sandbox_later(sandbox))
else:
    await sandbox.close()
```

**Test:** Integration-level (E2B is mocked in unit tests).

## 5. Description fallback mixes finance/program domains

**Problem:** Handler used `intent_data.get("description")` as fallback, which is the generic finance field. If intent detection populated it with "$100.50" from expense parsing, the program would be generated about "$100.50".

**Location:** `src/skills/generate_program/handler.py`, line 213

**Fix:** Removed `intent_data.get("description")` fallback. Now only uses `program_description` (the generate_program-specific field) or `message.text`:
```python
description = (
    intent_data.get("program_description")
    or message.text
    or ""
).strip()
```

**Test:** `test_description_fallback_skips_generic_field`
