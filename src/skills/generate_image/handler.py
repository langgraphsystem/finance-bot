"""Image generation skill — Gemini native image generation.

Uses Google Gemini Image models to generate images from text prompts.
Primary: gemini-3.1-flash-image-preview (latest, fast)
Fallback: gemini-3-pro-image-preview (high quality)
"""

import logging
from typing import Any

from google.genai import types

from src.core.context import SessionContext
from src.core.llm.clients import google_client
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_MODELS = ("gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview")


async def _generate(prompt: str, model: str) -> bytes | None:
    """Generate an image using Gemini Image API.

    Returns raw image bytes (PNG/JPG) or None if no image in response.
    """
    client = google_client()
    response = await client.aio.models.generate_content(
        model=model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
        ),
    )

    if not response.candidates:
        return None

    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data

    return None


register_strings("generate_image", {"en": {}, "ru": {}, "es": {}})


class GenerateImageSkill:
    name = "generate_image"
    intents = ["generate_image"]
    model = "gemini-3.1-flash-image-preview"

    def get_system_prompt(self, context: SessionContext) -> str:
        return (
            "You generate images from user descriptions using AI. "
            f"Respond in the user's language ({context.language or 'en'})."
        )

    @observe(name="generate_image")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        prompt = intent_data.get("image_prompt") or message.text or ""

        if not prompt.strip():
            return SkillResult(
                response_text="Describe the image you want to generate."
            )

        last_error = None
        for model_id in _MODELS:
            try:
                image_bytes = await _generate(prompt, model_id)
                if image_bytes:
                    logger.info(
                        "Image generated for user %s via %s (%d bytes)",
                        context.user_id, model_id, len(image_bytes),
                    )
                    return SkillResult(response_text="", photo_bytes=image_bytes)
            except Exception as e:
                logger.warning("Image generation failed with %s: %s", model_id, e)
                last_error = e

        logger.error("All image models failed for user %s: %s", context.user_id, last_error)
        return SkillResult(
            response_text="Failed to generate image. Try a different description."
        )


skill = GenerateImageSkill()
