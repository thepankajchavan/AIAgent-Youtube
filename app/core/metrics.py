"""
Prometheus Metrics — Custom metrics for monitoring pipeline performance.

Tracks:
- Pipeline execution counts (total, completed, failed)
- Pipeline duration by step
- External API call counts and errors
- Celery task queue depths
- Media storage usage
"""

from loguru import logger
from prometheus_client import Counter, Gauge, Histogram, Info

# ── Application Info ──────────────────────────────────────────

app_info = Info("app", "Application information")
app_info.info(
    {"name": "youtube-shorts-automation", "version": "1.0.0", "environment": "production"}
)

# ── Pipeline Metrics ──────────────────────────────────────────

pipeline_total = Counter(
    "pipeline_total", "Total number of pipelines triggered", ["video_format", "provider"]
)

pipeline_completed = Counter(
    "pipeline_completed", "Number of successfully completed pipelines", ["video_format", "provider"]
)

pipeline_failed = Counter(
    "pipeline_failed", "Number of failed pipelines", ["video_format", "provider", "failure_step"]
)

pipeline_duration_seconds = Histogram(
    "pipeline_duration_seconds",
    "End-to-end pipeline execution time",
    ["video_format", "provider"],
    buckets=[30, 60, 120, 300, 600, 900, 1800, 3600],  # 30s to 1h
)

# ── Step-Level Metrics ────────────────────────────────────────

step_duration_seconds = Histogram(
    "step_duration_seconds",
    "Duration of individual pipeline steps",
    ["step"],
    buckets=[5, 10, 30, 60, 120, 300, 600],  # 5s to 10min
)

# ── External API Metrics ──────────────────────────────────────

external_api_calls = Counter(
    "external_api_calls_total",
    "Total calls to external APIs",
    ["service"],  # openai, anthropic, elevenlabs, pexels, youtube
)

external_api_errors = Counter(
    "external_api_errors_total", "Failed calls to external APIs", ["service", "error_type"]
)

external_api_duration_seconds = Histogram(
    "external_api_duration_seconds",
    "External API call duration",
    ["service"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60],
)

# ── Celery Metrics ────────────────────────────────────────────

active_celery_tasks = Gauge(
    "active_celery_tasks", "Number of currently running Celery tasks", ["queue"]
)

celery_queue_depth = Gauge("celery_queue_depth", "Number of tasks waiting in each queue", ["queue"])

celery_worker_online = Gauge(
    "celery_worker_online", "Number of online Celery workers", ["worker_name"]
)

# ── Database Metrics ──────────────────────────────────────────

db_connections_active = Gauge("db_connections_active", "Number of active database connections")

db_query_duration_seconds = Histogram(
    "db_query_duration_seconds",
    "Database query execution time",
    ["query_type"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1, 2, 5],
)

# ── Media Storage Metrics ─────────────────────────────────────

media_disk_usage_bytes = Gauge(
    "media_disk_usage_bytes",
    "Disk space used by media files",
    ["media_type"],  # audio, video, output
)

media_files_total = Gauge("media_files_total", "Total number of media files", ["media_type"])

# ── HTTP Metrics (provided by instrumentator) ─────────────────
# http_requests_total
# http_request_duration_seconds
# http_requests_in_progress


def track_pipeline_start(video_format: str, provider: str):
    """Record pipeline initiation."""
    pipeline_total.labels(video_format=video_format, provider=provider).inc()
    logger.debug(f"Metrics: Pipeline started - format={video_format} provider={provider}")


def track_pipeline_complete(video_format: str, provider: str, duration: float):
    """Record successful pipeline completion."""
    pipeline_completed.labels(video_format=video_format, provider=provider).inc()
    pipeline_duration_seconds.labels(video_format=video_format, provider=provider).observe(duration)
    logger.debug(f"Metrics: Pipeline completed - duration={duration:.2f}s")


def track_pipeline_failure(video_format: str, provider: str, failure_step: str):
    """Record pipeline failure."""
    pipeline_failed.labels(
        video_format=video_format, provider=provider, failure_step=failure_step
    ).inc()
    logger.debug(f"Metrics: Pipeline failed at {failure_step}")


def track_step_duration(step: str, duration: float):
    """Record step execution time."""
    step_duration_seconds.labels(step=step).observe(duration)


def track_api_call(service: str, duration: float):
    """Record external API call."""
    external_api_calls.labels(service=service).inc()
    external_api_duration_seconds.labels(service=service).observe(duration)


def track_api_error(service: str, error_type: str):
    """Record external API error."""
    external_api_errors.labels(service=service, error_type=error_type).inc()
