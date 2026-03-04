"""Live reminder testing — sends reminder commands in EN/RU/ES via Telegram.

Usage:
    python scripts/test_reminders_live.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = str(Path(__file__).parent.parent)
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(ROOT) / ".env", override=True)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ANSI colors
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Test scenarios: (message, expected_substrings, description)
REMINDER_TESTS = [
    # ── Russian ──
    (
        "ru",
        "напомни позвонить врачу в 6 вечера",
        ["🔔", "позвонить врачу"],
        "RU: one-shot with time",
    ),
    ("ru", "напоминай каждый день в 8 утра пить воду", ["🔔", "пить воду"], "RU: daily recurring"),
    (
        "ru",
        "напомни через 10 минут проверить духовку",
        ["🔔", "духовку"],
        "RU: relative time ('через 10 минут')",
    ),
    # ── English ──
    ("en", "remind me to call the dentist at 3pm", ["🔔", "dentist"], "EN: one-shot with time"),
    (
        "en",
        "set a daily reminder at 7am to take vitamins",
        ["🔔", "vitamins"],
        "EN: daily recurring",
    ),
    ("en", "remind me in 15 minutes to check the oven", ["🔔", "oven"], "EN: relative time"),
    # ── Spanish ──
    (
        "es",
        "recuérdame llamar al doctor a las 5 de la tarde",
        ["🔔", "doctor"],
        "ES: one-shot with time",
    ),
    (
        "es",
        "ponme un recordatorio diario a las 9 de la mañana para tomar agua",
        ["🔔", "agua"],
        "ES: daily recurring",
    ),
    # ── Edge cases ──
    ("ru", "напомни", ["?", "напомн"], "RU: empty — should ask what"),
    ("en", "remind me", ["?"], "EN: empty — should ask what"),
    # ── Verify list ──
    ("ru", "мои задачи", ["врачу"], "RU: verify reminders in task list"),
]


async def get_bot_username() -> str:
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
        data = resp.json()
        return data["result"]["username"]


async def main():
    from telethon import TelegramClient

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        print(f"{RED}ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH required{RESET}")
        return

    bot_username = await get_bot_username()
    print(f"{BOLD}Testing reminders on @{bot_username} — EN / RU / ES{RESET}\n")

    session_path = str(Path(__file__).parent / "test_telegram")
    client = TelegramClient(session_path, int(api_id), api_hash)

    await client.connect()
    if not await client.is_user_authorized():
        print(f"{RED}Session expired. Run: python scripts/telegram_auth.py{RESET}")
        await client.disconnect()
        return

    me = await client.get_me()
    print(f"{GREEN}Logged in as: {me.first_name}{RESET}")

    bot_entity = await client.get_entity(f"@{bot_username}")

    # Get latest bot message ID
    recent = await client.get_messages(bot_entity, limit=1)
    last_seen_id = recent[0].id if recent else 0

    passed = 0
    failed = 0
    results = []
    current_lang = None

    for test_item in REMINDER_TESTS:
        lang, text, expected, description = test_item

        if lang != current_lang:
            current_lang = lang
            print(f"\n{BOLD}{CYAN}{'─' * 50}")
            print(f"  Language: {lang.upper()}")
            print(f"{'─' * 50}{RESET}")

        print(f"\n  {BOLD}[TEST]{RESET} {description}")
        print(f"    {DIM}Sent:{RESET} {text}")

        # Drain stale messages — keep draining until no new messages for 2s
        for _ in range(5):
            await asyncio.sleep(2)
            drain = await client.get_messages(bot_entity, limit=10, min_id=last_seen_id)
            found_new = False
            for m in drain:
                if not m.out and m.id > last_seen_id:
                    last_seen_id = m.id
                    found_new = True
            if not found_new:
                break

        t0 = time.perf_counter()
        await client.send_message(bot_entity, text)

        # Wait for reply — skip cron reminder notifications
        # Cron notifications use "🔔 **Напоминание**\n\n" format
        # Command responses use "🔔 Напоминание установлено" or "🔔 Ежедневное"
        # or other skill-specific formats (task list, clarification)
        reply_text = None
        for _ in range(45):  # 90s timeout
            await asyncio.sleep(2)
            msgs = await client.get_messages(bot_entity, limit=5, min_id=last_seen_id)
            for m in reversed(msgs):
                if not m.out and m.id > last_seen_id:
                    txt = m.text or m.message or ""
                    # Skip cron reminder notifications (bold markdown format)
                    if txt.startswith("🔔 **"):
                        last_seen_id = m.id
                        continue
                    reply_text = txt
                    last_seen_id = m.id
                    break
            if reply_text is not None:
                break

        elapsed = int((time.perf_counter() - t0) * 1000)

        if reply_text is None:
            print(f"    {RED}TIMEOUT (90s){RESET}")
            failed += 1
            results.append((lang, description, "TIMEOUT", ""))
            continue

        # Check expected substrings
        reply_lower = reply_text.lower()
        missing = [s for s in expected if s.lower() not in reply_lower]

        status = "PASS" if not missing else "FAIL"
        if missing:
            print(f"    {RED}FAIL{RESET} — missing: {missing}")
            print(f"    {DIM}Response:{RESET} {reply_text[:250]}")
            failed += 1
        else:
            print(f"    {GREEN}PASS{RESET} ({elapsed}ms)")
            print(f"    {DIM}Response:{RESET} {reply_text[:250]}")
            passed += 1

        results.append((lang, description, status, reply_text[:300]))

        # Wait between tests (longer pause to avoid race conditions with slow responses)
        await asyncio.sleep(5)

    await client.disconnect()

    # Summary
    print(f"\n{BOLD}{'=' * 50}{RESET}")
    total = passed + failed
    color = GREEN if failed == 0 else RED
    print(f"{BOLD}Results: {color}{passed}/{total} passed{RESET}")

    # Per-language breakdown
    for lang_code in ["ru", "en", "es"]:
        lang_results = [r for r in results if r[0] == lang_code]
        if lang_results:
            lang_pass = sum(1 for r in lang_results if r[2] == "PASS")
            c = GREEN if lang_pass == len(lang_results) else YELLOW
            print(f"  {lang_code.upper()}: {c}{lang_pass}/{len(lang_results)}{RESET}")

    if failed > 0:
        print(f"\n{YELLOW}Failed tests:{RESET}")
        for lang, desc, status, resp in results:
            if status != "PASS":
                print(f"  [{lang}] {desc}: {resp[:100]}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
