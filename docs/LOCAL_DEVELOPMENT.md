# Local Development Guide

**Running YouTube Shorts Automation Engine locally without Docker**

This guide will help you run the entire project in your IDE/terminal for development and testing.

---

## 📋 Prerequisites

### 1. Install Python 3.12

✅ **Already Installed** - Python 3.12.0 detected

### 2. Install PostgreSQL 16

**Windows:**
```bash
# Download from: https://www.postgresql.org/download/windows/
# Or use installer: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads

# After installation, add to PATH:
# C:\Program Files\PostgreSQL\16\bin
```

**Verify installation:**
```bash
psql --version
# Should output: psql (PostgreSQL) 16.x
```

### 3. Install Redis 7

**Windows:**
```bash
# Download Redis for Windows:
# https://github.com/microsoftarchive/redis/releases

# Or use Windows Subsystem for Linux (WSL):
wsl --install
wsl
sudo apt-get update
sudo apt-get install redis-server
redis-server --daemonize yes
```

**Verify installation:**
```bash
redis-cli ping
# Should output: PONG
```

### 4. Install FFmpeg

**Windows:**
```bash
# Download from: https://ffmpeg.org/download.html
# Or use Chocolatey:
choco install ffmpeg

# Or use winget:
winget install ffmpeg

# Add to PATH:
# C:\ffmpeg\bin
```

**Verify installation:**
```bash
ffmpeg -version
ffprobe -version
```

---

## 🚀 Setup Steps

### Step 1: Create Virtual Environment

```bash
# Navigate to project directory
cd "C:\Users\satya\Desktop\AI Agents"

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows CMD:
venv\Scripts\activate

# Windows PowerShell:
venv\Scripts\Activate.ps1

# Windows Git Bash:
source venv/Scripts/activate

# Verify activation (you should see (venv) in prompt)
python --version
```

### Step 2: Install Python Dependencies

```bash
# Upgrade pip
python -m pip install --upgrade pip

# Install production dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -r requirements-dev.txt

# Verify installation
pip list | grep fastapi
pip list | grep celery
```

### Step 3: Set Up PostgreSQL Database

```bash
# Connect to PostgreSQL
psql -U postgres

# In PostgreSQL prompt:
CREATE DATABASE content_engine;
CREATE USER content_user WITH PASSWORD 'your_password_here';
GRANT ALL PRIVILEGES ON DATABASE content_engine TO content_user;
\q

# Verify database created
psql -U postgres -l | grep content_engine
```

### Step 4: Set Up Redis

```bash
# Start Redis server
# Windows (if installed natively):
redis-server

# Windows (if using WSL):
wsl
sudo service redis-server start
redis-cli ping  # Should return PONG
exit

# Verify Redis is running
redis-cli ping
```

### Step 5: Create .env File

```bash
# Copy template
cp .env.docker .env

# Edit .env file
notepad .env  # or code .env if using VS Code
```

**Local Development .env Configuration:**

```bash
# ═══════════════════════════════════════════════════════════════
# LOCAL DEVELOPMENT ENVIRONMENT
# ═══════════════════════════════════════════════════════════════

# ── Application ────────────────────────────────────────────────
APP_NAME=youtube-shorts-automation
APP_ENV=development
DEBUG=true
LOG_LEVEL=DEBUG

# ── Database (Local PostgreSQL) ────────────────────────────────
DATABASE_URL=postgresql+asyncpg://postgres:your_password_here@localhost:5432/content_engine
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:your_password_here@localhost:5432/content_engine

# ── Redis (Local) ──────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# ── LLM APIs ───────────────────────────────────────────────────
OPENAI_API_KEY=sk-your-openai-key-here
OPENAI_MODEL=gpt-4o

ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929

# ── Text-to-Speech ─────────────────────────────────────────────
ELEVENLABS_API_KEY=your-elevenlabs-key-here
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM

# ── Stock Footage ──────────────────────────────────────────────
PEXELS_API_KEY=your-pexels-key-here

# ── Telegram ───────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=your-bot-token-from-botfather
TELEGRAM_WEBHOOK_URL=  # Leave empty for polling mode

# ── YouTube ────────────────────────────────────────────────────
YOUTUBE_CLIENT_SECRETS_FILE=client_secrets.json
YOUTUBE_TOKEN_FILE=youtube_token.json

# ── Security ───────────────────────────────────────────────────
ENCRYPTION_KEY=your-32-character-encryption-key
API_AUTH_ENABLED=false  # Disable for local testing

# ── Media ──────────────────────────────────────────────────────
MEDIA_DIR=media

# ── CORS ───────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
```

