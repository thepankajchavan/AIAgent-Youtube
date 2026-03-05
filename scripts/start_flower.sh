#!/usr/bin/env bash
# Start Flower monitoring UI for Celery

echo "Starting Flower..."
celery -A app.core.celery_app flower --port=5555
