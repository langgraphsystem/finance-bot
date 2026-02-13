import logging

from langfuse import Langfuse, observe

from src.core.config import settings

logger = logging.getLogger(__name__)

_langfuse: Langfuse | None = None


def get_langfuse() -> Langfuse | None:
    global _langfuse
    if _langfuse is None and settings.langfuse_public_key:
        try:
            _langfuse = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
        except Exception as e:
            logger.warning("Failed to init Langfuse: %s", e)
    return _langfuse


# Re-export the decorator for use in other modules
__all__ = ["observe", "get_langfuse"]
