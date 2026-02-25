"""Writing domain orchestrator — drafts, translations, posts, proofreading."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You help users write: draft messages, translate text, write posts/reviews,
proofread, generate cards, and create/modify programs.
Match the tone to the context (formal email vs casual text vs professional review response).
Write the content directly — no preamble.
Use HTML tags for Telegram (<b>bold</b>). No Markdown."""

writing_orchestrator = DeepAgentOrchestrator(
    domain=Domain.writing,
    model="claude-sonnet-4-6",
    skill_names=[
        "draft_message",
        "translate_text",
        "write_post",
        "proofread",
        "generate_card",
        "generate_program",
        "modify_program",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": "profile", "hist": 5, "sql": False, "sum": False},
)
