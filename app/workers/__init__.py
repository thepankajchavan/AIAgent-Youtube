# Celery autodiscover will find tasks in these modules.
# Explicit imports ensure the task decorators register on app startup.
from app.workers.script_tasks import generate_script_task  # noqa: F401
from app.workers.media_tasks import generate_audio_task, fetch_visuals_task  # noqa: F401
from app.workers.assembly_tasks import assemble_video_task  # noqa: F401
from app.workers.upload_tasks import upload_to_youtube_task  # noqa: F401
from app.workers.pipeline import run_pipeline_task  # noqa: F401
