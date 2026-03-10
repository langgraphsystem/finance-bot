"""Dual-search executor: Gemini + Grok in parallel, Gemini synthesizes."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from src.core.config import settings

logger = logging.getLogger(__name__)

_GROK_TIMEOUT_SECONDS = 15

_GROK_SEARCH_SYSTEM = (
    "You are a web search assistant. Search the web and return factual, "
    "up-to-date information. Include specific numbers, prices, dates, "
    "and source references where possible. Be concise — max 10 bullet points."
)

_SYNTHESIS_TEMPLATE = """\
Merge two search results into ONE unified response.

Rules:
- Lead with the most relevant answer
- Deduplicate — do NOT repeat facts from both sources
- If sources disagree, note both viewpoints
- Telegram HTML only (<b>, <i>). No Markdown.
- Respond in {language}
- Max 15 lines, scannable bullets

Source 1 (Google):
{gemini_result}

Source 2 (Grok):
{grok_result}

User query: {query}"""

_ERROR_MESSAGES: dict[str, str] = {
    "en": "Could not retrieve search results. Please try again.",
    "ru": "Не удалось получить результаты поиска. Попробуйте ещё раз.",
    "es": "No se pudieron obtener los resultados de búsqueda. Inténtelo de nuevo.",
    "de": "Suchergebnisse konnten nicht abgerufen werden. Bitte versuchen Sie es erneut.",
    "fr": "Impossible de récupérer les résultats de recherche. Veuillez réessayer.",
    "pt": "Não foi possível obter os resultados da pesquisa. Tente novamente.",
    "it": "Impossibile recuperare i risultati della ricerca. Riprova.",
    "tr": "Arama sonuçları alınamadı. Lütfen tekrar deneyin.",
    "uk": "Не вдалося отримати результати пошуку. Спробуйте ще раз.",
    "kk": "Іздеу нәтижелерін алу мүмкін болмады. Қайта көріңіз.",
    "pl": "Nie udało się pobrać wyników wyszukiwania. Spróbuj ponownie.",
    "ar": "تعذر الحصول على نتائج البحث. يرجى المحاولة مرة أخرى.",
    "zh": "无法获取搜索结果，请重试。",
    "ja": "検索結果を取得できませんでした。もう一度お試しください。",
    "ko": "검색 결과를 가져올 수 없습니다. 다시 시도해 주세요.",
    "th": "ไม่สามารถดึงผลการค้นหาได้ กรุณาลองใหม่อีกครั้ง",
    "vi": "Không thể lấy kết quả tìm kiếm. Vui lòng thử lại.",
    "id": "Tidak dapat mengambil hasil pencarian. Silakan coba lagi.",
}


async def _grok_web_search(query: str, language: str) -> str:
    """Search via Grok with built-in web search (Responses API)."""
    from src.core.llm.clients import xai_client

    client = xai_client()
    lang_instruction = f" Respond in {language}." if language != "en" else ""
    system_msg = _GROK_SEARCH_SYSTEM + lang_instruction
    logger.debug(
        "grok_web_search: model=%s query_len=%d", settings.grok_dual_search_model, len(query),
    )
    response = await client.responses.create(
        model=settings.grok_dual_search_model,
        instructions=system_msg,
        input=[{"role": "user", "content": query}],
        tools=[{"type": "web_search"}],
    )
    # Extract text from response output items
    parts: list[str] = []
    for item in response.output:
        if hasattr(item, "text"):
            parts.append(item.text)
        elif hasattr(item, "content") and item.content:
            for block in item.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
    return "\n".join(parts) or ""


async def _gemini_synthesize(
    gemini_result: str,
    grok_result: str,
    query: str,
    language: str,
) -> str:
    """Use Gemini Flash Lite to merge both search results."""
    from google.genai import types

    from src.core.llm.clients import google_client

    client = google_client()
    prompt = _SYNTHESIS_TEMPLATE.format(
        gemini_result=gemini_result,
        grok_result=grok_result,
        query=query,
        language=language,
    )
    response = await client.aio.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=1200),
    )
    return response.text or ""


async def dual_search(
    query: str,
    language: str,
    original_message: str = "",
    *,
    gemini_searcher: Callable[..., Coroutine[Any, Any, str]],
    trace_user_id: str = "",
) -> str:
    """Run Gemini + Grok search in parallel, synthesize via Gemini.

    Args:
        query: Search query text.
        language: User language code (en/ru/es).
        original_message: Original user message for context.
        gemini_searcher: Existing search function (e.g., search_and_answer).
        trace_user_id: User ID for logging.

    Returns:
        Synthesized search result text.
    """
    # Guard: no xAI key or feature flag off → Gemini only
    if not settings.xai_api_key or not settings.ff_dual_search:
        return await gemini_searcher(query, language, original_message)

    t0 = time.monotonic()

    gemini_result, grok_result = await asyncio.gather(
        gemini_searcher(query, language, original_message),
        asyncio.wait_for(_grok_web_search(query, language), timeout=_GROK_TIMEOUT_SECONDS),
        return_exceptions=True,
    )

    gemini_ok = isinstance(gemini_result, str) and gemini_result.strip()
    grok_ok = isinstance(grok_result, str) and grok_result.strip()

    elapsed = time.monotonic() - t0
    logger.info(
        "dual_search: gemini_ok=%s grok_ok=%s elapsed=%.2fs user=%s grok_model=%s",
        gemini_ok, grok_ok, elapsed, trace_user_id, settings.grok_dual_search_model,
    )

    if gemini_ok and grok_ok:
        try:
            synthesized = await _gemini_synthesize(
                gemini_result, grok_result, query, language,
            )
            if synthesized.strip():
                return synthesized
        except Exception:
            logger.exception("dual_search: synthesis failed, returning gemini result")
        return gemini_result

    if gemini_ok:
        return gemini_result

    if grok_ok:
        return grok_result

    # Both failed
    lang = language if language in _ERROR_MESSAGES else "en"
    return _ERROR_MESSAGES[lang]
