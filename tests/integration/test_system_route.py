"""Integration tests for system routes."""

import pytest
from httpx import AsyncClient
from unittest.mock import patch, MagicMock


class TestHealthCheck:
    """Test GET /api/v1/system/health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_all_healthy(self, client: AsyncClient, mocker):
        """Test health check when all services are healthy."""
        # Database is already healthy (test client uses real DB)
        # Mock Redis ping
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.close = MagicMock()

        mocker.patch("app.api.routes.system.Redis.from_url", return_value=mock_redis)

        response = await client.get("/api/v1/system/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "healthy"
        assert data["redis"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_redis_unhealthy(self, client: AsyncClient, mocker):
        """Test health check when Redis is down."""
        # Mock Redis to fail
        mocker.patch(
            "app.api.routes.system.Redis.from_url",
            side_effect=Exception("Connection refused")
        )

        response = await client.get("/api/v1/system/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "healthy"
        assert "unhealthy" in data["redis"]


class TestGetTaskStatus:
    """Test GET /api/v1/system/tasks/{task_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_task_status_pending(self, client: AsyncClient, mocker):
        """Test getting status of pending task."""
        mock_result = MagicMock()
        mock_result.status = "PENDING"
        mock_result.ready.return_value = False

        mocker.patch(
            "app.api.routes.system.celery_app.AsyncResult",
            return_value=mock_result
        )

        response = await client.get("/api/v1/system/tasks/test-task-123")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "test-task-123"
        assert data["status"] == "PENDING"

    @pytest.mark.asyncio
    async def test_get_task_status_success(self, client: AsyncClient, mocker):
        """Test getting status of successful task."""
        mock_result = MagicMock()
        mock_result.status = "SUCCESS"
        mock_result.ready.return_value = True
        mock_result.result = {"video_id": "abc123"}

        mocker.patch(
            "app.api.routes.system.celery_app.AsyncResult",
            return_value=mock_result
        )

        response = await client.get("/api/v1/system/tasks/test-task-123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "SUCCESS"
        assert data["result"]["video_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_get_task_status_failure(self, client: AsyncClient, mocker):
        """Test getting status of failed task."""
        mock_result = MagicMock()
        mock_result.status = "FAILURE"
        mock_result.ready.return_value = False
        mock_result.info = "Task failed: API error"

        mocker.patch(
            "app.api.routes.system.celery_app.AsyncResult",
            return_value=mock_result
        )

        response = await client.get("/api/v1/system/tasks/test-task-123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "FAILURE"


class TestRevokeTask:
    """Test POST /api/v1/system/tasks/{task_id}/revoke endpoint."""

    @pytest.mark.asyncio
    async def test_revoke_task_success(self, client: AsyncClient, mocker):
        """Test revoking a task."""
        mock_control = MagicMock()
        mock_control.revoke = MagicMock()

        mocker.patch(
            "app.api.routes.system.celery_app.control",
            mock_control
        )

        response = await client.post("/api/v1/system/tasks/test-task-123/revoke")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "test-task-123"
        assert data["action"] == "revoked"

        mock_control.revoke.assert_called_once_with("test-task-123", terminate=False)

    @pytest.mark.asyncio
    async def test_revoke_task_with_terminate(self, client: AsyncClient, mocker):
        """Test revoking with terminate flag."""
        mock_control = MagicMock()
        mock_control.revoke = MagicMock()

        mocker.patch(
            "app.api.routes.system.celery_app.control",
            mock_control
        )

        response = await client.post(
            "/api/v1/system/tasks/test-task-123/revoke?terminate=true"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "terminated"

        mock_control.revoke.assert_called_once_with("test-task-123", terminate=True)

    @pytest.mark.asyncio
    async def test_revoke_task_failure(self, client: AsyncClient, mocker):
        """Test revoke failure."""
        mock_control = MagicMock()
        mock_control.revoke.side_effect = Exception("Celery error")

        mocker.patch(
            "app.api.routes.system.celery_app.control",
            mock_control
        )

        response = await client.post("/api/v1/system/tasks/test-task-123/revoke")

        assert response.status_code == 500
