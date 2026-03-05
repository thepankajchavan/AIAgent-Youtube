from celery import Celery
from celery.signals import task_failure
from kombu import Exchange, Queue
import asyncio
import traceback

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "content_engine",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# ── Serialization ────────────────────────────────────────────
celery_app.conf.accept_content = ["json"]
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True

# ── Result settings ──────────────────────────────────────────
celery_app.conf.result_expires = 60 * 60 * 24  # 24 hours
celery_app.conf.task_track_started = True

# ── Retry defaults (applied to all tasks unless overridden) ──
celery_app.conf.task_default_retry_delay = 30        # seconds
celery_app.conf.task_max_retries = 3
celery_app.conf.task_acks_late = True                 # re-deliver on worker crash
celery_app.conf.worker_prefetch_multiplier = 1        # fair scheduling

# ── Performance Optimization (Phase 8) ────────────────────────
celery_app.conf.worker_max_tasks_per_child = 100      # Prevent memory leaks (restart after 100 tasks)
celery_app.conf.worker_disable_rate_limits = False    # Enable rate limiting
celery_app.conf.task_compression = 'gzip'              # Compress large task payloads
celery_app.conf.result_compression = 'gzip'            # Compress results
celery_app.conf.task_reject_on_worker_lost = True     # Requeue tasks if worker dies
celery_app.conf.task_time_limit = 3600                # Hard limit: 1 hour
celery_app.conf.task_soft_time_limit = 3300           # Soft limit: 55 minutes (raise exception)
celery_app.conf.broker_connection_retry_on_startup = True  # Retry broker connection on startup
celery_app.conf.broker_pool_limit = 10                # Connection pool limit

# ── Task autodiscovery ───────────────────────────────────────
celery_app.autodiscover_tasks(["app.workers"])

# ── Celery Beat Schedule (Periodic Tasks) ────────────────────
celery_app.conf.beat_schedule = {
    # Clean up completed project media files every day at 2 AM
    "cleanup-completed-projects": {
        "task": "cleanup_tasks.cleanup_completed_projects",
        "schedule": 60 * 60 * 24,  # Every 24 hours
        "options": {"queue": "default"}
    },
    # Clean up failed project media files every 6 hours
    "cleanup-failed-projects": {
        "task": "cleanup_tasks.cleanup_failed_projects",
        "schedule": 60 * 60 * 6,  # Every 6 hours
        "options": {"queue": "default"}
    },
    # Clean up orphaned files every 12 hours
    "cleanup-orphaned-files": {
        "task": "cleanup_tasks.cleanup_orphaned_files",
        "schedule": 60 * 60 * 12,  # Every 12 hours
        "options": {"queue": "default"}
    },
    # Update disk metrics every 5 minutes
    "update-disk-metrics": {
        "task": "cleanup_tasks.update_disk_metrics",
        "schedule": 60 * 5,  # Every 5 minutes
        "options": {"queue": "default"}
    },
}

# ── Queues ───────────────────────────────────────────────────
default_exchange = Exchange("default", type="direct")
media_exchange = Exchange("media", type="direct")

celery_app.conf.task_queues = (
    Queue("default", default_exchange, routing_key="default"),
    Queue("scripts", default_exchange, routing_key="scripts"),
    Queue("media", media_exchange, routing_key="media"),
    Queue("upload", default_exchange, routing_key="upload"),
)

celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"

# ── Task routing (filled in Phase 3 when tasks exist) ────────
celery_app.conf.task_routes = {
    "app.workers.script_tasks.*": {"queue": "scripts"},
    "app.workers.scene_tasks.split_scenes_task": {"queue": "scripts"},
    "app.workers.scene_tasks.generate_visuals_task": {"queue": "media"},
    "app.workers.media_tasks.*": {"queue": "media"},
    "app.workers.upload_tasks.*": {"queue": "upload"},
}

# ── Dead Letter Queue (DLQ) Handler ──────────────────────────
@task_failure.connect
def handle_task_failure(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, einfo=None, **extra_kwargs):
    """
    Handle permanently failed tasks and move them to DLQ.

    This signal fires when a task fails after all retry attempts.
    """
    from app.core.dlq import DeadLetterQueue
    from loguru import logger

    # Only process if task has exhausted all retries
    if sender and hasattr(sender, 'max_retries'):
        max_retries = sender.max_retries
        current_retries = sender.request.retries if hasattr(sender, 'request') else 0

        # If task still has retries left, don't add to DLQ yet
        if max_retries is not None and current_retries < max_retries:
            return

    # Extract project_id from kwargs if present
    project_id = kwargs.get('project_id') if kwargs else None

    # Get full traceback
    traceback_str = str(einfo) if einfo else traceback

    logger.error(
        f"Task {task_id} permanently failed: {exception}. "
        f"Adding to DLQ. Project: {project_id}"
    )

    # Add to DLQ asynchronously
    try:
        asyncio.run(
            DeadLetterQueue.add_failed_task(
                task_id=task_id,
                task_name=sender.name if sender else "unknown",
                args=args or (),
                kwargs=kwargs or {},
                exception=exception,
                traceback_str=traceback_str,
                project_id=project_id
            )
        )
    except Exception as e:
        logger.error(f"Failed to add task to DLQ: {e}")
