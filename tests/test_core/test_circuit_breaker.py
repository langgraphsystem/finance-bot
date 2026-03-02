"""Tests for circuit breaker pattern."""

from src.core.circuit_breaker import CircuitBreaker, CircuitState, all_circuit_statuses, circuits


def test_initial_state():
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=1.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True
    assert cb.failure_count == 0
    assert cb.total_trips == 0


def test_stays_closed_under_threshold():
    cb = CircuitBreaker("test", failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True


def test_opens_at_threshold():
    cb = CircuitBreaker("test", failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False
    assert cb.total_trips == 1


def test_success_resets_count():
    cb = CircuitBreaker("test", failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.failure_count == 0
    assert cb.state == CircuitState.CLOSED


def test_half_open_after_recovery(monkeypatch):
    import time

    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Simulate time passing
    cb.last_failure_time = time.monotonic() - 1.0
    assert cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN


def test_half_open_success_closes():
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
    cb.state = CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_half_open_failure_reopens():
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
    cb.state = CircuitState.HALF_OPEN
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.total_trips == 1


def test_manual_reset():
    cb = CircuitBreaker("test", failure_threshold=1)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    cb.reset()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


def test_status_dict():
    cb = CircuitBreaker("test_svc", failure_threshold=5)
    status = cb.status()
    assert status["name"] == "test_svc"
    assert status["state"] == "closed"
    assert status["failure_threshold"] == 5


def test_named_circuits_exist():
    assert "mem0" in circuits
    assert "anthropic" in circuits
    assert "openai" in circuits
    assert "google" in circuits
    assert "redis" in circuits


def test_all_circuit_statuses():
    statuses = all_circuit_statuses()
    assert isinstance(statuses, dict)
    assert "mem0" in statuses
    assert statuses["mem0"]["state"] == "closed"
