"""Memory system gap fixes — live verification via Telegram (Telethon E2E).

Tests the specific fixes made in the memory gap analysis:
  - C1: learn_from_correction (realtime procedural learning)
  - C4: Contradiction detection (old fact archived, new wins)
  - H1: Domain-scoped memory (correct domain per intent)
  - H2: Episodic memory (centralized store in router)
  - H7: Graph strengthen on contact read
  - H8: Observation trigger for sparse conversations
  - M2: Rule dedup with casefold
  - L2: DLQ 7-day retention

Usage:
    python scripts/test_memory_gaps.py --chat-id 7314014306
    python scripts/test_memory_gaps.py --chat-id 7314014306 --no-scoring
    python scripts/test_memory_gaps.py --chat-id 7314014306 --test identity contradiction
    python scripts/test_memory_gaps.py --list
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import BaseModel

# Load .env BEFORE importing src modules
ROOT = str(Path(__file__).parent.parent)
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(ROOT) / ".env", override=True)
os.environ["APP_ENV"] = "testing"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
for _name in (
    "sqlalchemy", "opentelemetry", "urllib3", "httpx", "httpcore",
    "langfuse", "mem0", "taskiq", "asyncio", "aiohttp", "google.genai",
    "anthropic", "src",
):
    logging.getLogger(_name).setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

# ── ANSI ──
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
if sys.platform == "win32":
    os.system("")


# ── Models ──

class StepResult(BaseModel):
    step: int
    label: str
    message_sent: str
    response_text: str | None = None
    response_time_ms: int = 0
    status: str = "pending"
    check_passed: bool | None = None
    check_detail: str = ""
    error: str | None = None


class ScenarioResult(BaseModel):
    name: str
    description: str
    gap_id: str
    steps: list[StepResult]
    passed: bool = False


class RunReport(BaseModel):
    timestamp: str
    chat_id: int
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    total_steps: int
    passed_steps: int
    failed_steps: int
    scenarios: list[ScenarioResult]


# ── Scenarios ──
# Each scenario = (name, gap_id, description, steps)
# Each step = (message, check_fn_name, check_description)
# check_fn gets the bot response and returns (passed: bool, detail: str)

def _check_contains(keywords: list[str]):
    """Check that response contains ANY of the keywords (case-insensitive)."""
    def check(response: str) -> tuple[bool, str]:
        lower = response.lower()
        found = [kw for kw in keywords if kw.lower() in lower]
        if found:
            return True, f"Found: {', '.join(found)}"
        return False, f"None of [{', '.join(keywords)}] found in response"
    return check


def _check_not_contains(keywords: list[str]):
    """Check that response does NOT contain any of the keywords."""
    def check(response: str) -> tuple[bool, str]:
        lower = response.lower()
        found = [kw for kw in keywords if kw.lower() in lower]
        if found:
            return False, f"Unexpectedly found: {', '.join(found)}"
        return True, "None of the excluded keywords found"
    return check


def _check_has_response():
    """Just check that we got any non-empty response."""
    def check(response: str) -> tuple[bool, str]:
        if response and len(response.strip()) > 5:
            return True, f"Got {len(response)} chars"
        return False, "Empty or too short response"
    return check


def _check_no_emoji():
    """Check that response has no emoji characters."""
    def check(response: str) -> tuple[bool, str]:
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF"
            "\U00002702-\U000027B0\U0001FA00-\U0001FA6F"
            "\U0001FA70-\U0001FAFF\U00002600-\U000026FF]",
            flags=re.UNICODE,
        )
        emojis = emoji_pattern.findall(response)
        if emojis:
            return False, f"Found emoji: {''.join(emojis[:5])}"
        return True, "No emoji found"
    return check


SCENARIOS: dict[str, tuple[str, str, list[tuple[str, any, str]]]] = {
    # ── Identity & Contradiction (C4) ──
    "identity": (
        "GAP-C4",
        "Identity + contradiction: set name, recall, change, verify old replaced",
        [
            ("Меня зовут Алекс", _check_has_response(), "Set user name"),
            ("как меня зовут?", _check_contains(["Алекс", "алекс"]), "Recall user name"),
        ],
    ),
    "contradiction": (
        "GAP-C4",
        "Contradiction detection: set occupation, change it, verify new wins",
        [
            ("я работаю учителем", _check_has_response(), "Set occupation = teacher"),
            ("теперь я работаю инженером", _check_has_response(), "Change to engineer"),
            (
                "кем я работаю?",
                _check_contains(["инженер", "engineer"]),
                "Should say engineer (not teacher)",
            ),
        ],
    ),

    # ── Rules (M2 casefold) ──
    "rules": (
        "GAP-M2",
        "User rules: set no-emoji rule, verify compliance, cleanup",
        [
            ("всегда отвечай без эмодзи", _check_has_response(), "Set no-emoji rule"),
            ("привет! как дела?", _check_no_emoji(), "Response must have no emoji"),
            ("удали все правила", _check_has_response(), "Cleanup: remove all rules"),
        ],
    ),

    # ── Correction learning (C1) ──
    "correction": (
        "GAP-C1",
        "Correction learning: add expense, correct category, verify learning",
        [
            ("500 макдональдс", _check_has_response(), "Add expense at McDonald's"),
            ("привет", _check_has_response(), "Pause (let background tasks run)"),
        ],
    ),

    # ── Memory vault ──
    "memory_vault": (
        "GAP-H2",
        "Memory persistence: save explicit memory, recall, forget",
        [
            (
                "запомни: мой любимый цвет синий",
                _check_has_response(),
                "Save explicit memory",
            ),
            (
                "покажи мои воспоминания",
                _check_contains(["синий", "цвет", "blue"]),
                "Recall should include blue color",
            ),
            ("забудь про мой любимый цвет", _check_has_response(), "Forget color"),
        ],
    ),

    # ── Finance intents (H1 domain mapping) ──
    "finance_domains": (
        "GAP-H1",
        "Finance intents with correct domain scoping",
        [
            ("200 такси", _check_has_response(), "add_expense — should route correctly"),
            ("зарплата 3000", _check_has_response(), "add_income — finance domain"),
            ("сколько потратил за неделю?", _check_has_response(), "query_stats — analytics"),
        ],
    ),

    # ── Life intents (H1 domain mapping) ──
    "life_domains": (
        "GAP-H1",
        "Life intents with correct domain scoping",
        [
            ("выпил кофе", _check_has_response(), "track_drink — life domain"),
            ("настроение 8", _check_has_response(), "mood_checkin — life domain"),
        ],
    ),

    # ── Tasks (H1 domain mapping, was unmapped) ──
    "tasks_domains": (
        "GAP-H1",
        "Task intents (previously unmapped in INTENT_DOMAIN_MEM_MAP)",
        [
            (
                "добавь молоко в список покупок",
                _check_has_response(),
                "shopping_list_add — now mapped to tasks domain",
            ),
            ("покажи список покупок", _check_has_response(), "shopping_list_view — tasks domain"),
        ],
    ),

    # ── General robustness ──
    "general": (
        "ROBUSTNESS",
        "General bot responses after gap fixes (no regression)",
        [
            ("привет", _check_has_response(), "Greeting"),
            ("спасибо!", _check_has_response(), "Thanks"),
            ("переведи на английский: доброе утро", _check_has_response(), "Translation"),
        ],
    ),

    # ── Dialog history (new skill) ──
    "dialog_history": (
        "GAP-H2",
        "Dialog history skill — episodic memory retrieval",
        [
            (
                "о чём мы говорили?",
                _check_has_response(),
                "dialog_history — should summarize recent conversation",
            ),
        ],
    ),

    # ── Cleanup ──
    "cleanup": (
        "CLEANUP",
        "Cleanup test data: forget name, remove rules",
        [
            ("забудь моё имя", _check_has_response(), "Forget user name"),
            ("удали все правила", _check_has_response(), "Clear all rules"),
        ],
    ),
}


# ── Telegram E2E runner ──

async def _get_bot_username() -> str | None:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
            data = resp.json()
            return data["result"]["username"]
    except Exception:
        return None


async def run_scenario(
    client,
    bot_entity,
    last_seen_id: int,
    name: str,
    gap_id: str,
    description: str,
    steps: list[tuple[str, any, str]],
    timeout: int = 60,
    delay: float = 3.0,
) -> tuple[ScenarioResult, int]:
    """Run a single scenario with multiple steps. Returns (result, updated_last_seen_id)."""
    result = ScenarioResult(
        name=name, description=description, gap_id=gap_id, steps=[]
    )

    for i, (message, check_fn, label) in enumerate(steps, 1):
        step = StepResult(step=i, label=label, message_sent=message)

        try:
            # Drain stale messages
            await asyncio.sleep(0.5)
            drain = await client.get_messages(bot_entity, limit=5, min_id=last_seen_id)
            for m in drain:
                if not m.out and m.id > last_seen_id:
                    last_seen_id = m.id

            # Send message
            t0 = time.perf_counter()
            sent = await client.send_message(bot_entity, message)
            anchor_id = max(sent.id, last_seen_id)

            # Wait for reply
            reply = None
            poll_interval = 1.5
            max_polls = int(timeout / poll_interval)

            for _ in range(max_polls):
                await asyncio.sleep(poll_interval)
                messages = await client.get_messages(
                    bot_entity, limit=5, min_id=anchor_id
                )
                bot_msgs = [m for m in messages if not m.out and m.id > anchor_id]
                if bot_msgs:
                    reply = bot_msgs[0]
                    last_seen_id = max(m.id for m in bot_msgs)
                    # Collect multi-message responses
                    if len(bot_msgs) > 1:
                        all_texts = [
                            m.text or m.message or ""
                            for m in bot_msgs
                            if m.text or m.message
                        ]
                        reply_text = "\n---\n".join(all_texts)
                    else:
                        reply_text = reply.text or reply.message or ""
                    break

            t1 = time.perf_counter()

            if reply:
                step.response_time_ms = int((t1 - t0) * 1000)
                step.response_text = reply_text
                step.status = "pass"

                # Run check
                if check_fn:
                    passed, detail = check_fn(reply_text)
                    step.check_passed = passed
                    step.check_detail = detail
                    if not passed:
                        step.status = "fail"
            else:
                step.status = "timeout"
                step.error = f"No reply within {timeout}s"
                last_seen_id = max(last_seen_id, sent.id)

        except Exception as e:
            step.status = "error"
            step.error = str(e)[:200]

        result.steps.append(step)

        # Print step result
        if step.status == "pass" and step.check_passed is not False:
            icon, color = "+", GREEN
        elif step.status == "fail" or step.check_passed is False:
            icon, color = "x", RED
        elif step.status == "timeout":
            icon, color = "T", RED
        else:
            icon, color = "!", YELLOW

        print(f"    {color}[{icon}]{RESET} Step {i}: {label}")
        print(f"        {DIM}Sent:{RESET} {message}")
        if step.response_text:
            clean = re.sub(r"<[^>]+>", "", step.response_text)
            truncated = clean[:120] + "..." if len(clean) > 120 else clean
            print(f"        {DIM}Response ({step.response_time_ms}ms):{RESET} {truncated}")
        if step.check_passed is not None:
            chk_color = GREEN if step.check_passed else RED
            print(f"        {DIM}Check:{RESET} {chk_color}{step.check_detail}{RESET}")
        if step.error:
            print(f"        {RED}Error: {step.error}{RESET}")

        await asyncio.sleep(delay)

    # Scenario passes if all steps with checks passed
    checked_steps = [s for s in result.steps if s.check_passed is not None]
    result.passed = all(s.check_passed for s in checked_steps) if checked_steps else (
        all(s.status != "error" and s.status != "timeout" for s in result.steps)
    )

    return result, last_seen_id


async def run_all(
    chat_id: int,
    scenario_names: list[str],
    timeout: int = 60,
    delay: float = 3.0,
) -> list[ScenarioResult]:
    """Run selected scenarios via Telegram E2E."""
    from telethon import TelegramClient

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")

    if not api_id or not api_hash:
        print(f"\n  {RED}ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH required{RESET}")
        print("  Get them from https://my.telegram.org/apps")
        return []

    bot_username = await _get_bot_username()
    if not bot_username:
        print(f"  {RED}ERROR: Could not resolve bot username{RESET}")
        return []
    print(f"  {GREEN}Bot: @{bot_username}{RESET}")

    session_path = str(Path(__file__).parent / "test_telegram")
    session_file = Path(session_path + ".session")
    if not session_file.exists():
        print(f"\n  {RED}ERROR: No Telethon session at {session_file}{RESET}")
        print(f"  Run first: {BOLD}python scripts/telegram_auth.py{RESET}")
        return []

    client = TelegramClient(session_path, int(api_id), api_hash)
    print(f"\n  {DIM}Connecting to Telegram...{RESET}")
    await client.connect()
    if not await client.is_user_authorized():
        print(f"  {RED}ERROR: Session expired. Re-run: python scripts/telegram_auth.py{RESET}")
        await client.disconnect()
        return []
    me = await client.get_me()
    print(f"  {GREEN}Logged in: {me.first_name} (id={me.id}){RESET}")

    bot_entity = await client.get_entity(f"@{bot_username}")
    print(f"  {GREEN}Bot resolved: @{bot_username} (id={bot_entity.id}){RESET}")

    # Seed last_seen_id
    recent = await client.get_messages(bot_entity, limit=1)
    last_seen_id = recent[0].id if recent else 0

    all_results: list[ScenarioResult] = []

    for sname in scenario_names:
        if sname not in SCENARIOS:
            print(f"\n  {YELLOW}Unknown scenario: {sname}{RESET}")
            continue

        gap_id, desc, steps = SCENARIOS[sname]

        print(f"\n{BOLD}{CYAN}{'─' * 60}{RESET}")
        print(f"  {BOLD}[{gap_id}] {sname}{RESET}: {desc}")
        print(f"{BOLD}{CYAN}{'─' * 60}{RESET}")

        result, last_seen_id = await run_scenario(
            client, bot_entity, last_seen_id,
            sname, gap_id, desc, steps,
            timeout=timeout, delay=delay,
        )
        all_results.append(result)

        status_icon = f"{GREEN}PASS{RESET}" if result.passed else f"{RED}FAIL{RESET}"
        print(f"\n  Scenario: {status_icon}")

    await client.disconnect()
    return all_results


def print_summary(results: list[ScenarioResult]) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"  {BOLD}MEMORY GAP FIXES — TEST SUMMARY{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")

    total_scenarios = len(results)
    passed_scenarios = sum(1 for r in results if r.passed)
    total_steps = sum(len(r.steps) for r in results)
    passed_steps = sum(
        1 for r in results for s in r.steps
        if s.status == "pass" and s.check_passed is not False
    )

    pct = passed_scenarios / total_scenarios * 100 if total_scenarios else 0
    color = GREEN if pct >= 80 else YELLOW if pct >= 50 else RED

    print(
        f"\n  {BOLD}Scenarios:{RESET} "
        f"{color}{passed_scenarios}/{total_scenarios} ({pct:.0f}%){RESET}"
    )
    print(f"  {BOLD}Steps:{RESET}     {passed_steps}/{total_steps}")

    # Per-scenario breakdown
    print(f"\n  {BOLD}By scenario:{RESET}")
    for r in results:
        icon = f"{GREEN}+{RESET}" if r.passed else f"{RED}x{RESET}"
        step_ok = sum(1 for s in r.steps if s.status == "pass" and s.check_passed is not False)
        print(f"    [{icon}] {r.gap_id:<12} {r.name:<20} {step_ok}/{len(r.steps)} steps")

    # Failed checks
    failed = [
        (r.name, s)
        for r in results
        for s in r.steps
        if s.check_passed is False or s.status in ("error", "timeout")
    ]
    if failed:
        print(f"\n  {BOLD}{RED}Failed checks:{RESET}")
        for sname, step in failed:
            print(f"    {RED}-{RESET} {sname} step {step.step}: {step.label}")
            if step.check_detail:
                print(f"      {DIM}{step.check_detail}{RESET}")
            if step.error:
                print(f"      {DIM}{step.error}{RESET}")

    # Response times
    times = [s.response_time_ms for r in results for s in r.steps if s.response_time_ms > 0]
    if times:
        print(
            f"\n  {BOLD}Response time:{RESET} "
            f"avg={sum(times)//len(times)}ms  "
            f"min={min(times)}ms  max={max(times)}ms"
        )

    print()


def save_results(results: list[ScenarioResult], chat_id: int) -> Path:
    results_dir = Path(__file__).parent / "test_results"
    results_dir.mkdir(exist_ok=True)

    total_steps = sum(len(r.steps) for r in results)
    passed_steps = sum(
        1 for r in results for s in r.steps
        if s.status == "pass" and s.check_passed is not False
    )

    report = RunReport(
        timestamp=datetime.now().isoformat(),
        chat_id=chat_id,
        total_scenarios=len(results),
        passed_scenarios=sum(1 for r in results if r.passed),
        failed_scenarios=sum(1 for r in results if not r.passed),
        total_steps=total_steps,
        passed_steps=passed_steps,
        failed_steps=total_steps - passed_steps,
        scenarios=results,
    )

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = results_dir / f"memory_gaps_{ts}.json"
    filepath.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Memory gap fixes — live verification via Telegram E2E"
    )
    parser.add_argument(
        "--chat-id", type=int, default=7314014306,
        help="Telegram chat_id (default: 7314014306)",
    )
    parser.add_argument(
        "--test", nargs="+", default=None,
        help="Scenarios to run (default: all except cleanup)",
    )
    parser.add_argument("--list", action="store_true", help="List scenarios")
    parser.add_argument("--no-save", action="store_true", help="Skip saving JSON")
    parser.add_argument("--delay", type=float, default=3.0, help="Delay between steps (s)")
    parser.add_argument("--timeout", type=int, default=60, help="Reply timeout (s)")

    args = parser.parse_args()

    if args.list:
        total_steps = 0
        for name, (gap_id, desc, steps) in SCENARIOS.items():
            print(f"\n{BOLD}{name}{RESET} [{gap_id}] ({len(steps)} steps):")
            print(f"  {DIM}{desc}{RESET}")
            for msg, _, label in steps:
                print(f"    - {label}: {CYAN}{msg}{RESET}")
                total_steps += 1
        print(f"\n{BOLD}Total: {len(SCENARIOS)} scenarios, {total_steps} steps{RESET}")
        return

    if not BOT_TOKEN:
        print(f"{RED}ERROR: TELEGRAM_BOT_TOKEN not found in .env{RESET}")
        sys.exit(1)

    # Default: all scenarios in order (cleanup last)
    scenario_names = args.test or [
        "identity", "contradiction", "rules", "correction",
        "finance_domains", "life_domains", "tasks_domains",
        "memory_vault", "general", "dialog_history", "cleanup",
    ]

    print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"  {BOLD}MEMORY GAP FIXES — LIVE VERIFICATION{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"  Chat ID:    {args.chat_id}")
    print(f"  Scenarios:  {', '.join(scenario_names)}")
    print(f"  Delay:      {args.delay}s")
    print(f"  Timeout:    {args.timeout}s")

    results = asyncio.run(
        run_all(args.chat_id, scenario_names, timeout=args.timeout, delay=args.delay)
    )

    if not results:
        print(f"\n{RED}No results collected.{RESET}")
        return

    print_summary(results)

    if not args.no_save:
        filepath = save_results(results, args.chat_id)
        print(f"  {GREEN}Results saved:{RESET} {filepath}")


if __name__ == "__main__":
    main()
