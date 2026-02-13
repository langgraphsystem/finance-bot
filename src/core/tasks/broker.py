"""Taskiq broker configuration."""

from taskiq_redis import ListQueueBroker

from src.core.config import settings

broker = ListQueueBroker(url=settings.redis_url)
