"""Circuit breaker pattern for external service protection.

Prevents cascading failures when external services (LLM APIs, Mem0, Redis)
are down. Tracks failure counts and automatically stops calling failed
services for a recovery period.

States:
    CLOSED  → Normal operation, requests pass through
    OPEN    → Service failing, requests short-circuited
    HALF_OPEN → Testing recovery, limited requests allowed
"""

import logging
import time
from enum import StrEnum

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    __slots__ = (
        "name",
        "state",
        "failure_count",
        "failure_threshold",
        "recovery_timeout",
        "last_failure_time",
        "half_open_calls",
        "half_open_max_calls",
        "total_trips",
    )

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = 0.0
        self.half_open_calls = 0
        self.half_open_max_calls = half_open_max_calls
        self.total_trips = 0

    def can_execute(self) -> bool:
        """Check if a request should be allowed through."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                logger.info("Circuit %s → HALF_OPEN after %.1fs recovery", self.name, elapsed)
                return True
            return False

        # HALF_OPEN — allow limited calls to test recovery
        return self.half_open_calls < self.half_open_max_calls

    def record_success(self) -> None:
        """Record a successful call — resets failure count, closes circuit."""
        if self.state == CircuitState.HALF_OPEN:
            logger.info("Circuit %s → CLOSED (recovered)", self.name)
            self.state = CircuitState.CLOSED
        self.failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call — may trip the circuit open."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.total_trips += 1
            logger.warning("Circuit %s → OPEN (half-open test failed)", self.name)
            return

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.total_trips += 1
            logger.warning(
                "Circuit %s → OPEN after %d failures (threshold=%d)",
                self.name,
                self.failure_count,
                self.failure_threshold,
            )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0

    def status(self) -> dict:
        """Return circuit status for health checks."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "total_trips": self.total_trips,
        }


# Named circuit breakers for key external services
circuits: dict[str, CircuitBreaker] = {
    "mem0": CircuitBreaker("mem0", failure_threshold=3, recovery_timeout=30.0),
    "anthropic": CircuitBreaker("anthropic", failure_threshold=3, recovery_timeout=60.0),
    "openai": CircuitBreaker("openai", failure_threshold=3, recovery_timeout=60.0),
    "google": CircuitBreaker("google", failure_threshold=3, recovery_timeout=60.0),
    "redis": CircuitBreaker("redis", failure_threshold=5, recovery_timeout=15.0),
}


def get_circuit(name: str) -> CircuitBreaker:
    """Get a named circuit breaker. Creates one if not found."""
    if name not in circuits:
        circuits[name] = CircuitBreaker(name)
    return circuits[name]


def all_circuit_statuses() -> dict[str, dict]:
    """Return status of all circuits for health monitoring."""
    return {name: cb.status() for name, cb in circuits.items()}
