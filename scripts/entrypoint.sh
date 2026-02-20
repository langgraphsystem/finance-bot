#!/bin/bash
set -e

PROCESS_TYPE="${RAILWAY_PROCESS_TYPE:-web}"

TASK_MODULES="src.core.tasks.memory_tasks src.core.tasks.notification_tasks src.core.tasks.life_tasks src.core.tasks.reminder_tasks src.core.tasks.profile_tasks src.core.tasks.proactivity_tasks src.core.tasks.booking_tasks"

if [ "$PROCESS_TYPE" = "worker" ]; then
    echo "Starting Taskiq scheduler (background)..."
    python -m taskiq scheduler src.core.tasks.broker:scheduler $TASK_MODULES &

    echo "Starting Taskiq worker..."
    exec python -m taskiq worker src.core.tasks.broker:broker $TASK_MODULES
else
    echo "Running database migrations..."
    python -m alembic upgrade head

    echo "Starting web server..."
    exec python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
fi
