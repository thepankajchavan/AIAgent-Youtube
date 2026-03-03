from celery import Celery
from kombu import Exchange, Queue

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

# ── Task autodiscovery ───────────────────────────────────────
celery_app.autodiscover_tasks(["app.workers"])

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
    "app.workers.media_tasks.*": {"queue": "media"},
    "app.workers.upload_tasks.*": {"queue": "upload"},
}
