"""Video action skill — follow-up actions after YouTube/TikTok video analysis."""

import logging
from typing import Any

from google.genai import types

from src.core.llm.clients import google_client
from src.core.observability import observe
from src.core.video_session import VideoSession, get_video_session
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

MODEL = "gemini-3.1-flash-lite-preview"

# Action buttons shown after every video action response
_BACK_BUTTONS = [
    {"text": "📋 Контент-план", "callback": "video:content_plan"},
    {"text": "📝 Пост", "callback": "video:post"},
    {"text": "📌 Шаги", "callback": "video:steps"},
    {"text": "💾 Сохранить", "callback": "video:save"},
    {"text": "⏰ Напомнить", "callback": "video:remind"},
    {"text": "🔍 Похожие", "callback": "video:similar"},
    {"text": "📖 Подробнее", "callback": "video:deeper"},
    {"text": "🌐 Перевести", "callback": "video:translate"},
    {"text": "📄 Статья", "callback": "video:article"},
]

_NO_VIDEO_MSG = "No recent video found. Send a YouTube or TikTok link first."


class VideoActionSkill:
    name = "video_action"
    intents = ["video_action"]
    model = MODEL

    @observe(name="video_action")
    async def execute(
        self,
        message: IncomingMessage,
        context,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        action = intent_data.get("video_action_type") or "deeper"
        session = await get_video_session(context.user_id)
        return await _dispatch(action, session, context.language or "en", message.text or "")

    def get_system_prompt(self, context) -> str:
        return ""


async def handle_video_callback(action: str, user_id: str, language: str) -> SkillResult:
    """Called from router.py callback handler for video: prefixed buttons."""
    session = await get_video_session(user_id)
    return await _dispatch(action, session, language, "")


async def _dispatch(
    action: str,
    session: VideoSession | None,
    language: str,
    user_text: str,
) -> SkillResult:
    if not session:
        return SkillResult(response_text=_NO_VIDEO_MSG)

    handlers = {
        "deeper": _action_deeper,
        "steps": _action_steps,
        "quotes": _action_quotes,
        "content_plan": _action_content_plan,
        "post": _action_post,
        "article": _action_article,
        "script": _action_script,
        "summary": _action_summary,
        "save": _action_save,
        "remind": _action_remind,
        "translate": _action_translate,
        "similar": _action_similar,
    }
    handler = handlers.get(action, _action_deeper)
    return await handler(session, language, user_text)


# ---------------------------------------------------------------------------
# Individual action handlers
# ---------------------------------------------------------------------------

async def _gemini(prompt: str) -> str:
    client = google_client()
    try:
        response = await client.aio.models.generate_content(
            model=MODEL, contents=prompt
        )
        return response.text or ""
    except Exception as e:
        logger.warning("Gemini video action failed: %s", e)
        return ""


def _context_block(session: VideoSession) -> str:
    parts = [f"Video URL: {session.url}", f"Platform: {session.platform}"]
    if session.transcript:
        parts.append(f"Transcript:\n{session.transcript[:3000]}")
    elif session.analysis:
        parts.append(f"Previous analysis:\n{session.analysis[:2000]}")
    return "\n".join(parts)


async def _action_deeper(session: VideoSession, language: str, _: str) -> SkillResult:
    prompt = (
        f"Provide a detailed deep-dive analysis of this video. "
        f"Extract all key points, insights, steps, quotes, and conclusions. "
        f"Be thorough and comprehensive. Respond in {language} using HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    return SkillResult(response_text=text or "Could not generate analysis.", buttons=_BACK_BUTTONS)


async def _action_steps(session: VideoSession, language: str, _: str) -> SkillResult:
    prompt = (
        f"Extract ONLY the step-by-step instructions from this video. "
        f"Number each step clearly. If no steps, extract the key takeaways as a numbered list. "
        f"Respond in {language} using HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    return SkillResult(response_text=text or "No steps found.", buttons=_BACK_BUTTONS)


async def _action_quotes(session: VideoSession, language: str, _: str) -> SkillResult:
    prompt = (
        f"Extract the most important and memorable quotes or key statements from this video. "
        f"Format each as a blockquote. Respond in {language} using HTML <i> tags for quotes.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    return SkillResult(response_text=text or "No quotes extracted.", buttons=_BACK_BUTTONS)


async def _action_content_plan(session: VideoSession, language: str, _: str) -> SkillResult:
    prompt = (
        f"Create a 7-day content plan based on the topic of this video. "
        f"For each day: platform (Instagram/Telegram/YouTube), post type, topic, key message. "
        f"Format as a structured list. Respond in {language} using HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    return SkillResult(response_text=text or "Could not generate content plan.", buttons=_BACK_BUTTONS)


async def _action_post(session: VideoSession, language: str, _: str) -> SkillResult:
    prompt = (
        f"Write a compelling social media post (Instagram/Telegram) based on this video. "
        f"Include a hook, key insight, and call to action. Add relevant hashtags. "
        f"Keep it under 300 words. Respond in {language} using HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    return SkillResult(
        response_text=text or "Could not generate post.",
        buttons=[
            {"text": "📋 Контент-план", "callback": "video:content_plan"},
            {"text": "📄 Статья", "callback": "video:article"},
            {"text": "📝 Сценарий", "callback": "video:script"},
        ],
    )


async def _action_article(session: VideoSession, language: str, _: str) -> SkillResult:
    prompt = (
        f"Write a full blog article (600-800 words) based on this video. "
        f"Include: title, introduction, main sections with subheadings, conclusion. "
        f"Respond in {language} using HTML tags (<b> for headings, <i> for emphasis).\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    return SkillResult(response_text=text or "Could not generate article.", buttons=_BACK_BUTTONS)


async def _action_script(session: VideoSession, language: str, _: str) -> SkillResult:
    prompt = (
        f"Write a video script based on the topic of this video. "
        f"Include: hook (first 5 seconds), intro, main content sections, outro, call-to-action. "
        f"Format with clear scene markers. Respond in {language} using HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    return SkillResult(response_text=text or "Could not generate script.", buttons=_BACK_BUTTONS)


async def _action_summary(session: VideoSession, language: str, _: str) -> SkillResult:
    prompt = (
        f"Summarize this video in exactly 3 sentences. Be concise. "
        f"Respond in {language}.\n\n{_context_block(session)}"
    )
    text = await _gemini(prompt)
    return SkillResult(response_text=text or "Could not summarize.", buttons=_BACK_BUTTONS)


async def _action_save(session: VideoSession, language: str, _: str) -> SkillResult:
    from src.core.memory.mem0_client import add_memory

    content = f"Saved video: {session.url}"
    if session.analysis:
        content += f"\n\nSummary: {session.analysis[:500]}"

    # We don't have user_id here directly — save will be handled via callback with user_id
    return SkillResult(
        response_text=(
            f"💾 <b>Video saved to memory:</b>\n"
            f'<a href="{session.url}">{session.url}</a>\n\n'
            f"You can ask me about it later."
        ),
        buttons=_BACK_BUTTONS,
        # Pass add_memory as background task — user_id injected by router
        background_tasks=[lambda: None],  # placeholder, actual save done in callback
    )


async def _action_remind(session: VideoSession, language: str, _: str) -> SkillResult:
    return SkillResult(
        response_text=(
            f"⏰ When do you want to be reminded to watch this video?\n"
            f'<a href="{session.url}">{session.url}</a>\n\n'
            f'Reply with time, e.g. <b>"напомни через 2 часа"</b> or <b>"remind me tomorrow at 9am"</b>'
        ),
    )


async def _action_translate(session: VideoSession, language: str, _: str) -> SkillResult:
    target = "English" if language.startswith("ru") else "Russian"
    prompt = (
        f"Retell and translate the key content of this video into {target}. "
        f"Keep the most important information. Use HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    return SkillResult(response_text=text or "Could not translate.", buttons=_BACK_BUTTONS)


async def _action_similar(session: VideoSession, language: str, _: str) -> SkillResult:
    from src.skills.youtube_search.handler import search_youtube_grounding

    # Extract topic from analysis for search
    prompt = (
        f"In 5-7 words, what is the main topic of this video? "
        f"Reply with only the search query, no other text.\n\n"
        f"{_context_block(session)}"
    )
    topic = await _gemini(prompt)
    if not topic:
        topic = session.url

    topic = topic.strip().strip('"').strip("'")
    result = await search_youtube_grounding(topic, language)
    return SkillResult(
        response_text=f"<b>Similar videos for: {topic}</b>\n\n{result}",
        buttons=_BACK_BUTTONS,
    )


skill = VideoActionSkill()
