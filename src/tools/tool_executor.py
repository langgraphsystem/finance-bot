"""Tool executor — dispatches LLM tool calls to data_tools functions.

Injects family_id and user_id from SessionContext into every call.
The LLM never controls these parameters.
"""

import json
import logging
from typing import Any

from src.core.context import SessionContext
from src.core.observability import observe
from src.tools.data_tools import (
    aggregate_data,
    create_record,
    delete_record,
    query_data,
    update_record,
)

logger = logging.getLogger(__name__)

TOOL_FUNCTIONS = {
    "query_data": query_data,
    "create_record": create_record,
    "update_record": update_record,
    "delete_record": delete_record,
    "aggregate_data": aggregate_data,
}


@observe(name="tool_execute")
async def execute_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    context: SessionContext,
) -> dict[str, Any]:
    """Execute a single tool call with security context injection."""
    func = TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return {"error": f"Unknown tool: {tool_name}"}

    # Inject security context — LLM cannot override
    arguments["family_id"] = context.family_id
    arguments["user_id"] = context.user_id
    arguments["role"] = context.role

    try:
        return await func(**arguments)
    except (ValueError, TypeError) as e:
        logger.warning("Tool %s validation error: %s", tool_name, e)
        return {"error": str(e)}
    except Exception:
        logger.exception("Tool %s execution error", tool_name)
        return {"error": f"Internal error executing {tool_name}"}


async def execute_tool_calls_openai(
    tool_calls: list,
    context: SessionContext,
) -> list[dict[str, Any]]:
    """Execute OpenAI-format tool calls, return results for the next LLM turn."""
    results = []
    for tc in tool_calls:
        tool_name = tc.function.name
        try:
            arguments = json.loads(tc.function.arguments)
        except (json.JSONDecodeError, AttributeError):
            arguments = {}

        result = await execute_tool_call(tool_name, arguments, context)
        results.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, default=str),
        })
    return results
