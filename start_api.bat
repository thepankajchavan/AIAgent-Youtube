@echo off
REM Start FastAPI server for local development

echo.
echo ════════════════════════════════════════════════════════════
echo   Starting FastAPI Server
echo ════════════════════════════════════════════════════════════
echo.

cd "C:\Users\satya\Desktop\AI Agents"
call venv\Scripts\activate.bat

echo [INFO] Checking Redis...
docker ps --filter "name=redis-local" --format "{{.Names}}: {{.Status}}"

echo.
echo [INFO] Starting FastAPI server on http://localhost:8000
echo [INFO] API docs available at http://localhost:8000/docs
echo.
echo Press Ctrl+C to stop the server
echo.

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
