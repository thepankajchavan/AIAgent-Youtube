# 🎬 YouTube Shorts Automation Engine

**AI-powered video generation from topic to YouTube upload — fully automated.**

[![CI Pipeline](https://github.com/yourusername/youtube-shorts-automation/workflows/CI%20Pipeline/badge.svg)](https://github.com/yourusername/youtube-shorts-automation/actions)
[![Coverage](https://codecov.io/gh/yourusername/youtube-shorts-automation/branch/main/graph/badge.svg)](https://codecov.io/gh/yourusername/youtube-shorts-automation)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?logo=docker&logoColor=white)](https://www.docker.com/)

---

## 📖 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Demo](#-demo)
- [Quick Start](#-quick-start)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Documentation](#-documentation)
- [Development](#-development)
- [Deployment](#-deployment)
- [Monitoring](#-monitoring)
- [Contributing](#-contributing)
- [License](#-license)
- [Acknowledgments](#-acknowledgments)

---

## 🎯 Overview

The YouTube Shorts Automation Engine is a **production-grade system** that generates and publishes YouTube Shorts videos with **zero manual intervention**. Simply provide a topic via Telegram, and the system handles everything:

1. **Script Generation** — AI writes an engaging script using GPT-4o or Claude
2. **Voice Synthesis** — Converts script to natural speech with ElevenLabs TTS
3. **Visual Assembly** — Fetches relevant stock footage from Pexels
4. **Video Encoding** — Assembles final video with FFmpeg (9:16 aspect ratio)
5. **YouTube Upload** — Publishes to your channel with optimized metadata
6. **Real-time Notifications** — Updates you via Telegram at every step

**End-to-end pipeline: 3-8 minutes from topic to published video.**

## ✨ Features

### 🤖 AI-Powered Content Generation
- **Dual LLM support**: OpenAI GPT-4o and Anthropic Claude Sonnet
- **Format-aware prompts**: Short (30-60s) and Long (5-10min) video formats
- **Automatic tag generation**: SEO-optimized tags and descriptions
- **Content moderation**: Built-in safety checks to prevent policy violations

### 🎙️ Professional Text-to-Speech
- **ElevenLabs multilingual_v2**: Natural-sounding voice synthesis
- **Customizable voices**: Support for 100+ voices in 29 languages
- **Voice cloning**: Clone your own voice for brand consistency
- **Emotion control**: Adjust stability, similarity, and style parameters

### 🎥 Intelligent Visual Assembly
- **Pexels integration**: Access to 3+ million free stock videos
- **Smart clip selection**: Orientation matching, quality scoring, duration filtering
- **GPU acceleration**: NVENC/VA-API hardware encoding support
- **Parallel processing**: Concurrent clip processing for faster assembly

### 📤 YouTube Automation
- **OAuth2 authentication**: Secure, automatic token refresh
- **Resumable uploads**: 10MB chunks with retry logic
- **Shorts optimization**: Automatic #Shorts tag and 9:16 formatting
- **Privacy controls**: Configurable privacy settings (public, unlisted, private)

### 💬 Telegram Integration
- **8 interactive commands**: /video, /status, /list, /cancel, /retry, and more
- **Real-time status updates**: Live progress notifications via Redis pub/sub
- **User allowlist**: Access control with per-user rate limiting (5 videos/hour)
- **Rich formatting**: Emoji status indicators and formatted messages

### 🛡️ Enterprise-Grade Reliability
- **Dead Letter Queue**: Capture and analyze permanently failed tasks
- **Circuit breakers**: Graceful degradation for external API failures
- **Automatic fallbacks**: OpenAI → Anthropic, Pexels → placeholder videos
- **Resume from failure**: Smart retry from last completed step
- **Media cleanup**: Automated cleanup with configurable retention policies

### 📊 Comprehensive Monitoring
- **Prometheus metrics**: 10+ custom metrics for pipeline tracking
- **Grafana dashboards**: Pre-built dashboards for pipeline, workers, and API
- **Alertmanager**: 9 alerting rules with email/Slack notifications
- **Celery Flower**: Real-time task monitoring and management
- **Distributed tracing**: Request tracking across all components

### ⚡ Performance & Scaling
- **Horizontal scaling**: Docker Compose, Kubernetes HPA, KEDA support
- **Redis caching**: Query result caching for external APIs (24h TTL)
- **Connection pooling**: Optimized database connections (pool_size=20)
- **Composite indexes**: 5 database indexes for common query patterns
- **Queue backpressure**: Automatic pipeline rejection when queue depth >50

### 🔒 Security Hardening
- **API key authentication**: Per-user API keys with request tracking
- **Input sanitization**: 13 prompt injection patterns blocked
- **Encrypted secrets**: OAuth tokens encrypted at rest
- **Rate limiting**: Per-endpoint and per-user limits
- **Security scanning**: Trivy vulnerability scanning in CI/CD

### 🚀 CI/CD Automation
- **GitHub Actions**: 6-job CI pipeline (test, lint, build, security, migrations)
- **Automated deployments**: Staging auto-deploy, production manual approval
- **Rollback capability**: Automatic rollback on deployment failures
- **Dependabot**: Weekly dependency updates with grouped PRs
- **Coverage tracking**: Codecov integration with 80%+ requirement

## Architecture

```
┌──────────────┐                  ┌──────────────┐
│   Telegram   │ ────────────────►│   FastAPI    │
│     Bot      │  POST /pipeline  │      API     │
└──────────────┘                  └──────┬───────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────┐
│                 Celery Workers                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────┐  │
│  │ Scripts  │→│ Audio +  │→│ Assembly │→│Upload│  │
│  │  (LLM)   │ │  Video   │ │ (FFmpeg) │ │(YT)  │  │
│  └──────────┘ └──────────┘ └──────────┘ └─────┘  │
└────────────────────────────────────────────────────┘
                         │
                         ▼
              ┌──────────────────┐
              │ Telegram Notifier│
              │  (Real-time      │
              │   status updates)│
              └──────────────────┘
```

## Quick Start (Docker)

### Prerequisites

- **Docker** 20.10+ with Compose V2
- **System Resources:** 8GB RAM, 6+ CPU cores, 20GB storage
- **API Keys:**
  - OpenAI API key (for script generation)
  - ElevenLabs API key (for text-to-speech)
  - Pexels API key (for stock footage)
  - Telegram Bot Token (from @BotFather)
  - YouTube OAuth credentials (optional, for uploading)

### 1. Clone and Configure

```bash
git clone <your-repo-url>
cd "AI Agents"

# Copy environment template
cp .env.docker .env

# Edit .env with your API keys
nano .env  # or use your preferred editor
```

### 2. Build and Start

```bash
# Build Docker images
docker compose build

# Start all services
docker compose up -d
```

**This starts 9 services:**
- postgres (PostgreSQL database)
- redis (message broker + cache)
- api (FastAPI server on http://localhost:8000)
- celery-default, celery-scripts, celery-media, celery-upload (workers)
- telegram-bot (Telegram bot polling)
- telegram-notifier (status updates)

### 3. Verify Health

```bash
# Check all services are running
docker compose ps

# Test API health
curl http://localhost:8000/health

# View logs
docker compose logs -f api
docker compose logs -f celery-scripts
```

### 4. Setup Telegram Bot

```bash
# Get your Telegram user ID from @userinfobot

# Add yourself to allowlist
docker compose exec api python scripts/manage_telegram_users.py add <YOUR_USER_ID>

# Send /start to your bot on Telegram
# Try: /video 5 facts about black holes
```

## Usage

### Telegram Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/video <topic>` | Generate 9:16 short video | `/video 5 facts about Mars` |
| `/video_long <topic>` | Generate 16:9 long video | `/video_long History of AI` |
| `/status <id>` | Check project status | `/status uuid-here` |
| `/list` | Show your recent projects | `/list` |
| `/cancel <id>` | Cancel running project | `/cancel uuid-here` |
| `/retry <id>` | Retry failed project | `/retry uuid-here` |

### REST API (Alternative)

```bash
# Trigger pipeline via API
curl -X POST http://localhost:8000/api/v1/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "5 amazing facts about black holes",
    "video_format": "short",
    "provider": "openai",
    "skip_upload": false
  }'

# Check project status
curl http://localhost:8000/api/v1/projects/{project_id}

# List all projects
curl http://localhost:8000/api/v1/projects
```

**API Documentation:** http://localhost:8000/docs (Swagger UI)

## Configuration

### Environment Variables (.env)

```bash
# Required API Keys
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=...
PEXELS_API_KEY=...
TELEGRAM_BOT_TOKEN=...

# Database (auto-configured in Docker)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/content_engine

# Redis (auto-configured in Docker)
REDIS_URL=redis://redis:6379/0
```

### Video Formats

- **Short** (9:16): 30-60 seconds, optimized for YouTube Shorts
- **Long** (16:9): 5-10 minutes, standard landscape format

### LLM Providers

- **OpenAI** (default): GPT-4o - faster, more consistent
- **Anthropic**: Claude Sonnet 4.5 - higher quality scripts

## Production Deployment

```bash
# Use production configuration
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Production features:**
- Nginx reverse proxy with rate limiting
- Internal-only database/redis (no port exposure)
- Strong password requirements
- WARNING-level logging
- Security headers

## Development

### Manual Setup (Without Docker)

**Requirements:**
- Python 3.12+
- PostgreSQL 16+
- Redis 7+
- FFmpeg (with ffprobe)

```bash
# Install dependencies
pip install -r requirements.txt

# Setup database
alembic upgrade head

# Start services (separate terminals)
scripts/start_api.bat          # or .sh on Linux/Mac
scripts/start_worker.bat
scripts/start_telegram_bot.bat
scripts/start_telegram_notifier.bat
```

### Project Structure

```
AI Agents/
├── app/
│   ├── api/               # FastAPI routes
│   ├── core/              # Config, database, Celery
│   ├── models/            # SQLAlchemy models
│   ├── services/          # LLM, TTS, Pexels, FFmpeg, YouTube
│   ├── telegram/          # Telegram bot handlers
│   └── workers/           # Celery tasks
├── alembic/               # Database migrations
├── docker/                # Docker configs
│   ├── entrypoint.sh      # Service router
│   └── nginx/             # Reverse proxy config
├── scripts/               # Startup scripts
├── media/                 # Generated files (volumes)
│   ├── audio/
│   ├── video/
│   └── output/
├── Dockerfile             # Multi-stage Python 3.12 + FFmpeg
├── docker-compose.yml     # 9-service stack
└── docker-compose.prod.yml # Production overrides
```

## Monitoring

### Logs

```bash
# View all logs
docker compose logs -f

# View specific service
docker compose logs -f api
docker compose logs -f celery-scripts

# View last 100 lines
docker compose logs --tail=100 celery-media
```

### Health Checks

```bash
# API health
curl http://localhost:8000/health

# Deep health (DB + Redis + Celery)
curl http://localhost:8000/api/v1/system/health

# Check running services
docker compose ps
```

### Task Monitoring

```bash
# Check Celery task status
curl http://localhost:8000/api/v1/system/tasks/{task_id}

# Revoke running task
curl -X POST http://localhost:8000/api/v1/system/tasks/{task_id}/revoke?terminate=true
```

## Troubleshooting

### Docker Issues

```bash
# Rebuild images (after code changes)
docker compose build --no-cache

# Reset everything (WARNING: deletes all data)
docker compose down -v
docker compose up -d

# View container logs
docker compose logs -f postgres
docker compose logs -f redis
```

### Common Errors

**"Database connection failed"**
- Check PostgreSQL is running: `docker compose ps postgres`
- Verify health: `docker compose exec postgres pg_isready`

**"Redis connection failed"**
- Check Redis is running: `docker compose ps redis`
- Verify health: `docker compose exec redis redis-cli ping`

**"FFmpeg not found"**
- Docker image includes FFmpeg automatically
- For manual setup: Install FFmpeg and add to PATH

**"API key not configured"**
- Check `.env` file exists and has all required keys
- Restart services: `docker compose restart`

**"Unauthorized user" (Telegram)**
- Add user to allowlist: `docker compose exec api python scripts/manage_telegram_users.py add <user_id>`

### Getting Help

- **Full Documentation:** See `PROJECT_STATUS.md` for detailed architecture
- **API Reference:** http://localhost:8000/docs
- **Report Issues:** https://github.com/anthropics/claude-code/issues

## Tech Stack

- **Backend:** FastAPI 0.115+, Python 3.12
- **Workers:** Celery 5.4 with Redis broker
- **Database:** PostgreSQL 16 (asyncpg + psycopg2)
- **Bot:** python-telegram-bot 20.7
- **LLMs:** OpenAI GPT-4o, Anthropic Claude Sonnet 4.5
- **TTS:** ElevenLabs multilingual_v2
- **Footage:** Pexels API
- **Assembly:** FFmpeg (H.264 encoding)
- **Upload:** YouTube Data API v3
- **Containers:** Docker 20.10+, Docker Compose V2

## License

MIT License - See LICENSE file for details

## Status

**Current Version:** Phase 3 Complete (Docker & Containerization)
- ✅ Phase 1: Foundation & Database
- ✅ Phase 2: Telegram Bot Integration
- ✅ Phase 3: Docker & Containerization
- ⏳ Phase 4: Security Hardening (Planned)
- ⏳ Phase 5: Testing & Quality (Planned)

**Last Updated:** 2026-03-03
