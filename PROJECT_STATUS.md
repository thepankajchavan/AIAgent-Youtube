# YouTube Shorts Automation Engine — Project Status & Build Phases

> **Project:** AI-Powered YouTube Shorts Automation
> **Trigger:** Telegram Bot
> **Stack:** FastAPI + Celery + PostgreSQL + Redis + FFmpeg
> **Last Updated:** 2026-03-03

---

## Table of Contents

1. [Project Vision](#1-project-vision)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Current Codebase Inventory](#4-current-codebase-inventory)
5. [What's Built (Completed)](#5-whats-built-completed)
6. [What's Missing (Gaps)](#6-whats-missing-gaps)
7. [Known Issues & Technical Debt](#7-known-issues--technical-debt)
8. [Build Phases (Roadmap to Production)](#8-build-phases-roadmap-to-production)
9. [API Reference](#9-api-reference)
10. [Data Models](#10-data-models)
11. [Pipeline Deep Dive](#11-pipeline-deep-dive)
12. [Environment & Configuration](#12-environment--configuration)
13. [Deployment Architecture (Target)](#13-deployment-architecture-target)

---

## 1. Project Vision

Build a **fully automated, production-grade system** that:

1. Receives a **topic** via a **Telegram bot** command (e.g., `/video "5 facts about black holes"`)
2. Generates a **video script** using LLMs (OpenAI GPT-4o or Anthropic Claude)
3. Converts the script to **speech** via ElevenLabs TTS
4. Fetches relevant **stock footage** from Pexels
5. **Assembles** the final video with FFmpeg (audio overlay + clip stitching)
6. **Uploads** the finished YouTube Short automatically
7. Sends the **YouTube link back** to the user on Telegram

**End-to-end flow — zero manual intervention after the user sends a topic.**

---

## 2. System Architecture

### High-Level Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                        USER (Telegram)                               │
│                     /video "topic here"                               │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────┐
│     TELEGRAM BOT         │  ◄── NOT BUILT YET
│  (python-telegram-bot)   │
│  - Parse commands        │
│  - Send status updates   │
│  - Return YouTube link   │
└──────────────┬───────────┘
               │ HTTP POST /api/v1/pipeline
               ▼
┌──────────────────────────┐       ┌──────────────────┐
│     FASTAPI SERVER       │◄─────►│   POSTGRESQL     │
│  - Validate request      │       │   - VideoProject │
│  - Create project record │       │   - Status track │
│  - Dispatch Celery task  │       └──────────────────┘
│  - Return 202 Accepted   │
└──────────────┬───────────┘
               │ Celery .delay()
               ▼
┌──────────────────────────┐       ┌──────────────────┐
│     CELERY WORKERS       │◄─────►│      REDIS       │
│                          │       │   - Broker       │
│  Step 1: Script Gen      │       │   - Results      │
│    ├─ OpenAI / Anthropic │       └──────────────────┘
│    └─ Returns JSON       │
│                          │
│  Step 2: Parallel        │
│    ├─ TTS (ElevenLabs)   │
│    └─ Clips (Pexels)     │
│                          │
│  Step 3: Assembly        │
│    └─ FFmpeg encode      │
│                          │
│  Step 4: Upload          │
│    └─ YouTube Data API   │
└──────────────────────────┘
```

### Pipeline State Machine

```
PENDING
   │
   ▼
SCRIPT_GENERATING ──────► FAILED
   │
   ├──────────────────┐
   ▼                  ▼
AUDIO_GENERATING   VIDEO_GENERATING ──► FAILED
   │                  │
   └────────┬─────────┘
            ▼
       ASSEMBLING ──────────────────► FAILED
            │
            ▼
       UPLOADING ───────────────────► FAILED
            │
            ▼
       COMPLETED
```

### Celery Canvas Pattern

```python
chain(
    generate_script_task.s(project_id, topic, format, provider),  # Sequential
    chord(
        group(                                                     # Parallel
            generate_audio_task.s(),
            fetch_visuals_task.s()
        ),
        assemble_video_task.s()                                    # Callback
    ),
    upload_to_youtube_task.s()                                     # Sequential
)
```

---

## 3. Technology Stack

### Core Framework

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Web Server | FastAPI | 0.115.6 | REST API with async support |
| ASGI Server | Uvicorn | 0.34.0 | Production ASGI runner |
| Task Queue | Celery | 5.4.0 | Distributed task orchestration |
| Message Broker | Redis | 5.2.1 | Celery broker + result backend |
| Database | PostgreSQL | 13+ | Persistent state storage |
| ORM | SQLAlchemy | 2.0.36 | Async ORM with connection pooling |
| Migrations | Alembic | 1.14.1 | Schema version control |

### AI & Media Services

| Service | Technology | Version | Purpose |
|---------|-----------|---------|---------|
| Script Gen | OpenAI API | 1.59.5 | GPT-4o script generation |
| Script Gen (alt) | Anthropic API | 0.42.0 | Claude script generation |
| Text-to-Speech | ElevenLabs | 1.50.5 | Multilingual v2 voice synthesis |
| Stock Footage | Pexels API | via httpx | Portrait/landscape video search |
| Video Assembly | FFmpeg | system | H.264 encoding, concat, overlay |
| YouTube Upload | Google APIs | 2.159.0 | OAuth2 resumable uploads |

### Infrastructure & Utilities

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Validation | Pydantic | 2.10.4 | Request/response schemas |
| HTTP Client | httpx | 0.28.1 | Async HTTP for external APIs |
| Retry Logic | Tenacity | 9.0.0 | Exponential backoff decorators |
| Logging | Loguru | 0.7.3 | Structured logging with rotation |
| Config | python-dotenv | 1.0.1 | Environment variable loading |

---

## 4. Current Codebase Inventory

### Directory Structure

```
AI Agents/
├── .env.example                    # Environment template (37 lines)
├── .gitignore                      # Ignore rules (38 lines)
├── requirements.txt                # Python dependencies (45 lines)
├── alembic.ini                     # Migration config (41 lines)
│
├── alembic/
│   ├── env.py                      # Migration environment (84 lines)
│   ├── script.py.mako              # Migration template
│   └── versions/                   # ⚠️ EMPTY — no migrations created
│
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI factory + lifespan (65 lines)
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── schemas.py              # Pydantic models (138 lines)
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── pipeline.py         # POST pipeline trigger (139 lines)
│   │       ├── projects.py         # CRUD for projects (161 lines)
│   │       └── system.py           # Health + task status (106 lines)
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # Pydantic Settings (84 lines)
│   │   ├── database.py             # Async engine + sessions (47 lines)
│   │   ├── celery_app.py           # Celery configuration (55 lines)
│   │   └── logging.py              # Loguru setup
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py                 # UUID + Timestamp mixins (38 lines)
│   │   └── video.py                # VideoProject model (70 lines)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_service.py          # Script generation (170 lines)
│   │   ├── tts_service.py          # ElevenLabs TTS (134 lines)
│   │   ├── visual_service.py       # Pexels video fetch (212 lines)
│   │   ├── media_service.py        # FFmpeg assembly (226 lines)
│   │   └── youtube_service.py      # YouTube upload (172 lines)
│   │
│   └── workers/
│       ├── __init__.py
│       ├── db.py                   # Sync DB for workers (46 lines)
│       ├── pipeline.py             # Chain/chord orchestrator (113 lines)
│       ├── script_tasks.py         # LLM task (110 lines)
│       ├── media_tasks.py          # Audio + video tasks (192 lines)
│       ├── assembly_tasks.py       # FFmpeg task (115 lines)
│       └── upload_tasks.py         # YouTube task (120 lines)
│
└── media/
    ├── audio/                      # Generated MP3 files
    ├── video/                      # Downloaded Pexels clips
    └── output/                     # Final assembled MP4 files
```

**Total: ~2,600 lines of Python across 26 files**

---

## 5. What's Built (Completed)

### 5.1 FastAPI Application Server — `app/main.py`

- Application factory pattern with `create_app()`
- Async lifespan context manager for startup/shutdown
- Automatic media directory creation (`media/audio`, `media/video`, `media/output`)
- CORS middleware (currently allows all origins)
- Route registration for 3 modules (pipeline, projects, system)
- Graceful database connection disposal on shutdown

### 5.2 Configuration Management — `app/core/config.py`

- Pydantic Settings with environment variable binding
- Supports all required API keys: OpenAI, Anthropic, ElevenLabs, Pexels, YouTube
- Dual database URLs: async (`asyncpg`) for FastAPI, sync (`psycopg2`) for Celery workers
- Redis/Celery broker and result backend URLs
- Media directory path with computed sub-paths (audio_dir, video_dir, output_dir)
- Cached singleton via `@lru_cache`

### 5.3 Database Layer — `app/core/database.py` + `app/models/`

- **AsyncEngine** with connection pooling (size=10, max_overflow=20, pre_ping=True)
- **VideoProject** ORM model with:
  - UUID primary key (auto-generated)
  - Timestamps (created_at, updated_at with server defaults)
  - Topic, script (Text), status (Enum), format (Enum)
  - Celery task ID tracking
  - Artifact paths: audio_path, video_path, output_path
  - YouTube fields: youtube_video_id, youtube_url
  - Error tracking: error_message
- **VideoStatus Enum**: PENDING, SCRIPT_GENERATING, AUDIO_GENERATING, VIDEO_GENERATING, ASSEMBLING, UPLOADING, COMPLETED, FAILED
- **VideoFormat Enum**: SHORT (9:16), LONG (16:9)
- FastAPI dependency `get_db()` with automatic commit/rollback

### 5.4 API Endpoints — `app/api/routes/`

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| `POST` | `/api/v1/pipeline` | Trigger single video pipeline | 202 Accepted |
| `POST` | `/api/v1/pipeline/batch` | Trigger up to 10 pipelines | 202 Accepted |
| `GET` | `/api/v1/projects` | List projects (paginated, filterable) | 200 |
| `GET` | `/api/v1/projects/{id}` | Get project details | 200 / 404 |
| `DELETE` | `/api/v1/projects/{id}` | Delete project | 200 / 404 |
| `POST` | `/api/v1/projects/{id}/retry` | Retry failed project | 200 / 400 / 404 |
| `GET` | `/api/v1/system/health` | Deep health (DB + Redis) | 200 |
| `GET` | `/api/v1/system/tasks/{id}` | Celery task status | 200 |
| `POST` | `/api/v1/system/tasks/{id}/revoke` | Cancel Celery task | 200 |

**Request Validation** via Pydantic schemas:
- Topic: 3–512 characters
- Format: `short` or `long`
- Provider: `openai` or `anthropic`
- Batch limit: max 10 pipelines per request
- Pagination: max 100 per page

### 5.5 LLM Script Generation — `app/services/llm_service.py`

- **Dual provider support**: OpenAI (GPT-4o) and Anthropic (Claude Sonnet)
- **Format-aware prompts**:
  - **Short (30–60s)**: Hook-driven, fast-paced, CTA ending, YouTube Shorts optimized
  - **Long (5–10min)**: Structured sections, in-depth content
- **JSON response format**: title, script, tags[], description
- **Retry**: 3 attempts, exponential backoff (4s→60s), handles HTTP errors and timeouts
- **Anthropic markdown fence handling**: Strips ` ```json ` wrappers from response
- Temperature: 0.9 (creative output), max tokens: 4096

### 5.6 Text-to-Speech — `app/services/tts_service.py`

- **ElevenLabs** multilingual_v2 model
- Configurable voice parameters: stability, similarity_boost, style
- **Streaming download** in 8KB chunks to MP3
- 120-second timeout for large scripts
- Retry: 3 attempts with exponential backoff
- Auto-generated filenames using UUID

### 5.7 Stock Footage — `app/services/visual_service.py`

- **Pexels API** integration with orientation filtering (portrait for Shorts, landscape for long-form)
- **Smart quality selection** algorithm:
  - Orientation match: +100 points
  - Resolution 720p–1080p: +50 points
  - Resolution >1080p: +20 points
  - Prefers MP4 format
- Multi-query search using LLM-generated tags (up to 4 queries)
- Duration filtering: 5–30 seconds per clip
- Streaming download with retry logic

### 5.8 Video Assembly — `app/services/media_service.py`

- **FFmpeg pipeline**:
  1. `scale_and_pad()` — Resize each clip to target resolution with black padding
  2. `concatenate_clips()` — FFmpeg concat demuxer to chain clips
  3. `overlay_audio()` — Mix TTS audio over concatenated video
- **Encoding settings**: H.264, CRF 23, fast preset, AAC 192kbps audio
- **Target resolutions**: 1080x1920 (Short 9:16), 1920x1080 (Long 16:9)
- Duration matching: trims to audio length
- Temporary work directory with cleanup
- 600-second subprocess timeout

### 5.9 YouTube Upload — `app/services/youtube_service.py`

- **OAuth2 authentication** with automatic token refresh
- Token persistence to `youtube_token.json`
- **Resumable uploads** in 10MB chunks with progress logging
- Shorts optimization: prepends `#Shorts` to title and tags
- Default privacy: `private` (safe for testing)
- Category support: Entertainment, Education, Science, etc.
- Retry: 3 attempts, exponential backoff (10s→120s)

### 5.10 Celery Task Orchestration — `app/workers/`

- **4 dedicated queues**: `default`, `scripts`, `media`, `upload`
- **Pipeline composition**: chain + chord + group (Canvas primitives)
- **Per-task configuration**:
  - Script gen: 3 retries, 30s delay, `scripts` queue
  - Audio gen: 3 retries, 30s delay, `media` queue
  - Visual fetch: 3 retries, 30s delay, `media` queue
  - Assembly: 2 retries, 60s delay, hard limit 10min, `media` queue
  - Upload: 2 retries, 120s delay, hard limit 15min, `upload` queue
- Database status updates at each step via sync sessions
- Acks late: True (redelivery on worker crash)
- Result expiration: 24 hours

### 5.11 Logging — `app/core/logging.py`

- **Loguru** with daily file rotation
- 30-day log retention with compression
- Color-coded console output
- Structured logging throughout all services and workers

---

## 6. What's Missing (Gaps)

### 6.1 Telegram Bot Integration — **Priority: CRITICAL**

The primary user interface doesn't exist. There is no:
- Telegram bot module or package
- Command parser (`/video`, `/status`, `/list`)
- Webhook or long-polling handler
- Status notification system (progress updates to user)
- Inline keyboard for actions (retry, delete, cancel)
- User session management
- Multi-user support

### 6.2 Database Migrations — **Priority: CRITICAL**

`alembic/versions/` directory is **empty**. The VideoProject table cannot be created without:
- Initial migration: `alembic revision --autogenerate -m "initial"`
- Migration runner: `alembic upgrade head`
- No migration exists = **database is unusable**

### 6.3 Docker & Containerization — **Priority: HIGH**

No containerization infrastructure:
- No `Dockerfile`
- No `docker-compose.yml`
- No container orchestration for PostgreSQL, Redis, FastAPI, Celery workers
- Manual setup required for all services

### 6.4 Authentication & Security — **Priority: HIGH**

- No API authentication (all endpoints publicly accessible)
- No rate limiting middleware
- CORS allows all origins (`*`)
- No API key validation on startup
- OAuth tokens stored in plaintext
- Topic field vulnerable to prompt injection

### 6.5 Testing — **Priority: HIGH**

- Zero test files
- No pytest configuration
- No unit tests for services
- No integration tests for pipeline
- No API endpoint tests
- No mocks for external services

### 6.6 Worker Management — **Priority: MEDIUM**

- No start scripts for Celery workers
- No process manager (supervisord, systemd)
- No worker health monitoring
- No auto-scaling configuration

### 6.7 Monitoring & Observability — **Priority: MEDIUM**

- No Prometheus metrics
- No Grafana dashboards
- No request tracing (OpenTelemetry)
- No alerting on failures
- No Celery Flower for task monitoring
- Log-only observability

### 6.8 Error Recovery & Notifications — **Priority: MEDIUM**

- No Dead Letter Queue for permanently failed tasks
- No webhook notifications on completion/failure
- Retry restarts full pipeline (no resume from failure point)
- No media file cleanup job (orphaned files accumulate)
- No scheduled maintenance tasks

### 6.9 Documentation — **Priority: MEDIUM**

- No README.md
- No setup guide
- No deployment instructions
- No API documentation (beyond auto-generated Swagger)
- No architecture diagrams in repo

---

## 7. Known Issues & Technical Debt

### Security Issues

| Issue | Location | Severity |
|-------|----------|----------|
| CORS allows all origins `*` | `app/main.py:41` | HIGH |
| No API authentication | All routes | HIGH |
| Topic vulnerable to prompt injection | `llm_service.py` | MEDIUM |
| OAuth token stored as plaintext JSON | `youtube_service.py` | MEDIUM |
| Database credentials in config defaults | `config.py` | LOW |
| Error messages may leak internal details | `system.py` | LOW |

### Data Integrity Issues

| Issue | Location | Severity |
|-------|----------|----------|
| No state transition constraints | `video.py` model | MEDIUM |
| Race condition: project created, Celery dispatch fails | `pipeline.py:56-63` | MEDIUM |
| DELETE doesn't revoke running Celery tasks | `projects.py` | MEDIUM |
| DELETE doesn't clean up media files | `projects.py` | LOW |
| No database indexes on status, created_at | `video.py` | LOW |
| Retry always uses `openai` provider (ignores original) | `projects.py:148` | LOW |

### Performance Issues

| Issue | Location | Severity |
|-------|----------|----------|
| FFmpeg subprocess blocks Celery worker thread | `media_service.py` | MEDIUM |
| Sync file I/O inside async functions | `tts_service.py`, `visual_service.py` | LOW |
| Worker DB pool undersized (5) | `workers/db.py` | LOW |
| No database query optimization (missing indexes) | `video.py` | LOW |

### Code Quality Issues

| Issue | Location | Severity |
|-------|----------|----------|
| Async/sync bridging via event loop creation | `script_tasks.py:19-25` | MEDIUM |
| Database context manager called 3x per task | All worker tasks | LOW |
| Generic `Exception` catches mask errors | Multiple services | LOW |
| Hardcoded category "entertainment" for all uploads | `upload_tasks.py` | LOW |
| `ffmpeg-python` in requirements but subprocess used directly | `requirements.txt` | LOW |

---

## 8. Build Phases (Roadmap to Production)

### Phase 1: Foundation & Database (Week 1)

**Goal**: Make the existing code actually runnable.

#### 1.1 Create Alembic Migrations

```bash
# Generate migration from VideoProject model
alembic revision --autogenerate -m "create video_project table"

# Apply to database
alembic upgrade head
```

**Tasks:**
- [ ] Generate initial migration for VideoProject table
- [ ] Add database indexes on `status`, `created_at`, `celery_task_id`
- [ ] Add index on `youtube_video_id` for lookup
- [ ] Verify migration runs cleanly on fresh PostgreSQL
- [ ] Add `alembic upgrade head` to startup checks

#### 1.2 Fix Critical Code Issues

**Tasks:**
- [ ] Fix async/sync bridging in worker tasks (use `asyncio.run()` properly)
- [ ] Add transaction safety in pipeline route (rollback if Celery dispatch fails)
- [ ] Add state transition validation to VideoProject model
- [ ] Fix retry endpoint to preserve original provider
- [ ] Add missing `__all__` exports in `__init__.py` files

#### 1.3 Configuration Validation

**Tasks:**
- [ ] Add startup validation for all required API keys
- [ ] Validate FFmpeg/FFprobe are installed and on PATH
- [ ] Validate database connectivity on startup
- [ ] Validate Redis connectivity on startup
- [ ] Add `.env` validation script

#### 1.4 Startup Scripts

**Files to create:**
```
scripts/
├── start_api.sh          # uvicorn app.main:app --host 0.0.0.0 --port 8000
├── start_worker.sh       # celery -A app.core.celery_app worker -Q default,scripts,media,upload
├── start_flower.sh       # celery -A app.core.celery_app flower --port=5555
└── setup_db.sh           # alembic upgrade head
```

**Deliverables:**
- Database schema created and versioned
- Application starts without errors
- Workers connect to broker successfully
- Single pipeline runs end-to-end

---

### Phase 2: Telegram Bot Integration (Week 2)

**Goal**: Build the primary user interface — Telegram bot.

#### 2.1 Bot Setup & Commands

**New module:** `app/telegram/`

```
app/telegram/
├── __init__.py
├── bot.py                # Bot initialization + command registration
├── handlers/
│   ├── __init__.py
│   ├── commands.py       # /start, /help, /video, /status, /list, /cancel
│   ├── callbacks.py      # Inline keyboard callback handlers
│   └── errors.py         # Global error handler
├── keyboards.py          # Inline keyboard builders
├── messages.py           # Message templates (formatted text)
└── middleware.py          # Rate limiting, user auth
```

#### 2.2 Command Reference

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Welcome message + usage guide | `/start` |
| `/help` | List all commands | `/help` |
| `/video <topic>` | Generate a new video | `/video 5 facts about Mars` |
| `/video_long <topic>` | Generate long-form video | `/video_long History of AI` |
| `/status <id>` | Check project status | `/status abc123` |
| `/list` | Show recent projects | `/list` |
| `/cancel <id>` | Cancel running pipeline | `/cancel abc123` |
| `/retry <id>` | Retry failed project | `/retry abc123` |

#### 2.3 Real-Time Status Updates

```
User sends: /video "5 facts about black holes"

Bot responds:
  "🎬 Starting video generation...
   📋 Project ID: abc-123
   ⏳ Status: Generating script..."

[Auto-update messages as pipeline progresses]

  "✍️ Script generated!
   🎙️ Generating voiceover...
   🎥 Fetching video clips..."

  "🔧 Assembling video..."

  "📤 Uploading to YouTube..."

  "✅ Done!
   🔗 https://youtube.com/watch?v=xyz
   📊 Title: 5 Mind-Blowing Facts About Black Holes"
```

#### 2.4 Implementation Details

**Tasks:**
- [ ] Install `python-telegram-bot` v21+ (async)
- [ ] Create bot via BotFather, obtain token
- [ ] Implement webhook mode (production) with fallback to polling (development)
- [ ] Build `/video` command → calls `POST /api/v1/pipeline` internally
- [ ] Build status polling loop (check project status every 5 seconds)
- [ ] Edit message in-place as status changes (no spam)
- [ ] Add inline keyboards: [Cancel] [Retry] [Delete]
- [ ] Implement user allowlist (restrict bot to authorized users)
- [ ] Add rate limiting (max 5 videos per user per hour)
- [ ] Handle long topics gracefully (split/truncate)
- [ ] Store Telegram user_id ↔ project_id mapping in database

#### 2.5 Database Changes

Add new model or extend VideoProject:

```python
# New columns for VideoProject
telegram_user_id: int           # Telegram user who requested
telegram_chat_id: int           # Chat where to send updates
telegram_message_id: int        # Message to edit for status updates
```

**Deliverables:**
- Telegram bot responds to all commands
- `/video` triggers full pipeline and sends YouTube link on completion
- Status updates edit messages in real-time
- User allowlist restricts access

---

### Phase 3: Docker & Deployment (Week 3)

**Goal**: Containerize everything for reproducible deployment.

#### 3.1 Docker Setup

**Files to create:**

```
docker/
├── Dockerfile              # Multi-stage Python build
├── Dockerfile.worker       # Celery worker image
├── docker-compose.yml      # Full stack orchestration
├── docker-compose.dev.yml  # Development overrides
├── .dockerignore           # Build context exclusions
└── nginx/
    └── nginx.conf          # Reverse proxy config
```

#### 3.2 docker-compose.yml Services

```yaml
services:
  # --- Infrastructure ---
  postgres:
    image: postgres:16-alpine
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck: pg_isready

  redis:
    image: redis:7-alpine
    volumes: [redisdata:/data]
    healthcheck: redis-cli ping

  # --- Application ---
  api:
    build: { dockerfile: docker/Dockerfile }
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    depends_on: [postgres, redis]
    ports: ["8000:8000"]

  worker-scripts:
    build: { dockerfile: docker/Dockerfile.worker }
    command: celery -A app.core.celery_app worker -Q scripts -c 2
    depends_on: [postgres, redis]

  worker-media:
    build: { dockerfile: docker/Dockerfile.worker }
    command: celery -A app.core.celery_app worker -Q media -c 2
    depends_on: [postgres, redis]

  worker-upload:
    build: { dockerfile: docker/Dockerfile.worker }
    command: celery -A app.core.celery_app worker -Q upload -c 1
    depends_on: [postgres, redis]

  telegram-bot:
    build: { dockerfile: docker/Dockerfile }
    command: python -m app.telegram.bot
    depends_on: [api]

  # --- Monitoring ---
  flower:
    build: { dockerfile: docker/Dockerfile }
    command: celery -A app.core.celery_app flower
    ports: ["5555:5555"]

  nginx:
    image: nginx:alpine
    ports: ["80:80", "443:443"]
    depends_on: [api]
```

#### 3.3 Dockerfile (Multi-Stage)

```dockerfile
# Stage 1: Build
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
WORKDIR /app
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### 3.4 Tasks

- [ ] Create multi-stage Dockerfile (Python 3.12 slim + FFmpeg)
- [ ] Create separate worker Dockerfile with FFmpeg
- [ ] Write docker-compose.yml with all 8 services
- [ ] Add health checks for all containers
- [ ] Configure volume mounts for media persistence
- [ ] Add Nginx reverse proxy with SSL termination
- [ ] Create `.dockerignore` to minimize build context
- [ ] Create `docker-compose.dev.yml` with hot-reload
- [ ] Test full stack with `docker compose up`
- [ ] Add migration step to API container startup

**Deliverables:**
- `docker compose up` starts entire system
- All services healthy and communicating
- Media files persisted across restarts
- Development mode with hot-reload

---

### Phase 4: Security Hardening (Week 4)

**Goal**: Make the system production-safe.

#### 4.1 API Authentication

**Tasks:**
- [ ] Add API key authentication middleware
- [ ] Generate API keys per-user with database storage
- [ ] Add `X-API-Key` header validation
- [ ] Exempt health endpoint from auth
- [ ] Add request logging with user identification

#### 4.2 Rate Limiting

**Tasks:**
- [ ] Add `slowapi` or custom Redis-based rate limiter
- [ ] Pipeline endpoint: 10 requests/minute per API key
- [ ] Batch endpoint: 2 requests/minute per API key
- [ ] System endpoints: 60 requests/minute
- [ ] Telegram bot: 5 videos/hour per user

#### 4.3 Input Sanitization

**Tasks:**
- [ ] Sanitize topic field against prompt injection
- [ ] Add content moderation check (OpenAI Moderation API)
- [ ] Validate file paths in media service
- [ ] Restrict CORS to specific origins
- [ ] Add Content Security Policy headers

#### 4.4 Secrets Management

**Tasks:**
- [ ] Move from `.env` files to Docker secrets or vault
- [ ] Encrypt YouTube OAuth token at rest
- [ ] Rotate API keys on schedule
- [ ] Add secret scanning to CI pipeline
- [ ] Remove default credentials from config.py

#### 4.5 Network Security

**Tasks:**
- [ ] Internal services not exposed to public network
- [ ] PostgreSQL and Redis only accessible from Docker network
- [ ] HTTPS enforcement via Nginx
- [ ] Add request size limits (prevent DoS via large payloads)

**Deliverables:**
- All endpoints authenticated
- Rate limiting active
- Secrets encrypted and managed
- Network properly segmented

---

### Phase 5: Testing & Quality (Week 5)

**Goal**: Achieve confidence through automated testing.

#### 5.1 Test Structure

```
tests/
├── conftest.py                # Shared fixtures (DB, client, mocks)
├── unit/
│   ├── test_llm_service.py    # Script generation with mocked APIs
│   ├── test_tts_service.py    # TTS with mocked ElevenLabs
│   ├── test_visual_service.py # Pexels search with mocked API
│   ├── test_media_service.py  # FFmpeg commands validation
│   ├── test_youtube_service.py# Upload with mocked Google API
│   └── test_schemas.py        # Pydantic validation
├── integration/
│   ├── test_pipeline_route.py # API endpoint integration
│   ├── test_project_route.py  # CRUD operations
│   ├── test_system_route.py   # Health checks
│   └── test_celery_tasks.py   # Task execution (eager mode)
├── e2e/
│   └── test_full_pipeline.py  # Complete pipeline (staging APIs)
└── fixtures/
    ├── sample_script.json     # Mock LLM response
    ├── sample_audio.mp3       # Test audio file
    └── sample_video.mp4       # Test video clip
```

#### 5.2 Tasks

- [ ] Install pytest, pytest-asyncio, pytest-cov, httpx (test client)
- [ ] Create conftest.py with database fixtures (test DB, rollback per test)
- [ ] Write unit tests for all 5 services (mock external APIs)
- [ ] Write integration tests for all API endpoints
- [ ] Write Celery task tests using `CELERY_ALWAYS_EAGER=True`
- [ ] Add E2E test with staging API keys
- [ ] Configure coverage reporting (target: 80%+)
- [ ] Add `pytest.ini` or `pyproject.toml` configuration
- [ ] Add pre-commit hooks (black, ruff, mypy)

#### 5.3 Code Quality Tools

```
# pyproject.toml additions
[tool.black]
line-length = 100

[tool.ruff]
select = ["E", "F", "I", "N", "W"]

[tool.mypy]
plugins = ["pydantic.mypy"]
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Deliverables:**
- 80%+ code coverage
- All tests passing in CI
- Pre-commit hooks enforce style
- Type checking with mypy

---

### Phase 6: Monitoring & Observability (Week 6)

**Goal**: See what's happening in production at all times.

#### 6.1 Metrics (Prometheus + Grafana)

**Custom metrics to track:**

| Metric | Type | Description |
|--------|------|-------------|
| `pipeline_total` | Counter | Total pipelines triggered |
| `pipeline_completed` | Counter | Successfully completed |
| `pipeline_failed` | Counter | Failed pipelines |
| `pipeline_duration_seconds` | Histogram | End-to-end pipeline time |
| `step_duration_seconds` | Histogram | Per-step timing (script, audio, visual, assembly, upload) |
| `external_api_calls` | Counter | Calls to OpenAI, ElevenLabs, Pexels, YouTube |
| `external_api_errors` | Counter | External API failures |
| `active_celery_tasks` | Gauge | Currently running tasks |
| `queue_depth` | Gauge | Tasks waiting per queue |
| `media_disk_usage_bytes` | Gauge | Storage used by media files |

#### 6.2 Alerting Rules

| Alert | Condition | Severity |
|-------|-----------|----------|
| Pipeline failure rate > 20% | `rate(pipeline_failed) / rate(pipeline_total) > 0.2` | CRITICAL |
| Worker offline | No heartbeat for 5 minutes | CRITICAL |
| API response time > 5s | p95 latency > 5000ms | WARNING |
| Disk usage > 80% | media volume > 80% capacity | WARNING |
| Redis memory > 80% | Redis used memory > 80% | WARNING |
| Queue depth > 50 | Tasks waiting > 50 | WARNING |
| External API error rate > 10% | Error rate per API > 10% | WARNING |

#### 6.3 Tasks

- [ ] Add `prometheus-fastapi-instrumentator` for API metrics
- [ ] Add custom Celery metrics exporter
- [ ] Add Prometheus + Grafana containers to docker-compose
- [ ] Create Grafana dashboards (pipeline, workers, APIs, system)
- [ ] Configure alerting rules (email/Slack/Telegram notifications)
- [ ] Add Celery Flower for task monitoring UI
- [ ] Add structured JSON logging for log aggregation
- [ ] Add request ID tracing across API → Celery → services

#### 6.4 docker-compose additions

```yaml
  prometheus:
    image: prom/prometheus
    volumes: [./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml]
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana
    volumes: [grafanadata:/var/lib/grafana]
    ports: ["3000:3000"]
```

**Deliverables:**
- Grafana dashboard showing pipeline health
- Alerts firing on critical failures
- Request tracing across all components
- Flower UI for Celery task inspection

---

### Phase 7: Reliability & Error Handling (Week 7)

**Goal**: Handle failures gracefully, recover automatically.

#### 7.1 Dead Letter Queue

**Tasks:**
- [ ] Configure Celery DLQ for permanently failed tasks
- [ ] Create DLQ consumer that logs and notifies
- [ ] Add admin endpoint to inspect/retry DLQ tasks
- [ ] Telegram notification to user on permanent failure

#### 7.2 Media Cleanup

**Tasks:**
- [ ] Create scheduled Celery beat task for orphan cleanup
- [ ] Delete media files for COMPLETED projects older than 7 days
- [ ] Delete media files for FAILED projects older than 24 hours
- [ ] Log cleanup actions for audit
- [ ] Add disk usage monitoring

#### 7.3 Graceful Degradation

**Tasks:**
- [ ] Add circuit breaker for external APIs (using `circuitbreaker` package)
- [ ] Fallback: if OpenAI fails, try Anthropic automatically
- [ ] Fallback: if Pexels fails, use placeholder visuals
- [ ] Queue backpressure: reject new pipelines when queue depth > threshold
- [ ] Graceful worker shutdown (complete current task before stopping)

#### 7.4 Resume from Failure

**Tasks:**
- [ ] Track last completed step in VideoProject model
- [ ] Retry endpoint resumes from failure point (not full restart)
- [ ] Skip completed steps (script, audio, visuals) if artifacts exist
- [ ] Add `resume_from` parameter to pipeline endpoint

**Deliverables:**
- Failed tasks captured and inspectable
- Media storage bounded and self-cleaning
- External API failures don't cascade
- Retry resumes from failure point

---

### Phase 8: Performance & Scaling (Week 8)

**Goal**: Handle 100+ concurrent pipelines efficiently.

#### 8.1 Worker Scaling

**Tasks:**
- [ ] Separate workers per queue (scripts, media, upload)
- [ ] Configure concurrency per worker type:
  - Scripts: 4 concurrent (I/O bound, API calls)
  - Media: 2 concurrent (CPU bound, FFmpeg)
  - Upload: 2 concurrent (I/O bound, large files)
- [ ] Add auto-scaling based on queue depth
- [ ] Worker prefetch optimization

#### 8.2 Database Optimization

**Tasks:**
- [ ] Add composite indexes: `(status, created_at)`, `(telegram_user_id, created_at)`
- [ ] Connection pool tuning per workload
- [ ] Add read replicas for query endpoints
- [ ] Implement query caching with Redis
- [ ] Add database connection pooling with PgBouncer

#### 8.3 Media Pipeline Optimization

**Tasks:**
- [ ] Parallel FFmpeg operations for clip scaling
- [ ] GPU-accelerated encoding (NVENC) if available
- [ ] Pre-process and cache common stock footage
- [ ] CDN for media delivery (S3 + CloudFront)
- [ ] Stream upload directly to YouTube (no intermediate file)

#### 8.4 Caching

**Tasks:**
- [ ] Cache Pexels search results (same query → same clips)
- [ ] Cache ElevenLabs voice list
- [ ] Cache YouTube category list
- [ ] Add Redis TTL for all cached items

**Deliverables:**
- System handles 100+ concurrent pipelines
- Sub-10-minute average pipeline duration
- Workers auto-scale based on load
- Database performs at scale

---

### Phase 9: CI/CD & DevOps (Week 9)

**Goal**: Automate testing, building, and deployment.

#### 9.1 GitHub Actions

```yaml
# .github/workflows/ci.yml
name: CI Pipeline
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres: { image: postgres:16 }
      redis: { image: redis:7 }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest --cov=app --cov-report=xml
      - uses: codecov/codecov-action@v4

  lint:
    runs-on: ubuntu-latest
    steps:
      - run: ruff check app/
      - run: mypy app/
      - run: black --check app/

  build:
    needs: [test, lint]
    runs-on: ubuntu-latest
    steps:
      - run: docker build -t content-engine .
      - run: docker push ghcr.io/username/content-engine
```

#### 9.2 Deployment Pipeline

```yaml
# .github/workflows/deploy.yml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: docker compose -f docker-compose.prod.yml pull
      - run: docker compose -f docker-compose.prod.yml up -d
      - run: docker compose exec api alembic upgrade head
      - run: curl -f http://localhost:8000/api/v1/system/health
```

#### 9.3 Tasks

- [ ] Create `.github/workflows/ci.yml` (test + lint + build)
- [ ] Create `.github/workflows/deploy.yml` (staging + production)
- [ ] Add branch protection rules (require passing CI)
- [ ] Add Dependabot for dependency updates
- [ ] Create `requirements-dev.txt` (pytest, black, ruff, mypy)
- [ ] Add pre-commit hooks configuration
- [ ] Set up container registry (GHCR or Docker Hub)
- [ ] Create staging environment
- [ ] Add rollback capability

**Deliverables:**
- Every push runs tests and linting
- Merges to main auto-deploy to staging
- Production deploys via release tags
- Automatic dependency updates

---

### Phase 10: Polish & Launch (Week 10)

**Goal**: Final polish, documentation, and production launch.

#### 10.1 Documentation

**Tasks:**
- [ ] Write comprehensive README.md
- [ ] Create CONTRIBUTING.md
- [ ] Document all API endpoints (beyond auto-generated Swagger)
- [ ] Write deployment guide (VPS, AWS, GCP)
- [ ] Create architecture decision records (ADRs)
- [ ] Add inline code documentation for complex logic
- [ ] Create user guide for Telegram bot

#### 10.2 Feature Polish

**Tasks:**
- [ ] Add video thumbnail generation
- [ ] Add scheduling: `/video "topic" at 3pm`
- [ ] Add video templates (intro/outro overlays)
- [ ] Add analytics: video performance tracking
- [ ] Add multi-language support for scripts and TTS
- [ ] Add custom voice selection via Telegram
- [ ] Add video preview before upload

#### 10.3 Production Checklist

```
Pre-Launch Checklist:
├── [ ] All API keys are production keys (not dev/test)
├── [ ] YouTube OAuth scopes are minimal
├── [ ] Database backups configured (daily)
├── [ ] Redis persistence enabled (AOF)
├── [ ] SSL certificates installed (Let's Encrypt)
├── [ ] Domain configured and DNS propagated
├── [ ] Telegram webhook URL points to production
├── [ ] Rate limiting tested under load
├── [ ] Error alerting verified (send test alert)
├── [ ] Log rotation configured (30 days retention)
├── [ ] Media cleanup cron job active
├── [ ] Monitoring dashboards accessible
├── [ ] Rollback procedure documented and tested
├── [ ] Load test completed (target: 50 concurrent pipelines)
└── [ ] Security audit completed
```

**Deliverables:**
- Production system live and monitored
- Documentation complete
- Users onboarded via Telegram
- System handling real traffic

---

## 9. API Reference

### Pipeline Endpoints

#### `POST /api/v1/pipeline`
Trigger a single video generation pipeline.

**Request Body:**
```json
{
  "topic": "5 amazing facts about black holes",
  "video_format": "short",        // "short" (9:16) | "long" (16:9)
  "provider": "openai",           // "openai" | "anthropic"
  "skip_upload": false            // Skip YouTube upload
}
```

**Response (202 Accepted):**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "celery_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "message": "Pipeline started for topic: 5 amazing facts about black holes"
}
```

#### `POST /api/v1/pipeline/batch`
Trigger up to 10 pipelines simultaneously.

**Request Body:**
```json
{
  "topics": [
    {"topic": "Facts about Mars", "video_format": "short"},
    {"topic": "History of AI", "video_format": "short"}
  ]
}
```

### Project Endpoints

#### `GET /api/v1/projects?page=1&per_page=20&status=completed`
List projects with pagination and optional status filter.

#### `GET /api/v1/projects/{project_id}`
Get full project details including YouTube URL.

#### `DELETE /api/v1/projects/{project_id}`
Delete a project record.

#### `POST /api/v1/projects/{project_id}/retry`
Retry a failed project (resets status to PENDING).

### System Endpoints

#### `GET /api/v1/system/health`
Deep health check (database + Redis connectivity).

**Response:**
```json
{
  "status": "healthy",
  "app": "content-engine",
  "database": "connected",
  "redis": "connected"
}
```

#### `GET /api/v1/system/tasks/{task_id}`
Check Celery task status.

#### `POST /api/v1/system/tasks/{task_id}/revoke`
Cancel a running Celery task.

---

## 10. Data Models

### VideoProject

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key (auto-generated) |
| `topic` | String(512) | User-provided topic |
| `script` | Text | LLM-generated script (nullable) |
| `status` | Enum | Pipeline state (see state machine) |
| `video_format` | Enum | SHORT (9:16) or LONG (16:9) |
| `celery_task_id` | String(255) | Celery task tracking |
| `audio_path` | String(500) | Path to generated MP3 |
| `video_path` | String(500) | Path to downloaded clips |
| `output_path` | String(500) | Path to final MP4 |
| `youtube_video_id` | String(50) | YouTube video ID |
| `youtube_url` | String(255) | YouTube watch URL |
| `error_message` | Text | Error details (nullable) |
| `created_at` | DateTime(tz) | Row creation timestamp |
| `updated_at` | DateTime(tz) | Last update timestamp |

### VideoStatus Enum

| Value | Description |
|-------|-------------|
| `PENDING` | Created, waiting for worker |
| `SCRIPT_GENERATING` | LLM generating script |
| `AUDIO_GENERATING` | ElevenLabs generating TTS |
| `VIDEO_GENERATING` | Pexels clips downloading |
| `ASSEMBLING` | FFmpeg encoding final video |
| `UPLOADING` | Uploading to YouTube |
| `COMPLETED` | Pipeline finished successfully |
| `FAILED` | Pipeline failed (see error_message) |

---

## 11. Pipeline Deep Dive

### Step 1: Script Generation

```
Input:  topic="5 facts about black holes", format="short", provider="openai"
Model:  GPT-4o (temperature=0.9, max_tokens=4096)
Output: {
  "title": "5 Mind-Blowing Black Hole Facts You Didn't Know",
  "script": "Did you know that a black hole the size of a coin would...",
  "tags": ["black holes", "space", "science", "facts", "astronomy"],
  "description": "Discover 5 incredible facts about black holes..."
}
```

- System prompt customized for short (30-60s) vs long (5-10min) format
- JSON response mode enforced
- 3 retries with exponential backoff (4s → 8s → 16s, max 60s)

### Step 2a: Audio Generation (Parallel)

```
Input:  script text, voice_id="21m00Tcm4TlvDq8ikWAM"
Model:  eleven_multilingual_v2
Output: media/audio/{uuid}.mp3
```

- Streaming download in 8KB chunks
- 120-second timeout
- 3 retries with exponential backoff

### Step 2b: Visual Fetching (Parallel)

```
Input:  tags=["black holes", "space", "science", "astronomy"]
API:    Pexels Video Search
Filter: orientation="portrait", duration=5-30s
Output: media/video/{uuid}_0.mp4, {uuid}_1.mp4, ...
```

- Searches up to 4 tag queries
- Quality scoring algorithm picks best variant
- Downloads multiple clips per query

### Step 3: Video Assembly

```
Input:  audio.mp3 + [clip1.mp4, clip2.mp4, ...]
Target: 1080x1920 (9:16 for Shorts)
Codec:  H.264 (libx264), CRF 23, fast preset
Audio:  AAC 192kbps
Output: media/output/final_{uuid}.mp4
```

Pipeline:
1. Scale each clip → target resolution (black padding for aspect ratio)
2. Concatenate clips via FFmpeg concat demuxer
3. Overlay TTS audio (trim to audio duration)
4. Clean up temporary files

### Step 4: YouTube Upload

```
Input:  final_{uuid}.mp4 + metadata from script
Method: Resumable upload (10MB chunks)
Auth:   OAuth2 with automatic token refresh
Output: { video_id: "dQw4w9WgXcQ", url: "https://youtube.com/watch?v=..." }
```

- Adds `#Shorts` to title and tags for Shorts visibility
- Default privacy: `private`
- Category: Entertainment (customizable)

---

## 12. Environment & Configuration

### Required Environment Variables

```bash
# ─── Application ───────────────────────────────
APP_NAME=content-engine
APP_ENV=production               # development | staging | production
DEBUG=false
LOG_LEVEL=INFO                   # DEBUG | INFO | WARNING | ERROR

# ─── Database ─────────────────────────────────
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/content_engine
DATABASE_URL_SYNC=postgresql+psycopg2://user:pass@host:5432/content_engine

# ─── Redis / Celery ───────────────────────────
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# ─── LLM APIs ─────────────────────────────────
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929

# ─── Text-to-Speech ───────────────────────────
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM

# ─── Stock Footage ─────────────────────────────
PEXELS_API_KEY=...

# ─── YouTube ───────────────────────────────────
YOUTUBE_CLIENT_SECRETS_FILE=client_secrets.json
YOUTUBE_TOKEN_FILE=youtube_token.json

# ─── Telegram (Phase 2) ───────────────────────
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USERS=123456,789012    # Comma-separated user IDs
TELEGRAM_WEBHOOK_URL=https://yourdomain.com/telegram/webhook

# ─── Media ─────────────────────────────────────
MEDIA_DIR=media
```

### External Service Dependencies

| Service | Purpose | Free Tier | Production Cost |
|---------|---------|-----------|-----------------|
| OpenAI | Script generation | $5 credit | ~$0.03/script |
| Anthropic | Script generation (alt) | $5 credit | ~$0.02/script |
| ElevenLabs | Text-to-speech | 10k chars/month | ~$0.30/minute |
| Pexels | Stock video footage | Unlimited | Free |
| YouTube Data API | Video upload | 10k units/day | Free |
| Redis | Task broker | Self-hosted | ~$0/month |
| PostgreSQL | Data persistence | Self-hosted | ~$0/month |

**Estimated cost per video: $0.35–$0.65** (depending on script length and TTS duration)

---

## 13. Deployment Architecture (Target)

### Production Setup (Single VPS)

```
┌─────────────────────────────────────────────────────────────┐
│                       VPS (4 CPU, 8GB RAM)                  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                 Docker Compose                       │    │
│  │                                                     │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │    │
│  │  │  Nginx   │  │  FastAPI  │  │  Telegram Bot    │  │    │
│  │  │  :80/443 │─►│  :8000   │  │  (webhook/poll)  │  │    │
│  │  └──────────┘  └──────────┘  └──────────────────┘  │    │
│  │                      │                              │    │
│  │  ┌──────────────────────────────────────────────┐   │    │
│  │  │              Celery Workers                   │   │    │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐  │   │    │
│  │  │  │ Scripts  │ │  Media   │ │   Upload     │  │   │    │
│  │  │  │ Worker   │ │  Worker  │ │   Worker     │  │   │    │
│  │  │  │ (c=4)   │ │  (c=2)   │ │   (c=2)     │  │   │    │
│  │  │  └──────────┘ └──────────┘ └──────────────┘  │   │    │
│  │  └──────────────────────────────────────────────┘   │    │
│  │                      │                              │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │    │
│  │  │PostgreSQL│  │  Redis   │  │  Flower :5555    │  │    │
│  │  │  :5432   │  │  :6379   │  │  (monitoring)    │  │    │
│  │  └──────────┘  └──────────┘  └──────────────────┘  │    │
│  │                                                     │    │
│  │  ┌──────────┐  ┌──────────┐                         │    │
│  │  │Prometheus│  │ Grafana  │                         │    │
│  │  │  :9090   │  │  :3000   │                         │    │
│  │  └──────────┘  └──────────┘                         │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  Volumes:                                                   │
│  ├── /data/postgres    (database)                           │
│  ├── /data/redis       (broker)                             │
│  ├── /data/media       (audio, video, output)               │
│  └── /data/logs        (application logs)                   │
└─────────────────────────────────────────────────────────────┘
```

### Minimum Hardware Requirements

| Environment | CPU | RAM | Storage | Cost (approx) |
|-------------|-----|-----|---------|----------------|
| Development | 2 cores | 4 GB | 20 GB | Local machine |
| Staging | 2 cores | 4 GB | 40 GB | ~$20/month |
| Production | 4 cores | 8 GB | 100 GB | ~$40/month |
| Production (scaled) | 8 cores | 16 GB | 200 GB | ~$80/month |

---

## Summary: Phase Timeline

```
Week  1: ██████████ Phase 1 — Foundation (migrations, fixes, scripts)
Week  2: ██████████ Phase 2 — Telegram Bot (commands, status, keyboards)
Week  3: ██████████ Phase 3 — Docker (containers, compose, nginx)
Week  4: ██████████ Phase 4 — Security (auth, rate limiting, secrets)
Week  5: ██████████ Phase 5 — Testing (unit, integration, e2e, coverage)
Week  6: ██████████ Phase 6 — Monitoring (Prometheus, Grafana, alerts)
Week  7: ██████████ Phase 7 — Reliability (DLQ, cleanup, circuit breakers)
Week  8: ██████████ Phase 8 — Performance (scaling, caching, optimization)
Week  9: ██████████ Phase 9 — CI/CD (GitHub Actions, auto-deploy)
Week 10: ██████████ Phase 10 — Polish & Launch (docs, features, go-live)
```

**Current progress: ~55% of total scope built (core pipeline complete, operational infrastructure missing)**

---

> **Next Action**: Start Phase 1 — Generate Alembic migrations, fix critical code issues, create startup scripts, and validate the pipeline runs end-to-end.
