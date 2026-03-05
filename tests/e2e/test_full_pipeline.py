"""End-to-end tests for complete video pipeline.

These tests require a running database and Redis.
Skipped by default when running unit tests only.
"""

import pytest
from httpx import AsyncClient
from unittest.mock import MagicMock
from pathlib import Path

from app.models.video import VideoProject, VideoStatus


@pytest.mark.e2e
class TestFullPipelineE2E:
    """End-to-end test of complete pipeline."""

    @pytest.mark.asyncio
    async def test_complete_pipeline_flow(
        self, client: AsyncClient, db_session, mocker, tmp_path
    ):
        """Test complete pipeline from API request to database updates."""

        # Mock external services
        mock_script = {
            "title": "Space Facts",
            "script": "Test script",
            "tags": ["space"],
            "description": "Test",
        }
        mocker.patch(
            "app.services.llm_service.generate_script", return_value=mock_script
        )

        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"audio")
        mocker.patch(
            "app.services.tts_service.generate_speech", return_value=audio_path
        )

        video_paths = [tmp_path / "video.mp4"]
        video_paths[0].write_bytes(b"video")
        mocker.patch(
            "app.services.visual_service.fetch_clips", return_value=video_paths
        )

        final_video = tmp_path / "final.mp4"
        final_video.write_bytes(b"final")
        mocker.patch(
            "app.services.media_service.assemble_video", return_value=final_video
        )

        mocker.patch(
            "app.services.youtube_service.upload_video",
            return_value={
                "video_id": "test123",
                "url": "https://youtube.com/watch?v=test123",
            },
        )

        # Mock Celery dispatch
        mock_task = MagicMock()
        mock_task.id = "task-e2e-123"
        mocker.patch(
            "app.api.routes.pipeline.run_pipeline_task.delay",
            return_value=mock_task,
        )

        # Mock backpressure check
        mocker.patch(
            "app.core.circuit_breaker.QueueBackpressure.can_accept_new_pipeline",
            return_value=(True, 0),
        )

        # Trigger pipeline
        response = await client.post(
            "/api/v1/pipeline",
            json={
                "topic": "5 space facts",
                "video_format": "short",
                "provider": "openai",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending"

        # Verify project created
        from sqlalchemy import select

        result = await db_session.execute(select(VideoProject))
        project = result.scalar_one()
        assert project.topic == "5 space facts"
