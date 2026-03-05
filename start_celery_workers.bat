@echo off
REM Start Celery workers for scripts, media, and upload queues

echo.
echo ════════════════════════════════════════════════════════════
echo   Starting Celery Workers - Scripts, Media, Upload Queues
echo ════════════════════════════════════════════════════════════
echo.

cd "C:\Users\satya\Desktop\AI Agents"
call venv\Scripts\activate.bat

echo [INFO] Starting Celery workers for scripts, media, upload queues...
echo [INFO] Pool mode: solo (required for Windows)
echo.
echo Press Ctrl+C to stop the workers
echo.

celery -A app.core.celery_app worker --loglevel=info --pool=solo -Q scripts,media,upload
