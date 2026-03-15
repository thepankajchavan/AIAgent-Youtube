"""
Analytics Service — collects and processes YouTube video analytics.

Fetches performance data from YouTube Data API v3 and YouTube Analytics API,
stores snapshots for trend analysis and self-improvement.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings

settings = get_settings()


class AnalyticsService:
    """Collects and processes YouTube video analytics."""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=3, max=60),
        retry=retry_if_exception_type((ConnectionError, OSError, TimeoutError)),
    )
    async def collect_video_stats(self, youtube_video_id: str) -> dict:
        """
        Fetch stats for a single video using YouTube Data API v3.

        Returns dict with: views, likes, comments, watch_time_minutes,
        average_view_duration_seconds.
        """
        import asyncio

        from googleapiclient.discovery import build

        loop = asyncio.get_event_loop()

        def _fetch():
            youtube = build("youtube", "v3", developerKey=settings.openai_api_key)
            request = youtube.videos().list(
                part="statistics,contentDetails",
                id=youtube_video_id,
            )
            response = request.execute()
            items = response.get("items", [])
            if not items:
                raise ValueError(f"Video {youtube_video_id} not found on YouTube")

            item = items[0]
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})

            # Parse duration (ISO 8601 format: PT1M30S)
            duration_str = content.get("duration", "PT0S")
            duration_seconds = self._parse_iso_duration(duration_str)

            return {
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "shares": 0,  # Not available from basic stats API
                "watch_time_minutes": 0.0,  # Requires Analytics API
                "average_view_duration_seconds": duration_seconds,
            }

        result = await loop.run_in_executor(None, _fetch)
        logger.debug(
            "Video stats fetched — yt_id={} views={}", youtube_video_id, result["views"]
        )
        return result

    async def collect_analytics_report(self, youtube_video_id: str) -> dict:
        """
        Fetch detailed analytics using YouTube Analytics API.

        Requires OAuth with youtube.readonly + yt-analytics.readonly scopes.
        Returns detailed metrics dict.
        """
        import asyncio

        loop = asyncio.get_event_loop()

        def _fetch():
            from googleapiclient.discovery import build
            from app.services.youtube_service import _get_authenticated_service

            # Use the authenticated service for Analytics API
            try:
                from google.oauth2.credentials import Credentials
                import json
                from pathlib import Path
                from app.services.youtube_service import _read_token, SCOPES

                token_path = Path(settings.youtube_token_file)
                token_json = _read_token(token_path)
                if not token_json:
                    return {}

                creds = Credentials.from_authorized_user_info(
                    json.loads(token_json),
                    SCOPES + [
                        "https://www.googleapis.com/auth/youtube.readonly",
                        "https://www.googleapis.com/auth/yt-analytics.readonly",
                    ],
                )

                analytics = build("youtubeAnalytics", "v2", credentials=creds)

                today = date.today()
                start_date = (today - timedelta(days=30)).isoformat()
                end_date = today.isoformat()

                response = analytics.reports().query(
                    ids="channel==MINE",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched,averageViewDuration,"
                    "averageViewPercentage,shares",
                    filters=f"video=={youtube_video_id}",
                ).execute()

                rows = response.get("rows", [])
                if not rows:
                    return {}

                row = rows[0]
                return {
                    "views": int(row[0]) if len(row) > 0 else 0,
                    "watch_time_minutes": float(row[1]) if len(row) > 1 else 0.0,
                    "average_view_duration_seconds": float(row[2]) if len(row) > 2 else 0.0,
                    "average_view_percentage": float(row[3]) if len(row) > 3 else None,
                    "shares": int(row[4]) if len(row) > 4 else 0,
                }
            except Exception as exc:
                logger.warning("Analytics API unavailable: {}", exc)
                return {}

        result = await loop.run_in_executor(None, _fetch)
        return result

    async def collect_all_recent_videos(self, lookback_days: int = 7) -> list[dict]:
        """
        Collect stats for all videos uploaded in the last N days.

        Skips videos that already have a snapshot for today.
        """
        from sqlalchemy import select, and_
        from app.core.database import async_session_factory
        from app.models.video import VideoProject, VideoStatus
        from app.models.analytics import VideoAnalytics

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        today = date.today()
        collected = []

        async with async_session_factory() as session:
            # Find videos with YouTube IDs uploaded recently
            query = (
                select(VideoProject)
                .where(VideoProject.youtube_video_id.isnot(None))
                .where(VideoProject.status == VideoStatus.COMPLETED)
                .where(VideoProject.created_at > cutoff)
            )
            result = await session.execute(query)
            projects = result.scalars().all()

            for project in projects:
                # Check if snapshot already exists for today
                existing = await session.execute(
                    select(VideoAnalytics).where(
                        and_(
                            VideoAnalytics.youtube_video_id == project.youtube_video_id,
                            VideoAnalytics.snapshot_date == today,
                        )
                    )
                )
                if existing.scalar_one_or_none():
                    logger.debug(
                        "Snapshot exists for {} on {}", project.youtube_video_id, today
                    )
                    continue

                try:
                    stats = await self.collect_video_stats(project.youtube_video_id)

                    # Try to get detailed analytics too
                    detailed = await self.collect_analytics_report(
                        project.youtube_video_id
                    )
                    if detailed:
                        stats.update(
                            {
                                k: v
                                for k, v in detailed.items()
                                if v is not None and v != 0
                            }
                        )

                    # Store snapshot
                    analytics_record = VideoAnalytics(
                        id=uuid.uuid4(),
                        project_id=str(project.id),
                        youtube_video_id=project.youtube_video_id,
                        snapshot_date=today,
                        views=stats["views"],
                        likes=stats["likes"],
                        comments=stats["comments"],
                        shares=stats.get("shares", 0),
                        watch_time_minutes=stats.get("watch_time_minutes", 0.0),
                        average_view_duration_seconds=stats.get(
                            "average_view_duration_seconds", 0.0
                        ),
                        click_through_rate=stats.get("click_through_rate"),
                        average_view_percentage=stats.get("average_view_percentage"),
                    )
                    session.add(analytics_record)
                    collected.append(stats)

                    logger.info(
                        "Analytics collected — project={} yt_id={} views={}",
                        project.id,
                        project.youtube_video_id,
                        stats["views"],
                    )

                except Exception as exc:
                    logger.warning(
                        "Failed to collect stats for {} ({}): {}",
                        project.id,
                        project.youtube_video_id,
                        exc,
                    )
                    continue

            await session.commit()

        logger.info(
            "Analytics collection complete — {} videos processed", len(collected)
        )
        return collected

    async def get_top_performing_videos(
        self, limit: int = 10, days: int = 30
    ) -> list[dict]:
        """
        Get top performing videos by views in the last N days.

        Joins with video_projects to get script content and metadata.
        """
        from sqlalchemy import select, desc
        from app.core.database import async_session_factory
        from app.models.analytics import VideoAnalytics
        from app.models.video import VideoProject

        cutoff = date.today() - timedelta(days=days)

        async with async_session_factory() as session:
            query = (
                select(VideoAnalytics, VideoProject)
                .join(
                    VideoProject,
                    VideoAnalytics.project_id == sa.cast(VideoProject.id, sa.String),
                )
                .where(VideoAnalytics.snapshot_date >= cutoff)
                .order_by(desc(VideoAnalytics.views))
                .limit(limit)
            )
            result = await session.execute(query)
            rows = result.all()

        return [
            {
                "project_id": str(project.id),
                "topic": project.topic,
                "views": analytics.views,
                "retention": analytics.average_view_percentage,
                "script_excerpt": (project.script or "")[:200],
                "prompt_version_id": project.prompt_version_id,
                "trend_topic_used": project.trend_topic_used,
            }
            for analytics, project in rows
        ]

    async def get_performance_summary(self, days: int = 30) -> dict:
        """Return aggregated performance stats for the last N days."""
        from sqlalchemy import select, func, desc
        from app.core.database import async_session_factory
        from app.models.analytics import VideoAnalytics
        from app.models.video import VideoProject

        cutoff = date.today() - timedelta(days=days)

        async with async_session_factory() as session:
            # Aggregate stats
            agg_query = select(
                func.sum(VideoAnalytics.views).label("total_views"),
                func.avg(VideoAnalytics.views).label("avg_views"),
                func.avg(VideoAnalytics.average_view_percentage).label("avg_retention"),
                func.avg(VideoAnalytics.click_through_rate).label("avg_ctr"),
                func.count(VideoAnalytics.id).label("snapshot_count"),
            ).where(VideoAnalytics.snapshot_date >= cutoff)

            result = await session.execute(agg_query)
            row = result.one()

            # Best video
            best_query = (
                select(VideoAnalytics, VideoProject)
                .join(
                    VideoProject,
                    VideoAnalytics.project_id == sa.cast(VideoProject.id, sa.String),
                )
                .where(VideoAnalytics.snapshot_date >= cutoff)
                .order_by(desc(VideoAnalytics.views))
                .limit(1)
            )
            best_result = await session.execute(best_query)
            best_row = best_result.first()

            # Worst video
            worst_query = (
                select(VideoAnalytics, VideoProject)
                .join(
                    VideoProject,
                    VideoAnalytics.project_id == sa.cast(VideoProject.id, sa.String),
                )
                .where(VideoAnalytics.snapshot_date >= cutoff)
                .where(VideoAnalytics.views > 0)
                .order_by(VideoAnalytics.views.asc())
                .limit(1)
            )
            worst_result = await session.execute(worst_query)
            worst_row = worst_result.first()

        return {
            "total_views": int(row.total_views or 0),
            "avg_views": round(float(row.avg_views or 0), 1),
            "avg_retention": round(float(row.avg_retention or 0), 1),
            "avg_ctr": round(float(row.avg_ctr or 0), 2),
            "snapshot_count": int(row.snapshot_count or 0),
            "best_video": (
                {
                    "topic": best_row[1].topic,
                    "views": best_row[0].views,
                    "project_id": str(best_row[1].id),
                }
                if best_row
                else None
            ),
            "worst_video": (
                {
                    "topic": worst_row[1].topic,
                    "views": worst_row[0].views,
                    "project_id": str(worst_row[1].id),
                }
                if worst_row
                else None
            ),
            "days": days,
        }

    @staticmethod
    def _parse_iso_duration(duration: str) -> float:
        """Parse ISO 8601 duration (PT1H2M3S) to seconds."""
        import re

        match = re.match(
            r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration
        )
        if not match:
            return 0.0
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return float(hours * 3600 + minutes * 60 + seconds)
