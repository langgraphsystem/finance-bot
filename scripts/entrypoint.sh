#!/bin/bash
set -e

PROCESS_TYPE="${RAILWAY_PROCESS_TYPE:-web}"

if [ "$PROCESS_TYPE" = "worker" ]; then
    echo "Starting Taskiq worker..."
    exec python -m taskiq worker src.core.tasks.broker:broker
else
    echo "Running database migrations..."
    python -m alembic upgrade head

    echo "Starting web server..."
    exec python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
fi
