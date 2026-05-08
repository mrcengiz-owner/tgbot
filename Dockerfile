FROM python:3.12-slim

WORKDIR /app

# Dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

# Run server
CMD ["gunicorn", "telegram_panel.wsgi:application", "--bind", "0.0.0.0:8000"]