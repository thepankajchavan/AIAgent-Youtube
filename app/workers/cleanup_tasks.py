"""
Media Cleanup Tasks - Automatic cleanup of old media files.

Scheduled tasks that clean up:
- COMPLETED project media files older than 7 days
- FAILED project media files older than 24 hours
- Orphaned media files (no associated project)
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from celery import shared_task
from loguru import logger
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_async_session
from app.core.metrics import media_disk_usage_bytes, media_files_total
from app.models.video_project import ProjectStatus, VideoProject


@shared_task(name="cleanup_tasks.cleanup_completed_projects")
def cleanup_completed_projects_task() -> dict[str, Any]:
    """
    Clean up media files for completed projects older than 7 days.

    Returns:
        Dictionary with cleanup statistics
    """
    import asyncio

    return asyncio.run(cleanup_completed_projects())


async def cleanup_completed_projects() -> dict[str, Any]:
    """Clean up old completed project media files."""
    settings = get_settings()
    cutoff_time = datetime.now(UTC) - timedelta(days=7)

    deleted_files = 0
    freed_bytes = 0
    deleted_projects = []

    async for session in get_async_session():
        try:
            # Get completed projects older than 7 days
            query = select(VideoProject).where(
                VideoProject.status == ProjectStatus.COMPLETED,
                VideoProject.updated_at < cutoff_time,
            )
            result = await session.execute(query)
            projects = result.scalars().all()

            logger.info(f"Found {len(projects)} completed projects older than 7 days for cleanup")

            for project in projects:
                try:
                    # Count and delete media files
                    files_deleted, bytes_freed = await _delete_project_media(
                        project.id, settings.audio_dir, settings.video_dir, settings.output_dir
                    )

                    deleted_files += files_deleted
                    freed_bytes += bytes_freed
                    deleted_projects.append(project.id)

                    logger.info(
                        f"Cleaned up project {project.id}: "
                        f"{files_deleted} files, {bytes_freed / 1024 / 1024:.2f} MB freed"
                    )
                except Exception as e:
                    logger.error(f"Error cleaning project {project.id}: {e}")

            # Update disk usage metrics
            await _update_disk_metrics(settings)

        except Exception as e:
            logger.error(f"Error in cleanup_completed_projects: {e}")
        finally:
            await session.close()
            break

    logger.info(
        f"Cleanup completed: {deleted_files} files deleted, "
        f"{freed_bytes / 1024 / 1024:.2f} MB freed, "
        f"{len(deleted_projects)} projects cleaned"
    )

    return {
        "task": "cleanup_completed_projects",
        "deleted_files": deleted_files,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / 1024 / 1024, 2),
        "projects_cleaned": len(deleted_projects),
        "project_ids": deleted_projects,
    }


@shared_task(name="cleanup_tasks.cleanup_failed_projects")
def cleanup_failed_projects_task() -> dict[str, Any]:
    """
    Clean up media files for failed projects older than 24 hours.

    Returns:
        Dictionary with cleanup statistics
    """
    import asyncio

    return asyncio.run(cleanup_failed_projects())


async def cleanup_failed_projects() -> dict[str, Any]:
    """Clean up old failed project media files."""
    settings = get_settings()
    cutoff_time = datetime.now(UTC) - timedelta(hours=24)

    deleted_files = 0
    freed_bytes = 0
    deleted_projects = []

    async for session in get_async_session():
        try:
            # Get failed projects older than 24 hours
            query = select(VideoProject).where(
                VideoProject.status == ProjectStatus.FAILED, VideoProject.updated_at < cutoff_time
            )
            result = await session.execute(query)
            projects = result.scalars().all()

            logger.info(f"Found {len(projects)} failed projects older than 24 hours for cleanup")

            for project in projects:
                try:
                    # Count and delete media files
                    files_deleted, bytes_freed = await _delete_project_media(
                        project.id, settings.audio_dir, settings.video_dir, settings.output_dir
                    )

                    deleted_files += files_deleted
                    freed_bytes += bytes_freed
                    deleted_projects.append(project.id)

                    logger.info(
                        f"Cleaned up failed project {project.id}: "
                        f"{files_deleted} files, {bytes_freed / 1024 / 1024:.2f} MB freed"
                    )
                except Exception as e:
                    logger.error(f"Error cleaning failed project {project.id}: {e}")

            # Update disk usage metrics
            await _update_disk_metrics(settings)

        except Exception as e:
            logger.error(f"Error in cleanup_failed_projects: {e}")
        finally:
            await session.close()
            break

    logger.info(
        f"Failed projects cleanup: {deleted_files} files deleted, "
        f"{freed_bytes / 1024 / 1024:.2f} MB freed, "
        f"{len(deleted_projects)} projects cleaned"
    )

    return {
        "task": "cleanup_failed_projects",
        "deleted_files": deleted_files,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / 1024 / 1024, 2),
        "projects_cleaned": len(deleted_projects),
        "project_ids": deleted_projects,
    }


@shared_task(name="cleanup_tasks.cleanup_orphaned_files")
def cleanup_orphaned_files_task() -> dict[str, Any]:
    """
    Clean up orphaned media files (no associated project).

    Returns:
        Dictionary with cleanup statistics
    """
    import asyncio

    return asyncio.run(cleanup_orphaned_files())


async def cleanup_orphaned_files() -> dict[str, Any]:
    """Clean up orphaned media files."""
    settings = get_settings()

    deleted_files = 0
    freed_bytes = 0

    async for session in get_async_session():
        try:
            # Get all project IDs
            query = select(VideoProject.id)
            result = await session.execute(query)
            valid_project_ids = {str(row[0]) for row in result.all()}

            logger.info(f"Checking for orphaned files (valid projects: {len(valid_project_ids)})")

            # Check each media directory
            for _dir_name, dir_path in [
                ("audio", settings.audio_dir),
                ("video", settings.video_dir),
                ("output", settings.output_dir),
            ]:
                if not dir_path.exists():
                    continue

                for file_path in dir_path.iterdir():
                    if not file_path.is_file():
                        continue

                    # Extract project ID from filename (format: {project_id}_*.ext)
                    filename = file_path.stem
                    if "_" in filename:
                        project_id_str = filename.split("_")[0]

                        # If project ID not in valid set, it's orphaned
                        if project_id_str not in valid_project_ids:
                            try:
                                file_size = file_path.stat().st_size
                                file_path.unlink()
                                deleted_files += 1
                                freed_bytes += file_size

                                logger.debug(f"Deleted orphaned file: {file_path.name}")
                            except Exception as e:
                                logger.error(f"Error deleting orphaned file {file_path}: {e}")

            # Update disk usage metrics
            await _update_disk_metrics(settings)

        except Exception as e:
            logger.error(f"Error in cleanup_orphaned_files: {e}")
        finally:
            await session.close()
            break

    logger.info(
        f"Orphaned files cleanup: {deleted_files} files deleted, "
        f"{freed_bytes / 1024 / 1024:.2f} MB freed"
    )

    return {
        "task": "cleanup_orphaned_files",
        "deleted_files": deleted_files,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / 1024 / 1024, 2),
    }


@shared_task(name="cleanup_tasks.update_disk_metrics")
def update_disk_metrics_task() -> dict[str, Any]:
    """
    Update disk usage metrics for monitoring.

    Returns:
        Dictionary with current disk usage
    """
    import asyncio

    return asyncio.run(update_disk_metrics())


async def update_disk_metrics() -> dict[str, Any]:
    """Update Prometheus metrics for disk usage."""
    settings = get_settings()
    return await _update_disk_metrics(settings)


# ── Helper Functions ──────────────────────────────────────────


async def _delete_project_media(
    project_id: int, audio_dir: Path, video_dir: Path, output_dir: Path
) -> tuple[int, int]:
    """
    Delete all media files for a project.

    Args:
        project_id: Project ID
        audio_dir: Audio directory path
        video_dir: Video directory path
        output_dir: Output directory path

    Returns:
        Tuple of (files_deleted, bytes_freed)
    """
    deleted_count = 0
    bytes_freed = 0

    project_id_str = str(project_id)

    # Check all media directories
    for media_dir in [audio_dir, video_dir, output_dir]:
        if not media_dir.exists():
            continue

        # Find files matching project ID pattern
        for file_path in media_dir.glob(f"{project_id_str}_*"):
            if file_path.is_file():
                try:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    bytes_freed += file_size
                except Exception as e:
                    logger.error(f"Error deleting file {file_path}: {e}")

    return deleted_count, bytes_freed


async def _update_disk_metrics(settings: Any) -> dict[str, Any]:
    """
    Update Prometheus metrics for disk usage.

    Args:
        settings: Application settings

    Returns:
        Dictionary with disk usage statistics
    """
    stats = {}

    for media_type, dir_path in [
        ("audio", settings.audio_dir),
        ("video", settings.video_dir),
        ("output", settings.output_dir),
    ]:
        if not dir_path.exists():
            stats[media_type] = {"bytes": 0, "files": 0}
            media_disk_usage_bytes.labels(media_type=media_type).set(0)
            media_files_total.labels(media_type=media_type).set(0)
            continue

        total_bytes = 0
        file_count = 0

        for file_path in dir_path.iterdir():
            if file_path.is_file():
                total_bytes += file_path.stat().st_size
                file_count += 1

        stats[media_type] = {
            "bytes": total_bytes,
            "mb": round(total_bytes / 1024 / 1024, 2),
            "files": file_count,
        }

        # Update Prometheus metrics
        media_disk_usage_bytes.labels(media_type=media_type).set(total_bytes)
        media_files_total.labels(media_type=media_type).set(file_count)

    total_bytes = sum(s["bytes"] for s in stats.values())
    total_files = sum(s["files"] for s in stats.values())

    logger.debug(f"Disk usage: {total_bytes / 1024 / 1024:.2f} MB total, " f"{total_files} files")

    return {
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / 1024 / 1024, 2),
        "total_files": total_files,
        "by_type": stats,
    }
