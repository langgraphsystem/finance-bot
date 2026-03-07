"""YouTube search skill — dual-mode: Gemini Search Grounding (quick) + YouTube API (detailed)."""

import asyncio
import logging
import re
from typing import Any

import httpx
from google.genai import types

from src.core.config import settings
from src.core.context import SessionContext
from src.core.llm.clients import google_client
from src.core.observability import observe
from src.core.video_session import VideoSession, save_video_session
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings
from src.skills.base import SkillResult
from src.skills.video_action.i18n import get_video_buttons

logger = logging.getLogger(__name__)

# Regex to detect YouTube URLs in text
_YT_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:"
    r"youtube\.com/(?:watch\?v=|shorts/|live/|embed/)"
    r"|youtu\.be/"
    r"|m\.youtube\.com/watch\?v="
    r")[\w\-]+",
)

# Regex to detect TikTok URLs in text
_TT_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:"
    r"tiktok\.com/@[\w.\-]+/video/\d+"
    r"|tiktok\.com/t/[\w\-]+"
    r"|vm\.tiktok\.com/[\w\-]+"
    r"|vt\.tiktok\.com/[\w\-]+"
    r")",
)

YOUTUBE_GROUNDING_PROMPT = """\
You are a YouTube research assistant with access to Google Search.
You can find videos, analyze their content, describe what's in them, \
and extract key information including transcripts.

Rules:
- Show MAXIMUM 3 videos. No more than 3 — this is for a phone screen.
- Analyze each video in depth — describe what it covers, \
extract key steps, tips, conclusions, or transcription highlights.
- For tutorials: list the key steps clearly with numbers.
- For reviews: highlight pros, cons, and the bottom-line verdict.
- For product videos: mention price, features, and recommendation.
- Show video title (bold), channel name, and a YouTube URL.
- Use HTML tags for Telegram (<b>bold</b>, <i>italic</i>). No Markdown.
- ALWAYS respond in the same language as the user's message/query."""

YOUTUBE_API_PROMPT = """\
You are a YouTube research assistant. Summarize video content for the user.

Rules:
- Lead with the most useful information from the videos.
- For tutorials: list key steps clearly with numbers.
- For reviews: highlight pros, cons, and a bottom-line verdict.
- Cite the video title when referencing specific content.
- Always include the video URL as a clickable link.
- Present ALL videos from the list — the user asked for a detailed list.
- Use bullet points for steps or comparisons.
- Use HTML tags for Telegram (<b>bold</b>, <i>italic</i>). No Markdown.
- ALWAYS respond in the same language as the user's message/query."""

YOUTUBE_ANALYZE_PROMPT = """\
You are a YouTube video analyst with access to Google Search.
The user sent a specific YouTube video link. Analyze this video in depth.

Rules:
- Describe what the video is about and what it covers.
- For tutorials: list the key steps clearly with numbers.
- For reviews: highlight pros, cons, and the bottom-line verdict.
- For music: mention the artist, song name, and genre.
- For lectures/talks: summarize the main points and conclusions.
- Extract key insights, tips, or transcription highlights.
- Show video title (bold), channel name, view count if available.
- Include the original YouTube URL as a clickable link.
- Use HTML tags for Telegram (<b>bold</b>, <i>italic</i>). No Markdown.
- ALWAYS respond in the same language as the user's message/query."""

YOUTUBE_NATIVE_ANALYZE_PROMPT = """\
You are directly watching a YouTube video. Analyze what you see and hear in the video itself.

Rules:
- Summarize the main topic and key points from the actual video content.
- For tutorials: list numbered steps extracted from what is shown/said in the video.
- For reviews: extract pros, cons, and verdict from the video content itself.
- For lectures/talks: summarize the arguments and conclusions presented.
- For music: identify the artist, song, genre, and mood from what you hear.
- If the user asks a specific question, answer it using the video content.
- Show the video title (bold) if identifiable. Include the original URL as a clickable link.
- Use HTML tags for Telegram (<b>bold</b>, <i>italic</i>). No Markdown.
- ALWAYS respond in the same language as the user's message."""

YT_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

MAX_TRANSCRIPT_SEGMENTS = 150
MAX_TRANSCRIPT_CHARS = 3000

FALLBACK_NOTE = (
    "\n\n<i>Based on Google Search — for bulk video lists, configure YOUTUBE_API_KEY.</i>"
)


register_strings("youtube_search", {"en": {}, "ru": {}, "es": {}})


