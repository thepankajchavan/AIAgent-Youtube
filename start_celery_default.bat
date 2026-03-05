@echo off
REM Start Celery worker for default queue

echo.
echo ════════════════════════════════════════════════════════════
echo   Starting Celery Worker - Default Queue
echo ════════════════════════════════════════════════════════════
echo.

cd "C:\Users\satya\Desktop\AI Agents"
call venv\Scripts\activate.bat

echo [INFO] Starting Celery worker for default queue...
echo [INFO] Pool mode: solo (required for Windows)
echo.
echo Press Ctrl+C to stop the worker
echo.

celery -A app.core.celery_app worker --loglevel=info --pool=solo -Q default
