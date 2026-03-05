"""
Resume Helper - Smart pipeline resumption from failure point.

Tracks completed steps and skips them on retry, avoiding redundant work.
"""

from pathlib import Path

from loguru import logger

from app.models.video import VideoProject, VideoStatus


class PipelineResume:
    """Handles smart resumption of failed pipelines."""

    # Define step ordering for resume logic
    STEP_ORDER = ["script", "audio", "video", "assembly", "upload"]

    @classmethod
    def mark_step_completed(cls, project: VideoProject, step: str) -> None:
        """
        Mark a pipeline step as completed for resume tracking.

        Args:
            project: VideoProject instance
            step: Step name (script, audio, video, assembly, upload)
        """
        if project.last_completed_step is None or step not in cls.STEP_ORDER:
            project.last_completed_step = step
            return

        current_idx = cls.STEP_ORDER.index(project.last_completed_step)
        new_idx = cls.STEP_ORDER.index(step)

        # Only update if new step is further along
        if new_idx > current_idx:
            project.last_completed_step = step

        logger.debug(f"Project {project.id}: marked step '{step}' as completed")

    @classmethod
    def mark_artifact_available(
        cls, project: VideoProject, artifact_type: str, path: Path | str
    ) -> None:
        """
        Mark an artifact as available for resumption.

        Args:
            project: VideoProject instance
            artifact_type: Type of artifact (script, audio, video, output)
            path: Path to the artifact file
        """
        if project.artifacts_available is None:
            project.artifacts_available = {}

        project.artifacts_available[artifact_type] = str(path)

        logger.debug(f"Project {project.id}: artifact '{artifact_type}' marked available at {path}")

    @classmethod
    def get_resume_point(cls, project: VideoProject) -> tuple[str | None, set[str]]:
        """
        Determine where to resume pipeline execution.

        Args:
            project: VideoProject instance

        Returns:
            Tuple of (resume_from_step, completed_steps_set)
        """
        if not project.last_completed_step:
            logger.info(f"Project {project.id}: No completed steps, starting from beginning")
            return None, set()

        completed_steps = set()
        resume_from = None

        last_completed_idx = cls.STEP_ORDER.index(project.last_completed_step)

        # All steps up to and including last_completed_step are done
        for i in range(last_completed_idx + 1):
            completed_steps.add(cls.STEP_ORDER[i])

        # Resume from the next step
        if last_completed_idx + 1 < len(cls.STEP_ORDER):
            resume_from = cls.STEP_ORDER[last_completed_idx + 1]

        logger.info(
            f"Project {project.id}: Resuming from '{resume_from}', "
            f"skipping completed steps: {completed_steps}"
        )

        return resume_from, completed_steps

    @classmethod
    def should_skip_step(cls, step: str, completed_steps: set[str]) -> bool:
        """
        Check if a step should be skipped based on completed steps.

        Args:
            step: Step name to check
            completed_steps: Set of completed step names

        Returns:
            True if step should be skipped, False otherwise
        """
        return step in completed_steps

    @classmethod
    def verify_artifacts_exist(cls, project: VideoProject) -> dict[str, bool]:
        """
        Verify that tracked artifacts actually exist on disk.

        Args:
            project: VideoProject instance

        Returns:
            Dictionary mapping artifact types to existence status
        """
        if not project.artifacts_available:
            return {}

        verified = {}

        for artifact_type, path_str in project.artifacts_available.items():
            path = Path(path_str)
            exists = path.exists() and path.is_file()
            verified[artifact_type] = exists

            if not exists:
                logger.warning(
                    f"Project {project.id}: Artifact '{artifact_type}' marked available "
                    f"but missing at {path}"
                )

        return verified

    @classmethod
    def get_artifact_path(cls, project: VideoProject, artifact_type: str) -> Path | None:
        """
        Get the path to a previously generated artifact.

        Args:
            project: VideoProject instance
            artifact_type: Type of artifact (script, audio, video, output)

        Returns:
            Path to artifact or None if not available
        """
        if not project.artifacts_available:
            return None

        path_str = project.artifacts_available.get(artifact_type)
        if not path_str:
            return None

        path = Path(path_str)

        # Verify file still exists
        if not path.exists():
            logger.warning(
                f"Project {project.id}: Artifact '{artifact_type}' path exists in DB "
                f"but file missing: {path}"
            )
            return None

        return path

    @classmethod
    def can_resume_from_failure(cls, project: VideoProject) -> bool:
        """
        Check if a failed project can be resumed (has completed at least one step).

        Args:
            project: VideoProject instance

        Returns:
            True if resumable, False if needs full restart
        """
        if project.status != VideoStatus.FAILED:
            return False

        if not project.last_completed_step:
            logger.info(f"Project {project.id}: Cannot resume, no steps completed")
            return False

        # Verify at least one artifact exists
        verified = cls.verify_artifacts_exist(project)

        if not any(verified.values()):
            logger.warning(
                f"Project {project.id}: No artifacts available despite tracking, "
                "will restart from beginning"
            )
            return False

        return True

    @classmethod
    def reset_resume_tracking(cls, project: VideoProject) -> None:
        """
        Reset resume tracking (used when forcing full restart).

        Args:
            project: VideoProject instance
        """
        project.last_completed_step = None
        project.artifacts_available = {}
        logger.info(f"Project {project.id}: Resume tracking reset")
