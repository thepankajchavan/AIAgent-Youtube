# API Reference

Complete documentation for all REST API endpoints in the YouTube Shorts Automation Engine.

## Base URL

```
Development: http://localhost:8000
Production:  https://your-domain.com
```

## Authentication

All API endpoints (except `/health`) require API key authentication.

**Header:**
```
X-API-Key: your-api-key-here
```

**Obtaining an API Key:**
```bash
# Create API key via admin endpoint
curl -X POST http://localhost:8000/api/v1/admin/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "My App", "description": "Production API key"}'
```

---

## Table of Contents

1. [Pipeline Endpoints](#pipeline-endpoints)
2. [Project Endpoints](#project-endpoints)
3. [Admin Endpoints](#admin-endpoints)
4. [System Endpoints](#system-endpoints)
5. [Schemas](#schemas)
6. [Error Codes](#error-codes)

---

## Pipeline Endpoints

### POST /api/v1/pipeline

Trigger a single video generation pipeline.

**Request Body:**
```json
{
  "topic": "5 amazing facts about black holes",
  "video_format": "short",
  "provider": "openai",
  "skip_upload": false
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `topic` | string | Yes | Video topic (3-512 characters) |
| `video_format` | string | No | Video format: `short` (9:16) or `long` (16:9). Default: `short` |
| `provider` | string | No | LLM provider: `openai` or `anthropic`. Default: `openai` |
| `skip_upload` | boolean | No | Skip YouTube upload. Default: `false` |

**Response (202 Accepted):**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "celery_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "message": "Pipeline started for topic: 5 amazing facts about black holes"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/pipeline \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "topic": "5 amazing facts about space",
    "video_format": "short",
    "provider": "openai"
  }'
```

---

### POST /api/v1/pipeline/batch

Trigger multiple pipelines simultaneously (up to 10).

**Request Body:**
```json
{
  "topics": [
    {
      "topic": "Facts about Mars",
      "video_format": "short",
      "provider": "openai"
    },
    {
      "topic": "History of AI",
      "video_format": "short",
      "provider": "anthropic"
    }
  ]
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `topics` | array | Yes | Array of pipeline requests (max 10) |

**Response (202 Accepted):**
```json
{
  "projects": [
    {
      "project_id": "550e8400-e29b-41d4-a716-446655440001",
      "celery_task_id": "task-id-1",
      "status": "pending"
    },
    {
      "project_id": "550e8400-e29b-41d4-a716-446655440002",
      "celery_task_id": "task-id-2",
      "status": "pending"
    }
  ],
  "message": "2 pipelines started successfully"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/pipeline/batch \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "topics": [
      {"topic": "Space facts", "video_format": "short"},
      {"topic": "AI history", "video_format": "short"}
    ]
  }'
```

---

## Project Endpoints

### GET /api/v1/projects

List all projects with pagination and filtering.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `page` | integer | No | Page number (default: 1) |
| `per_page` | integer | No | Items per page (default: 20, max: 100) |
| `status` | string | No | Filter by status (see [VideoStatus](#videostatus)) |

**Response (200 OK):**
```json
{
  "projects": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "topic": "5 facts about Mars",
      "status": "completed",
      "video_format": "short",
      "youtube_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
      "created_at": "2026-03-03T10:30:00Z",
      "updated_at": "2026-03-03T10:38:00Z"
    }
  ],
  "total": 42,
  "page": 1,
  "per_page": 20,
  "pages": 3
}
```

**Example:**
```bash
# Get first page
curl http://localhost:8000/api/v1/projects

# Get page 2 with 50 items
curl "http://localhost:8000/api/v1/projects?page=2&per_page=50"

# Filter by status
curl "http://localhost:8000/api/v1/projects?status=completed"
```

---

### GET /api/v1/projects/{project_id}

Get detailed information about a specific project.

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | UUID | Yes | Project ID |

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "topic": "5 facts about Mars",
  "script": "Did you know that Mars has the largest volcano in our solar system...",
  "status": "completed",
  "video_format": "short",
  "celery_task_id": "task-id-123",
  "audio_path": "media/audio/uuid.mp3",
  "video_path": "media/video/uuid",
  "output_path": "media/output/final_uuid.mp4",
  "youtube_video_id": "dQw4w9WgXcQ",
  "youtube_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
  "error_message": null,
  "created_at": "2026-03-03T10:30:00Z",
  "updated_at": "2026-03-03T10:38:00Z"
}
```

**Response (404 Not Found):**
```json
{
  "detail": "Project not found"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/projects/550e8400-e29b-41d4-a716-446655440000
```

---

### DELETE /api/v1/projects/{project_id}

Delete a project and its associated media files.

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | UUID | Yes | Project ID |

**Response (200 OK):**
```json
{
  "message": "Project deleted successfully",
  "project_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response (404 Not Found):**
```json
{
  "detail": "Project not found"
}
```

**Example:**
```bash
curl -X DELETE http://localhost:8000/api/v1/projects/550e8400-e29b-41d4-a716-446655440000 \
  -H "X-API-Key: your-api-key"
```

---

### POST /api/v1/projects/{project_id}/retry

Retry a failed project. Resumes from the last completed step.

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | UUID | Yes | Project ID |

**Response (200 OK):**
```json
{
  "message": "Project retry initiated",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "new_celery_task_id": "new-task-id-456",
  "resume_from": "assembly"
}
```

**Response (400 Bad Request):**
```json
{
  "detail": "Project is not in failed state"
}
```

**Response (404 Not Found):**
```json
{
  "detail": "Project not found"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/projects/550e8400-e29b-41d4-a716-446655440000/retry \
  -H "X-API-Key: your-api-key"
```

---

## Admin Endpoints

### POST /api/v1/admin/keys

Create a new API key.

**Request Body:**
```json
{
  "name": "Production API",
  "description": "API key for production deployment"
}
```

**Response (201 Created):**
```json
{
  "id": "key-id-123",
  "key": "sk_live_abcdef123456",
  "name": "Production API",
  "description": "API key for production deployment",
  "is_active": true,
  "created_at": "2026-03-03T10:00:00Z"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/admin/keys \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Mobile App",
    "description": "API key for mobile application"
  }'
```

---

### GET /api/v1/admin/keys

List all API keys.

**Response (200 OK):**
```json
{
  "keys": [
    {
      "id": "key-id-123",
      "name": "Production API",
      "is_active": true,
      "total_requests": 1523,
      "last_used_at": "2026-03-03T14:30:00Z",
      "created_at": "2026-03-03T10:00:00Z"
    }
  ]
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/admin/keys
```

---

### GET /api/v1/admin/keys/{key_id}

Get details about a specific API key.

**Response (200 OK):**
```json
{
  "id": "key-id-123",
  "key": "sk_live_***456",
  "name": "Production API",
  "description": "API key for production deployment",
  "is_active": true,
  "total_requests": 1523,
  "last_used_at": "2026-03-03T14:30:00Z",
  "created_at": "2026-03-03T10:00:00Z"
}
```

---

### PATCH /api/v1/admin/keys/{key_id}/revoke

Revoke (deactivate) an API key.

**Response (200 OK):**
```json
{
  "message": "API key revoked successfully",
  "key_id": "key-id-123"
}
```

---

### PATCH /api/v1/admin/keys/{key_id}/activate

Reactivate a revoked API key.

**Response (200 OK):**
```json
{
  "message": "API key activated successfully",
  "key_id": "key-id-123"
}
```

---

### DELETE /api/v1/admin/keys/{key_id}

Permanently delete an API key.

**Response (200 OK):**
```json
{
  "message": "API key deleted successfully",
  "key_id": "key-id-123"
}
```

---

### GET /api/v1/admin/dlq/tasks

List all tasks in the Dead Letter Queue (permanently failed).

**Response (200 OK):**
```json
{
  "tasks": [
    {
      "task_id": "failed-task-123",
      "task_name": "generate_script_task",
      "project_id": "550e8400-e29b-41d4-a716-446655440000",
      "exception_type": "APIError",
      "failed_at": "2026-03-03T10:30:00Z"
    }
  ],
  "total": 3
}
```

---

### GET /api/v1/admin/dlq/tasks/{task_id}

Get detailed information about a failed task.

**Response (200 OK):**
```json
{
  "task_id": "failed-task-123",
  "task_name": "generate_script_task",
  "args": ["project-id", "topic", "short", "openai"],
  "kwargs": {},
  "exception_type": "APIError",
  "exception_message": "OpenAI API rate limit exceeded",
  "traceback": "Traceback (most recent call last)...",
  "failed_at": "2026-03-03T10:30:00Z"
}
```

---

### POST /api/v1/admin/dlq/tasks/{task_id}/retry

Retry a task from the Dead Letter Queue.

**Response (200 OK):**
```json
{
  "message": "Task retried successfully",
  "task_id": "failed-task-123",
  "new_task_id": "retry-task-456"
}
```

---

### DELETE /api/v1/admin/dlq/tasks/{task_id}

Remove a task from the Dead Letter Queue.

**Response (200 OK):**
```json
{
  "message": "Task removed from DLQ",
  "task_id": "failed-task-123"
}
```

---

## System Endpoints

### GET /health

Basic health check (public, no authentication required).

**Response (200 OK):**
```json
{
  "status": "healthy"
}
```

**Example:**
```bash
curl http://localhost:8000/health
```

---

### GET /api/v1/system/health

Deep health check with database and Redis connectivity.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "app": "youtube-shorts-automation",
  "version": "1.0.0",
  "database": "connected",
  "redis": "connected",
  "celery": "3 workers active"
}
```

**Response (503 Service Unavailable):**
```json
{
  "status": "unhealthy",
  "database": "disconnected",
  "redis": "connected"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/system/health
```

---

### GET /api/v1/system/tasks/{task_id}

Check Celery task status.

**Response (200 OK):**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "state": "SUCCESS",
  "result": {
    "project_id": "550e8400-e29b-41d4-a716-446655440000",
    "youtube_url": "https://youtube.com/watch?v=dQw4w9WgXcQ"
  },
  "traceback": null
}
```

**Task States:**
- `PENDING` - Task is waiting for execution
- `STARTED` - Task has been started
- `RETRY` - Task is being retried
- `FAILURE` - Task raised an exception
- `SUCCESS` - Task executed successfully

**Example:**
```bash
curl http://localhost:8000/api/v1/system/tasks/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

---

### POST /api/v1/system/tasks/{task_id}/revoke

Revoke (cancel) a running Celery task.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `terminate` | boolean | No | Terminate task immediately (default: false) |

**Response (200 OK):**
```json
{
  "message": "Task revoked successfully",
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "terminated": true
}
```

**Example:**
```bash
# Graceful revoke
curl -X POST http://localhost:8000/api/v1/system/tasks/task-id/revoke

# Force terminate
curl -X POST "http://localhost:8000/api/v1/system/tasks/task-id/revoke?terminate=true"
```

---

### GET /api/v1/system/circuit-breakers

Get status of all circuit breakers.

**Response (200 OK):**
```json
{
  "circuit_breakers": [
    {
      "service": "openai",
      "state": "closed",
      "fail_count": 0,
      "last_failure": null
    },
    {
      "service": "anthropic",
      "state": "closed",
      "fail_count": 0,
      "last_failure": null
    },
    {
      "service": "elevenlabs",
      "state": "open",
      "fail_count": 5,
      "last_failure": "2026-03-03T10:30:00Z",
      "opens_at": "2026-03-03T10:32:00Z"
    }
  ]
}
```

**Circuit Breaker States:**
- `closed` - Normal operation
- `open` - Too many failures, blocking requests
- `half_open` - Testing if service recovered

---

### POST /api/v1/system/circuit-breakers/{service}/reset

Manually reset a circuit breaker.

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `service` | string | Yes | Service name (openai, anthropic, elevenlabs, pexels, youtube) |

**Response (200 OK):**
```json
{
  "message": "Circuit breaker reset successfully",
  "service": "elevenlabs",
  "state": "closed"
}
```

---

### GET /api/v1/system/queue-depth

Get current queue depth and backpressure status.

**Response (200 OK):**
```json
{
  "queues": {
    "default": 3,
    "scripts": 12,
    "media": 8,
    "upload": 2
  },
  "total": 25,
  "backpressure_active": false,
  "backpressure_threshold": 50
}
```

---

### GET /api/v1/system/cache/stats

Get cache statistics.

**Response (200 OK):**
```json
{
  "memory_used": "12.5 MB",
  "keys_total": 342,
  "keys_by_prefix": {
    "cache:project:": 156,
    "cache:pexels:": 89,
    "cache:voices:": 12
  },
  "hit_rate": 0.87
}
```

---

### POST /api/v1/system/cache/invalidate

Invalidate all caches.

**Response (200 OK):**
```json
{
  "message": "All caches invalidated",
  "keys_deleted": {
    "project": 156,
    "pexels": 89,
    "voices": 12
  },
  "total": 257
}
```

---

## Schemas

### VideoStatus

Enum representing pipeline status:

- `pending` - Created, waiting for worker
- `script_generating` - LLM generating script
- `audio_generating` - ElevenLabs generating TTS
- `video_generating` - Pexels clips downloading
- `assembling` - FFmpeg encoding final video
- `uploading` - Uploading to YouTube
- `completed` - Pipeline finished successfully
- `failed` - Pipeline failed (see error_message)

### VideoFormat

Enum representing video format:

- `short` - 9:16 aspect ratio (1080x1920) for YouTube Shorts
- `long` - 16:9 aspect ratio (1920x1080) for standard videos

### LLMProvider

Enum representing LLM provider:

- `openai` - OpenAI GPT-4o (default)
- `anthropic` - Anthropic Claude Sonnet 4.5

---

## Error Codes

### HTTP Status Codes

| Code | Meaning | Description |
|------|---------|-------------|
| 200 | OK | Request succeeded |
| 201 | Created | Resource created successfully |
| 202 | Accepted | Request accepted, processing asynchronously |
| 400 | Bad Request | Invalid request parameters |
| 401 | Unauthorized | Missing or invalid API key |
| 404 | Not Found | Resource not found |
| 422 | Unprocessable Entity | Validation error |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Server error |
| 503 | Service Unavailable | Service temporarily unavailable |

### Error Response Format

```json
{
  "detail": "Error message here",
  "type": "validation_error",
  "errors": [
    {
      "loc": ["body", "topic"],
      "msg": "String should have at least 3 characters",
      "type": "string_too_short"
    }
  ]
}
```

---

## Rate Limiting

Rate limits are enforced per API key:

| Endpoint | Limit | Window |
|----------|-------|--------|
| POST /api/v1/pipeline | 10 requests | 1 minute |
| POST /api/v1/pipeline/batch | 2 requests | 1 minute |
| GET /api/v1/projects | 60 requests | 1 minute |
| Other endpoints | 60 requests | 1 minute |

**Rate Limit Headers:**
```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1709478600
```

**Rate Limit Exceeded Response (429):**
```json
{
  "detail": "Rate limit exceeded. Try again in 42 seconds.",
  "retry_after": 42
}
```

---

## Webhooks (Future Feature)

Webhook support for real-time notifications is planned for v1.1.0.

---

## Interactive API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

---

**Last Updated:** 2026-03-03
**API Version:** 1.0.0
