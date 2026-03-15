"""Unit tests for TrendHealthMonitor service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SETTINGS_PATH = "app.services.trend_health_service.get_settings"
AIOREDIS_PATH = "app.services.trend_health_service.aioredis"


def _make_settings(**overrides) -> MagicMock:
    """Build a mock settings object with trend-health defaults."""
    defaults = {
        "redis_url": "redis://localhost:6379/0",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_mock_redis(**overrides) -> MagicMock:
    """Build a mock async Redis client with standard async methods."""
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.aclose = AsyncMock()
    for key, value in overrides.items():
        setattr(mock_redis, key, value)
    return mock_redis


# ===========================================================================
# record_successful_fetch
# ===========================================================================


class TestRecordSuccessfulFetch:
    """Tests for TrendHealthMonitor.record_successful_fetch()."""

    @patch(AIOREDIS_PATH)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_records_timestamp_in_redis(self, mock_settings, mock_aioredis):
        """Verify set is called with the health key and an ISO timestamp."""
        from app.services.trend_health_service import REDIS_HEALTH_KEY, TrendHealthMonitor

        mock_settings.return_value = _make_settings()

        mock_redis = _make_mock_redis()
        mock_aioredis.from_url.return_value = mock_redis

        monitor = TrendHealthMonitor()
        await monitor.record_successful_fetch()

        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == REDIS_HEALTH_KEY
        # Second arg should be an ISO timestamp string
        assert "T" in call_args[0][1]
        mock_redis.aclose.assert_awaited_once()


# ===========================================================================
# check_health
# ===========================================================================


class TestCheckHealth:
    """Tests for TrendHealthMonitor.check_health()."""

    @patch(AIOREDIS_PATH)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_healthy_when_recent_fetch(self, mock_settings, mock_aioredis):
        """Returns healthy when last fetch was within threshold."""
        from app.services.trend_health_service import TrendHealthMonitor

        mock_settings.return_value = _make_settings()

        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        mock_redis = _make_mock_redis(get=AsyncMock(return_value=recent))
        mock_aioredis.from_url.return_value = mock_redis

        monitor = TrendHealthMonitor()
        health = await monitor.check_health()

        assert health["healthy"] is True
        assert health["status"] == "healthy"
        assert health["last_fetch_ago_hours"] < 2.0
        assert health["last_fetch_at"] == recent

    @patch(AIOREDIS_PATH)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_stale_when_old_fetch(self, mock_settings, mock_aioredis):
        """Returns unhealthy/stale when last fetch exceeds threshold (>12h)."""
        from app.services.trend_health_service import TrendHealthMonitor

        mock_settings.return_value = _make_settings()

        old = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        mock_redis = _make_mock_redis(get=AsyncMock(return_value=old))
        mock_aioredis.from_url.return_value = mock_redis

        monitor = TrendHealthMonitor()
        health = await monitor.check_health()

        assert health["healthy"] is False
        assert health["status"] == "stale"
        assert health["last_fetch_ago_hours"] >= 23.0

    @patch(AIOREDIS_PATH)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_never_fetched(self, mock_settings, mock_aioredis):
        """Returns unhealthy/never_fetched when Redis has no key."""
        from app.services.trend_health_service import TrendHealthMonitor

        mock_settings.return_value = _make_settings()

        mock_redis = _make_mock_redis(get=AsyncMock(return_value=None))
        mock_aioredis.from_url.return_value = mock_redis

        monitor = TrendHealthMonitor()
        health = await monitor.check_health()

        assert health["healthy"] is False
        assert health["status"] == "never_fetched"
        assert health["last_fetch_at"] is None
        assert health["last_fetch_ago_hours"] is None


# ===========================================================================
# should_alert
# ===========================================================================


class TestShouldAlert:
    """Tests for TrendHealthMonitor.should_alert()."""

    @patch(AIOREDIS_PATH)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_should_alert_true_when_stale(self, mock_settings, mock_aioredis):
        """should_alert returns True when health is unhealthy (stale)."""
        from app.services.trend_health_service import TrendHealthMonitor

        mock_settings.return_value = _make_settings()

        old = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
        mock_redis = _make_mock_redis(get=AsyncMock(return_value=old))
        mock_aioredis.from_url.return_value = mock_redis

        monitor = TrendHealthMonitor()
        assert await monitor.should_alert() is True

    @patch(AIOREDIS_PATH)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_should_alert_false_when_healthy(self, mock_settings, mock_aioredis):
        """should_alert returns False when health is healthy."""
        from app.services.trend_health_service import TrendHealthMonitor

        mock_settings.return_value = _make_settings()

        recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        mock_redis = _make_mock_redis(get=AsyncMock(return_value=recent))
        mock_aioredis.from_url.return_value = mock_redis

        monitor = TrendHealthMonitor()
        assert await monitor.should_alert() is False
