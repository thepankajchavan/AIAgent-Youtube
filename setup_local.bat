@echo off
REM ═══════════════════════════════════════════════════════════════
REM Local Development Setup Script
REM ═══════════════════════════════════════════════════════════════

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║   YouTube Shorts Automation - Local Setup                  ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

REM Check Python
echo [1/6] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.12 not found. Please install Python 3.12
    goto :error
)
python --version
echo [OK] Python found
echo.

REM Check pip
echo [2/6] Checking pip...
pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip not found
    goto :error
)
echo [OK] pip found
echo.

REM Create virtual environment
echo [3/6] Creating virtual environment...
if not exist venv (
    python -m venv venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)
echo.

REM Activate and install dependencies
echo [4/6] Installing dependencies...
echo This may take a few minutes...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
pip install -r requirements-dev.txt --quiet
echo [OK] Dependencies installed
echo.

REM Create media directories
echo [5/6] Creating media directories...
if not exist media\audio mkdir media\audio
if not exist media\video mkdir media\video
if not exist media\output mkdir media\output
if not exist logs mkdir logs
echo [OK] Directories created
echo.

REM Check .env file
echo [6/6] Checking .env file...
if not exist .env (
    copy .env.docker .env >nul
    echo [WARN] Created .env file from template
    echo [ACTION REQUIRED] Edit .env and add your API keys:
    echo   - OPENAI_API_KEY
    echo   - ELEVENLABS_API_KEY
    echo   - PEXELS_API_KEY
    echo   - TELEGRAM_BOT_TOKEN
) else (
    echo [OK] .env file exists
)
echo.

echo ╔════════════════════════════════════════════════════════════╗
echo ║   Setup Complete!                                          ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo Next steps:
echo   1. Install PostgreSQL 16 (if not installed)
echo   2. Install Redis 7 (if not installed)
echo   3. Install FFmpeg (if not installed)
echo   4. Edit .env file with your API keys
echo   5. Run database migrations: alembic upgrade head
echo   6. Start services (see docs/LOCAL_DEVELOPMENT.md)
echo.
echo Run 'check_requirements.bat' to verify prerequisites
echo.
pause
goto :eof

:error
echo.
echo Setup failed! Please check the errors above.
pause
exit /b 1
