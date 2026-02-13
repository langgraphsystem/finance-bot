"""Embedding generation for transactions (text-embedding-3-small)."""
import logging

from src.core.llm.clients import openai_client
from src.core.observability import observe

logger = logging.getLogger(__name__)


@observe(name="get_embedding")
async def get_embedding(text: str) -> list[float]:
    """Generate embedding for text using OpenAI text-embedding-3-small."""
    client = openai_client()
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding
