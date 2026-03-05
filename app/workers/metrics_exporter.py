"""
Celery Metrics Exporter — Collects metrics from Celery workers.

Exports:
- Active task counts per queue
- Queue depths (tasks waiting)
- Worker online status
- Task success/failure rates
"""

import time

from loguru import logger
from prometheus_client import start_http_server

from app.core.celery_app import celery_app
from app.core.metrics import (
    active_celery_tasks,
    celery_queue_depth,
    celery_worker_online,
)


def collect_celery_metrics():
    """Collect current Celery metrics and update Prometheus gauges."""
    try:
        # Get worker stats
        stats = celery_app.control.inspect()

        if stats is None:
            logger.warning("No Celery workers available for metrics collection")
            return

        # Active tasks
        active_tasks_data = stats.active()
        if active_tasks_data:
            # Reset all gauges first
            active_celery_tasks._metrics.clear()

            for _worker, tasks in active_tasks_data.items():
                # Extract queue from task routing
                for task in tasks:
                    queue = task.get("delivery_info", {}).get("routing_key", "default")
                    active_celery_tasks.labels(queue=queue).inc()

        # Reserved tasks (queue depth approximation)
        reserved_tasks_data = stats.reserved()
        if reserved_tasks_data:
            celery_queue_depth._metrics.clear()

            for _worker, tasks in reserved_tasks_data.items():
                for task in tasks:
                    queue = task.get("delivery_info", {}).get("routing_key", "default")
                    celery_queue_depth.labels(queue=queue).inc()

        # Worker online status
        registered = stats.registered()
        if registered:
            celery_worker_online._metrics.clear()

            for worker_name in registered:
                celery_worker_online.labels(worker_name=worker_name).set(1)

        logger.debug("Celery metrics collected successfully")

    except Exception as e:
        logger.error(f"Failed to collect Celery metrics: {e}")


def run_metrics_exporter(port: int = 9090, interval: int = 15):
    """
    Start Prometheus HTTP server and periodically collect Celery metrics.

    Args:
        port: Port to expose Prometheus metrics
        interval: Collection interval in seconds
    """
    # Start Prometheus HTTP server
    start_http_server(port)
    logger.info(f"📊 Celery metrics exporter started on port {port}")
    logger.info(f"Metrics available at http://localhost:{port}/metrics")

    # Continuous collection loop
    try:
        while True:
            collect_celery_metrics()
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Metrics exporter stopped")


if __name__ == "__main__":
    run_metrics_exporter()
