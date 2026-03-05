@echo off
REM ═══════════════════════════════════════════════════════════════
REM Master Stop Script - YouTube Shorts Automation Engine
REM ═══════════════════════════════════════════════════════════════

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║   YouTube Shorts Automation - Stop All Services            ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

echo Stopping all services...
echo.

REM ═══════════════════════════════════════════════════════════════
REM Stop Python processes (FastAPI and Celery)
REM ═══════════════════════════════════════════════════════════════

echo [1/3] Stopping Python processes (FastAPI, Celery)...

REM Find and kill all python processes related to the project
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /FO LIST ^| findstr /C:"PID:"') do (
    echo   Stopping process %%i...
    taskkill /PID %%i /F >nul 2>&1
)

REM Also try killing any uvicorn processes
tasklist /FI "IMAGENAME eq uvicorn.exe" >nul 2>&1
if not errorlevel 1 (
    echo   Stopping uvicorn...
    taskkill /IM uvicorn.exe /F >nul 2>&1
)

REM Also try killing any celery processes
tasklist /FI "IMAGENAME eq celery.exe" >nul 2>&1
if not errorlevel 1 (
    echo   Stopping celery...
    taskkill /IM celery.exe /F >nul 2>&1
)

echo [OK] Python processes stopped
echo.

REM ═══════════════════════════════════════════════════════════════
REM Stop Redis container
REM ═══════════════════════════════════════════════════════════════

echo [2/3] Stopping Redis container...
docker stop redis-local >nul 2>&1
if errorlevel 1 (
    echo [WARN] Redis container not found or already stopped
) else (
    echo [OK] Redis container stopped
)
echo.

REM ═══════════════════════════════════════════════════════════════
REM Close terminal windows
REM ═══════════════════════════════════════════════════════════════

echo [3/3] Closing terminal windows...

REM Kill any cmd windows with our specific titles
taskkill /FI "WINDOWTITLE eq FastAPI Server*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Celery - Default Queue*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Celery - Workers*" /F >nul 2>&1

echo [OK] Terminal windows closed
echo.

REM ═══════════════════════════════════════════════════════════════
REM Verify everything is stopped
REM ═══════════════════════════════════════════════════════════════

echo Verifying services are stopped...
echo.

REM Check if port 8000 is free
netstat -ano | findstr :8000 >nul 2>&1
if errorlevel 1 (
    echo [OK] Port 8000 is free
) else (
    echo [WARN] Something is still using port 8000
    echo Run this to find and kill it:
    echo   netstat -ano ^| findstr :8000
    echo   taskkill /PID [PID] /F
)

REM Check Redis container status
docker ps --filter "name=redis-local" --format "{{.Status}}" | findstr "Up" >nul 2>&1
if errorlevel 1 (
    echo [OK] Redis container is stopped
) else (
    echo [WARN] Redis container is still running
)

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║   All Services Stopped Successfully!                       ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo To restart services, run: start_all.bat
echo.
pause
