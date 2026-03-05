"""Unit tests for individual Celery worker tasks with mocked DB and services."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock
from contextlib import contextmanager

from app.models.video import VideoProject, VideoStatus


# ── Helper: mock get_sync_db context manager ─────────────────
def _make_mock_db(project):
    """Create a mock get_sync_db that returns a session with the given project."""

    @contextmanager
    def mock_get_sync_db():
        session = MagicMock()
        session.get.return_value = project
        yield session

    return mock_get_sync_db


def _make_project(status=VideoStatus.PENDING, **kwargs):
    """Create a mock VideoProject for testing."""
    project = MagicMock(spec=VideoProject)
    project.id = "test-project-uuid"
    project.status = status
    project.topic = kwargs.get("topic", "test topic")
    project.telegram_user_id = None
    project.telegram_chat_id = None
    project.telegram_message_id = None
    project.error_message = None
    project.validate_status_transition = MagicMock(return_value=True)
    return project


class TestScriptTask:
    """Test generate_script_task worker."""

    @patch("app.workers.script_tasks.emit_status_update")
    @patch("app.workers.script_tasks.get_sync_db")
    @patch("app.workers.script_tasks._run_async")
    def test_script_task_success(self, mock_run_async, mock_db, mock_emit):
        """Test successful script generation stores result and returns pipeline data."""
        from app.workers.script_tasks import generate_script_task

        script_data = {
            "title": "Test Title",
            "script": "Test script content",
            "tags": ["test", "shorts"],
            "description": "Test description",
        }
        mock_run_async.return_value = script_data

        project = _make_project(status=VideoStatus.PENDING)
        mock_db.side_effect = _make_mock_db(project)

        # Call task directly — bind=True means Celery injects self automatically
        result = generate_script_task(
            project_id="test-project-uuid",
            topic="test topic",
            video_format="short",
            provider="openai",
        )

        assert result["project_id"] == "test-project-uuid"
        assert result["script_data"] == script_data
        assert result["video_format"] == "short"
        assert project.script == script_data["script"]
        project.validate_status_transition.assert_called_once_with(
            VideoStatus.SCRIPT_GENERATING
        )

    @patch("app.workers.script_tasks._mark_project_failed")
    @patch("app.workers.script_tasks.emit_status_update")
    @patch("app.workers.script_tasks.get_sync_db")
    @patch("app.workers.script_tasks._run_async")
    def test_script_task_content_moderation_blocks(
        self, mock_run_async, mock_db, mock_emit, mock_mark_failed
    ):
        """Test that content moderation rejection propagates as failure."""
        from app.workers.script_tasks import generate_script_task

        mock_run_async.side_effect = ValueError(
            "Topic violates content policy (Violence)"
        )

        project = _make_project(status=VideoStatus.PENDING)
        mock_db.side_effect = _make_mock_db(project)

        # Simulate retries exhausted so _mark_project_failed is called
        with patch.object(generate_script_task, "max_retries", 0):
            with pytest.raises(ValueError):
                generate_script_task(
                    project_id="test-project-uuid",
                    topic="violent topic",
                )

        mock_mark_failed.assert_called_once()
        assert mock_mark_failed.call_args[0][0] == "test-project-uuid"
        assert "content policy" in mock_mark_failed.call_args[0][1]


class TestAudioTask:
    """Test generate_audio_task worker."""

    @patch("app.workers.media_tasks.emit_status_update")
    @patch("app.workers.media_tasks.get_sync_db")
    @patch("app.workers.media_tasks._run_async")
    def test_audio_task_success(self, mock_run_async, mock_db, mock_emit, tmp_path):
        """Test successful audio generation stores path and returns pipeline data."""
        from app.workers.media_tasks import generate_audio_task

        audio_path = tmp_path / "test_audio.mp3"
        audio_path.write_bytes(b"fake_audio_data")
        mock_run_async.return_value = audio_path

        project = _make_project(status=VideoStatus.SCRIPT_GENERATING)
        mock_db.side_effect = _make_mock_db(project)

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"script": "test script"},
            "video_format": "short",
        }

        result = generate_audio_task(pipeline_data=pipeline_data)

        assert result["audio_path"] == str(audio_path)
        assert result["project_id"] == "test-project-uuid"
        assert project.audio_path == str(audio_path)
        project.validate_status_transition.assert_called_once_with(
            VideoStatus.AUDIO_GENERATING
        )


class TestVisualTask:
    """Test fetch_visuals_task worker."""

    @patch("app.core.config.get_settings")
    @patch("app.workers.media_tasks.emit_status_update")
    @patch("app.workers.media_tasks.get_sync_db")
    @patch("app.workers.media_tasks._run_async")
    def test_visual_task_success(self, mock_run_async, mock_db, mock_emit, mock_settings, tmp_path):
        """Test successful visual fetch stores paths and returns pipeline data."""
        from app.workers.media_tasks import fetch_visuals_task

        # Force stock footage path (not AI video)
        mock_settings.return_value = MagicMock(ai_video_enabled=False)

        clip1 = tmp_path / "clip1.mp4"
        clip2 = tmp_path / "clip2.mp4"
        clip1.write_bytes(b"video1")
        clip2.write_bytes(b"video2")
        mock_run_async.return_value = [clip1, clip2]

        project = _make_project(status=VideoStatus.SCRIPT_GENERATING)
        mock_db.side_effect = _make_mock_db(project)

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"script": "test", "tags": ["nature", "ocean"]},
            "video_format": "short",
        }

        result = fetch_visuals_task(pipeline_data=pipeline_data)

        assert len(result["clip_paths"]) == 2
        assert result["project_id"] == "test-project-uuid"
        project.validate_status_transition.assert_called_once_with(
            VideoStatus.VIDEO_GENERATING
        )

    @patch("app.core.config.get_settings")
    @patch("app.workers.media_tasks.emit_status_update")
    @patch("app.workers.media_tasks.get_sync_db")
    @patch("app.workers.media_tasks._run_async")
    def test_visual_task_no_clips_found(self, mock_run_async, mock_db, mock_emit, mock_settings):
        """Test that empty clip list still returns (no error unless assembly checks)."""
        from app.workers.media_tasks import fetch_visuals_task

        mock_settings.return_value = MagicMock(ai_video_enabled=False)
        mock_run_async.return_value = []

        project = _make_project(status=VideoStatus.SCRIPT_GENERATING)
        mock_db.side_effect = _make_mock_db(project)

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"script": "test", "tags": []},
            "video_format": "short",
        }

        result = fetch_visuals_task(pipeline_data=pipeline_data)
        assert result["clip_paths"] == []


class TestAssemblyTask:
    """Test assemble_video_task worker."""

    @patch("app.workers.assembly_tasks.emit_status_update")
    @patch("app.workers.assembly_tasks.get_sync_db")
    @patch("app.workers.assembly_tasks.assemble_video")
    def test_assembly_task_merges_parallel_results(
        self, mock_assemble, mock_db, mock_emit, tmp_path
    ):
        """Test that chord callback correctly merges audio and visual results."""
        from app.workers.assembly_tasks import assemble_video_task

        output_path = tmp_path / "final.mp4"
        mock_assemble.return_value = output_path

        project = _make_project(status=VideoStatus.AUDIO_GENERATING)
        mock_db.side_effect = _make_mock_db(project)

        # Simulate chord results: list of two dicts from parallel tasks
        parallel_results = [
            {
                "project_id": "test-project-uuid",
                "script_data": {"script": "test"},
                "video_format": "short",
                "audio_path": "/media/audio/test.mp3",
            },
            {
                "project_id": "test-project-uuid",
                "script_data": {"script": "test"},
                "video_format": "short",
                "clip_paths": ["/media/video/clip1.mp4", "/media/video/clip2.mp4"],
            },
        ]

        result = assemble_video_task(parallel_results=parallel_results)

        assert result["output_path"] == str(output_path)
        assert project.output_path == str(output_path)
        mock_assemble.assert_called_once()
        project.validate_status_transition.assert_called_once_with(
            VideoStatus.ASSEMBLING
        )

    @patch("app.workers.assembly_tasks._mark_project_failed")
    @patch("app.workers.assembly_tasks.emit_status_update")
    @patch("app.workers.assembly_tasks.get_sync_db")
    def test_assembly_task_missing_audio_fails(self, mock_db, mock_emit, mock_mark_failed):
        """Test that missing audio_path in parallel results raises error."""
        from app.workers.assembly_tasks import assemble_video_task

        project = _make_project(status=VideoStatus.AUDIO_GENERATING)
        mock_db.side_effect = _make_mock_db(project)

        parallel_results = [
            {
                "project_id": "test-project-uuid",
                "video_format": "short",
                # No audio_path!
            },
            {
                "project_id": "test-project-uuid",
                "video_format": "short",
                "clip_paths": ["/media/video/clip1.mp4"],
            },
        ]

        with patch.object(assemble_video_task, "max_retries", 0):
            with pytest.raises(ValueError):
                assemble_video_task(parallel_results=parallel_results)

        mock_mark_failed.assert_called_once()
        assert "test-project-uuid" == mock_mark_failed.call_args[0][0]

    @patch("app.workers.assembly_tasks._mark_project_failed")
    @patch("app.workers.assembly_tasks.emit_status_update")
    @patch("app.workers.assembly_tasks.get_sync_db")
    def test_assembly_task_missing_clips_fails(self, mock_db, mock_emit, mock_mark_failed):
        """Test that missing clip_paths in parallel results raises error."""
        from app.workers.assembly_tasks import assemble_video_task

        project = _make_project(status=VideoStatus.AUDIO_GENERATING)
        mock_db.side_effect = _make_mock_db(project)

        parallel_results = [
            {
                "project_id": "test-project-uuid",
                "video_format": "short",
                "audio_path": "/media/audio/test.mp3",
            },
            {
                "project_id": "test-project-uuid",
                "video_format": "short",
                # No clip_paths!
            },
        ]

        with patch.object(assemble_video_task, "max_retries", 0):
            with pytest.raises(ValueError):
                assemble_video_task(parallel_results=parallel_results)

        mock_mark_failed.assert_called_once()
        assert "test-project-uuid" == mock_mark_failed.call_args[0][0]


class TestUploadTask:
    """Test upload_to_youtube_task worker."""

    @patch("app.workers.upload_tasks.emit_status_update")
    @patch("app.workers.upload_tasks.get_sync_db")
    @patch("app.workers.upload_tasks.upload_video")
    def test_upload_task_success(self, mock_upload, mock_db, mock_emit, tmp_path):
        """Test successful YouTube upload sets COMPLETED status."""
        from app.workers.upload_tasks import upload_to_youtube_task

        output_file = tmp_path / "final.mp4"
        output_file.write_bytes(b"video_data")

        mock_upload.return_value = {
            "video_id": "yt_abc123",
            "url": "https://www.youtube.com/watch?v=yt_abc123",
        }

        project = _make_project(status=VideoStatus.ASSEMBLING)
        mock_db.side_effect = _make_mock_db(project)

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {
                "title": "Test Video",
                "description": "Test desc",
                "tags": ["test"],
            },
            "video_format": "short",
            "output_path": str(output_file),
        }

        result = upload_to_youtube_task(pipeline_data=pipeline_data)

        assert result["youtube_video_id"] == "yt_abc123"
        assert result["youtube_url"] == "https://www.youtube.com/watch?v=yt_abc123"
        assert project.status == VideoStatus.COMPLETED
        assert project.youtube_video_id == "yt_abc123"
        project.validate_status_transition.assert_called_once_with(
            VideoStatus.UPLOADING
        )

    @patch("app.workers.upload_tasks._mark_project_failed")
    @patch("app.workers.upload_tasks.emit_status_update")
    @patch("app.workers.upload_tasks.get_sync_db")
    def test_upload_task_missing_file_fails(self, mock_db, mock_emit, mock_mark_failed):
        """Test that missing output file raises FileNotFoundError."""
        from app.workers.upload_tasks import upload_to_youtube_task

        project = _make_project(status=VideoStatus.ASSEMBLING)
        mock_db.side_effect = _make_mock_db(project)

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"title": "Test", "description": "Test", "tags": []},
            "video_format": "short",
            "output_path": "/nonexistent/video.mp4",
        }

        with patch.object(upload_to_youtube_task, "max_retries", 0):
            with pytest.raises(FileNotFoundError):
                upload_to_youtube_task(pipeline_data=pipeline_data)

        mock_mark_failed.assert_called_once()
        assert "test-project-uuid" == mock_mark_failed.call_args[0][0]

    @patch("app.workers.upload_tasks._mark_project_failed")
    @patch("app.workers.upload_tasks.emit_status_update")
    @patch("app.workers.upload_tasks.get_sync_db")
    def test_upload_task_no_output_path_fails(self, mock_db, mock_emit, mock_mark_failed):
        """Test that missing output_path in pipeline data raises error."""
        from app.workers.upload_tasks import upload_to_youtube_task

        project = _make_project(status=VideoStatus.ASSEMBLING)
        mock_db.side_effect = _make_mock_db(project)

        pipeline_data = {
            "project_id": "test-project-uuid",
            "script_data": {"title": "Test", "description": "Test", "tags": []},
            "video_format": "short",
            # No output_path!
        }

        with patch.object(upload_to_youtube_task, "max_retries", 0):
            with pytest.raises(ValueError):
                upload_to_youtube_task(pipeline_data=pipeline_data)

        mock_mark_failed.assert_called_once()
        assert "test-project-uuid" == mock_mark_failed.call_args[0][0]


class TestTaskFailureHandling:
    """Test that tasks set FAILED status and error_message on errors."""

    @patch("app.workers.script_tasks._mark_project_failed")
    @patch("app.workers.script_tasks.emit_status_update")
    @patch("app.workers.script_tasks.get_sync_db")
    @patch("app.workers.script_tasks._run_async")
    def test_task_sets_failed_status_on_error(
        self, mock_run_async, mock_db, mock_emit, mock_mark_failed
    ):
        """Test that task failure calls _mark_project_failed with error details."""
        from app.workers.script_tasks import generate_script_task

        mock_run_async.side_effect = RuntimeError("LLM API is down")

        project = _make_project(status=VideoStatus.PENDING)
        mock_db.side_effect = _make_mock_db(project)

        # Simulate retries exhausted so _mark_project_failed is called
        with patch.object(generate_script_task, "max_retries", 0):
            with pytest.raises(RuntimeError):
                generate_script_task(
                    project_id="test-project-uuid",
                    topic="test topic",
                )

        mock_mark_failed.assert_called_once()
        assert mock_mark_failed.call_args[0][0] == "test-project-uuid"
        assert "LLM API is down" in mock_mark_failed.call_args[0][1]
