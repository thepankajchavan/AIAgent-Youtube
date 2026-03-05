"""Integration tests for pipeline routes."""

from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from app.models.video import VideoProject, VideoStatus


class TestTriggerPipeline:
    """Test POST /api/v1/pipeline endpoint."""

    @pytest.mark.asyncio
    async def test_trigger_pipeline_success(self, client: AsyncClient, db_session, mocker):
        """Test successful pipeline trigger."""
        mock_celery_result = MagicMock()
        mock_celery_result.id = "celery-task-123"

        mock_delay = mocker.patch(
            "app.api.routes.pipeline.run_pipeline_task.delay", return_value=mock_celery_result
        )

        # Mock backpressure check
        mocker.patch(
            "app.core.circuit_breaker.QueueBackpressure.can_accept_new_pipeline",
            return_value=(True, 0),
        )

        response = await client.post(
            "/api/v1/pipeline",
            json={
                "topic": "5 facts about space",
                "video_format": "short",
                "provider": "openai",
                "skip_upload": False,
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "project_id" in data
        assert data["celery_task_id"] == "celery-task-123"
        assert data["status"] == "pending"

        mock_delay.assert_called_once()
        call_kwargs = mock_delay.call_args[1]
        assert call_kwargs["topic"] == "5 facts about space"

        from sqlalchemy import select

        result = await db_session.execute(select(VideoProject))
        projects = result.scalars().all()
        assert len(projects) == 1
        assert projects[0].status == VideoStatus.PENDING

    @pytest.mark.asyncio
    async def test_trigger_pipeline_invalid_topic(self, client: AsyncClient):
        """Test validation errors."""
        response = await client.post("/api/v1/pipeline", json={"topic": "ab"})  # Too short
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_trigger_pipeline_celery_failure(self, client: AsyncClient, mocker):
        """Test Celery dispatch failures."""
        mocker.patch(
            "app.api.routes.pipeline.run_pipeline_task.delay", side_effect=Exception("Redis error")
        )
        mocker.patch(
            "app.core.circuit_breaker.QueueBackpressure.can_accept_new_pipeline",
            return_value=(True, 0),
        )

        response = await client.post("/api/v1/pipeline", json={"topic": "Test topic"})

        assert response.status_code == 503


class TestBatchPipeline:
    """Test POST /api/v1/pipeline/batch endpoint."""

    @pytest.mark.asyncio
    async def test_batch_pipeline_success(self, client: AsyncClient, mocker):
        """Test batch pipeline trigger."""
        mock_celery_result = MagicMock()
        mock_celery_result.id = "task-123"

        mocker.patch(
            "app.api.routes.pipeline.run_pipeline_task.delay", return_value=mock_celery_result
        )

        response = await client.post(
            "/api/v1/pipeline/batch", json=[{"topic": "Topic 1"}, {"topic": "Topic 2"}]
        )

        assert response.status_code == 202
        data = response.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_batch_pipeline_exceeds_limit(self, client: AsyncClient):
        """Test batch limit enforcement."""
        requests = [{"topic": f"Topic {i}"} for i in range(11)]
        response = await client.post("/api/v1/pipeline/batch", json=requests)
        assert response.status_code == 400
