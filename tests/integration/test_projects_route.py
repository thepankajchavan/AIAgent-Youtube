"""Integration tests for projects routes."""

import pytest
import uuid
from httpx import AsyncClient

from app.models.video import VideoProject, VideoStatus, VideoFormat


class TestListProjects:
    """Test GET /api/v1/projects endpoint."""

    @pytest.mark.asyncio
    async def test_list_projects_empty(self, client: AsyncClient):
        """Test listing when no projects exist."""
        response = await client.get("/api/v1/projects")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["projects"] == []

    @pytest.mark.asyncio
    async def test_list_projects_with_data(self, client: AsyncClient, db_session):
        """Test listing multiple projects."""
        # Create test projects
        projects = [
            VideoProject(topic=f"Test {i}", status=VideoStatus.PENDING)
            for i in range(5)
        ]
        for p in projects:
            db_session.add(p)
        await db_session.commit()

        response = await client.get("/api/v1/projects")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["projects"]) == 5

    @pytest.mark.asyncio
    async def test_list_projects_pagination(self, client: AsyncClient, db_session):
        """Test pagination."""
        projects = [VideoProject(topic=f"Test {i}") for i in range(25)]
        for p in projects:
            db_session.add(p)
        await db_session.commit()

        # Page 1
        response = await client.get("/api/v1/projects?page=1&per_page=10")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 25
        assert len(data["projects"]) == 10
        assert data["page"] == 1

        # Page 2
        response = await client.get("/api/v1/projects?page=2&per_page=10")
        data = response.json()
        assert len(data["projects"]) == 10
        assert data["page"] == 2

    @pytest.mark.asyncio
    async def test_list_projects_filter_by_status(self, client: AsyncClient, db_session):
        """Test filtering by status."""
        projects = [
            VideoProject(topic="Completed 1", status=VideoStatus.COMPLETED),
            VideoProject(topic="Failed 1", status=VideoStatus.FAILED),
            VideoProject(topic="Completed 2", status=VideoStatus.COMPLETED),
        ]
        for p in projects:
            db_session.add(p)
        await db_session.commit()

        response = await client.get("/api/v1/projects?status=completed")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert all(p["status"] == "completed" for p in data["projects"])


class TestGetProject:
    """Test GET /api/v1/projects/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_project_success(self, client: AsyncClient, db_session):
        """Test getting a project by ID."""
        project = VideoProject(
            topic="Test project",
            status=VideoStatus.COMPLETED,
            script="Test script content"
        )
        db_session.add(project)
        await db_session.commit()

        response = await client.get(f"/api/v1/projects/{project.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(project.id)
        assert data["topic"] == "Test project"
        assert data["status"] == "completed"
        assert data["script"] == "Test script content"

    @pytest.mark.asyncio
    async def test_get_project_not_found(self, client: AsyncClient):
        """Test getting non-existent project."""
        fake_id = uuid.uuid4()
        response = await client.get(f"/api/v1/projects/{fake_id}")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestDeleteProject:
    """Test DELETE /api/v1/projects/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_project_success(self, client: AsyncClient, db_session):
        """Test deleting a project."""
        project = VideoProject(topic="To delete")
        db_session.add(project)
        await db_session.commit()
        project_id = project.id

        response = await client.delete(f"/api/v1/projects/{project_id}")

        assert response.status_code == 200
        assert "deleted" in response.json()["message"]

        # Verify project is gone
        deleted = await db_session.get(VideoProject, project_id)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_project_not_found(self, client: AsyncClient):
        """Test deleting non-existent project."""
        fake_id = uuid.uuid4()
        response = await client.delete(f"/api/v1/projects/{fake_id}")

        assert response.status_code == 404


class TestRetryProject:
    """Test POST /api/v1/projects/{id}/retry endpoint."""

    @pytest.mark.asyncio
    async def test_retry_failed_project(self, client: AsyncClient, db_session, mocker):
        """Test retrying a failed project."""
        project = VideoProject(
            topic="Failed project",
            status=VideoStatus.FAILED,
            error_message="Previous error"
        )
        db_session.add(project)
        await db_session.commit()

        # Mock Celery
        mock_result = mocker.MagicMock()
        mock_result.id = "retry-task-123"
        mocker.patch(
            "app.api.routes.projects.run_pipeline_task.delay",
            return_value=mock_result
        )

        response = await client.post(f"/api/v1/projects/{project.id}/retry")

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_retry_non_failed_project(self, client: AsyncClient, db_session):
        """Test that only FAILED projects can be retried."""
        project = VideoProject(topic="Test", status=VideoStatus.COMPLETED)
        db_session.add(project)
        await db_session.commit()

        response = await client.post(f"/api/v1/projects/{project.id}/retry")

        assert response.status_code == 409
        assert "Only FAILED projects" in response.json()["detail"]
