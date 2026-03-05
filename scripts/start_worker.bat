@echo off
REM Start Celery worker

echo Starting Celery worker...
celery -A app.core.celery_app worker --queues=default,scripts,media,upload --pool=solo --loglevel=info
