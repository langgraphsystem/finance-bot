import json
import logging
from collections.abc import Callable
from typing import Any

import instructor
from anthropic import AsyncAnthropic
from google import genai
from openai import AsyncOpenAI

from src.core.config import settings

logger = logging.getLogger(__name__)


def get_anthropic_client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


def get_google_client() -> genai.Client:
    return genai.Client(api_key=settings.google_ai_api_key)


def get_instructor_anthropic():
    """Instructor-wrapped Anthropic client for structured output."""
    return instructor.from_anthropic(get_anthropic_client())


def get_instructor_openai():
    """Instructor-wrapped OpenAI client for structured output."""
    return instructor.from_openai(get_openai_client())


# Singleton clients (lazy initialization)
_anthropic: AsyncAnthropic | None = None
_openai: AsyncOpenAI | None = None
_google: genai.Client | None = None


def anthropic_client() -> AsyncAnthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = get_anthropic_client()
    return _anthropic


def openai_client() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = get_openai_client()
    return _openai


def google_client() -> genai.Client:
    global _google
    if _google is None:
        _google = get_google_client()
    return _google


async def generate_text(
    model: str,
    system: str,
    messages: list[dict[str, str]] | None = None,
    max_tokens: int = 1024,
    *,
    prompt: str | None = None,
) -> str:
    """Unified LLM call — routes to the correct SDK based on model ID.

    Supports OpenAI (gpt-*), Anthropic (claude-*), and Google (gemini-*) models.
    Returns the generated text content.

    Pass either ``messages`` (list of dicts) or ``prompt`` (single string).
    """
    if prompt is not None and messages is None:
        messages = [{"role": "user", "content": prompt}]
    if not messages:
        raise ValueError("Either messages or prompt is required")

    from src.core.llm.prompts import PromptAdapter

    if model.startswith("gpt-"):
        client = openai_client()
        resp = await client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            **PromptAdapter.for_openai(system, messages),
        )
        return resp.choices[0].message.content or ""
    elif model.startswith("claude-"):
        client = anthropic_client()
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            **PromptAdapter.for_claude(system, messages),
        )
        return resp.content[0].text
    elif model.startswith("gemini-"):
        from google.genai import types

        client = google_client()
        # Single message → pass as plain string; multi-turn → structured contents
        if len(messages) == 1:
            contents = messages[0]["content"]
        else:
            contents = [
                {
                    "role": ("user" if m["role"] == "user" else "model"),
                    "parts": [{"text": m["content"]}],
                }
                for m in messages
            ]
        resp = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
        return resp.text or ""
    else:
        raise ValueError(f"Unknown model prefix: {model}")


# ---------------------------------------------------------------------------
# Tool-augmented LLM call (function calling)
# ---------------------------------------------------------------------------


