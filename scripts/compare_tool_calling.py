"""Compare tool-calling: GPT-5.2 (none/low/medium/high) vs Grok models.

Sends identical prompts to all model variants with DATA_TOOL_SCHEMAS, measures:
- Tool call correctness (name + key args)
- Latency (seconds)
- Estimated cost (USD)

Usage:
    python scripts/compare_tool_calling.py
"""

import asyncio
import json
import os
import sys
import time

from dotenv import load_dotenv
from openai import AsyncOpenAI

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

load_dotenv(os.path.join(ROOT, ".env"), override=True)

SYSTEM_PROMPT = """\
You help users manage tasks, reminders, to-do lists, and shopping lists.
Create tasks, show the task list, mark tasks done, set reminders.
Manage shopping lists: add items, view lists, check off items, clear lists.
Be concise: one-line confirmations, structured lists.
Use the provided tools to interact with the database."""

# Test cases: (user_message, expected_tool, expected_args_subset)
TEST_CASES = [
    ("Создай задачу: купить молоко", "create_record", {"table": "tasks"}),
    ("Покажи мои задачи", "query_data", {"table": "tasks"}),
    ("Добавь хлеб в список покупок", "create_record", {"table": "shopping_list_items"}),
    ("Покажи список покупок", "query_data", {"table": "shopping_list_items"}),
    ("Сколько у меня задач?", "aggregate_data", {"table": "tasks", "metric": "count"}),
    ("Удали задачу с id 550e8400-e29b-41d4-a716-446655440000", "delete_record", {"table": "tasks"}),
    ("Create a task: call dentist tomorrow, high priority", "create_record", {"table": "tasks"}),
    ("Show my shopping list", "query_data", {"table": "shopping_list_items"}),
    (
        "Отметь задачу 550e8400-e29b-41d4-a716-446655440000 как выполненную",
        "update_record",
        {"table": "tasks"},
    ),
    ("Clear my shopping list", "delete_record", {"table": "shopping_list_items"}),
]

# (label, model_id, provider, reasoning_effort or None)
MODELS = [
    ("gpt-5.2 (none)", "gpt-5.2", "openai", None),
    ("gpt-5.2 (low)", "gpt-5.2", "openai", "low"),
    ("gpt-5.2 (medium)", "gpt-5.2", "openai", "medium"),
    ("gpt-5.2 (high)", "gpt-5.2", "openai", "high"),
]

# Cost per 1K tokens (input, output)
COST_MAP = {
    "gpt-5.2": (0.005, 0.015),
}


async def call_model(
    client: AsyncOpenAI,
    model_id: str,
    label: str,
    user_message: str,
    reasoning_effort: str | None = None,
) -> dict:
    """Call model with tools, return tool call info + timing."""
    start = time.time()
    try:
        kwargs: dict = {
            "model": model_id,
            "max_completion_tokens": 1024,
            "tools": DATA_TOOL_SCHEMAS,
            "tool_choice": "auto",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        }
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        resp = await client.chat.completions.create(**kwargs)
        elapsed = time.time() - start
        msg = resp.choices[0].message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append({"name": tc.function.name, "args": args})

        usage = resp.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        rates = COST_MAP.get(model_id, (0.001, 0.005))
        cost = (tokens_in / 1000) * rates[0] + (tokens_out / 1000) * rates[1]

        return {
            "label": label,
            "model": model_id,
            "elapsed": elapsed,
            "tool_calls": tool_calls,
            "text": msg.content or "",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost": cost,
            "error": None,
        }
    except Exception as e:
        return {
            "label": label,
            "model": model_id,
            "elapsed": time.time() - start,
            "tool_calls": [],
            "text": "",
            "tokens_in": 0,
            "tokens_out": 0,
            "cost": 0,
            "error": str(e),
        }


def check_result(result: dict, expected_tool: str, expected_args: dict) -> tuple[bool, str]:
    """Check if model called the right tool with expected args."""
    if result["error"]:
        return False, f"ERROR: {result['error']}"
    if not result["tool_calls"]:
        return False, "No tool call (text only)"

    tc = result["tool_calls"][0]
    if tc["name"] != expected_tool:
        return False, f"Wrong tool: {tc['name']} (expected {expected_tool})"

    for key, val in expected_args.items():
        actual = tc["args"].get(key)
        if actual != val:
            return False, f"Wrong arg {key}={actual!r} (expected {val!r})"

    return True, "OK"


