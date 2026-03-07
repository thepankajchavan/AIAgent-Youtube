"""Unit tests for PipelineResume — step completion, artifact tracking, resume point."""

from pathlib import Path
from unittest.mock import MagicMock

from app.workers.resume_helper import PipelineResume


def _make_project(**kwargs):
    """Create a mock VideoProject with resume-related fields."""
    project = MagicMock()
    project.id = kwargs.get("id", "test-uuid")
    project.last_completed_step = kwargs.get("last_completed_step", None)
    project.artifacts_available = kwargs.get("artifacts_available", None)
    project.status = kwargs.get("status", MagicMock())
    return project


class TestMarkStepCompleted:
    """Test step completion tracking."""

    def test_marks_first_step(self):
        project = _make_project()
        PipelineResume.mark_step_completed(project, "script")
        assert project.last_completed_step == "script"

    def test_advances_step(self):
        project = _make_project(last_completed_step="script")
        PipelineResume.mark_step_completed(project, "audio")
        assert project.last_completed_step == "audio"

    def test_does_not_regress(self):
        project = _make_project(last_completed_step="assembly")
        PipelineResume.mark_step_completed(project, "script")
        # Should NOT go backwards
        assert project.last_completed_step == "assembly"

    def test_marks_final_step(self):
        project = _make_project(last_completed_step="assembly")
        PipelineResume.mark_step_completed(project, "upload")
        assert project.last_completed_step == "upload"


class TestMarkArtifactAvailable:
    """Test artifact path tracking."""

    def test_marks_first_artifact(self):
        project = _make_project(artifacts_available=None)
        PipelineResume.mark_artifact_available(project, "audio", Path("/tmp/audio.mp3"))
        assert project.artifacts_available == {"audio": str(Path("/tmp/audio.mp3"))}

    def test_marks_multiple_artifacts(self):
        project = _make_project(artifacts_available={"audio": str(Path("/tmp/audio.mp3"))})
        PipelineResume.mark_artifact_available(project, "output", Path("/tmp/out.mp4"))
        assert project.artifacts_available["output"] == str(Path("/tmp/out.mp4"))
        assert project.artifacts_available["audio"] == str(Path("/tmp/audio.mp3"))


class TestGetResumePoint:
    """Test resume point calculation."""

    def test_no_completed_steps(self):
        project = _make_project()
        resume_from, completed = PipelineResume.get_resume_point(project)
        assert resume_from is None
        assert completed == set()

    def test_resume_after_script(self):
        project = _make_project(last_completed_step="script")
        resume_from, completed = PipelineResume.get_resume_point(project)
        assert resume_from == "audio"
        assert completed == {"script"}

    def test_resume_after_audio(self):
        project = _make_project(last_completed_step="audio")
        resume_from, completed = PipelineResume.get_resume_point(project)
        assert resume_from == "video"
        assert completed == {"script", "audio"}

    def test_resume_after_assembly(self):
        project = _make_project(last_completed_step="assembly")
        resume_from, completed = PipelineResume.get_resume_point(project)
        assert resume_from == "upload"
        assert completed == {"script", "audio", "video", "assembly"}

    def test_all_steps_completed(self):
        project = _make_project(last_completed_step="upload")
        resume_from, completed = PipelineResume.get_resume_point(project)
        assert resume_from is None
        assert completed == {"script", "audio", "video", "assembly", "upload"}


class TestShouldSkipStep:
    """Test skip logic."""

    def test_skip_completed(self):
        assert PipelineResume.should_skip_step("script", {"script", "audio"}) is True

    def test_do_not_skip_pending(self):
        assert PipelineResume.should_skip_step("video", {"script", "audio"}) is False
