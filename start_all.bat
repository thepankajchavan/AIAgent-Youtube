@echo off
REM ═══════════════════════════════════════════════════════════════
REM Master Startup Script - YouTube Shorts Automation Engine
REM ═══════════════════════════════════════════════════════════════

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║   YouTube Shorts Automation - Master Startup               ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

REM Change to project directory
cd /d "C:\Users\satya\Desktop\AI Agents"

echo [1/7] Checking prerequisites...
echo.

REM Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv venv
    pause
    exit /b 1
)

REM Check if Redis container exists
docker ps -a --filter "name=redis-local" --format "{{.Names}}" | findstr /C:"redis-local" >nul
if errorlevel 1 (
    echo [ERROR] Redis container not found!
    echo Please run: docker run -d --name redis-local -p 6379:6379 redis:7-alpine
    pause
    exit /b 1
)

echo [OK] Prerequisites found
echo.

echo ╔════════════════════════════════════════════════════════════╗
echo ║   Ready to start all services                              ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo This will open 5 terminal windows:
echo   - Terminal 1: FastAPI Server (http://localhost:8000)
echo   - Terminal 2: Celery Default Queue Worker
echo   - Terminal 3: Celery Scripts/Media/Upload Workers
echo   - Terminal 4: Celery Beat (Auto-Scheduler)
echo   - Terminal 5: Telegram Bot + Notifier
echo.
echo Press Ctrl+C now to cancel, or
pause

REM ═══════════════════════════════════════════════════════════════
REM Start Services
REM ═══════════════════════════════════════════════════════════════

echo.
echo [2/7] Starting Redis...
docker start redis-local >nul 2>&1

REM Verify Redis is running
docker exec redis-local redis-cli ping >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Redis failed to start!
    pause
    exit /b 1
)
echo [OK] Redis is running on port 6379
echo.

echo [3/7] Starting FastAPI Server...
start "FastAPI Server" cmd /k "cd /d "C:\Users\satya\Desktop\AI Agents" && call venv\Scripts\activate.bat && echo [FastAPI Server Starting...] && echo. && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
timeout /t 2 /nobreak >nul
echo [OK] FastAPI server starting in new window
echo.

echo [4/7] Starting Celery Default Queue Worker...
start "Celery - Default Queue" cmd /k "cd /d "C:\Users\satya\Desktop\AI Agents" && call venv\Scripts\activate.bat && echo [Celery Default Queue Starting...] && echo. && celery -A app.core.celery_app worker --loglevel=info --pool=solo -Q default"
timeout /t 2 /nobreak >nul
echo [OK] Celery default worker starting in new window
echo.

echo [5/7] Starting Celery Workers (Scripts/Media/Upload)...
start "Celery - Workers" cmd /k "cd /d "C:\Users\satya\Desktop\AI Agents" && call venv\Scripts\activate.bat && echo [Celery Workers Starting...] && echo. && celery -A app.core.celery_app worker --loglevel=info --pool=solo -Q scripts,media,upload"
timeout /t 2 /nobreak >nul
echo [OK] Celery workers starting in new window
echo.

echo [6/7] Starting Celery Beat (Auto-Scheduler)...
start "Celery - Beat Scheduler" cmd /k "cd /d "C:\Users\satya\Desktop\AI Agents" && call venv\Scripts\activate.bat && echo [Celery Beat Starting...] && echo. && celery -A app.core.celery_app beat --loglevel=info"
timeout /t 2 /nobreak >nul
echo [OK] Celery Beat scheduler starting in new window
echo.

echo [7/7] Starting Telegram Bot + Notifier...
start "Telegram Bot" cmd /k "cd /d "C:\Users\satya\Desktop\AI Agents" && call venv\Scripts\activate.bat && echo [Telegram Bot Starting...] && echo. && python telegram_bot.py"
timeout /t 2 /nobreak >nul
echo [OK] Telegram bot starting in new window
echo.

REM ═══════════════════════════════════════════════════════════════
REM Show Status
REM ═══════════════════════════════════════════════════════════════

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║   All Services Started Successfully!                       ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo Services running:
echo   [*] Redis            - localhost:6379
echo   [*] FastAPI          - http://localhost:8000
echo   [*] Celery Default   - default queue worker
echo   [*] Celery Workers   - scripts, media, upload queues
echo   [*] Celery Beat      - auto-scheduler (fires at set times)
echo   [*] Telegram Bot     - receives commands + sends notifications
echo.
echo ─────────────────────────────────────────────────────────────
echo Quick Links:
echo ─────────────────────────────────────────────────────────────
echo   API Documentation:  http://localhost:8000/docs
echo   Health Check:       http://localhost:8000/health
echo.
echo ─────────────────────────────────────────────────────────────
echo Auto-Schedule:
echo ─────────────────────────────────────────────────────────────
echo   Times are set in .env: AUTO_SCHEDULE_TIMES
echo   Celery Beat reads the schedule and fires at those times.
echo   Changing .env requires restarting Beat.
echo.
echo ─────────────────────────────────────────────────────────────
echo To Stop All Services:
echo ─────────────────────────────────────────────────────────────
echo   Run: stop_all.bat
echo   Or: Press Ctrl+C in each terminal window
echo.
echo Waiting 5 seconds, then testing API...
timeout /t 5 /nobreak >nul

REM Test API health
echo Testing API health...
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    echo [WARN] API not responding yet (may still be starting)
    echo Check the "FastAPI Server" terminal window for status
) else (
    echo [OK] API is responding!
)
echo.

echo ╔════════════════════════════════════════════════════════════╗
echo ║   Setup Complete - All 6 services running!                 ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo You can close this window now.
echo All services are running in their own terminal windows.
echo.
pause