def _convert_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI tool schema format to Anthropic tool_use format."""
    result = []
    for t in tools:
        f = t["function"]
        result.append({
            "name": f["name"],
            "description": f["description"],
            "input_schema": f["parameters"],
        })
    return result


def _convert_tools_to_gemini(tools: list[dict]):
    """Convert OpenAI tool schema format to Gemini function declarations."""
    from google.genai import types

    declarations = []
    for t in tools:
        f = t["function"]
        declarations.append(
            types.FunctionDeclaration(
                name=f["name"],
                description=f["description"],
                parameters=f["parameters"],
            )
        )
    return [types.Tool(function_declarations=declarations)]


async def generate_text_with_tools(
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict],
    tool_executor: Callable | None = None,
    max_tokens: int = 2048,
    max_tool_rounds: int = 3,
) -> tuple[str, list[dict]]:
    """LLM call with function calling / tool_use support.

    Routes to the correct SDK based on model prefix.
    Handles the multi-turn loop: LLM → tool_call → execute → LLM → ...

    Returns (final_text, tool_call_log).
    """
    from src.core.llm.prompts import PromptAdapter

    tool_call_log: list[dict] = []

    for round_num in range(max_tool_rounds + 1):
        if model.startswith("gpt-"):
            client = openai_client()
            resp = await client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                tools=tools,
                tool_choice="auto",
                **PromptAdapter.for_openai(system, messages),
            )
            msg = resp.choices[0].message

            if msg.tool_calls and tool_executor:
                # Append assistant message with tool calls
                messages.append(msg.model_dump(exclude_none=True))
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments)
                    result = await tool_executor(tc.function.name, args)
                    tool_call_log.append({
                        "round": round_num,
                        "name": tc.function.name,
                        "args": args,
                        "result": result,
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    })
                continue

            return msg.content or "", tool_call_log

        elif model.startswith("claude-"):
            client = anthropic_client()
            anthropic_tools = _convert_tools_to_anthropic(tools)

            # Build Claude-format messages (filter out tool messages)
            claude_msgs = []
            for m in messages:
                if m.get("role") in ("user", "assistant"):
                    claude_msgs.append(m)

            resp = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=claude_msgs if claude_msgs else [{"role": "user", "content": "."}],
                tools=anthropic_tools,
            )

            tool_use_blocks = [b for b in resp.content if b.type == "tool_use"]
            text_blocks = [b for b in resp.content if b.type == "text"]

            if tool_use_blocks and tool_executor:
                messages.append({
                    "role": "assistant",
                    "content": [b.model_dump() for b in resp.content],
                })
                tool_results = []
                for tb in tool_use_blocks:
                    result = await tool_executor(tb.name, tb.input)
                    tool_call_log.append({
                        "round": round_num,
                        "name": tb.name,
                        "args": tb.input,
                        "result": result,
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tb.id,
                        "content": json.dumps(result, default=str),
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            return (text_blocks[0].text if text_blocks else ""), tool_call_log

        elif model.startswith("gemini-"):
            from google.genai import types

            client = google_client()
            gemini_tools = _convert_tools_to_gemini(tools)

            if len(messages) == 1 and isinstance(messages[0].get("content"), str):
                contents = messages[0]["content"]
            else:
                contents = [
                    {
                        "role": ("user" if m["role"] == "user" else "model"),
                        "parts": (
                            [{"text": m["content"]}]
                            if isinstance(m.get("content"), str)
                            else m.get("parts", [{"text": str(m.get("content", ""))}])
                        ),
                    }
                    for m in messages
                    if m.get("role") in ("user", "assistant", "model")
                ]

            resp = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    tools=gemini_tools,
                ),
            )

            fc_parts = [
                p for p in (resp.candidates[0].content.parts or [])
                if hasattr(p, "function_call") and p.function_call
            ]

            if fc_parts and tool_executor:
                for fc_part in fc_parts:
                    fc = fc_part.function_call
                    args = dict(fc.args) if fc.args else {}
                    result = await tool_executor(fc.name, args)
                    tool_call_log.append({
                        "round": round_num,
                        "name": fc.name,
                        "args": args,
                        "result": result,
                    })

                # Rebuild messages with function responses for next round
                if isinstance(contents, str):
                    contents = [{"role": "user", "parts": [{"text": contents}]}]
                contents.append({
                    "role": "model",
                    "parts": [{"text": p.text} for p in resp.candidates[0].content.parts if p.text]
                    + [
                        {
                            "functionCall": {
                                "name": fc_part.function_call.name,
                                "args": dict(fc_part.function_call.args)
                                if fc_part.function_call.args
                                else {},
                            }
                        }
                        for fc_part in fc_parts
                    ],
                })
                contents.append({
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": entry["name"],
                                "response": entry["result"],
                            }
                        }
                        for entry in tool_call_log
                        if entry["round"] == round_num
                    ],
                })
                # Convert back to messages format for next loop iteration
                messages = [
                    {"role": c["role"], "content": str(c.get("parts", "")), "parts": c.get("parts")}
                    for c in contents
                ]
                continue

            return resp.text or "", tool_call_log

        else:
            raise ValueError(f"Unknown model prefix: {model}")

    logger.warning("generate_text_with_tools exhausted %d rounds", max_tool_rounds)
    return "I needed more steps to complete this request.", tool_call_log
