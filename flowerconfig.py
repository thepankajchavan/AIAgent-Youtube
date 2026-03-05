"""
Flower Configuration for Celery Monitoring.

Flower is a web-based tool for monitoring and managing Celery workers and tasks.
Access at: http://localhost:5555
"""

import os

# ── Celery Broker Configuration ──────────────────────────────────────
broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/0")

# ── Flower Web Server ─────────────────────────────────────────────────
# Port for Flower web interface
port = int(os.getenv("FLOWER_PORT", "5555"))

# Address to bind to (0.0.0.0 for all interfaces in Docker)
address = os.getenv("FLOWER_ADDRESS", "0.0.0.0")

# ── Authentication ────────────────────────────────────────────────────
# Basic authentication (username:password)
# For production, set FLOWER_BASIC_AUTH environment variable
basic_auth = os.getenv("FLOWER_BASIC_AUTH", "admin:admin").split(",")

# URL prefix (useful if behind reverse proxy)
url_prefix = os.getenv("FLOWER_URL_PREFIX", "")

# ── Task Filtering ────────────────────────────────────────────────────
# Max number of tasks to keep in memory
max_tasks = int(os.getenv("FLOWER_MAX_TASKS", "10000"))

# Task columns to display
task_columns = [
    "name",
    "uuid",
    "state",
    "args",
    "kwargs",
    "result",
    "received",
    "started",
    "runtime",
    "worker"
]

# ── UI Configuration ──────────────────────────────────────────────────
# Auto-refresh interval in milliseconds (0 to disable)
auto_refresh = int(os.getenv("FLOWER_AUTO_REFRESH", "5000"))  # 5 seconds

# Enable/disable debug mode
debug = os.getenv("FLOWER_DEBUG", "false").lower() == "true"

# Timezone for timestamps
timezone = os.getenv("TZ", "UTC")

# ── Logging ───────────────────────────────────────────────────────────
# Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
logging = os.getenv("FLOWER_LOG_LEVEL", "INFO")

# ── Persistence ───────────────────────────────────────────────────────
# Enable persistent mode (stores state to disk)
persistent = os.getenv("FLOWER_PERSISTENT", "true").lower() == "true"

# Database file for persistent mode
db = os.getenv("FLOWER_DB", "/data/flower.db")

# ── Broker API ────────────────────────────────────────────────────────
# Enable broker connection retries
broker_api = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")

# ── Purge Offline Workers ─────────────────────────────────────────────
# Automatically purge offline workers after this time (seconds)
# Set to 0 to disable
purge_offline_workers = int(os.getenv("FLOWER_PURGE_OFFLINE_WORKERS", "86400"))  # 24 hours

# ── Inspector Timeout ─────────────────────────────────────────────────
# Timeout for worker inspections (seconds)
inspect_timeout = float(os.getenv("FLOWER_INSPECT_TIMEOUT", "10.0"))

# ── State Save Interval ───────────────────────────────────────────────
# Interval to save state to database in persistent mode (seconds)
state_save_interval = int(os.getenv("FLOWER_STATE_SAVE_INTERVAL", "300"))  # 5 minutes
