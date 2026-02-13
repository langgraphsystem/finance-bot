"""Exception hierarchy for Finance Bot."""


class FinanceBotError(Exception):
    """Base exception for all Finance Bot errors."""
    pass


class LLMError(FinanceBotError):
    """LLM API call failed."""
    pass


class LLMFallbackError(LLMError):
    """Both primary and fallback LLM failed."""
    pass


class DatabaseError(FinanceBotError):
    """Database operation failed."""
    pass


class UnauthorizedError(FinanceBotError):
    """User is not authorized."""
    pass


class RateLimitError(FinanceBotError):
    """Rate limit exceeded."""
    pass


class OCRError(FinanceBotError):
    """OCR processing failed."""
    pass


class ValidationError(FinanceBotError):
    """Data validation failed."""
    pass
