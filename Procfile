web: alembic upgrade head && python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python -m taskiq worker src.core.tasks.broker:broker
