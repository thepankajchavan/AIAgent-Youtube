"""
Trend Health Monitor — tracks trend fetching health and alerts on failures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import redis.asyncio as aioredis
from loguru import logger

from app.core.config import get_settings

REDIS_HEALTH_KEY = "autopilot:last_trend_fetch"
ALERT_THRESHOLD_HOURS = 12


class TrendHealthMonitor:
    """Monitors trend fetching health and alerts on failures."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def record_successful_fetch(self) -> None:
        """Record a successful trend fetch timestamp in Redis."""
        try:
            r = aioredis.from_url(self._settings.redis_url, decode_responses=True)
            try:
                await r.set(
                    REDIS_HEALTH_KEY,
                    datetime.now(timezone.utc).isoformat(),
                )
            finally:
                await r.aclose()
        except Exception as exc:
            logger.warning("Failed to record trend health: {}", exc)

    async def check_health(self) -> dict:
        """Returns health status including last fetch time and hours since."""
        try:
            r = aioredis.from_url(self._settings.redis_url, decode_responses=True)
            try:
                val = await r.get(REDIS_HEALTH_KEY)
            finally:
                await r.aclose()

            if val:
                last_fetch = datetime.fromisoformat(val)
                hours_ago = (datetime.now(timezone.utc) - last_fetch).total_seconds() / 3600
                return {
                    "healthy": hours_ago < ALERT_THRESHOLD_HOURS,
                    "last_fetch_ago_hours": round(hours_ago, 2),
                    "last_fetch_at": val,
                    "status": "healthy" if hours_ago < ALERT_THRESHOLD_HOURS else "stale",
                }

            return {
                "healthy": False,
                "last_fetch_ago_hours": None,
                "last_fetch_at": None,
                "status": "never_fetched",
            }

        except Exception as exc:
            logger.warning("Health check failed: {}", exc)
            return {
                "healthy": False,
                "last_fetch_ago_hours": None,
                "last_fetch_at": None,
                "status": "check_failed",
            }

    async def should_alert(self) -> bool:
        """True if last successful fetch was > ALERT_THRESHOLD_HOURS ago."""
        health = await self.check_health()
        return not health["healthy"]
