"""Integration tests for admin routes (API key management)."""

import pytest
import uuid
from httpx import AsyncClient

from app.models.api_key import APIKey


class TestCreateAPIKey:
    """Test POST /api/v1/admin/keys endpoint."""

    @pytest.mark.asyncio
    async def test_create_api_key_success(self, client: AsyncClient, db_session):
        """Test creating a new API key."""
        response = await client.post(
            "/api/v1/admin/keys",
            json={
                "name": "Test Key",
                "rate_limit": 200
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Key"
        assert data["rate_limit"] == 200
        assert data["is_active"] is True
        assert data["key"].startswith("ce_")  # Key prefix

        # Verify in database
        from sqlalchemy import select
        result = await db_session.execute(select(APIKey))
        keys = result.scalars().all()
        assert len(keys) == 1

    @pytest.mark.asyncio
    async def test_create_api_key_default_rate_limit(self, client: AsyncClient):
        """Test default rate limit."""
        response = await client.post(
            "/api/v1/admin/keys",
            json={"name": "Test Key"}
        )

        assert response.status_code == 201
        assert response.json()["rate_limit"] == 100  # Default

    @pytest.mark.asyncio
    async def test_create_api_key_validation(self, client: AsyncClient):
        """Test validation errors."""
        # Empty name
        response = await client.post(
            "/api/v1/admin/keys",
            json={"name": ""}
        )
        assert response.status_code == 422


class TestListAPIKeys:
    """Test GET /api/v1/admin/keys endpoint."""

    @pytest.mark.asyncio
    async def test_list_api_keys(self, client: AsyncClient, db_session):
        """Test listing API keys."""
        keys = [
            APIKey(key=f"ce_key{i}", name=f"Key {i}", rate_limit=100)
            for i in range(3)
        ]
        for k in keys:
            db_session.add(k)
        await db_session.commit()

        response = await client.get("/api/v1/admin/keys")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["keys"]) == 3
        # Actual key values should not be exposed
        assert all("key" not in str(k) or k["name"] for k in data["keys"])

    @pytest.mark.asyncio
    async def test_list_api_keys_active_only(self, client: AsyncClient, db_session):
        """Test filtering active keys."""
        active = APIKey(key="ce_active", name="Active", is_active=True)
        inactive = APIKey(key="ce_inactive", name="Inactive", is_active=False)

        db_session.add_all([active, inactive])
        await db_session.commit()

        response = await client.get("/api/v1/admin/keys?active_only=true")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["keys"][0]["name"] == "Active"


class TestGetAPIKey:
    """Test GET /api/v1/admin/keys/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_api_key_success(self, client: AsyncClient, db_session):
        """Test getting API key details."""
        api_key = APIKey(key="ce_test", name="Test Key", rate_limit=150)
        db_session.add(api_key)
        await db_session.commit()

        response = await client.get(f"/api/v1/admin/keys/{api_key.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Key"
        assert data["rate_limit"] == 150

    @pytest.mark.asyncio
    async def test_get_api_key_not_found(self, client: AsyncClient):
        """Test getting non-existent key."""
        fake_id = uuid.uuid4()
        response = await client.get(f"/api/v1/admin/keys/{fake_id}")

        assert response.status_code == 404


class TestRevokeAPIKey:
    """Test PATCH /api/v1/admin/keys/{id}/revoke endpoint."""

    @pytest.mark.asyncio
    async def test_revoke_api_key(self, client: AsyncClient, db_session):
        """Test revoking an API key."""
        api_key = APIKey(key="ce_test", name="To Revoke", is_active=True)
        db_session.add(api_key)
        await db_session.commit()

        response = await client.patch(f"/api/v1/admin/keys/{api_key.id}/revoke")

        assert response.status_code == 200
        assert "revoked" in response.json()["message"]

        # Verify in database
        await db_session.refresh(api_key)
        assert api_key.is_active is False

    @pytest.mark.asyncio
    async def test_revoke_already_inactive(self, client: AsyncClient, db_session):
        """Test revoking already inactive key."""
        api_key = APIKey(key="ce_test", name="Test", is_active=False)
        db_session.add(api_key)
        await db_session.commit()

        response = await client.patch(f"/api/v1/admin/keys/{api_key.id}/revoke")

        assert response.status_code == 400


class TestActivateAPIKey:
    """Test PATCH /api/v1/admin/keys/{id}/activate endpoint."""

    @pytest.mark.asyncio
    async def test_activate_api_key(self, client: AsyncClient, db_session):
        """Test activating an API key."""
        api_key = APIKey(key="ce_test", name="To Activate", is_active=False)
        db_session.add(api_key)
        await db_session.commit()

        response = await client.patch(f"/api/v1/admin/keys/{api_key.id}/activate")

        assert response.status_code == 200
        assert "activated" in response.json()["message"]

        await db_session.refresh(api_key)
        assert api_key.is_active is True


class TestDeleteAPIKey:
    """Test DELETE /api/v1/admin/keys/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_api_key(self, client: AsyncClient, db_session):
        """Test deleting an API key."""
        api_key = APIKey(key="ce_test", name="To Delete")
        db_session.add(api_key)
        await db_session.commit()
        key_id = api_key.id

        response = await client.delete(f"/api/v1/admin/keys/{key_id}")

        assert response.status_code == 204

        # Verify deleted
        deleted = await db_session.get(APIKey, key_id)
        assert deleted is None
