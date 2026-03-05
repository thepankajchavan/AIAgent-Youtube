@echo off
REM Apply Alembic migrations to create/update database schema

echo Applying database migrations...
python -m alembic upgrade head

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ✅ Database setup complete!
) else (
    echo.
    echo ❌ Migration failed!
    exit /b 1
)
