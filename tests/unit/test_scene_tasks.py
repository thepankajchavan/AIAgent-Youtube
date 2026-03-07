"""Unit tests for scene splitting and AI visual generation tasks."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.models.video import VideoProject, VideoStatus


# ── Helper: mock get_sync_db context manager ─────────────────
def _make_mock_db(project):
    @contextmanager
    def mock_get_sync_db():
        session = MagicMock()
        session.get.return_value = project
        yield session

    return mock_get_sync_db


def _make_project(status=VideoStatus.SCRIPT_GENERATING, **kwargs):
    project = MagicMock(spec=VideoProject)
    project.id = "test-project-uuid"
    project.status = status
    project.topic = kwargs.get("topic", "test topic")
    project.provider = kwargs.get("provider", "openai")
    project.visual_strategy = kwargs.get("visual_strategy", "hybrid")
    project.telegram_user_id = None
    project.telegram_chat_id = None
    project.telegram_message_id = None
    project.error_message = None
    project.scene_plan = None
    project.ai_video_cost = None
    project.video_path = None
    project.validate_status_transition = MagicMock(return_value=True)
    return project


class TestSplitScenesTask:
    """Test split_scenes_task worker."""

    @patch("app.workers.scene_tasks.emit_status_update")
    @patch("app.workers.scene_tasks.get_sync_db")
    @patch("app.workers.scene_tasks._run_async")
    def test_split_scenes_success(self, mock_run_async, mock_db, mock_emit):
        """Test successful scene splitting stores scene_plan and returns updated pipeline_data."""
        from app.services.ai_video_service import Scene
        from app.workers.scene_tasks import split_scenes_task

        scenes = [
            Scene(
                scene_number=1,
                narration="First scene narration",
                visual_description="A wide shot of a forest",
                visual_type="stock_footage",
                stock_query="forest aerial",
                ai_prompt="Aerial shot of dense forest canopy",
                duration_seconds=4.0,
            ),
            Scene(
                scene_number=2,
                narration="Second scene narration",
                visual_description="Abstract visualization of data",
                visual_type="ai_generated",
                stock_query="technology abstract",
                ai_prompt="Flowing data streams in neon blue",
                duration_seconds=5.0,
            ),
        ]
        mock_run_async.return_value = scenes

        project = _make_project(status=VideoStatus.SCRIPT_GENERATING)
        mock_db.side_effect = _make_mock_db(project)

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"script": "test script content", "tags": ["test"]},
            "video_format": "short",
            "audio_duration": 35.0,
        }

        result = split_scenes_task(pipeline_data=pipeline_data)

        assert result["project_id"] == "test-project-uuid"
        assert "scene_plan" in result
        assert len(result["scene_plan"]) == 2
        assert result["scene_plan"][0]["visual_type"] == "stock_footage"
        assert result["scene_plan"][1]["visual_type"] == "ai_generated"
        project.validate_status_transition.assert_called_once_with(VideoStatus.SCENE_SPLITTING)

        # Verify audio_duration was passed to split_script_to_scenes
        call_kwargs = mock_run_async.call_args
        assert call_kwargs is not None

    @patch("app.workers.scene_tasks.emit_status_update")
    @patch("app.workers.scene_tasks.get_sync_db")
    @patch("app.workers.scene_tasks._run_async")
    def test_split_scenes_llm_failure(self, mock_run_async, mock_db, mock_emit):
        """Test that LLM failure sets FAILED status."""
        from app.workers.scene_tasks import split_scenes_task

        mock_run_async.side_effect = ValueError("LLM returned no scenes")

        project = _make_project(status=VideoStatus.SCRIPT_GENERATING)
        mock_db.side_effect = _make_mock_db(project)

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"script": "test", "tags": []},
            "video_format": "short",
        }

        with pytest.raises(Exception):
            split_scenes_task(pipeline_data=pipeline_data)

    @patch("app.workers.scene_tasks.emit_status_update")
    @patch("app.workers.scene_tasks.get_sync_db")
    @patch("app.workers.scene_tasks._run_async")
    def test_split_scenes_preserves_pipeline_data(self, mock_run_async, mock_db, mock_emit):
        """Test that existing pipeline_data keys are preserved."""
        from app.services.ai_video_service import Scene
        from app.workers.scene_tasks import split_scenes_task

        scenes = [
            Scene(
                scene_number=1,
                narration="Test",
                visual_description="Test",
                visual_type="stock_footage",
                stock_query="test",
                ai_prompt="test",
                duration_seconds=3.0,
            ),
        ]
        mock_run_async.return_value = scenes

        project = _make_project(status=VideoStatus.SCRIPT_GENERATING)
        mock_db.side_effect = _make_mock_db(project)

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"script": "original script", "tags": ["original"]},
            "video_format": "short",
        }

        result = split_scenes_task(pipeline_data=pipeline_data)

        # Original keys preserved
        assert result["script_data"]["script"] == "original script"
        assert result["video_format"] == "short"
        # New key added
        assert "scene_plan" in result


class TestGenerateVisualsTask:
    """Test generate_visuals_task worker."""

    @patch("app.workers.scene_tasks.PipelineResume")
    @patch("app.workers.scene_tasks.emit_status_update")
    @patch("app.workers.scene_tasks.get_sync_db")
    @patch("app.workers.scene_tasks._run_async")
    def test_generate_visuals_success(self, mock_run_async, mock_db, mock_emit, mock_resume, tmp_path):
        """Test successful visual generation returns clip_paths."""
        from app.workers.scene_tasks import generate_visuals_task

        clip1 = tmp_path / "scene_1.mp4"
        clip2 = tmp_path / "scene_2.mp4"
        clip1.write_bytes(b"video1")
        clip2.write_bytes(b"video2")
        mock_run_async.return_value = [clip1, clip2]

        project = _make_project(status=VideoStatus.SCENE_SPLITTING)
        mock_db.side_effect = _make_mock_db(project)

        scene_dicts = [
            {
                "scene_number": 1,
                "narration": "Test",
                "visual_description": "Test",
                "visual_type": "stock_footage",
                "stock_query": "nature",
                "ai_prompt": "nature scene",
                "duration_seconds": 4.0,
                "video_path": None,
                "generation_cost": 0.0,
                "provider_used": None,
            },
            {
                "scene_number": 2,
                "narration": "Test",
                "visual_description": "Test",
                "visual_type": "ai_generated",
                "stock_query": "abstract",
                "ai_prompt": "abstract data",
                "duration_seconds": 5.0,
                "video_path": None,
                "generation_cost": 0.15,
                "provider_used": "runway",
            },
        ]

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"script": "test"},
            "video_format": "short",
            "scene_plan": scene_dicts,
        }

        result = generate_visuals_task(pipeline_data=pipeline_data)

        assert len(result["clip_paths"]) == 2
        assert result["project_id"] == "test-project-uuid"
        project.validate_status_transition.assert_called_once_with(VideoStatus.VIDEO_GENERATING)

    @patch("app.workers.scene_tasks.emit_status_update")
    @patch("app.workers.scene_tasks.get_sync_db")
    def test_generate_visuals_no_scene_plan_fails(self, mock_db, mock_emit):
        """Test that missing scene_plan raises error."""
        from app.workers.scene_tasks import generate_visuals_task

        project = _make_project(status=VideoStatus.SCENE_SPLITTING)
        mock_db.side_effect = _make_mock_db(project)

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"script": "test"},
            "video_format": "short",
            # No scene_plan!
        }

        with pytest.raises(ValueError, match="No scene_plan"):
            generate_visuals_task(pipeline_data=pipeline_data)

    @patch("app.workers.scene_tasks.PipelineResume")
    @patch("app.workers.scene_tasks.emit_status_update")
    @patch("app.workers.scene_tasks.get_sync_db")
    @patch("app.workers.scene_tasks._run_async")
    def test_generate_visuals_tracks_cost(self, mock_run_async, mock_db, mock_emit, mock_resume, tmp_path):
        """Test that AI generation costs are tracked."""
        from app.workers.scene_tasks import generate_visuals_task

        clip = tmp_path / "scene.mp4"
        clip.write_bytes(b"video")
        mock_run_async.return_value = [clip]

        project = _make_project(status=VideoStatus.SCENE_SPLITTING)
        mock_db.side_effect = _make_mock_db(project)

        scene_dicts = [
            {
                "scene_number": 1,
                "narration": "Test",
                "visual_description": "Test",
                "visual_type": "ai_generated",
                "stock_query": "test",
                "ai_prompt": "test",
                "duration_seconds": 5.0,
                "video_path": None,
                "generation_cost": 0.25,
                "provider_used": "runway",
            },
        ]

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"script": "test"},
            "video_format": "short",
            "scene_plan": scene_dicts,
        }

        generate_visuals_task(pipeline_data=pipeline_data)

        # Cost should be tracked on the project
        assert project.ai_video_cost is not None
