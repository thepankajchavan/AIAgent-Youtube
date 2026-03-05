# Startup Scripts

This directory contains startup scripts for the YouTube Shorts Automation Engine.

## Windows (.bat files)

Run scripts directly from the command prompt:

```cmd
cd "C:\Users\satya\Desktop\AI Agents"

# Setup database (run once)
scripts\setup_db.bat

# Validate configuration
scripts\validate_config.bat

# Start services (each in a separate terminal)
scripts\start_api.bat
scripts\start_worker.bat
scripts\start_flower.bat
scripts\start_telegram_bot.bat
scripts\start_telegram_notifier.bat
```

## Linux/Mac (.sh files)

First, make scripts executable:

```bash
chmod +x scripts/*.sh
```

Then run:

```bash
cd "/path/to/AI Agents"

# Setup database (run once)
./scripts/setup_db.sh

# Validate configuration
./scripts/validate_config.sh

# Start services (each in a separate terminal)
./scripts/start_api.sh
./scripts/start_worker.sh
./scripts/start_flower.sh
./scripts/start_telegram_bot.sh
./scripts/start_telegram_notifier.sh
```

## Service Descriptions

- **start_api** - Starts the FastAPI web server on http://localhost:8000
- **start_worker** - Starts the Celery worker for background tasks
- **start_flower** - Starts Flower monitoring UI on http://localhost:5555
- **start_telegram_bot** - Starts the Telegram bot for user commands
- **start_telegram_notifier** - Starts the notification service for status updates
- **setup_db** - Applies Alembic migrations to create/update database schema
- **validate_config** - Validates configuration without starting services

## Startup Order

1. **First Time Setup:**
   - Ensure PostgreSQL and Redis are running
   - Run `setup_db` to create database tables
   - Run `validate_config` to check configuration

2. **Normal Operation:**
   - Start all services in separate terminals:
     1. `start_api`
     2. `start_worker`
     3. `start_telegram_bot` (for Telegram interface)
     4. `start_telegram_notifier` (for status notifications)
     5. `start_flower` (optional, for monitoring)

## Troubleshooting

- **"alembic: command not found"** - Run from the project root directory
- **"Database connection failed"** - Check PostgreSQL is running and connection string in .env
- **"Redis connection failed"** - Check Redis is running on localhost:6379
- **"FFmpeg not found"** - Install FFmpeg and add to PATH
- **"API key not configured"** - Check .env file for required API keys
- **"Telegram bot token not configured"** - Get token from @BotFather and add to .env
- **"Unauthorized user"** - Add user to allowlist: `python scripts/manage_telegram_users.py add <user_id>`
