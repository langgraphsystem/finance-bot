"""Complexity router — decides whether a request needs a deep-agent orchestrator.

For generate_program: simple requests (short, single-component) use the
existing single-pass skill. Complex requests (long, multi-component, full-stack)
are routed to the ProgramOrchestrator.
"""

DEEP_AGENT_INTENTS: set[str] = {"generate_program"}

# Keywords indicating multi-component or architectural complexity
_MULTI_KEYWORDS = {"и ", " плюс ", " also ", " and ", "with ", "с "}
_COMPLEX_KEYWORDS = {
    "полный", "комплексный", "архитектура", "full", "complete",
    "full-stack", "fullstack", "rest api", "database", "auth",
    "авторизация", "authentication", "database", "базой данных",
    "микросервис", "microservice",
}


def classify_complexity(message: str, intent: str) -> bool:
    """Return True if this request needs a deep-agent orchestrator.

    Thresholds for generate_program:
    - message > 80 words, OR
    - multi-component keywords present AND message > 40 words, OR
    - architectural keywords present
    """
    if intent not in DEEP_AGENT_INTENTS:
        return False

    lower = message.lower()
    words = len(message.split())

    has_multi = any(kw in lower for kw in _MULTI_KEYWORDS)
    has_complex_kw = any(kw in lower for kw in _COMPLEX_KEYWORDS)

    if words > 80:
        return True
    if has_multi and words > 40:
        return True
    if has_complex_kw:
        return True
    return False
