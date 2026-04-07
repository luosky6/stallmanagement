# ==============================================================================
# StallManagement — Dockerfile
# ==============================================================================
# Base image : python:3.9-slim (3.7-slim has limited availability; 3.9 is
#              fully compatible with the Django 3.2 / Python 3.7+ codebase)
# Server     : Daphne (ASGI, supports HTTP + WebSocket)
# ==============================================================================

FROM python:3.9-slim

# Prevent .pyc files and enable stdout/stderr logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required by mysqlclient
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-libmysqlclient-dev \
    gcc \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cached unless requirements change)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy project source
COPY . .

# Create the logs directory (mounted as a volume in production)
RUN mkdir -p /app/logs

# Non-root user for security
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Default command — overridden by docker-compose.yml
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "StallManagement.asgi:application"]