class YouTubeSearchSkill:
    name = "youtube_search"
    intents = ["youtube_search"]
    model = "gemini-3.1-flash-lite-preview"

    @observe(name="youtube_search")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = (
            intent_data.get("youtube_query")
            or intent_data.get("search_topic")
            or intent_data.get("search_query")
            or message.text
            or ""
        ).strip()

        if not query:
            return SkillResult(response_text="What would you like me to find on YouTube?")

        language = context.language or "en"

        # Check if query contains a YouTube URL → analyze that specific video
        yt_url = extract_youtube_url(query)
        if yt_url:
            answer = await analyze_youtube_url(yt_url, query, language)
            session = VideoSession(
                url=yt_url,
                platform="youtube",
                analysis=answer,
                language=language,
            )
            await save_video_session(context.user_id, session)
            return SkillResult(response_text=answer, buttons=get_video_buttons(language))

        # Check if query contains a TikTok URL → analyze that video
        tt_url = extract_tiktok_url(query)
        if tt_url:
            answer = await analyze_tiktok_url(tt_url, query, language)
            session = VideoSession(
                url=tt_url,
                platform="tiktok",
                analysis=answer,
                language=language,
            )
            await save_video_session(context.user_id, session)
            return SkillResult(response_text=answer, buttons=get_video_buttons(language))

        detail_mode = bool(intent_data.get("detail_mode"))
        has_api_key = bool(settings.youtube_api_key)

        if detail_mode and has_api_key:
            answer = await search_youtube(query, language)
        else:
            answer = await search_youtube_grounding(query, language)

        return SkillResult(response_text=answer)

    def get_system_prompt(self, context: SessionContext) -> str:
        return YOUTUBE_GROUNDING_PROMPT.format(language=context.language or "en")


# ---------------------------------------------------------------------------
# Quick mode: Gemini + Google Search Grounding
# ---------------------------------------------------------------------------


async def search_youtube_grounding(query: str, language: str) -> str:
    """Search YouTube via Gemini with Google Search grounding."""
    client = google_client()
    system = YOUTUBE_GROUNDING_PROMPT.format(language=language)
    prompt = f"{system}\n\nFind YouTube videos about: {query}"

    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        text = response.text or ""
        if text:
            return text
    except Exception as e:
        logger.warning("Gemini YouTube grounding failed: %s, falling back to LLM", e)

    # Fallback: Gemini without grounding
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
        )
        text = response.text or ""
        if text:
            return text + FALLBACK_NOTE
    except Exception as e:
        logger.error("Gemini YouTube fallback also failed: %s", e)

    return "I couldn't find videos. Try again or rephrase your query?"


# ---------------------------------------------------------------------------
# URL analysis mode: Gemini analyses a specific YouTube video
# ---------------------------------------------------------------------------


def extract_youtube_url(text: str) -> str | None:
    """Extract the first YouTube URL from text, or None."""
    m = _YT_URL_RE.search(text)
    return m.group(0) if m else None


def extract_tiktok_url(text: str) -> str | None:
    """Extract the first TikTok URL from text, or None."""
    m = _TT_URL_RE.search(text)
    return m.group(0) if m else None


async def download_tiktok_audio(url: str) -> tuple[bytes, str] | None:
    """Download TikTok audio using yt-dlp. Returns (audio_bytes, filename) or None."""
    import os
    import tempfile

    import yt_dlp

    def _download() -> tuple[bytes, str] | None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_tpl = os.path.join(tmpdir, "audio.%(ext)s")
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": output_tpl,
                "noplaylist": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    return None
            for fname in os.listdir(tmpdir):
                fpath = os.path.join(tmpdir, fname)
                with open(fpath, "rb") as f:
                    return f.read(), fname
        return None

    return await asyncio.to_thread(_download)


async def transcribe_tiktok(url: str) -> str:
    """Download TikTok audio and transcribe with Whisper. Returns transcript or ''."""
    from src.core.voice import transcribe_video_audio

    try:
        result = await download_tiktok_audio(url)
        if not result:
            return ""
        audio_bytes, filename = result
        return await transcribe_video_audio(audio_bytes, filename)
    except Exception as e:
        logger.warning("TikTok audio transcription failed: %s", e)
        return ""


async def analyze_tiktok_url(url: str, user_text: str, language: str) -> str:
    """Analyze a TikTok video URL.

    Downloads audio via yt-dlp → transcribes with Whisper → Gemini summarizes.
    Falls back to Google Search grounding if download/transcription fails.
    """
    client = google_client()
    extra = user_text.replace(url, "").strip()
    user_request = extra or "Summarize this video."

    # Primary: download audio → transcribe → Gemini summarizes transcript
    transcript = await transcribe_tiktok(url)
    if transcript:
        prompt = (
            f"{YOUTUBE_NATIVE_ANALYZE_PROMPT}\n\n"
            f"This is a TikTok video transcript:\n{transcript[:4000]}\n\n"
            f"Video URL: {url}\n"
            f"User request: {user_request}\n"
            f"Respond in language: {language}"
        )
        try:
            response = await client.aio.models.generate_content(
                model="gemini-3.1-flash-lite-preview",
                contents=prompt,
            )
            text = response.text or ""
            if text:
                return text
        except Exception as e:
            logger.warning("Gemini TikTok transcript analysis failed: %s", e)

    # Fallback: Google Search grounding
    extra_part = f"\nUser's comment: {extra}" if extra else ""
    prompt = f"{YOUTUBE_ANALYZE_PROMPT}\n\nAnalyze this TikTok video: {url}{extra_part}"
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        text = response.text or ""
        if text:
            return text
    except Exception as e:
        logger.warning("TikTok grounding fallback failed: %s", e)

    return f'Could not analyze the video. Try opening it directly: <a href="{url}">{url}</a>'