### Step 6: Create Media Directories

```bash
# Create required directories
mkdir -p media/audio
mkdir -p media/video
mkdir -p media/output
mkdir -p logs
```

### Step 7: Run Database Migrations

```bash
# Apply all migrations
alembic upgrade head

# Verify migrations applied
alembic current

# Check database tables
psql -U postgres -d content_engine -c "\dt"
```

### Step 8: Add Telegram User (Optional)

```bash
# Get your Telegram user ID from @userinfobot

# Add yourself to allowlist
python scripts/manage_telegram_users.py add YOUR_USER_ID "Your Name"

# Verify
python scripts/manage_telegram_users.py list
```

---

## 🎯 Running the Application

You need to run **4 separate terminal windows/tabs** for full functionality:

### Terminal 1: FastAPI Server

```bash
# Activate venv
venv\Scripts\activate

# Start FastAPI
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Output:
# INFO:     Uvicorn running on http://0.0.0.0:8000
# INFO:     Application startup complete
```

**Test:**
```bash
# In another terminal:
curl http://localhost:8000/health
# Should return: {"status":"healthy"}
```

### Terminal 2: Celery Worker (Default Queue)

```bash
# Activate venv
venv\Scripts\activate

# Start Celery worker for default queue
celery -A app.core.celery_app worker --loglevel=info --pool=solo -Q default

# Note: --pool=solo is required on Windows
```

### Terminal 3: Celery Worker (Scripts + Media + Upload Queues)

```bash
# Activate venv
venv\Scripts\activate

# Start Celery worker for all other queues
celery -A app.core.celery_app worker --loglevel=info --pool=solo -Q scripts,media,upload

# Note: Running multiple queues in one worker for local development
```

### Terminal 4: Telegram Bot (Optional)

```bash
# Activate venv
venv\Scripts\activate

# Start Telegram bot
python telegram_bot.py

# Output:
# INFO - Telegram bot started (polling mode)
```

### Terminal 5: Telegram Notifier (Optional)

```bash
# Activate venv
venv\Scripts\activate

# Start Telegram notifier
python telegram_notifier.py

# Output:
# INFO - Telegram notifier started (Redis pub/sub)
```

---

## 🧪 Testing the Application

### Test 1: API Health Check

```bash
# Test basic health
curl http://localhost:8000/health

# Test deep health check
curl http://localhost:8000/api/v1/system/health
```

### Test 2: Trigger Pipeline via API

```bash
# Trigger a video generation
curl -X POST http://localhost:8000/api/v1/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "5 amazing facts about Python programming",
    "video_format": "short",
    "provider": "openai"
  }'

# Response:
# {
#   "project_id": "550e8400-...",
#   "celery_task_id": "a1b2c3d4-...",
#   "status": "pending"
# }
```

### Test 3: Check Project Status

```bash
# Get all projects
curl http://localhost:8000/api/v1/projects

# Get specific project
curl http://localhost:8000/api/v1/projects/550e8400-...
```

### Test 4: Telegram Bot (if running)

```
1. Open Telegram
2. Find your bot
3. Send: /start
4. Send: /video 3 interesting facts about AI
5. Watch the status updates in real-time!
```

---

## 📊 Monitoring & Debugging

### View Logs

**FastAPI logs:**
```bash
# Check logs/app.log
tail -f logs/app.log

# Or check terminal output
```

**Celery logs:**
```bash
# Check terminal output of Celery workers
# Or check logs/celery.log
```

### PostgreSQL Database

