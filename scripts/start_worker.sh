#!/usr/bin/env bash
# Start Celery worker

echo "Starting Celery worker..."
celery -A app.core.celery_app worker --queues=default,scripts,media,upload --loglevel=info