async def analyze_youtube_native(url: str, user_text: str, language: str) -> str:
    """Analyze a YouTube video using Gemini's native video understanding.

    Passes the YouTube URL as a fileData part — Gemini watches the actual video
    content (audio + visuals) rather than searching for information about it.
    """
    client = google_client()
    extra = user_text.replace(url, "").strip()
    user_prompt = extra or "Analyze and summarize this video."
    prompt = (
        f"{YOUTUBE_NATIVE_ANALYZE_PROMPT}\n\n"
        f"User request: {user_prompt}\n"
        f"Video URL: {url}\n"
        f"Respond in language: {language}"
    )
    response = await client.aio.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        contents=types.Content(
            parts=[
                types.Part(file_data=types.FileData(file_uri=url, mime_type="video/*")),
                types.Part(text=prompt),
            ]
        ),
    )
    return response.text or ""


async def analyze_youtube_url(url: str, user_text: str, language: str) -> str:
    """Analyze a specific YouTube video URL.

    Tries native Gemini video understanding first (watches the actual video),
    falls back to Google Search grounding if native processing fails.
    """
    # Primary: native video processing — Gemini watches the video directly
    try:
        text = await analyze_youtube_native(url, user_text, language)
        if text:
            return text
    except Exception as e:
        logger.warning("Gemini native video processing failed: %s, falling back to grounding", e)

    # Fallback: Google Search grounding — finds info about the video
    client = google_client()
    system = YOUTUBE_ANALYZE_PROMPT.format(language=language)
    extra = user_text.replace(url, "").strip()
    extra_part = f"\nUser's comment: {extra}" if extra else ""
    prompt = f"{system}\n\nAnalyze this YouTube video: {url}{extra_part}"

    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        text = response.text or ""
        if text:
            return text
    except Exception as e:
        logger.warning("Gemini YouTube grounding fallback also failed: %s", e)

    return f'Could not analyze the video. Try opening it directly: <a href="{url}">{url}</a>'


# ---------------------------------------------------------------------------
# Detailed mode: YouTube Data API v3 + transcript + Gemini summarization
# ---------------------------------------------------------------------------


async def search_youtube(query: str, language: str) -> str:
    """Search YouTube for top 3 videos, fetch transcript, summarize with Gemini."""
    api_key = settings.youtube_api_key

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                YT_SEARCH_URL,
                params={
                    "part": "snippet",
                    "q": query,
                    "key": api_key,
                    "maxResults": 3,
                    "type": "video",
                    "relevanceLanguage": language[:2],
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("YouTube search API failed: %s", e)
            return "Could not reach YouTube. Try again later."

    items = data.get("items", [])
    if not items:
        return f"No videos found for: <b>{query}</b>"

    videos = [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "description": item["snippet"]["description"][:200],
            "url": f"https://youtube.com/watch?v={item['id']['videoId']}",
        }
        for item in items
    ]

    transcript_text = await _get_transcript(videos[0]["id"])
    return await _summarize_with_gemini(query, videos, transcript_text, language)


async def _get_transcript(video_id: str) -> str | None:
    """Fetch YouTube transcript using youtube-transcript-api (sync → thread)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        def _fetch() -> str:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "ru", "es"])
            return " ".join(entry["text"] for entry in transcript[:MAX_TRANSCRIPT_SEGMENTS])

        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.debug("Transcript not available for %s: %s", video_id, e)
        return None


async def _summarize_with_gemini(
    query: str,
    videos: list[dict],
    transcript: str | None,
    language: str,
) -> str:
    """Summarize YouTube results with Gemini Flash."""
    client = google_client()
    system = YOUTUBE_API_PROMPT.format(language=language)

    videos_block = "\n\n".join(
        f"Title: {v['title']}\nChannel: {v['channel']}\n"
        f"URL: {v['url']}\nDescription: {v['description']}"
        for v in videos
    )

    transcript_block = (
        f"\n\nTranscript excerpt from top video:\n{transcript[:MAX_TRANSCRIPT_CHARS]}"
        if transcript
        else ""
    )

    prompt = (
        f"{system}\n\n"
        f"User searched for: {query}\n\n"
        f"Found videos:\n{videos_block}"
        f"{transcript_block}\n\n"
        "Summarize what these videos cover. "
        "If a transcript is available, extract the most useful steps or insights. "
        "Always include the video URL as a link."
    )

    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
        )
        return response.text or _html_fallback(videos)
    except Exception as e:
        logger.warning("Gemini YouTube summary failed: %s", e)
        return _html_fallback(videos)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _html_fallback(videos: list[dict]) -> str:
    lines = ["<b>YouTube results:</b>", ""]
    for v in videos:
        lines.append(f"<b>{v['title']}</b> — {v['channel']}")
        lines.append(f'<a href="{v["url"]}">Watch on YouTube</a>')
        lines.append("")
    return "\n".join(lines).strip()


skill = YouTubeSearchSkill()
