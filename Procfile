web: alembic upgrade head && python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python -m taskiq worker src.core.tasks.broker:broker src.core.tasks.memory_tasks src.core.tasks.notification_tasks src.core.tasks.life_tasks src.core.tasks.reminder_tasks src.core.tasks.profile_tasks src.core.tasks.proactivity_tasks src.core.tasks.booking_tasks
