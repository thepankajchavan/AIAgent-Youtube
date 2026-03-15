"""
Pattern Service — analyzes video performance data to discover winning patterns.

Uses LLM analysis to identify correlations between script content/structure
and video performance metrics.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa

from loguru import logger

from app.core.config import get_settings

settings = get_settings()


class PatternService:
    """Analyzes video performance data to discover winning patterns."""

    async def analyze_patterns(self) -> list[dict]:
        """
        Analyze top/bottom performing videos to discover patterns.

        1. Fetch top 20 and bottom 20 performing videos with metadata
        2. Send to LLM for pattern analysis
        3. Store discovered patterns
        4. Deactivate contradicted old patterns
        """
        from app.services.analytics_service import AnalyticsService

        analytics_service = AnalyticsService()

        # Get top and bottom performing videos
        top_videos = await analytics_service.get_top_performing_videos(
            limit=20, days=90
        )
        bottom_videos = await self._get_bottom_performing_videos(limit=20, days=90)

        if len(top_videos) < 5 or len(bottom_videos) < 5:
            logger.info(
                "Not enough data for pattern analysis — top={} bottom={}",
                len(top_videos),
                len(bottom_videos),
            )
            return []

        # Build LLM prompt
        prompt = self._build_analysis_prompt(top_videos, bottom_videos)

        # Call LLM
        patterns = await self._analyze_with_llm(prompt)

        if not patterns:
            logger.info("No patterns discovered from LLM analysis")
            return []

        # Store patterns
        stored = await self._store_patterns(patterns, len(top_videos) + len(bottom_videos))

        logger.info("Pattern analysis complete — {} patterns discovered", len(stored))
        return stored

    async def _get_bottom_performing_videos(
        self, limit: int = 20, days: int = 90
    ) -> list[dict]:
        """Get worst performing videos by views."""
        from sqlalchemy import select, asc
        from datetime import date, timedelta
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
                .where(VideoAnalytics.views > 0)
                .order_by(asc(VideoAnalytics.views))
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

    def _build_analysis_prompt(
        self, top_videos: list[dict], bottom_videos: list[dict]
    ) -> str:
        """Build the LLM prompt for pattern analysis."""
        top_section = "\n".join(
            f"  - Topic: {v['topic']}, Views: {v['views']}, "
            f"Retention: {v.get('retention', 'N/A')}%, "
            f"Script: {v.get('script_excerpt', 'N/A')}"
            for v in top_videos
        )

        bottom_section = "\n".join(
            f"  - Topic: {v['topic']}, Views: {v['views']}, "
            f"Retention: {v.get('retention', 'N/A')}%, "
            f"Script: {v.get('script_excerpt', 'N/A')}"
            for v in bottom_videos
        )

        return (
            "You are a YouTube Shorts performance analyst. Analyze these video "
            "performance records and identify clear patterns.\n\n"
            f"TOP PERFORMING VIDEOS:\n{top_section}\n\n"
            f"LOW PERFORMING VIDEOS:\n{bottom_section}\n\n"
            "Identify patterns in these categories:\n"
            "1. hook_style - What hook styles (question, statistic, bold claim, story) perform best?\n"
            "2. topic - What topics/niches get the most views?\n"
            "3. script_structure - What script structures (problem-solution, listicle, story) work best?\n"
            "4. length - What script length (word count) correlates with higher retention?\n"
            "5. cta - What call-to-action styles drive engagement?\n\n"
            "For each pattern found, respond in this JSON format:\n"
            "[\n"
            "  {\n"
            '    "pattern_type": "hook_style",\n'
            '    "description": "Questions in the first sentence get 2.5x more views",\n'
            '    "confidence": 0.85,\n'
            '    "recommendation": "Start scripts with a provocative question"\n'
            "  }\n"
            "]\n\n"
            "Return ONLY valid JSON array. Identify 3-7 patterns."
        )

    async def _analyze_with_llm(self, prompt: str) -> list[dict]:
        """Send analysis prompt to LLM and parse response."""
        from app.services.llm_service import LLMProvider, _call_openai, _call_anthropic

        messages = [{"role": "user", "content": prompt}]
        system = (
            "You are a data analyst specializing in YouTube Shorts performance. "
            "Analyze the provided data and return actionable patterns as JSON."
        )

        try:
            # Try OpenAI first
            raw = await _call_openai(
                [{"role": "system", "content": system}] + messages
            )
        except Exception:
            try:
                raw = await _call_anthropic(messages, system)
            except Exception as exc:
                logger.error("Both LLM providers failed for pattern analysis: {}", exc)
                return []

        # Parse JSON response
        try:
            from app.services.llm_service import _extract_json

            # The response should be a JSON array
            raw = raw.strip()
            if raw.startswith("["):
                patterns = json.loads(raw)
            else:
                # Try to extract from the response
                result = _extract_json(raw)
                if isinstance(result, list):
                    patterns = result
                elif isinstance(result, dict) and "patterns" in result:
                    patterns = result["patterns"]
                else:
                    patterns = [result]

            return [
                p
                for p in patterns
                if isinstance(p, dict) and "pattern_type" in p and "description" in p
            ]
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse pattern analysis response: {}", exc)
            return []

    async def _store_patterns(
        self, patterns: list[dict], sample_size: int
    ) -> list[dict]:
        """Store discovered patterns in the database."""
        from app.core.database import async_session_factory
        from app.models.analytics import PerformancePattern

        stored = []
        now = datetime.now(timezone.utc)

        async with async_session_factory() as session:
            for pattern in patterns:
                # Deactivate old patterns of the same type
                from sqlalchemy import update

                await session.execute(
                    update(PerformancePattern)
                    .where(PerformancePattern.pattern_type == pattern["pattern_type"])
                    .where(PerformancePattern.is_active.is_(True))
                    .values(is_active=False, updated_at=now)
                )

                record = PerformancePattern(
                    id=uuid.uuid4(),
                    pattern_type=pattern["pattern_type"],
                    description=pattern["description"],
                    pattern_data=json.dumps(
                        {
                            "recommendation": pattern.get("recommendation", ""),
                            "raw_pattern": pattern,
                        }
                    ),
                    confidence_score=min(float(pattern.get("confidence", 0.5)), 1.0),
                    sample_size=sample_size,
                    avg_views=0.0,
                    avg_retention=None,
                    supporting_evidence=json.dumps([]),
                    is_active=True,
                    discovered_at=now,
                )
                session.add(record)
                stored.append(
                    {
                        "id": str(record.id),
                        "pattern_type": record.pattern_type,
                        "description": record.description,
                        "confidence_score": record.confidence_score,
                    }
                )

            await session.commit()

        return stored

    async def get_active_patterns(
        self, min_confidence: float = 0.6
    ) -> list[dict]:
        """Get all active performance patterns above confidence threshold."""
        from sqlalchemy import select
        from app.core.database import async_session_factory
        from app.models.analytics import PerformancePattern

        async with async_session_factory() as session:
            query = (
                select(PerformancePattern)
                .where(PerformancePattern.is_active.is_(True))
                .where(PerformancePattern.confidence_score >= min_confidence)
                .order_by(PerformancePattern.confidence_score.desc())
            )
            result = await session.execute(query)
            patterns = result.scalars().all()

        return [
            {
                "id": str(p.id),
                "pattern_type": p.pattern_type,
                "description": p.description,
                "confidence_score": p.confidence_score,
                "sample_size": p.sample_size,
                "pattern_data": json.loads(p.pattern_data) if p.pattern_data else {},
            }
            for p in patterns
        ]

    async def should_run_analysis(self) -> bool:
        """
        Check if we have enough new data to run analysis.

        Requires at least PATTERN_ANALYSIS_MIN_VIDEOS total videos with analytics
        and at least 5 new videos since the last analysis.
        """
        from sqlalchemy import select, func
        from app.core.database import async_session_factory
        from app.models.analytics import VideoAnalytics, PerformancePattern

        async with async_session_factory() as session:
            # Count total videos with analytics
            total_q = select(
                func.count(func.distinct(VideoAnalytics.project_id))
            )
            total_result = await session.execute(total_q)
            total_count = total_result.scalar() or 0

            if total_count < settings.pattern_analysis_min_videos:
                logger.debug(
                    "Not enough videos for analysis: {} < {}",
                    total_count,
                    settings.pattern_analysis_min_videos,
                )
                return False

            # Check last analysis time
            last_q = (
                select(PerformancePattern.discovered_at)
                .order_by(PerformancePattern.discovered_at.desc())
                .limit(1)
            )
            last_result = await session.execute(last_q)
            last_analysis = last_result.scalar_one_or_none()

            if last_analysis is None:
                return True  # Never analyzed before

            # Count new videos since last analysis
            new_q = select(
                func.count(func.distinct(VideoAnalytics.project_id))
            ).where(VideoAnalytics.collected_at > last_analysis)
            new_result = await session.execute(new_q)
            new_count = new_result.scalar() or 0

            if new_count < 5:
                logger.debug(
                    "Not enough new videos since last analysis: {} < 5", new_count
                )
                return False

        return True
