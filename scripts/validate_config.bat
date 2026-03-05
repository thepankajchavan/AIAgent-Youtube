@echo off
REM Validate configuration without starting services

echo Running configuration validation...
python -c "import asyncio; from app.core.validation import validate_all; asyncio.run(validate_all())"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ✅ Configuration is valid!
) else (
    echo.
    echo ❌ Configuration validation failed!
    exit /b 1
)