```bash
# Connect to database
psql -U postgres -d content_engine

# View all projects
SELECT id, topic, status, created_at FROM video_projects ORDER BY created_at DESC LIMIT 10;

# View specific project
SELECT * FROM video_projects WHERE id = 'your-project-id';

# Count projects by status
SELECT status, COUNT(*) FROM video_projects GROUP BY status;

# Exit
\q
```

### Redis

```bash
# Connect to Redis
redis-cli

# Check queues
LLEN celery  # Default queue
LLEN scripts  # Scripts queue
LLEN media  # Media queue
LLEN upload  # Upload queue

# Check running tasks
KEYS celery-task-meta-*

# Exit
exit
```

---

## 🛠️ Troubleshooting

### Issue: "ImportError: No module named 'app'"

**Solution:**
```bash
# Make sure you're in the project root directory
cd "C:\Users\satya\Desktop\AI Agents"

# Make sure virtual environment is activated
venv\Scripts\activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Issue: "psycopg2.OperationalError: could not connect to server"

**Solution:**
```bash
# Check if PostgreSQL is running
# Windows Services: Search for "postgresql-x64-16"

# Or restart PostgreSQL
net stop postgresql-x64-16
net start postgresql-x64-16

# Verify connection
psql -U postgres -c "SELECT version();"
```

### Issue: "redis.exceptions.ConnectionError"

**Solution:**
```bash
# Check if Redis is running
redis-cli ping

# If not running (Windows):
redis-server

# If not running (WSL):
wsl
sudo service redis-server start
```

### Issue: "FileNotFoundError: FFmpeg not found"

**Solution:**
```bash
# Check FFmpeg installation
ffmpeg -version

# If not found, add to PATH or reinstall
# Windows: Add C:\ffmpeg\bin to PATH environment variable
```

### Issue: Celery worker crashes on Windows

**Solution:**
```bash
# Use --pool=solo on Windows
celery -A app.core.celery_app worker --loglevel=info --pool=solo -Q default

# Alternative: Use eventlet
pip install eventlet
celery -A app.core.celery_app worker --loglevel=info --pool=eventlet -Q default
```

---

## 🔧 Development Workflow

### Making Code Changes

1. **Edit code** in your IDE
2. **FastAPI auto-reloads** (if using --reload flag)
3. **Celery workers** need manual restart:
   ```bash
   # Stop worker: Ctrl+C
   # Start worker: celery -A app.core.celery_app worker ...
   ```

### Running Tests

```bash
# Activate venv
venv\Scripts\activate

# Run all tests
pytest -v

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/unit/test_llm_service.py -v
```

### Code Quality Checks

```bash
# Format code with Black
black app/ tests/

# Lint with Ruff
ruff check app/ tests/

# Type check with MyPy
mypy app/

# Run all pre-commit hooks
pre-commit run --all-files
```

---

## 📝 Quick Reference

### Starting Everything (All Terminals)

```bash
# Terminal 1: FastAPI
venv\Scripts\activate && uvicorn app.main:app --reload --port 8000

# Terminal 2: Celery Default
venv\Scripts\activate && celery -A app.core.celery_app worker --loglevel=info --pool=solo -Q default

# Terminal 3: Celery Other Queues
venv\Scripts\activate && celery -A app.core.celery_app worker --loglevel=info --pool=solo -Q scripts,media,upload

# Terminal 4: Telegram Bot (optional)
venv\Scripts\activate && python telegram_bot.py

# Terminal 5: Telegram Notifier (optional)
venv\Scripts\activate && python telegram_notifier.py
```

### Stopping Everything

```bash
# In each terminal:
Ctrl + C

# Stop PostgreSQL (if needed)
net stop postgresql-x64-16

# Stop Redis (if needed)
redis-cli shutdown
```

---

## 🎯 Next Steps

Once local testing is complete:

1. ✅ **Test all features** - Generate a video end-to-end
2. ✅ **Check logs** - Verify no errors
3. ✅ **Run tests** - pytest --cov=app
4. ✅ **Code quality** - black, ruff, mypy
5. ✅ **Ready for Docker** - Package everything for deployment

---

**Need help with:**
- Setting up PostgreSQL or Redis?
- Configuring API keys?
- Troubleshooting errors?
- Running specific tests?

Let me know and I'll help you through it!
