# Celery autodiscover will find tasks in these modules.
# Explicit imports ensure the task decorators register on app startup.
from app.workers.analytics_tasks import collect_analytics_task  # noqa: F401
from app.workers.assembly_tasks import assemble_video_task  # noqa: F401
from app.workers.auto_schedule_tasks import (  # noqa: F401
    dispatch_scheduled_task,
    schedule_evaluation_task,
    scheduled_video_task,
)
from app.workers.cleanup_tasks import (  # noqa: F401
    cleanup_completed_projects_task,
    cleanup_failed_projects_task,
    cleanup_orphaned_files_task,
    update_disk_metrics_task,
)
from app.workers.media_tasks import fetch_visuals_task, generate_audio_task  # noqa: F401
from app.workers.pattern_tasks import analyze_patterns_task  # noqa: F401
from app.workers.pipeline import run_pipeline_task  # noqa: F401
from app.workers.scene_tasks import generate_visuals_task, split_scenes_task  # noqa: F401
from app.workers.script_tasks import generate_script_task  # noqa: F401
from app.workers.trend_tasks import (  # noqa: F401
    check_trend_health_task,
    cleanup_expired_trends_task,
    collect_all_trends_task,
)
from app.workers.upload_tasks import upload_to_youtube_task  # noqa: F401
