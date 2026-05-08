#!/bin/bash

# Migrate database
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput

# Start both web server and scheduled tasks in background
echo "Starting Telegram Bot Panel..."

# Start scheduled tasks worker in background
python manage.py run_scheduled_tasks &
SCHEDULED_PID=$!

# Start web server with gunicorn
gunicorn telegram_panel.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 120 \
    --log-file -

# Cleanup on exit
trap "kill $SCHEDULED_PID 2>/dev/null" EXIT

wait