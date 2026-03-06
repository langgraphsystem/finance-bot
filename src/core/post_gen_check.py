"""Post-generation rule check — verify LLM output complies with user rules.

Phase 13: After skill execution, a lightweight Haiku check ensures the
response doesn't violate user rules (language, emoji, length, bot name, style).

Gated by feature flag `ff_post_gen_check` (adds ~1s latency).
"""

import logging

from src.core.config import settings

logger = logging.getLogger(__name__)

CHECK_PROMPT = """You are a compliance checker. Check if the bot response follows ALL user rules.

User rules:
{rules}

Bot response:
{response}

Does the response violate any of the rules above? Answer ONLY with:
- "OK" if no violations
- "VIOLATION: <which rule was broken>" if a rule was violated

Answer:"""


async def check_response_rules(
    response_text: str,
    user_rules: list[str],
) -> tuple[bool, str]:
    """Check if the response complies with user rules.

    Returns:
        (True, "") if OK.
        (False, violation_description) if a rule was violated.
    """
    if not settings.ff_post_gen_check:
        return True, ""

    if not user_rules or not response_text:
        return True, ""

    rules_text = "\n".join(f"- {r}" for r in user_rules)

    try:
        from src.core.llm.clients import anthropic_client

        client = anthropic_client()
        resp = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": CHECK_PROMPT.format(
                    rules=rules_text,
                    response=response_text[:2000],
                ),
            }],
        )
        answer = resp.content[0].text.strip() if resp.content else "OK"

        if answer.upper().startswith("OK"):
            return True, ""

        violation = answer.replace("VIOLATION:", "").strip()
        logger.info("Post-gen rule violation: %s", violation)
        return False, violation

    except Exception as e:
        # Fail-open: if check fails, allow the response through
        logger.warning("Post-gen rule check failed (fail-open): %s", e)
        return True, ""


async def regenerate_with_rule_reminder(
    original_response: str,
    violation: str,
    user_rules: list[str],
    system_prompt: str,
    user_message: str,
) -> str:
    """Regenerate response with explicit rule reminder after violation.

    Uses Gemini Flash for fast regeneration with the violated rule
    prominently placed in the prompt.
    """
    rules_text = "\n".join(f"- {r}" for r in user_rules)

    regeneration_prompt = f"""The previous response violated a user rule: {violation}

User rules (MUST follow ALL):
{rules_text}

Original user message: {user_message}

Previous response (DO NOT repeat this):
{original_response[:500]}

Generate a new response that strictly follows ALL user rules."""

    try:
        from src.core.llm.clients import google_client

        client = google_client()
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=regeneration_prompt,
        )
        return response.text or original_response
    except Exception as e:
        logger.warning("Post-gen regeneration failed: %s", e)
        return original_response
