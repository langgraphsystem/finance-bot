"""Tests for user profile auto-learning task."""

from src.core.tasks.profile_tasks import MIN_MESSAGES_FOR_LEARNING


def test_min_messages_constant():
    assert MIN_MESSAGES_FOR_LEARNING == 10