async def run_comparison():
    from src.core.llm.clients import openai_client
    from src.tools.data_tool_schemas import DATA_TOOL_SCHEMAS

    clients = {
        "openai": openai_client(),
    }

    labels = [label for label, *_ in MODELS]
    scores: dict[str, int] = {label: 0 for label in labels}
    times: dict[str, float] = {label: 0.0 for label in labels}
    costs: dict[str, float] = {label: 0.0 for label in labels}

    print("=" * 110)
    print(f"{'TOOL CALLING COMPARISON — 4 MODEL VARIANTS':^110}")
    print(f"{'GPT-5.2 reasoning levels: none/low/medium/high':^110}")
    print(f"{'Tasks Agent workload — ' + str(len(TEST_CASES)) + ' test cases':^110}")
    print("=" * 110)

    for i, (msg, expected_tool, expected_args) in enumerate(TEST_CASES, 1):
        print(f"\n{'─' * 110}")
        print(f"  Test {i}/{len(TEST_CASES)}: {msg}")
        print(f"  Expected: {expected_tool}({expected_args})")
        print(f"{'─' * 110}")

        # Run all model variants in parallel.
        results = await asyncio.gather(
            *[
                call_model(clients[provider], model_id, label, msg, reasoning)
                for label, model_id, provider, reasoning in MODELS
            ]
        )

        for res in results:
            passed, reason = check_result(res, expected_tool, expected_args)
            marker = "PASS" if passed else "FAIL"
            lbl = res["label"]

            scores[lbl] += int(passed)
            times[lbl] += res["elapsed"]
            costs[lbl] += res["cost"]

            tc_str = ""
            if res["tool_calls"]:
                tc = res["tool_calls"][0]
                tc_str = f"{tc['name']}({json.dumps(tc['args'], ensure_ascii=False)[:60]})"
            elif res["text"]:
                tc_str = f"[text] {res['text'][:40]}"

            print(
                f"  [{marker}] {lbl:28s}  "
                f"{res['elapsed']:5.2f}s  "
                f"${res['cost']:.5f}  "
                f"{tc_str}"
            )
            if not passed:
                print(f"         Reason: {reason}")

    # Summary table
    total = len(TEST_CASES)
    print(f"\n{'=' * 110}")
    print(f"{'SUMMARY':^110}")
    print(f"{'=' * 110}")

    col_w = 15
    print(f"  {'Metric':<16s}", end="")
    for label in labels:
        print(f"  {label[:col_w]:>{col_w}s}", end="")
    print()
    print(f"  {'─' * (16 + (col_w + 2) * len(labels))}")

    # Accuracy
    print(f"  {'Accuracy':<16s}", end="")
    for label in labels:
        s = scores[label]
        print(f"  {f'{s}/{total} ({s/total*100:.0f}%)':>{col_w}s}", end="")
    print()

    # Avg latency
    print(f"  {'Avg latency':<16s}", end="")
    for label in labels:
        print(f"  {f'{times[label]/total:.2f}s':>{col_w}s}", end="")
    print()

    # Total cost
    print(f"  {'Total cost':<16s}", end="")
    for label in labels:
        print(f"  {f'${costs[label]:.5f}':>{col_w}s}", end="")
    print()

    # Winners
    best_acc = max(labels, key=lambda label: (scores[label], -times[label]))
    best_lat = min(labels, key=lambda label: times[label])
    best_cost = min(labels, key=lambda label: costs[label])

    print(f"\n  Best accuracy:  {best_acc} ({scores[best_acc]}/{total})")
    print(f"  Best latency:   {best_lat} ({times[best_lat]/total:.2f}s avg)")
    print(f"  Best cost:      {best_cost} (${costs[best_cost]:.5f} total)")

    # vs baseline
    base = "gpt-5.2 (none)"
    base_cost = costs[base]
    base_time = times[base]
    if base_cost > 0 and base_time > 0:
        print(f"\n  {'Model':<28s}  {'vs GPT none: cost':>18s}  {'speed':>8s}  {'accuracy':>10s}")
        print(f"  {'─' * 68}")
        for label in labels:
            if label == base:
                continue
            sav = (1 - costs[label] / base_cost) * 100 if base_cost else 0
            spd = base_time / times[label] if times[label] > 0 else 0
            acc_diff = scores[label] - scores[base]
            sign = "+" if acc_diff >= 0 else ""
            print(
                f"  {label:<28s}  {sav:>+16.0f}% cost  {spd:>6.2f}x  "
                f"{sign}{acc_diff:>8d} tests"
            )


if __name__ == "__main__":
    asyncio.run(run_comparison())
