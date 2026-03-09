"""Video action skill — follow-up actions after YouTube/TikTok video analysis."""

import logging
from typing import Any

from src.core.llm.clients import google_client
from src.core.observability import observe
from src.core.video_session import VideoSession, get_video_session, update_video_session_last_text
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.video_action.i18n import get_video_buttons, get_writing_buttons, t

logger = logging.getLogger(__name__)

MODEL = "gemini-3.1-flash-lite-preview"


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
        language = context.language or "en"
        return await _dispatch(action, session, language, message.text or "", context.user_id)

    def get_system_prompt(self, context) -> str:
        return ""


async def handle_video_callback(action: str, user_id: str, language: str) -> SkillResult:
    """Called from router.py callback handler for video: prefixed buttons."""
    session = await get_video_session(user_id)
    return await _dispatch(action, session, language, "", user_id)


async def _dispatch(
    action: str,
    session: VideoSession | None,
    language: str,
    user_text: str,
    user_id: str,
) -> SkillResult:
    if not session:
        return SkillResult(response_text=t("no_video", language))

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
        "save_content": _action_save_content,
        "remind": _action_remind,
        "translate": _action_translate,
        "similar": _action_similar,
    }
    handler = handlers.get(action, _action_deeper)
    return await handler(session, language, user_text, user_id)


# ---------------------------------------------------------------------------
# Internal helpers
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


def _save_content_btn(language: str) -> dict:
    return {"text": t("btn_save_content", language), "callback": "video:save_content"}


def _buttons_with_save(language: str) -> list[dict]:
    """Video action buttons with save_content prepended (replaces video:save slot)."""
    buttons = get_video_buttons(language)
    # Replace the last btn (video:save) with save_content so user can save the generated text
    without_save = [b for b in buttons if b["callback"] != "video:save"]
    return [_save_content_btn(language)] + without_save


# ---------------------------------------------------------------------------
# Individual action handlers
# ---------------------------------------------------------------------------

async def _action_deeper(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    prompt = (
        f"Provide a detailed deep-dive analysis of this video. "
        f"Extract all key points, insights, steps, quotes, and conclusions. "
        f"Be thorough and comprehensive. Respond in {language} using HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    if text:
        await update_video_session_last_text(user_id, text)
    return SkillResult(
        response_text=text or t("err_analysis", language),
        buttons=_buttons_with_save(language),
    )


async def _action_steps(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    prompt = (
        f"Extract ONLY the step-by-step instructions from this video. "
        f"Number each step clearly. If no steps, extract the key takeaways as a numbered list. "
        f"Respond in {language} using HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    if text:
        await update_video_session_last_text(user_id, text)
    return SkillResult(
        response_text=text or t("err_steps", language),
        buttons=_buttons_with_save(language),
    )


async def _action_quotes(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    prompt = (
        f"Extract the most important and memorable quotes or key statements from this video. "
        f"Format each as a blockquote. Respond in {language} using HTML <i> tags for quotes.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    if text:
        await update_video_session_last_text(user_id, text)
    return SkillResult(
        response_text=text or t("err_quotes", language),
        buttons=_buttons_with_save(language),
    )


async def _action_content_plan(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    prompt = (
        f"Create a 7-day content plan based on the topic of this video. "
        f"For each day: platform (Instagram/Telegram/YouTube), post type, topic, key message. "
        f"Format as a structured list. Respond in {language} using HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    if text:
        await update_video_session_last_text(user_id, text)
    return SkillResult(
        response_text=text or t("err_content_plan", language),
        buttons=_buttons_with_save(language),
    )


async def _action_post(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    prompt = (
        f"Write a compelling social media post (Instagram/Telegram) based on this video. "
        f"Include a hook, key insight, and call to action. Add relevant hashtags. "
        f"Keep it under 300 words. Respond in {language} using HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    if text:
        await update_video_session_last_text(user_id, text)
    return SkillResult(
        response_text=text or t("err_post", language),
        buttons=[_save_content_btn(language)] + get_writing_buttons(language),
    )


async def _action_article(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    prompt = (
        f"Write a full blog article (600-800 words) based on this video. "
        f"Include: title, introduction, main sections with subheadings, conclusion. "
        f"Respond in {language} using HTML tags (<b> for headings, <i> for emphasis).\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    if text:
        await update_video_session_last_text(user_id, text)
    return SkillResult(
        response_text=text or t("err_article", language),
        buttons=_buttons_with_save(language),
    )


async def _action_script(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    prompt = (
        f"Write a video script based on the topic of this video. "
        f"Include: hook (first 5 seconds), intro, main content sections, outro, call-to-action. "
        f"Format with clear scene markers. Respond in {language} using HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    if text:
        await update_video_session_last_text(user_id, text)
    return SkillResult(
        response_text=text or t("err_script", language),
        buttons=_buttons_with_save(language),
    )


async def _action_summary(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    prompt = (
        f"Summarize this video in exactly 3 sentences. Be concise. "
        f"Respond in {language}.\n\n{_context_block(session)}"
    )
    text = await _gemini(prompt)
    if text:
        await update_video_session_last_text(user_id, text)
    return SkillResult(
        response_text=text or t("err_summary", language),
        buttons=_buttons_with_save(language),
    )


async def _action_save(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    """Save the video URL + analysis to Mem0. Actual write happens in router.py callback."""
    return SkillResult(
        response_text=(
            f'💾 <b>{t("saved_title", language)}</b>\n'
            f'<a href="{session.url}">{session.url}</a>\n\n'
            f'{t("saved_note", language)}'
        ),
        buttons=get_video_buttons(language),
        background_tasks=[lambda: None],  # actual Mem0 write done in router.py
    )


async def _action_save_content(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    """Save the last generated text (content plan / post / article / etc) to Mem0.
    Actual Mem0 write is handled in router.py callback with the correct user_id."""
    last_text = session.extra.get("last_text", "")
    if not last_text:
        # Fallback: save video URL if no generated content yet
        return await _action_save(session, language, _, user_id)
    return SkillResult(
        response_text=(
            f'💾 <b>{t("saved_content_title", language)}</b>\n'
            f'{t("saved_note", language)}'
        ),
        buttons=get_video_buttons(language),
        background_tasks=[lambda: None],  # actual Mem0 write done in router.py
    )


async def _action_remind(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    return SkillResult(
        response_text=(
            f'⏰ {t("remind_prompt", language)}\n'
            f'<a href="{session.url}">{session.url}</a>\n\n'
            f'{t("remind_hint", language)}'
        ),
    )


async def _action_translate(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    target = "English" if language.startswith("ru") or language.startswith("es") else "Russian"
    prompt = (
        f"Retell and translate the key content of this video into {target}. "
        f"Keep the most important information. Use HTML tags.\n\n"
        f"{_context_block(session)}"
    )
    text = await _gemini(prompt)
    if text:
        await update_video_session_last_text(user_id, text)
    return SkillResult(
        response_text=text or t("err_translate", language),
        buttons=_buttons_with_save(language),
    )


async def _action_similar(
    session: VideoSession, language: str, _: str, user_id: str
) -> SkillResult:
    from src.skills.youtube_search.handler import search_youtube_grounding

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
        response_text=f'<b>{t("similar_title", language)} {topic}</b>\n\n{result}',
        buttons=get_video_buttons(language),
    )


skill = VideoActionSkill()
