"""Research domain orchestrator — web search, answers, comparisons."""

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator

SYSTEM_PROMPT = """\
You answer questions, search the web, compare options, and find places/videos.
Lead with the answer. Be concise: 1-5 sentences for facts, bullet points for comparisons.
For maps_search and youtube_search, provide structured results with key details.
Use HTML tags for Telegram (<b>bold</b>, <i>italic</i>). No Markdown."""

research_orchestrator = DeepAgentOrchestrator(
    domain=Domain.research,
    model="gemini-3-flash-preview",
    skill_names=[
        "quick_answer",
        "web_search",
        "compare_options",
        "maps_search",
        "youtube_search",
        "price_check",
        "web_action",
        "browser_action",
    ],
    system_prompt=SYSTEM_PROMPT,
    context_config={"mem": False, "hist": 3, "sql": False, "sum": False},
)
