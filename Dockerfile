# Telegram Panel Dockerfile
FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Django setup
RUN python manage.py migrate --noinput || true
RUN python manage.py collectstatic --noinput || true

# Expose port
EXPOSE 8000

# Run with gunicorn
CMD ["gunicorn", "telegram_panel.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]