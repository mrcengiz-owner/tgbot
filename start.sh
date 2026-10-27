#!/bin/bash

python manage.py migrate --noinput
python manage.py collectstatic --noinput

echo "Starting Telegram Bot Panel..."

python manage.py run_scheduled_tasks &
SCHEDULED_PID=$!

gunicorn telegram_panel.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 120 \
    --log-file - &
GUNICORN_PID=$!

cleanup() {
    kill "$SCHEDULED_PID" "$GUNICORN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait "$GUNICORN_PID"
cleanup
