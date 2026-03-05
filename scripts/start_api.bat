@echo off
REM Start FastAPI server with Uvicorn

echo Starting FastAPI server...
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
